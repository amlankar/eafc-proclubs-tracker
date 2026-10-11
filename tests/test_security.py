"""Offline regressions for the actual HTTP and authentication trust boundaries."""

import base64
import hashlib
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from test_archive import CONFIG

from proclubs.config import validate_config
from proclubs.security import (
    LoginThrottle,
    authenticate,
    hash_password,
    migrate_credentials,
    parse_password_hash,
    validate_credentials,
)
from proclubs.server import BoundedHTTPServer, handler, query_filters, safe_csv_name, serve


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.credentials = {"username": "club", "password_hash": hash_password("päss:word")}

    def test_salted_passwords_and_constant_format_validation(self):
        other = hash_password("päss:word")
        self.assertNotEqual(other, self.credentials["password_hash"])
        for value in ["x" * 64, "pbkdf2_sha256$1$00$00", None, "pbkdf2_sha256$999999999$00$00"]:
            with self.assertRaises(ValueError):
                parse_password_hash(value)
        good = "Basic " + base64.b64encode("club:päss:word".encode()).decode()
        self.assertTrue(authenticate(good, self.credentials))
        for value in [
            None,
            "Basic !!!",
            "Bearer token",
            "Basic " + base64.b64encode(b"club:wrong").decode(),
            "x" * 5000,
        ]:
            self.assertFalse(authenticate(value, self.credentials))

    def test_password_migration_keeps_the_current_password_and_private_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sharing.json"
            password = Path(folder) / "password.txt"
            password.write_text("existing-password\n")
            path.write_text(
                json.dumps(
                    {
                        "username": "club",
                        "password_hash": hashlib.sha256(b"existing-password").hexdigest(),
                    }
                )
            )
            credentials = migrate_credentials(path, password)
            token = "Basic " + base64.b64encode(b"club:existing-password").decode()
            self.assertTrue(authenticate(token, credentials))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(migrate_credentials(path, password), credentials)

    def test_throttle_expires_and_does_not_grow_unbounded(self):
        now = [0]
        throttle = LoginThrottle(limit=2, window=60, clock=lambda: now[0])
        self.assertFalse(throttle.blocked())
        throttle.fail()
        throttle.fail()
        self.assertTrue(throttle.blocked())
        for _ in range(100):
            throttle.fail()
        self.assertEqual(len(throttle.failures), 2)
        now[0] = 60
        self.assertFalse(throttle.blocked())

    def test_bad_filters_fail_before_archive_queries(self):
        for query in [
            "kind=bad",
            "kind=league&kind=friendly",
            "start=-1",
            "start=nan",
            "start=5&end=4",
            "start=5&end=5",
            "other=x",
            "start=999999999999999",
            "&".join(["kind=all"] * 9),
        ]:
            with self.assertRaises(ValueError):
                query_filters(query)
        self.assertEqual(query_filters("kind=playoff&start=0&end=9"), ("playoff", 0, 9))

    def test_csv_formula_prefixes_and_whitespace(self):
        for name in [
            "=1+1",
            "+1",
            "-1",
            "@SUM(A1)",
            "  =1+1",
            "\tformula",
            "\rformula",
            "\nformula",
        ]:
            self.assertTrue(safe_csv_name(name).startswith("'"))
        self.assertEqual(safe_csv_name("player-one"), "player-one")

    def test_config_cannot_disable_api_cooldowns(self):
        import copy

        for key, value in [
            ("minimum_interval_seconds", 10),
            ("active_interval_seconds", 10),
            ("block_cooldown_seconds", 10),
            ("error_cooldown_seconds", 10),
            ("request_spacing_seconds", True),
            ("timeout_seconds", 0),
        ]:
            config = copy.deepcopy(CONFIG)
            config["collector"][key] = value
            with self.assertRaises(ValueError):
                validate_config(config)

    def test_unauthenticated_network_binding_fails(self):
        with self.assertRaisesRegex(ValueError, "Network binding"):
            serve("unused", CONFIG, host="0.0.0.0")

    def test_request_saturation_is_bounded_and_recovers(self):
        gate = threading.Event()
        entered = threading.Event()

        class DummyHandler:
            def __init__(self, *args):
                entered.set()
                gate.wait(2)

        server = BoundedHTTPServer(("127.0.0.1", 0), DummyHandler, max_workers=1)
        first, peer = socket.socketpair()
        second, second_peer = socket.socketpair()
        try:
            server.process_request(first, ("127.0.0.1", 1))
            self.assertTrue(entered.wait(1))
            server.process_request(second, ("127.0.0.1", 2))
            self.assertEqual(second.fileno(), -1)
            gate.set()
            self.assertTrue(server.workers.acquire(timeout=2))
            server.workers.release()
        finally:
            gate.set()
            peer.close()
            second_peer.close()
            server.server_close()

    def test_malformed_configuration_and_credentials_are_rejected(self):
        for value in [None, [], "invalid", {"club": [], "collector": [], "dashboard": []}]:
            with self.assertRaises(ValueError):
                validate_config(value)
        for value in [None, [], "invalid", {}]:
            with self.assertRaises(ValueError):
                validate_credentials(value)

    def test_handlers_validate_credentials_before_serving(self):
        with self.assertRaises(ValueError):
            handler("unused", CONFIG, {"username": "club", "password_hash": "0" * 64})
