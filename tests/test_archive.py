import copy
import fcntl
import json
import tempfile
import tomllib
import unittest
import urllib.error
from pathlib import Path

from proclubs.collector import collect, endpoints, import_seed
from proclubs.decode import decode_info, decode_player, normalize
from proclubs.store import Store

ROOT = Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / "tests/fixtures/config.toml").read_text())
SEED = ROOT / "tests/fixtures/seed"
MANIFEST = json.loads((SEED / "manifest.json").read_text())
BASE_TIME = MANIFEST["observed"]


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "stats.sqlite3"
        self.config = copy.deepcopy(CONFIG)
        import_seed(self.db, self.config, SEED)
        # Not in the real baseline: supply daily metadata only in the test archive.
        s = self.store()
        try:
            run = s.db.execute("SELECT id FROM runs LIMIT 1").fetchone()[0]
            s.ingest(run, "season", json.loads((SEED / "summary.json").read_text()), BASE_TIME)
        finally:
            s.close()

    def tearDown(self):
        self.temp.cleanup()

    def store(self):
        return Store(self.db, self.config)

    def test_division_history_uses_saved_observations_and_preserves_missing_values(self):
        s = self.store()
        seed = json.loads((SEED / "summary.json").read_text())
        run = s.start_run("test", BASE_TIME + 86400)
        changed = copy.deepcopy(seed)
        changed[0]["currentDivision"] = "1"
        s.ingest(run, "summary", changed, BASE_TIME + 86400)
        run = s.start_run("test", BASE_TIME + 172800)
        s.ingest(run, "summary", [], BASE_TIME + 172800)
        run = s.start_run("test", BASE_TIME + 259200)
        changed[0]["currentDivision"] = "99"
        s.ingest(run, "summary", changed, BASE_TIME + 259200)
        points = s.dashboard()["division_history"]
        self.assertEqual([p["division"] for p in points], [2, 1, None, None])
        self.assertEqual([p["label"] for p in points], ["Division 1", "Elite", None, None])
        self.assertEqual(points[0]["observed"], BASE_TIME)
        self.assertEqual(s.dashboard(start=BASE_TIME + 300000)["division_history"], points)
        self.assertNotIn("division_history", s.trends())
        s.close()

    def test_trends_reconstruct_match_fields_independent_of_global_snapshots(self):
        s = self.store()
        try:
            trends = s.trends()
            self.assertEqual(len(trends["team"]), 10)
            self.assertEqual(trends["team"], sorted(trends["team"], key=lambda p: p["timestamp"]))
            point = trends["team"][0]
            raw = s.match(point["id"])
            club = str(self.config["club"]["id"])
            self.assertEqual(
                point["named"]["goalsconceded"], int(raw["clubs"][club]["goalsAgainst"])
            )
            for player in trends["players"]:
                for entry in player["history"]:
                    row = s.match(entry["match_id"])["players"][club][player["id"]]
                    decoded = decode_player(row)
                    self.assertEqual(
                        entry["events"], {k: v["value"] for k, v in decoded["decoded"].items()}
                    )
                    self.assertEqual(entry["named"]["passesmade"], int(row["passesmade"]))
                    self.assertEqual(entry["pass_completion"], decoded["ratios"]["pass_completion"])
            self.assertEqual(set(trends), {"team", "players"})
            run = s.start_run("test-global-change", BASE_TIME + 100)
            members = copy.deepcopy(s.latest("members")["data"])
            for member in members["members"]:
                member.update(goals="9999", gamesPlayed="10000", ratingAve="1.0")
            overall = copy.deepcopy(s.latest("overall")["data"])
            overall[0].update(goals="99999", gamesPlayed="10000", skillRating="999")
            s.ingest(run, "members", members, BASE_TIME + 100)
            s.ingest(run, "overall", overall, BASE_TIME + 100)
            self.assertEqual(s.trends(), trends)
            self.assertEqual(s.trends("playoff")["team"], [])
            self.assertEqual(
                len(s.trends(start=point["timestamp"], end=point["timestamp"] + 1)["team"]), 1
            )
            self.assertEqual(s.trends(start=BASE_TIME + 1000)["team"], [])
        finally:
            s.close()

    def test_trends_keep_more_than_match_list_limit_and_missing_events_are_null(self):
        s = self.store()
        try:
            match = json.loads((SEED / "league.json").read_text())[0]
            club = str(self.config["club"]["id"])
            for row in match["players"][club].values():
                for key in list(row):
                    if key.startswith("match_event_"):
                        del row[key]
                row["rating"] = "0"
            batch = []
            for i in range(501):
                copy_match = copy.deepcopy(match)
                copy_match["matchId"] = str(99000000000000 + i)
                copy_match["timestamp"] = BASE_TIME + 100 + i
                batch.append(copy_match)
            run = s.db.execute("SELECT id FROM runs LIMIT 1").fetchone()[0]
            s.ingest(run, "league", batch, BASE_TIME + 1000)
            self.assertEqual(len(s.dashboard()["archive"]["matches"]), 500)
            trends = s.trends()
            self.assertEqual(len(trends["team"]), 511)
            self.assertIsNone(trends["team"][-1]["events"])
            self.assertIsNone(trends["team"][-1]["rating"])
            self.assertIsNone(trends["players"][0]["history"][-1]["events"])
        finally:
            s.close()

    def test_seed_is_idempotent_and_not_added_to_matches(self):
        result = import_seed(self.db, self.config, SEED)
        self.assertEqual(result["status"], "skipped")
        s = self.store()
        try:
            dashboard = s.dashboard()
            self.assertEqual(dashboard["overall"]["gamesPlayed"], 62)
            self.assertEqual(dashboard["archive"]["games"], 10)
            self.assertEqual(dashboard["since_baseline"]["gamesPlayed"], 0)
            self.assertEqual(dashboard["labels"]["division"], "Division 1")
            self.assertEqual(s.db.execute("SELECT count(*) FROM runs").fetchone()[0], 1)
        finally:
            s.close()

    def test_initial_history_missing_matches_is_per_player_and_filter_independent(self):
        s = self.store()
        try:
            expected = {
                "player-one": 52,
                "player-two": 50,
                "player-three": 36,
                "player-four": 33,
                "player-five": 44,
            }
            original = s.dashboard()["initial_player_history"]
            self.assertEqual({p["name"]: p["missing_matches"] for p in original}, expected)
            self.assertTrue(all(p["id"] for p in original))
            self.assertEqual(
                s.dashboard("playoff", BASE_TIME + 1)["initial_player_history"], original
            )
            matches = json.loads((SEED / "league.json").read_text())
            for match in matches:
                match["matchId"] = "later-" + str(match["matchId"])
                match["timestamp"] = BASE_TIME + 3600
            run = s.start_run("test", BASE_TIME + 7200)
            s.ingest(run, "league", matches, BASE_TIME + 7200)
            self.assertEqual(s.dashboard()["initial_player_history"], original)
        finally:
            s.close()

    def test_null_club_details_preserve_match_stats(self):
        matches = json.loads((SEED / "league.json").read_text())
        for club in matches[0]["clubs"].values():
            club["details"] = None
        s = self.store()
        try:
            before = s.dashboard()["archive"]
            run = s.start_run("test", BASE_TIME + 3600)
            s.ingest(run, "league", matches, BASE_TIME + 3600)
            after = s.dashboard()["archive"]
            self.assertEqual(after["games"], before["games"])
            self.assertEqual(after["team_named"], before["team_named"])
            match = next(m for m in after["matches"] if m["id"] == str(matches[0]["matchId"]))
            self.assertEqual(match["opponent"], "Opponent")
        finally:
            s.close()

    def test_repeated_matches_update_without_double_counting(self):
        s = self.store()
        try:
            before = s.dashboard()["archive"]
            matches = json.loads((SEED / "league.json").read_text())
            run = s.start_run("test", BASE_TIME + 3600)
            s.ingest(run, "league", matches, BASE_TIME + 3600)
            self.assertEqual(before["events"], s.dashboard()["archive"]["events"])
            self.assertEqual(before["games"], s.dashboard()["archive"]["games"])
            # EA can correct a match after the initial observation.
            player = next(iter(matches[0]["players"]["900001"].values()))
            player["goals"] = str(int(player["goals"]) + 1)
            s.ingest(run, "league", matches, BASE_TIME + 3601)
            after = s.dashboard()["archive"]
            self.assertEqual(after["games"], 10)
            self.assertEqual(after["team_named"]["goals"], before["team_named"]["goals"] + 1)
            self.assertGreater(s.db.execute("SELECT count(*) FROM responses").fetchone()[0], 10)
        finally:
            s.close()

    def test_filters_and_weighted_rates(self):
        s = self.store()
        try:
            archive = s.dashboard()["archive"]
            self.assertEqual(s.dashboard("friendly")["archive"]["games"], 0)
            latest = archive["matches"][0]
            selected = s.dashboard(start=latest["timestamp"], end=latest["timestamp"] + 1)[
                "archive"
            ]
            self.assertEqual(selected["games"], 1)
            player = next(p for p in selected["players"] if p["name"] == "player-one")
            self.assertEqual(player["pass_completion"], round(24 / 34 * 100, 2))
            self.assertEqual(player["rating"], 7.9)
            self.assertEqual(player["events"]["interceptions"], 2)
            self.assertEqual(archive["outcomes"]["W"], 6)
        finally:
            s.close()

    def test_tracking_totals_start_at_baseline_and_survive_snapshot_reset(self):
        s = self.store()
        try:
            initial = s.dashboard()["tracking"]
            self.assertEqual(initial["club"]["gamesPlayed"], 62)
            self.assertEqual(initial["post_baseline_games"], 0)
            self.assertEqual(
                next(p for p in initial["players"] if p["name"] == "player-one")["totals"]["goals"],
                12,
            )
            match = json.loads((SEED / "league.json").read_text())[0]
            match["matchId"] = "post-baseline-game"
            match["timestamp"] = BASE_TIME + 3600
            pid = next(
                k for k, p in match["players"]["900001"].items() if p["playername"] == "player-one"
            )
            match["players"]["900001"][pid]["playername"] = "player-one-renamed"
            match["players"]["900001"][pid]["goals"] = "2"
            run = s.start_run("test", BASE_TIME + 4000)
            s.ingest(run, "league", [match], BASE_TIME + 4000)
            s.ingest(run, "league", [match], BASE_TIME + 4001)
            reset = json.loads((SEED / "members.json").read_text())
            reset["members"][0]["goals"] = "0"
            s.ingest(run, "members", reset, BASE_TIME + 4001)
            ledger = s.dashboard("friendly")["tracking"]
            self.assertEqual(ledger["club"]["gamesPlayed"], 63)
            self.assertEqual(ledger["post_baseline_games"], 1)
            player = next(p for p in ledger["players"] if p["id"] == pid)
            self.assertEqual(player["totals"]["goals"], 14)
            self.assertEqual(player["totals"]["games"], 63)
            self.assertEqual(player["name"], "player-one-renamed")
        finally:
            s.close()

    def test_chart_history_matches_totals_and_respects_filters(self):
        s = self.store()
        try:
            d = s.dashboard()
            trend = d["match_trend"]
            self.assertEqual(len(trend), d["archive"]["games"])
            self.assertEqual([m["timestamp"] for m in trend], sorted(m["timestamp"] for m in trend))
            self.assertEqual(sum(m["goals"] for m in trend), d["archive"]["outcomes"]["goals"])
            for p in d["archive"]["players"]:
                self.assertEqual(len(p["history"]), p["games"])
                self.assertEqual(len({m["match_id"] for m in p["history"]}), p["games"])
                self.assertEqual(sum(m["goals"] for m in p["history"]), p["named"]["goals"])
                self.assertEqual(sum(m["passes"] for m in p["history"]), p["named"]["passesmade"])
                self.assertEqual(
                    p["shot_conversion"],
                    round(100 * p["named"]["goals"] / p["named"]["shots"], 2)
                    if p["named"]["shots"]
                    else None,
                )
            latest = trend[-1]
            selected = s.dashboard(start=latest["timestamp"], end=latest["timestamp"] + 1)
            self.assertEqual(selected["match_trend"], [latest])
            self.assertTrue(all(len(p["history"]) == 1 for p in selected["archive"]["players"]))
            self.assertEqual(s.dashboard("friendly")["match_trend"], [])
        finally:
            s.close()

    def test_missing_ratings_are_chart_gaps_and_corrections_replace_points(self):
        s = self.store()
        try:
            match = json.loads((SEED / "league.json").read_text())[0]
            for p in match["players"]["900001"].values():
                p["rating"] = "0"
            run = s.start_run("test", BASE_TIME + 3600)
            s.ingest(run, "league", [match], BASE_TIME + 3600)
            d = s.dashboard(start=match["timestamp"], end=match["timestamp"] + 1)
            self.assertEqual(len(d["match_trend"]), 1)
            self.assertIsNone(d["match_trend"][0]["rating"])
            for p in d["archive"]["players"]:
                self.assertIsNone(p["history"][0]["rating"])
                self.assertIsNone(p["rating"])
            next(iter(match["players"]["900001"].values()))["rating"] = "8.5"
            s.ingest(run, "league", [match], BASE_TIME + 3601)
            d = s.dashboard(start=match["timestamp"], end=match["timestamp"] + 1)
            self.assertEqual(len(d["match_trend"]), 1)
            self.assertEqual(d["match_trend"][0]["rating"], 8.5)
        finally:
            s.close()

    def test_name_changes_keep_stable_archive_player_id(self):
        s = self.store()
        try:
            match = json.loads((SEED / "league.json").read_text())[0]
            player_id = next(iter(match["players"]["900001"]))
            match["matchId"] = "new-match"
            match["timestamp"] += 3600
            match["players"]["900001"][player_id]["playername"] = "renamed_player"
            run = s.start_run("test", BASE_TIME + 3600)
            s.ingest(run, "league", [match], BASE_TIME + 3600)
            p = next(p for p in s.dashboard()["archive"]["players"] if p["id"] == player_id)
            self.assertIn("player-one", p["names"])
            self.assertIn("renamed_player", p["names"])
        finally:
            s.close()

    def test_reset_is_flagged_without_inventing_totals(self):
        s = self.store()
        try:
            old = json.loads((SEED / "members.json").read_text())
            old["members"][0]["goals"] = "0"
            run = s.start_run("test", BASE_TIME + 3600)
            s.ingest(run, "members", old, BASE_TIME + 3600)
            d = s.dashboard()
            self.assertTrue(d["counter_differences_uncertain"])
            self.assertIsNone(d["members"][0]["since_baseline"]["goals"])
            self.assertTrue(any(w["code"] == "counter_decrease" for w in d["warnings"]))
        finally:
            s.close()

    def test_full_new_window_warns_of_gap(self):
        s = self.store()
        try:
            appearances = {p["id"]: p["games"] for p in s.dashboard()["archive"]["players"]}
            matches = json.loads((SEED / "league.json").read_text())
            for i, m in enumerate(matches):
                m["matchId"] = f"new-{i}"
            run = s.start_run("test", BASE_TIME + 3600)
            s.ingest(run, "league", matches, BASE_TIME + 3600)
            d = s.dashboard()
            self.assertEqual(d["archive"]["games"], 20)
            self.assertEqual(len(d["match_trend"]), 20)
            for p in d["archive"]["players"]:
                self.assertEqual(p["games"], appearances[p["id"]] * 2)
                self.assertEqual(len(p["history"]), p["games"])
            s.ingest(run, "league", matches, BASE_TIME + 3601)
            self.assertEqual(s.dashboard()["archive"]["games"], 20)
            self.assertTrue(any(w["code"] == "history_gap" for w in d["warnings"]))
        finally:
            s.close()

    def test_configuration_cannot_mix_editions(self):
        other = copy.deepcopy(self.config)
        other["club"]["edition"] = "FC28"
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            Store(self.db, other)

    def test_wrong_club_match_rejected(self):
        s = self.store()
        try:
            matches = json.loads((SEED / "league.json").read_text())
            matches[0]["clubs"]["900001"]["details"]["name"] = "Another Club"
            with self.assertRaisesRegex(ValueError, "name differs"):
                s.ingest(s.start_run("test"), "league", matches)
        finally:
            s.close()

    def test_block_aborts_without_retries_and_persists_cooldown(self):
        calls = []

        def blocked(url, timeout):
            calls.append(url)
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

        now = BASE_TIME + 90000
        result = collect(self.db, self.config, request=blocked, now=now, sleeper=lambda _: None)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["cooldown_until"], now + 86400)
        result = collect(self.db, self.config, request=blocked, now=now + 3600)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(len(calls), 1)

    def test_minimum_interval_and_concurrent_lock(self):
        def forbidden(*args):
            self.fail("Should not call EA")

        self.assertEqual(
            collect(self.db, self.config, request=forbidden, now=BASE_TIME + 10)["status"],
            "skipped",
        )
        with (self.db.parent / "collector.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(
                collect(self.db, self.config, request=forbidden, now=BASE_TIME + 90000)["status"],
                "skipped",
            )

    def test_partial_batch_keeps_success_and_no_extra_calls(self):
        called = []

        def partial(url, timeout):
            label = next(
                label for label, endpoint, daily in endpoints(self.config) if endpoint == url
            )
            called.append(label)
            if label == "members":
                raise urllib.error.URLError("timeout")
            return json.loads((SEED / (label + ".json")).read_text()), 200

        result = collect(
            self.db, self.config, request=partial, now=BASE_TIME + 3600, sleeper=lambda _: None
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(called, ["overall", "members"])
        s = self.store()
        try:
            self.assertEqual(s.latest("overall")["observed"], BASE_TIME + 3600)
        finally:
            s.close()

    def test_http_429_respects_long_retry_after(self):
        def limited(url, timeout):
            raise urllib.error.HTTPError(url, 429, "Limited", {"Retry-After": "172800"}, None)

        result = collect(
            self.db, self.config, request=limited, now=BASE_TIME + 90000, sleeper=lambda _: None
        )
        self.assertEqual(result["cooldown_until"], BASE_TIME + 90000 + 172800)

    def test_regular_batch_is_six_spaced_requests(self):
        calls, spacings = [], []

        def success(url, timeout):
            label = next(
                label for label, endpoint, daily in endpoints(self.config) if endpoint == url
            )
            calls.append(label)
            return json.loads((SEED / (label + ".json")).read_text()), 200

        result = collect(
            self.db, self.config, request=success, now=BASE_TIME + 3600, sleeper=spacings.append
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(calls, ["overall", "members", "career", "league", "friendly", "playoff"])
        self.assertEqual(spacings, [3] * 5)

    def test_active_play_checks_matches_only_and_expires(self):
        now = BASE_TIME + 3600
        calls, spacings = [], []
        new_match = copy.deepcopy(json.loads((SEED / "league.json").read_text())[0])
        new_match.update(matchId="active-new", timestamp=now - 1740)

        def request(url, timeout):
            label = next(label for label, endpoint, _ in endpoints(self.config) if endpoint == url)
            calls.append(label)
            payload = json.loads((SEED / (label + ".json")).read_text())
            if label == "league":
                payload = [new_match] + payload[:9]
            return payload, 200

        collect(self.db, self.config, request=request, now=now, sleeper=spacings.append)
        s = self.store()
        self.assertEqual(int(s.state("active_until", 0)), now + 1800)
        self.assertEqual(s.dashboard()["activity"]["active_until"], now + 1800)
        s.close()
        calls.clear()
        spacings.clear()
        self.assertEqual(
            collect(self.db, self.config, request=request, now=now + 599)["status"], "skipped"
        )
        self.assertFalse(calls)
        result = collect(
            self.db, self.config, request=request, now=now + 600, sleeper=spacings.append
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(calls, ["league", "friendly", "playoff"])
        self.assertEqual(spacings, [3, 3])
        s = self.store()
        self.assertEqual(
            int(s.state("active_until", 0)), now + 1800
        )  # Repeated window never extends play.
        self.assertEqual(s.latest("overall")["observed"], now)
        s.close()
        calls.clear()
        # Active status expires; the last request still enforces the idle interval.
        self.assertEqual(
            collect(self.db, self.config, request=request, now=now + 1800)["status"], "skipped"
        )
        self.assertFalse(calls)
        collect(self.db, self.config, request=request, now=now + 4200, sleeper=lambda _: None)
        self.assertEqual(calls, ["overall", "members", "career", "league", "friendly", "playoff"])

    def test_active_session_extends_and_global_stats_stay_hourly(self):
        now = BASE_TIME + 3600
        calls = []
        match = copy.deepcopy(json.loads((SEED / "league.json").read_text())[0])

        def request(url, timeout):
            label = next(label for label, endpoint, _ in endpoints(self.config) if endpoint == url)
            calls.append(label)
            payload = json.loads((SEED / (label + ".json")).read_text())
            if label == "league":
                payload = [match] + payload[:9]
            return payload, 200

        for offset in range(0, 3601, 600):
            match.update(matchId=f"session-{offset}", timestamp=now + offset)
            calls.clear()
            collect(self.db, self.config, request=request, now=now + offset, sleeper=lambda _: None)
            self.assertEqual(len(calls), 6 if offset in {0, 3600} else 3)
        s = self.store()
        self.assertEqual(int(s.state("active_until", 0)), now + 5400)
        s.close()

        def blocked(url, timeout):
            raise urllib.error.HTTPError(url, 429, "Rate limited", {"Retry-After": "172800"}, None)

        result = collect(
            self.db, self.config, request=blocked, now=now + 4200, sleeper=lambda _: None
        )
        self.assertEqual(result["cooldown_until"], now + 4200 + 172800)
        self.assertEqual(
            collect(self.db, self.config, request=request, now=now + 4800)["reason"], "EA cooldown"
        )

    def test_old_or_future_new_matches_do_not_mark_active(self):
        now = BASE_TIME + 3600
        matches = json.loads((SEED / "league.json").read_text())
        old, future = copy.deepcopy(matches[0]), copy.deepcopy(matches[0])
        old.update(matchId="old-new", timestamp=now - 1800)
        future.update(matchId="future-new", timestamp=now + 10)

        def request(url, timeout):
            label = next(label for label, endpoint, _ in endpoints(self.config) if endpoint == url)
            return (
                [old, future]
                if label == "league"
                else json.loads((SEED / (label + ".json")).read_text())
            ), 200

        collect(self.db, self.config, request=request, now=now, sleeper=lambda _: None)
        s = self.store()
        self.assertEqual(int(s.state("active_until", 0)), 0)
        s.close()

    def test_export_retains_raw_unknown_fields_and_responses(self):
        s = self.store()
        try:
            export = s.export()
            match = export["matches"][0]
            self.assertIn("aggregate", match)
            self.assertIn(
                "match_event_aggregate_0", next(iter(match["players"]["900001"].values()))
            )
            self.assertEqual(len(export["snapshots"]), 10)
        finally:
            s.close()


class DecoderTests(unittest.TestCase):
    def test_bucket_duplicates_malformed_unknowns_and_safe_arithmetic(self):
        p = decode_player(
            {
                "match_event_aggregate_0": "215:10,30:4,32:2,34:3,112:1,38:2,9999:7,broken",
                "match_event_aggregate_1": "215:10",
                "passesmade": "10",
                "passattempts": "20",
                "goals": "0",
                "assists": "0",
                "shots": "0",
            }
        )
        self.assertEqual(p["events"]["215"], 10)
        self.assertEqual(p["unknown_events"], {"9999": 7})
        self.assertEqual(p["decoded"]["passes_completed_direction_unknown"]["value"], 1)
        self.assertEqual(p["decoded"]["dribble_beat_without_skill_move"]["value"], 0)
        self.assertEqual(len(p["problems"]), 2)
        self.assertEqual(p["ratios"]["pass_completion"], 50)
        self.assertIsNone(p["ratios"]["tackle_success"])

    def test_identifiers_names_and_region_rgb(self):
        self.assertEqual(
            normalize({"name": "12345", "matchId": "12345678901234567", "goals": "4"}),
            {"name": "12345", "matchId": "12345678901234567", "goals": 4},
        )
        info = decode_info({"regionId": 4543827, "customKit": {"kitColor1": "16777215"}})
        self.assertEqual(info["region_code"], "EUS")
        self.assertEqual(info["kit_colours"]["kitColor1"], "#ffffff")


if __name__ == "__main__":
    unittest.main()
