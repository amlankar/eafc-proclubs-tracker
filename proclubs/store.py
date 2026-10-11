import hashlib
import json
import sqlite3
import time
import zlib
from collections import Counter
from pathlib import Path

from .decode import (
    DIVISIONS,
    REPUTATION,
    catalog,
    decode_info,
    decode_player,
    member_labels,
    normalize,
    number,
    percent,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY, started INTEGER NOT NULL, finished INTEGER,
 source TEXT NOT NULL, status TEXT NOT NULL, import_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS responses (
 digest TEXT PRIMARY KEY, payload BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots (
 run_id INTEGER NOT NULL REFERENCES runs(id), endpoint TEXT NOT NULL,
 observed INTEGER NOT NULL, digest TEXT NOT NULL REFERENCES responses(digest),
 PRIMARY KEY(run_id, endpoint));
CREATE INDEX IF NOT EXISTS snapshots_endpoint ON snapshots(endpoint, observed);
CREATE TABLE IF NOT EXISTS matches (
 match_id TEXT PRIMARY KEY, timestamp INTEGER NOT NULL,
 first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
 digest TEXT NOT NULL REFERENCES responses(digest));
CREATE TABLE IF NOT EXISTS match_types (
 match_id TEXT NOT NULL REFERENCES matches(match_id), kind TEXT NOT NULL,
 PRIMARY KEY(match_id, kind));
CREATE TABLE IF NOT EXISTS warnings (
 id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES runs(id),
 observed INTEGER NOT NULL, code TEXT NOT NULL, message TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (
 id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES runs(id),
 endpoint TEXT NOT NULL, observed INTEGER NOT NULL, status INTEGER, error TEXT);
"""


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Store:
    def __init__(self, path, config, readonly=False):
        self.path, self.config = Path(path), config
        if readonly:
            # Keep WAL visibility while denying SQL writes; do not use immutable=1.
            self.db = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=20
            )
            self.db.execute("PRAGMA query_only=ON")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.db = sqlite3.connect(self.path, timeout=20)
            self.path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        if not readonly:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
        identity = canonical(config["club"])
        previous = self.state("identity")
        if previous and previous != identity:
            self.db.close()
            raise ValueError(
                "Club/edition configuration changed. Use a new data directory to keep archives separate."
            )
        if not previous:
            if readonly:
                self.db.close()
                raise ValueError("Archive must be initialized before serving it")
            self.set_state("identity", identity)
            self.db.commit()

    def close(self):
        self.db.close()

    def state(self, key, default=None):
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_state(self, key, value):
        self.db.execute(
            "INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def start_run(self, source, now=None, import_key=None):
        now = int(now or time.time())
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO runs(started,source,status,import_key) VALUES(?,?,?,?)",
                (now, source, "running", import_key),
            )
        return cursor.lastrowid

    def finish_run(self, run_id, status, now=None):
        with self.db:
            self.db.execute(
                "UPDATE runs SET finished=?,status=? WHERE id=?",
                (int(now or time.time()), status, run_id),
            )

    def warn(self, run_id, code, message, now=None):
        self.db.execute(
            "INSERT INTO warnings(run_id,observed,code,message) VALUES(?,?,?,?)",
            (run_id, int(now or time.time()), code, message),
        )

    def blob(self, data):
        encoded = canonical(data).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        self.db.execute(
            "INSERT OR IGNORE INTO responses VALUES(?,?)", (digest, zlib.compress(encoded))
        )
        return digest

    def load(self, digest):
        row = self.db.execute("SELECT payload FROM responses WHERE digest=?", (digest,)).fetchone()
        return json.loads(zlib.decompress(row[0]))

    def validate(self, endpoint, data):
        club = str(self.config["club"]["id"])
        if endpoint == "info":
            if (
                not isinstance(data, dict)
                or club not in data
                or data[club].get("name", "").casefold() != self.config["club"]["name"].casefold()
            ):
                raise ValueError("Club ID/name mismatch: refusing to attach another club's data")
        elif endpoint in {"members", "career"}:
            if not isinstance(data, dict) or not isinstance(data.get("members"), list):
                raise ValueError(f"Unexpected {endpoint} response shape")
            names = [m.get("name") for m in data["members"] if isinstance(m, dict)]
            if (
                len(names) != len(data["members"])
                or any(not isinstance(n, str) or not n for n in names)
                or len(set(names)) != len(names)
            ):
                raise ValueError("Invalid or duplicate member names")
        elif endpoint in {"overall", "summary", "season"}:
            if endpoint in {"summary", "season"} and data == []:
                return
            if not isinstance(data, list) or not any(
                str(x.get("clubId")) == club for x in data if isinstance(x, dict)
            ):
                raise ValueError(f"{endpoint}: configured club absent from response")
        elif endpoint in {"league", "friendly", "playoff"}:
            if not isinstance(data, list):
                raise ValueError("Unexpected match response shape")
            for match in data:
                if (
                    not isinstance(match, dict)
                    or not match.get("matchId")
                    or not isinstance(match.get("clubs"), dict)
                    or club not in match["clubs"]
                    or not isinstance(match.get("timestamp"), (int, float))
                ):
                    raise ValueError("Invalid match response or wrong club")
                if not isinstance(match.get("players", {}), dict):
                    raise ValueError("Invalid player response shape")
                returned_name = (match["clubs"][club].get("details") or {}).get("name")
                if (
                    returned_name
                    and returned_name.casefold() != self.config["club"]["name"].casefold()
                ):
                    raise ValueError(
                        "Match club name differs from configured club; possible edition rollover or ID reuse"
                    )
        elif endpoint == "achievements" and not isinstance(data, list):
            raise ValueError("Unexpected achievements response shape")

    def ingest(self, run_id, endpoint, data, observed=None):
        now = int(observed or time.time())
        self.validate(endpoint, data)
        with self.db:
            old = self.latest(endpoint)
            digest = self.blob(data)
            self.db.execute(
                "INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?)", (run_id, endpoint, now, digest)
            )
            if endpoint in {"summary", "season"} and data == []:
                self.warn(
                    run_id,
                    "metadata_unavailable",
                    f"{endpoint}: EA search returned no club. Raw response saved; no club totals inferred.",
                    now,
                )
            if endpoint in {"league", "friendly", "playoff"}:
                known = {
                    r[0]
                    for r in self.db.execute(
                        "SELECT match_id FROM match_types WHERE kind=?", (endpoint,)
                    )
                }
                new = {str(m["matchId"]) for m in data} - known
                if known and len(data) >= 10 and not ({str(m["matchId"]) for m in data} & known):
                    self.warn(
                        run_id,
                        "history_gap",
                        f"{endpoint}: the entire 10-match window is new. Older games may have been missed.",
                        now,
                    )
                for match in data:
                    match_digest = self.blob(match)
                    self.db.execute(
                        """INSERT INTO matches VALUES(?,?,?,?,?) ON CONFLICT(match_id)
                       DO UPDATE SET last_seen=excluded.last_seen,digest=excluded.digest""",
                        (str(match["matchId"]), int(match["timestamp"]), now, now, match_digest),
                    )
                    self.db.execute(
                        "INSERT OR IGNORE INTO match_types VALUES(?,?)",
                        (str(match["matchId"]), endpoint),
                    )
                self.set_state(f"new_{endpoint}", len(new))
            if old and endpoint in {"overall", "members", "career"}:
                drops = counter_drops(endpoint, old["data"], data, str(self.config["club"]["id"]))
                if drops:
                    self.warn(
                        run_id,
                        "counter_decrease",
                        f"{endpoint}: counters decreased ({'; '.join(drops[:12])}). Could be a reset, correction or roster change; no invented totals.",
                        now,
                    )

    def latest(self, endpoint, first=False):
        order = "ASC" if first else "DESC"
        row = self.db.execute(
            f"SELECT observed,digest FROM snapshots WHERE endpoint=? ORDER BY observed {order},run_id {order} LIMIT 1",
            (endpoint,),
        ).fetchone()
        return {"observed": row[0], "data": self.load(row[1])} if row else None

    def history(self, endpoint):
        return [
            {"observed": r[0], "data": self.load(r[1])}
            for r in self.db.execute(
                "SELECT observed,digest FROM snapshots WHERE endpoint=? ORDER BY observed,run_id",
                (endpoint,),
            )
        ]

    def match(self, match_id):
        row = self.db.execute("SELECT digest FROM matches WHERE match_id=?", (match_id,)).fetchone()
        return self.load(row[0]) if row else None

    def export(self):
        return {
            "config": self.config,
            "decoder": catalog(),
            "snapshots": [
                {"run_id": r[0], "endpoint": r[1], "observed": r[2], "data": self.load(r[3])}
                for r in self.db.execute("SELECT * FROM snapshots ORDER BY run_id,endpoint")
            ],
            "matches": [
                self.load(r[0])
                for r in self.db.execute("SELECT digest FROM matches ORDER BY timestamp")
            ],
            "runs": [dict(r) for r in self.db.execute("SELECT * FROM runs")],
            "warnings": [dict(r) for r in self.db.execute("SELECT * FROM warnings")],
            "attempts": [dict(r) for r in self.db.execute("SELECT * FROM attempts")],
        }

    def tracking_totals(self):
        """Starting counters + post-baseline captured LEAGUE matches, never both windows.

        This is a conservative local ledger, not a claim about EA season/career scope.
        It survives EA counter resets, with explicit incomplete-history coverage.
        """
        club = str(self.config["club"]["id"])
        base = self.latest("overall", first=True)
        if not base:
            return {"players": [], "club": {}, "observed": None, "post_baseline_games": 0}
        cutoff = base["observed"]
        baseline_club = select_club(base["data"], club)
        members = self.latest("members", first=True)
        baseline_members = {
            m["name"]: m for m in (members or {}).get("data", {}).get("members", [])
        }
        initial_window = self.latest("league", first=True)
        id_to_name = {}
        for match in (initial_window or {}).get("data", []):
            if match["timestamp"] <= cutoff:
                for pid, row in match.get("players", {}).get(club, {}).items():
                    if row.get("playername") in baseline_members:
                        id_to_name[pid] = row["playername"]
        initial_ids = {name: pid for pid, name in id_to_name.items()}
        fields = {
            "gamesPlayed": "games",
            "goals": "goals",
            "assists": "assists",
            "manOfTheMatch": "manOfTheMatch",
            "passesMade": "passes",
            "tacklesMade": "tackles",
            "redCards": "redCards",
            "cleanSheetsDef": "cleanSheetsDef",
            "cleanSheetsGK": "cleanSheetsGK",
        }
        players = {}
        for name, row in baseline_members.items():
            pid = initial_ids.get(name)
            key = pid or "baseline:" + name
            players[key] = {
                "id": pid,
                "name": name,
                "key": key,
                "baseline_name": name,
                "baseline": normalize(row),
                "link": "initial match player ID" if pid else "baseline name only",
                "captured_games": 0,
                "totals": {dest: number(row.get(src)) for src, dest in fields.items()},
                "captured": Counter(),
            }
        totals = {k: number(baseline_club.get(k)) for k in CLUB_COUNTERS}
        post_games = 0
        records = self.db.execute(
            "SELECT * FROM matches WHERE timestamp>? AND match_id IN (SELECT match_id FROM match_types WHERE kind='league') ORDER BY timestamp",
            (cutoff,),
        ).fetchall()
        for record in records:
            match = self.load(record["digest"])
            own = match["clubs"][club]
            post_games += 1
            totals["gamesPlayed"] += 1
            totals["goals"] += number(own.get("goals"))
            totals["goalsAgainst"] += number(own.get("goalsAgainst"))
            gf, ga = number(own.get("goals")), number(own.get("goalsAgainst"))
            result = "wins" if gf > ga else "losses" if gf < ga else "ties"
            if number(own.get("wins")) == 1:
                result = "wins"
            elif number(own.get("losses")) == 1:
                result = "losses"
            elif number(own.get("ties")) == 1:
                result = "ties"
            totals[result] += 1
            for pid, row in match.get("players", {}).get(club, {}).items():
                name = row.get("playername", pid)
                if pid not in players:
                    name_key = "baseline:" + name
                    if name_key in players:
                        players[pid] = players.pop(name_key)
                        players[pid].update(
                            id=pid, key=pid, link="name match at first captured appearance"
                        )
                    else:
                        players[pid] = {
                            "id": pid,
                            "key": pid,
                            "name": name,
                            "baseline_name": None,
                            "baseline": {},
                            "link": "no matching baseline; captured games only",
                            "captured_games": 0,
                            "totals": {dest: 0 for dest in fields.values()},
                            "captured": Counter(),
                        }
                item = players[pid]
                item["name"] = name
                item["captured_games"] += 1
                item["totals"]["games"] += 1
                for src, dest in (
                    ("goals", "goals"),
                    ("assists", "assists"),
                    ("mom", "manOfTheMatch"),
                    ("passesmade", "passes"),
                    ("tacklesmade", "tackles"),
                    ("redcards", "redCards"),
                    ("cleansheetsdef", "cleanSheetsDef"),
                    ("cleansheetsgk", "cleanSheetsGK"),
                ):
                    value = number(row.get(src))
                    item["totals"][dest] += value
                    item["captured"][dest] += value
        return {
            "players": list(players.values()),
            "club": totals,
            "observed": cutoff,
            "post_baseline_games": post_games,
            "scope": "Starting EA snapshot plus captured league matches strictly after its collection time. Excludes friendly/playoff additions. Missed matches and baseline scope differences are not estimated; averages/rates are not reconstructed from rounded baseline values.",
        }

    def initial_player_history(self):
        """Count the player appearances missing before collection began, independent of filters."""
        club = str(self.config["club"]["id"])
        baseline = self.latest("overall", first=True)
        members = self.latest("members", first=True)
        league = self.latest("league", first=True)
        captured, identities = {}, {}
        for match in (league or {}).get("data", []):
            if baseline and match["timestamp"] > baseline["observed"]:
                continue
            for pid, player in match.get("players", {}).get(club, {}).items():
                name = player.get("playername")
                identities[name] = pid
                captured.setdefault(name, set()).add(str(match["matchId"]))
        return [
            {
                "id": identities.get(m["name"]),
                "name": m["name"],
                "missing_matches": max(
                    0, int(number(m.get("gamesPlayed"))) - len(captured.get(m["name"], set()))
                ),
            }
            for m in (members or {}).get("data", {}).get("members", [])
        ]

    def division_history(self):
        club = str(self.config["club"]["id"])
        points = []
        for snapshot in self.history("summary"):
            code = str(select_club(snapshot["data"], club).get("currentDivision", ""))
            points.append(
                {
                    "observed": snapshot["observed"],
                    "division": int(code) if code in DIVISIONS else None,
                    "label": DIVISIONS.get(code),
                }
            )
        return points

    def dashboard(self, kind="all", start=None, end=None, include_trends=False):
        club = str(self.config["club"]["id"])
        latest = {
            ep: self.latest(ep)
            for ep in ("info", "summary", "season", "overall", "members", "career", "achievements")
        }
        overall = select_club((latest["overall"] or {}).get("data", []), club)
        summary = select_club((latest["summary"] or {}).get("data", []), club)
        season = select_club((latest["season"] or {}).get("data", []), club)
        baseline = self.latest("overall", first=True)
        baseline_overall = select_club(baseline["data"], club) if baseline else {}
        base_members = self.latest("members", first=True)
        initial = {m["name"]: m for m in (base_members or {}).get("data", {}).get("members", [])}
        members = (latest["members"] or {}).get("data", {}).get("members", [])
        career = (latest["career"] or {}).get("data", {}).get("members", [])
        counter_warnings = self.db.execute(
            "SELECT count(*) FROM warnings WHERE code='counter_decrease'"
        ).fetchone()[0]
        sql, params = "SELECT * FROM matches WHERE 1=1", []
        if start is not None:
            sql += " AND timestamp>=?"
            params.append(start)
        if end is not None:
            sql += " AND timestamp<?"
            params.append(end)
        if kind != "all":
            sql += " AND match_id IN (SELECT match_id FROM match_types WHERE kind=?)"
            params.append(kind)
        rows = self.db.execute(sql + " ORDER BY timestamp DESC", params).fetchall()
        players, matches, opponents, sessions, team_events, event_coverage = (
            {},
            [],
            {},
            {},
            Counter(),
            Counter(),
        )
        outcomes, all_unknown, team_named, team_ea_aggregate = (
            Counter(),
            Counter(),
            Counter(),
            Counter(),
        )
        problem_count = 0
        for record in rows:
            raw = self.load(record["digest"])
            own = raw["clubs"][club]
            other_id = next((k for k in raw["clubs"] if k != club), None)
            other = raw["clubs"].get(other_id, {})
            gf, ga = number(own.get("goals")), number(own.get("goalsAgainst"))
            result = "W" if gf > ga else "L" if gf < ga else "D"
            # League quit decisions can override the played score.
            if number(own.get("wins")) == 1:
                result = "W"
            elif number(own.get("losses")) == 1:
                result = "L"
            elif number(own.get("ties")) == 1:
                result = "D"
            outcomes[result] += 1
            outcomes["goals"] += gf
            outcomes["goalsAgainst"] += ga
            types = [
                r[0]
                for r in self.db.execute(
                    "SELECT kind FROM match_types WHERE match_id=?", (record["match_id"],)
                )
            ]
            opponent_name = (other.get("details") or {}).get("name") or "Opponent"
            op = opponents.setdefault(
                other_id or "unknown",
                {
                    "name": opponent_name,
                    "matches": 0,
                    "W": 0,
                    "D": 0,
                    "L": 0,
                    "goals": 0,
                    "goalsAgainst": 0,
                },
            )
            op["matches"] += 1
            op[result] += 1
            op["goals"] += gf
            op["goalsAgainst"] += ga
            match_players = []
            match_named, match_events = Counter(), Counter()
            match_event_rows = 0
            for player_id, player in raw.get("players", {}).get(club, {}).items():
                decoded = decode_player(player)
                problem_count += len(decoded["problems"])
                name = player.get("playername", str(player_id))
                item = players.setdefault(
                    player_id,
                    {
                        "id": player_id,
                        "name": name,
                        "names": [],
                        "games": 0,
                        "W": 0,
                        "D": 0,
                        "L": 0,
                        "named": Counter(),
                        "events": Counter(),
                        "unknown": Counter(),
                        "rating_sum": 0,
                        "rated_games": 0,
                        "positions": Counter(),
                        "platform": decoded["platform_family"],
                        "archetypes": Counter(),
                        "event_games": 0,
                        "history": [],
                    },
                )
                if name not in item["names"]:
                    item["names"].append(name)
                item["games"] += 1
                item[result] += 1
                item["positions"][player.get("pos", "unknown")] += 1
                item["archetypes"][str(player.get("archetypeid", "unknown"))] += 1
                # Stable player ids provide archive identity; gamertags are just display labels.
                item["event_games"] += bool(decoded["events"])
                point_named = {}
                for k, value in player.items():
                    if (
                        k
                        not in {
                            "rating",
                            "archetypeid",
                            "namespace",
                            "userResult",
                            "vprohackreason",
                            "gameTime",
                            "secondsPlayed",
                            "realtimegame",
                            "realtimeidle",
                            "SCORE",
                        }
                        and not k.startswith("match_event_")
                        and isinstance(normalize(value, k), (int, float))
                    ):
                        item["named"][k] += number(value)
                        team_named[k] += number(value)
                        point_named[k] = number(value)
                        match_named[k] += number(value)
                if number(player.get("rating")) > 0:
                    item["rating_sum"] += number(player["rating"])
                    item["rated_games"] += 1
                item["history"].append(
                    {
                        "match_id": record["match_id"],
                        "timestamp": record["timestamp"],
                        "opponent": opponent_name,
                        "result": result,
                        "rating": number(player.get("rating"))
                        if number(player.get("rating")) > 0
                        else None,
                        "goals": number(player.get("goals")),
                        "assists": number(player.get("assists")),
                        "shots": number(player.get("shots")),
                        "passes": number(player.get("passesmade")),
                        "pass_attempts": number(player.get("passattempts")),
                        "tackles": number(player.get("tacklesmade")),
                        "tackle_attempts": number(player.get("tackleattempts")),
                        "interceptions": decoded["decoded"]["interceptions"]["value"],
                        "second_assists": decoded["decoded"]["second_assists"]["value"],
                    }
                )
                if include_trends:
                    point_events = (
                        {k: d["value"] for k, d in decoded["decoded"].items()}
                        if decoded["events"]
                        else None
                    )
                    item["history"][-1].update(
                        named=point_named,
                        events=point_events,
                        rated_games=int(number(player.get("rating")) > 0),
                        **decoded["ratios"],
                    )
                    if point_events is not None:
                        match_events.update(point_events)
                        match_event_rows += 1
                for k, detail in decoded["decoded"].items():
                    item["events"][k] += detail["value"]
                    team_events[k] += detail["value"]
                    event_coverage[k] += bool(decoded["events"])
                item["unknown"].update(decoded["unknown_events"])
                all_unknown.update(decoded["unknown_events"])
                match_players.append(
                    {
                        "id": player_id,
                        "name": name,
                        "rating": number(player.get("rating")),
                        "goals": number(player.get("goals")),
                        "assists": number(player.get("assists")),
                    }
                )
            # EA aggregate includes whichever entities EA included. Keep separate from human rows.
            for k, value in raw.get("aggregate", {}).get(club, {}).items():
                if k in {
                    "shots",
                    "passattempts",
                    "passesmade",
                    "tackleattempts",
                    "tacklesmade",
                    "saves",
                    "goals",
                    "assists",
                }:
                    team_ea_aggregate[k] += number(value)
            matches.append(
                {
                    "id": record["match_id"],
                    "timestamp": record["timestamp"],
                    "types": types,
                    "opponent": opponent_name,
                    "opponent_id": other_id,
                    "goals": gf,
                    "goalsAgainst": ga,
                    "result": result,
                    "quit_win": bool(number(own.get("winnerByDnf"))),
                    "result_code": own.get("result"),
                    "players": match_players,
                }
            )
            if include_trends:
                # A player's conceded counter can repeat the score: use the club score once.
                match_named["goalsconceded"] = ga
                matches[-1].update(
                    named=dict(match_named),
                    events=dict(match_events) if match_event_rows else None,
                    rated_games=sum(p["rating"] > 0 for p in match_players),
                )
        for p in players.values():
            p["rating"] = (
                round(p.pop("rating_sum") / p["rated_games"], 2) if p["rated_games"] else None
            )
            p["pass_completion"] = percent(p["named"]["passesmade"], p["named"]["passattempts"])
            p["tackle_success"] = percent(p["named"]["tacklesmade"], p["named"]["tackleattempts"])
            p["shot_conversion"] = percent(p["named"]["goals"], p["named"]["shots"])
            p["shots_on_target_rate"] = percent(
                p["events"]["shots_on_target"], p["events"]["shots"]
            )
            p["goal_contributions_per_game"] = round(
                (p["named"]["goals"] + p["named"]["assists"]) / p["games"], 2
            )
        # Sessions are grouped by <=90-minute gaps, based only on archived matches.
        session = None
        for m in reversed(matches):
            if session is None or m["timestamp"] - session["end"] > 5400:
                session = {
                    "start": m["timestamp"],
                    "end": m["timestamp"],
                    "games": 0,
                    "W": 0,
                    "D": 0,
                    "L": 0,
                    "goals": 0,
                    "goalsAgainst": 0,
                }
                sessions[m["id"]] = session
            session["end"] = m["timestamp"]
            session["games"] += 1
            session[m["result"]] += 1
            session["goals"] += m["goals"]
            session["goalsAgainst"] += m["goalsAgainst"]
        info = (latest["info"] or {}).get("data", {}).get(club) or summary.get("clubInfo") or {}
        updated_members = [
            {
                "current": normalize(m),
                "labels": member_labels(m),
                "baseline": normalize(initial.get(m["name"], {})),
                "since_baseline": differences(initial.get(m["name"]), m, MEMBER_COUNTERS),
            }
            for m in members
        ]
        return {
            "club": self.config["club"],
            "info": decode_info(info),
            "summary": normalize(summary),
            "season": normalize(season),
            "tracking": self.tracking_totals(),
            "overall": normalize(overall),
            "labels": {
                "division": DIVISIONS.get(str(summary.get("currentDivision")), "Unresolved"),
                "reputation": REPUTATION.get(str(overall.get("reputationtier")), "Unresolved"),
            },
            "baseline": {
                "observed": baseline["observed"] if baseline else None,
                "overall": normalize(baseline_overall),
            },
            "since_baseline": differences(baseline_overall, overall, CLUB_COUNTERS),
            "counter_differences_uncertain": bool(counter_warnings),
            "initial_player_history": self.initial_player_history(),
            "members": updated_members,
            "career": normalize(career),
            "achievements": normalize((latest["achievements"] or {}).get("data", [])),
            "activity": {
                "active_until": int(self.state("active_until", 0)),
                "paused_until": int(self.state("cooldown_until", 0)),
            },
            "endpoint_times": {k: v["observed"] if v else None for k, v in latest.items()}
            | {
                row["endpoint"]: row["observed"]
                for row in self.db.execute(
                    "SELECT endpoint,MAX(observed) AS observed FROM snapshots GROUP BY endpoint"
                )
            },
            "archive": {
                "games": len(matches),
                "outcomes": dict(outcomes),
                "players": list(players.values()),
                "matches": matches[:500],
                "matches_shown": min(len(matches), 500),
                "team_named": dict(team_named),
                "ea_aggregate": dict(team_ea_aggregate),
                "events": dict(team_events),
                "unknown_events": dict(all_unknown),
                "event_player_rows": max(event_coverage.values(), default=0),
                "problems": problem_count,
                "opponents": list(opponents.values()),
                "sessions": list(reversed(list(sessions.values()))),
            },
            "match_trend": [
                {
                    "id": m["id"],
                    "timestamp": m["timestamp"],
                    "opponent": m["opponent"],
                    "goals": m["goals"],
                    "goalsAgainst": m["goalsAgainst"],
                    "result": m["result"],
                    "rating": round(
                        sum(p["rating"] for p in m["players"] if p["rating"] > 0)
                        / len([p for p in m["players"] if p["rating"] > 0]),
                        2,
                    )
                    if any(p["rating"] > 0 for p in m["players"])
                    else None,
                    **(
                        {
                            "named": m["named"],
                            "events": m["events"],
                            "rated_games": m["rated_games"],
                        }
                        if include_trends
                        else {}
                    ),
                }
                for m in reversed(matches)
            ],
            "division_history": self.division_history(),
            "trend": [
                {"observed": s["observed"], **normalize(select_club(s["data"], club))}
                for s in self.history("overall")
            ],
            "runs": [
                dict(r) for r in self.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 15")
            ],
            "warnings": [
                dict(r) for r in self.db.execute("SELECT * FROM warnings ORDER BY id DESC LIMIT 50")
            ],
            "cooldown_until": int(self.state("cooldown_until", 0)),
            "decoder": catalog(),
        }

    def trends(self, kind="all", start=None, end=None):
        dashboard = self.dashboard(kind, start, end, include_trends=True)
        return {
            "team": dashboard["match_trend"],
            "players": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "names": p["names"],
                    "history": list(reversed(p["history"])),
                }
                for p in dashboard["archive"]["players"]
            ],
        }


CLUB_COUNTERS = (
    "gamesPlayed",
    "wins",
    "losses",
    "ties",
    "goals",
    "goalsAgainst",
    "promotions",
    "relegations",
)
MEMBER_COUNTERS = (
    "gamesPlayed",
    "goals",
    "assists",
    "manOfTheMatch",
    "passesMade",
    "tacklesMade",
    "redCards",
    "cleanSheetsDef",
    "cleanSheetsGK",
)


def select_club(data, club):
    return next((item for item in data if str(item.get("clubId")) == club), {})


def differences(before, after, keys):
    if not before:
        return {key: None for key in keys}
    return {
        key: number(after[key]) - number(before[key])
        if key in before and key in after and number(after[key]) >= number(before[key])
        else None
        for key in keys
    }


def counter_drops(endpoint, before, after, club):
    if endpoint == "overall":
        pairs = [("club", select_club(before, club), select_club(after, club), CLUB_COUNTERS)]
    else:
        old = {m["name"]: m for m in before["members"]}
        pairs = [
            (m["name"], old[m["name"]], m, MEMBER_COUNTERS)
            for m in after["members"]
            if m["name"] in old
        ]
    return [
        f"{name}.{key}: {b[key]} → {a[key]}"
        for name, b, a, keys in pairs
        for key in keys
        if key in a and key in b and number(a[key]) < number(b[key])
    ]
