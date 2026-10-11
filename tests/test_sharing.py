"""Offline HTTP checks for the shared viewer; never calls EA or Tailscale."""

import base64
import json
import sqlite3
import tempfile
import threading
import tomllib
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

from proclubs.collector import import_seed
from proclubs.security import hash_password
from proclubs.server import BoundedHTTPServer, handler
from proclubs.store import Store

ROOT = Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / "tests/fixtures/config.toml").read_text())


class SharingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db = self.db = Path(self.temp.name) / "stats.sqlite3"
        import_seed(db, CONFIG, ROOT / "tests/fixtures/seed")
        credentials = {"username": "club", "password_hash": hash_password("test-password")}
        self.server = BoundedHTTPServer(("127.0.0.1", 0), handler(db, CONFIG, credentials))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def get(self, path, auth=None):
        request = urllib.request.Request(self.url + path)
        if auth:
            request.add_header("Authorization", auth)
        try:
            return urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc:
            return exc

    def auth(self, value="club:test-password"):
        return "Basic " + base64.b64encode(value.encode()).decode()

    def test_protected_trends_only_read_decoded_history(self):
        with self.get("/api/trends", self.auth()) as response:
            self.assertEqual(response.code, 200)
            trends = json.load(response)
            self.assertEqual(len(trends["team"]), 10)
            self.assertTrue(trends["players"][0]["history"][0]["events"])
            self.assertNotIn("runs", trends)
        with self.get("/api/trends?kind=bad", self.auth()) as response:
            self.assertEqual(response.code, 400)

    def test_protected_dashboard_includes_activity(self):
        with closing(Store(self.db, CONFIG)) as store:
            with store.db:
                store.set_state("active_until", 4102444800)
        with self.get("/api/dashboard", self.auth()) as response:
            dashboard = json.load(response)
            self.assertEqual(dashboard["activity"]["active_until"], 4102444800)
            self.assertEqual(dashboard["division_history"][0]["label"], "Division 1")
            self.assertNotIn("runs", dashboard)
            self.assertNotIn("warnings", dashboard)

    def test_match_only_check_advances_dashboard_update_time(self):
        with closing(Store(self.db, CONFIG)) as store:
            previous = store.latest("overall")["observed"]
            updated = previous + 600
            payload = store.latest("league")["data"]
            run = store.start_run("test", updated)
            store.ingest(run, "league", payload, updated)
            store.finish_run(run, "complete", updated)
        with self.get("/api/dashboard", self.auth()) as response:
            data = json.load(response)
            self.assertEqual(data["endpoint_times"]["overall"], previous)
            self.assertEqual(data["endpoint_times"]["league"], updated)
            self.assertEqual(max(t for t in data["endpoint_times"].values() if t), updated)
            self.assertEqual(data["archive"]["games"], 10)

    def test_non_get_methods_cannot_modify_archive(self):
        with closing(Store(self.db, CONFIG, readonly=True)) as s:
            before = s.export()
        for method in [
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
            "HEAD",
            "TRACE",
            "CONNECT",
            "CUSTOM",
        ]:
            for path in ["/api/dashboard", "/api/trends", "/api/collect", "/api/matches/1", "/"]:
                for auth in [None, self.auth()]:
                    request = urllib.request.Request(self.url + path, data=b"{}", method=method)
                    if auth:
                        request.add_header("Authorization", auth)
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request)
                    with caught.exception as response:
                        self.assertEqual(response.code, 405)
                        self.assertEqual(response.headers["Allow"], "GET")
        with closing(Store(self.db, CONFIG, readonly=True)) as s:
            self.assertEqual(s.export(), before)
        with self.get("/api/collect", self.auth()) as response:
            self.assertEqual(response.code, 404)

    def test_readonly_store_denies_writes_and_reads_collector_updates(self):
        reader = Store(self.db, CONFIG, readonly=True)
        writer = Store(self.db, CONFIG)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                reader.set_state("test-write", "blocked")
            with self.assertRaises(sqlite3.OperationalError):
                reader.db.execute("DELETE FROM matches")
            writer.set_state("test-update", "visible")
            writer.db.commit()
            self.assertEqual(reader.state("test-update"), "visible")
        finally:
            reader.close()
            writer.close()

    def test_every_route_requires_valid_credentials(self):
        for path in [
            "/",
            "/app.js",
            "/stat-help.js",
            "/style.css",
            "/health",
            "/api/dashboard",
            "/api/trends",
            "/api/export",
            "/api/players.csv",
            "/api/matches/1",
        ]:
            with self.get(path) as response:
                self.assertEqual(response.code, 401)
                self.assertIn("Basic", response.headers["WWW-Authenticate"])
        for auth in [
            "Basic !invalid!",
            self.auth("club:wrong"),
            self.auth("wrong:test-password"),
            self.auth("☃:test-password"),
            "Bearer test",
            self.auth("missing-colon"),
        ]:
            with self.get("/api/dashboard", auth) as response:
                self.assertEqual(response.code, 401)

    def test_failed_login_budget_is_enforced_over_http(self):
        for _ in range(20):
            with self.get("/health", "Basic invalid!") as response:
                self.assertEqual(response.code, 401)
        with self.get("/health", self.auth()) as response:
            self.assertEqual(response.code, 429)
            self.assertEqual(response.headers["Retry-After"], "60")

    def test_http_security_headers_and_strict_route_filters(self):
        with self.get("/health", self.auth()) as response:
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertIn("base-uri 'none'", response.headers["Content-Security-Policy"])
            self.assertNotIn("Python", response.headers["Server"])
        for path in [
            "/api/dashboard?start=-1",
            "/api/trends?kind=league&kind=friendly",
            "/api/dashboard?start=9&end=3",
        ]:
            with self.get(path, self.auth()) as response:
                self.assertEqual(response.code, 400)
        with self.get("/../config.toml", self.auth()) as response:
            self.assertEqual(response.code, 404)
        with self.get("/" + "a" * 2048, self.auth()) as response:
            self.assertEqual(response.code, 414)

    def test_viewer_works_without_archive_export_or_diagnostics(self):
        with self.get("/", self.auth()) as response:
            self.assertEqual(response.code, 200)
            self.assertNotIn(b'href="/api/export"', response.read())
        with self.get("/stat-help.js", self.auth()) as response:
            self.assertEqual(response.code, 200)
            self.assertIn(b"STAT_EXPLANATIONS", response.read())
        with self.get("/api/export", self.auth()) as response:
            self.assertEqual(response.code, 404)
        with self.get("/api/dashboard", self.auth()) as response:
            data = json.load(response)
            self.assertEqual(data["archive"]["games"], 10)
            self.assertNotIn("runs", data)
            self.assertNotIn("warnings", data)
            self.assertNotIn("decoder", data)
            self.assertNotIn("unknown_events", data["archive"])
            self.assertNotIn("baseline", data["tracking"]["players"][0])
            match_id = data["archive"]["matches"][0]["id"]
        with self.get("/api/matches/" + match_id, self.auth()) as response:
            self.assertIn("decoded_players", json.load(response))
        with self.get("/api/players.csv", self.auth()) as response:
            self.assertEqual(response.code, 200)
            self.assertIn(b"average_rating", response.read())


if __name__ == "__main__":
    unittest.main()
