"""Small, bounded batches. No concurrency, retries, proxies or challenge bypass."""

import fcntl
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import validate_config
from .store import Store, canonical

HEADERS = {
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
    "sec-fetch-site": "same-origin",
    "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
}
BASE = "https://proclubs.ea.com/api/fc/"


def endpoints(config):
    club = config["club"]
    common = {"platform": club["platform"]}
    specs = [
        ("info", "clubs/info", {"clubIds": club["id"]}, True),
        (
            "summary",
            "allTimeLeaderboard/search",
            {"clubName": club["name"], "maxResultCount": 50},
            True,
        ),
        (
            "season",
            "currentSeasonLeaderboard/search",
            {"clubName": club["name"], "maxResultCount": 50},
            True,
        ),
        ("overall", "clubs/overallStats", {"clubIds": club["id"]}, False),
        ("members", "members/stats", {"clubId": club["id"]}, False),
        ("career", "members/career/stats", {"clubId": club["id"]}, False),
        *[
            (
                kind,
                "clubs/matches",
                {"clubIds": club["id"], "matchType": kind + "Match", "maxResultCount": 10},
                False,
            )
            for kind in ("league", "friendly", "playoff")
        ],
        ("achievements", "club/playoffAchievements", {"clubId": club["id"]}, True),
    ]
    return [
        (label, BASE + path + "?" + urllib.parse.urlencode(common | params), daily)
        for label, path, params, daily in specs
    ]


def fetch(url, timeout):
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=HEADERS), timeout=timeout
    ) as response:
        # A bad upstream response must not fill the disk or become a snapshot.
        payload = response.read(8 * 1024 * 1024 + 1)
        if len(payload) > 8 * 1024 * 1024:
            raise ValueError("EA response exceeded 8 MiB")
        return json.loads(payload), response.status


def collect(db_path, config, request=fetch, now=None, sleeper=time.sleep):
    validate_config(config)
    now = int(time.time() if now is None else now)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with (db_path.parent / "collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped", "reason": "Another collector is running"}
        store = Store(db_path, config)
        try:
            opts = config["collector"]
            cooldown = int(store.state("cooldown_until", 0))
            if cooldown > now:
                return {"status": "skipped", "reason": "EA cooldown", "until": cooldown}
            last = int(store.state("last_attempt", 0))
            active = int(store.state("active_until", 0)) > now
            interval = (
                max(600, opts.get("active_interval_seconds", 600))
                if active
                else max(3000, opts["minimum_interval_seconds"])
            )
            if last and now - last < interval:
                return {
                    "status": "skipped",
                    "reason": "Minimum request interval",
                    "until": last + interval,
                }
            run = store.start_run("live", now)
            with store.db:
                abandoned = store.db.execute(
                    "SELECT id FROM runs WHERE status='running' AND id<>?", (run,)
                ).fetchall()
                for old in abandoned:
                    store.db.execute(
                        "UPDATE runs SET status='interrupted',finished=? WHERE id=?", (now, old[0])
                    )
                    store.warn(
                        run,
                        "interrupted_run",
                        f"Previous collection {old[0]} did not finish. Its successful endpoint snapshots remain available.",
                        now,
                    )
                store.set_state("last_attempt", now)
                # If interrupted or killed, the next invocation still waits an hour.
                store.set_state("cooldown_until", now + opts["error_cooldown_seconds"])
            overall = store.latest("overall")
            full_batch = (
                not active
                or not overall
                or now - overall["observed"] >= max(3600, opts["minimum_interval_seconds"])
            )
            active_until = int(store.state("active_until", 0))
            active_window = min(1800, max(600, opts.get("active_window_seconds", 1800)))
            successes = []
            for label, url, daily in endpoints(config):
                if not full_batch and label not in {"league", "friendly", "playoff"}:
                    continue
                latest = store.latest(label)
                if (
                    daily
                    and latest
                    and now - latest["observed"] < opts["metadata_interval_seconds"]
                ):
                    continue
                if successes:
                    sleeper(max(3, opts["request_spacing_seconds"]))
                try:
                    data, status = request(url, opts["timeout_seconds"])
                    if data is None and label in {"league", "friendly", "playoff", "achievements"}:
                        data = []
                    # Only newly archived, recent completed games indicate a session.
                    # Old history, corrections and repeated windows must not extend it.
                    recent_until = active_until
                    if label in {"league", "friendly", "playoff"} and isinstance(data, list):
                        known = {r[0] for r in store.db.execute("SELECT match_id FROM matches")}
                        for match in data:
                            timestamp = int(match["timestamp"])
                            if (
                                str(match["matchId"]) not in known
                                and now - active_window < timestamp <= now
                            ):
                                recent_until = max(recent_until, now + active_window)
                    store.ingest(run, label, data, now)
                    active_until = recent_until
                    with store.db:
                        store.db.execute(
                            "INSERT INTO attempts(run_id,endpoint,observed,status) VALUES(?,?,?,?)",
                            (run, label, now, status),
                        )
                    successes.append(label)
                except (
                    urllib.error.HTTPError,
                    urllib.error.URLError,
                    OSError,
                    ValueError,
                    TypeError,
                    KeyError,
                ) as exc:
                    status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
                    seconds = (
                        opts["block_cooldown_seconds"]
                        if status in {401, 403, 429}
                        else opts["error_cooldown_seconds"]
                    )
                    if isinstance(exc, urllib.error.HTTPError):
                        retry = exc.headers.get("Retry-After") if exc.headers else None
                        if retry:
                            try:
                                seconds = max(seconds, int(retry))
                            except ValueError:
                                from email.utils import parsedate_to_datetime

                                try:
                                    seconds = max(
                                        seconds, int(parsedate_to_datetime(retry).timestamp()) - now
                                    )
                                except (ValueError, TypeError):
                                    pass
                    with store.db:
                        store.set_state("cooldown_until", now + seconds)
                        store.db.execute(
                            "INSERT INTO attempts(run_id,endpoint,observed,status,error) VALUES(?,?,?,?,?)",
                            (run, label, now, status, str(exc)),
                        )
                        store.warn(
                            run,
                            "collection_failed",
                            f"{label}: {exc}. Batch stopped; no retries. Next eligible attempt after cooldown.",
                            now,
                        )
                    store.finish_run(run, "partial" if successes else "failed", now)
                    return {
                        "status": "partial" if successes else "failed",
                        "fetched": successes,
                        "failed_endpoint": label,
                        "error": str(exc),
                        "cooldown_until": now + seconds,
                    }
            with store.db:
                store.set_state("cooldown_until", 0)
                store.set_state("active_until", active_until)
            store.finish_run(run, "complete", now)
            return {
                "status": "complete",
                "fetched": successes,
                "new_matches": {
                    kind: int(store.state(f"new_{kind}", 0))
                    for kind in ("league", "friendly", "playoff")
                },
            }
        finally:
            store.close()


def import_seed(db_path, config, directory):
    """Idempotent offline bootstrap. All inputs validated before inserting anything."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["club"] != config["club"]:
        raise ValueError("Seed belongs to a different club/edition")
    data = {
        p.stem: json.loads(p.read_text())
        for p in sorted(directory.glob("*.json"))
        if p.name != "manifest.json"
    }
    key = hashlib.sha256(canonical({"manifest": manifest, "data": data}).encode()).hexdigest()
    store = Store(db_path, config)
    try:
        if store.db.execute("SELECT id FROM runs WHERE import_key=?", (key,)).fetchone():
            return {"status": "skipped", "reason": "Seed already imported"}
        if store.db.execute("SELECT count(*) FROM runs").fetchone()[0]:
            raise ValueError(
                "Bootstrap is only allowed on a new archive. Restore the database instead of re-importing old seeds."
            )
        for label, payload in data.items():
            if label not in {e[0] for e in endpoints(config)}:
                raise ValueError(f"Unknown seed endpoint {label}")
            store.validate(label, payload)
        run = store.start_run("baseline", manifest["observed"], key)
        for label, payload in data.items():
            store.ingest(run, label, payload, manifest["observed"])
        with store.db:
            store.set_state("last_attempt", manifest["observed"])
            baseline = store.latest("overall")
            total = (
                next(
                    (
                        x.get("gamesPlayed", 0)
                        for x in baseline["data"]
                        if str(x.get("clubId")) == config["club"]["id"]
                    ),
                    0,
                )
                if baseline
                else 0
            )
            store.warn(
                run,
                "baseline_coverage",
                f"Baseline preserves EA's cumulative totals ({total} games), but only the recent match window has detailed stats. Those two views must never be added together.",
                manifest["observed"],
            )
        store.finish_run(run, "complete", manifest["observed"])
        return {"status": "complete", "imported": list(data)}
    finally:
        store.close()
