"""Password verification and bounded failed-login throttling for the shared viewer."""

import base64
import hashlib
import hmac
import json
import secrets
import tempfile
import threading
import time
from collections import deque

ITERATIONS = 600_000
MAX_PASSWORD_BYTES = 1024


def hash_password(password):
    encoded = password.encode("utf-8")
    if not encoded or len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError("Password must contain 1–1024 UTF-8 bytes")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", encoded, salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def parse_password_hash(value):
    try:
        algorithm, iterations, salt, digest = value.split("$")
        count = int(iterations)
        salt, digest = bytes.fromhex(salt), bytes.fromhex(digest)
        if algorithm != "pbkdf2_sha256" or not ITERATIONS <= count <= 2_000_000:
            raise ValueError
        if len(salt) != 16 or len(digest) != 32:
            raise ValueError
        return count, salt, digest
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid sharing password verifier; run scripts/share.sh rotate") from exc


def validate_credentials(credentials):
    if not isinstance(credentials, dict):
        raise ValueError("Invalid sharing credentials")
    username = credentials.get("username")
    if (
        not isinstance(username, str)
        or not username
        or len(username.encode()) > 256
        or ":" in username
    ):
        raise ValueError("Invalid sharing username")
    parse_password_hash(credentials.get("password_hash"))


def authenticate(header, credentials):
    if not header or len(header) > 4096:
        return False
    try:
        scheme, token = header.split(" ", 1)
        if scheme.lower() != "basic":
            return False
        username, password = base64.b64decode(token, validate=True).decode("utf-8").split(":", 1)
        if len(password.encode()) > MAX_PASSWORD_BYTES:
            return False
        count, salt, expected = parse_password_hash(credentials["password_hash"])
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, count)
        return hmac.compare_digest(
            username.encode(), credentials["username"].encode()
        ) & hmac.compare_digest(actual, expected)
    except (KeyError, UnicodeError, ValueError):
        return False


def migrate_credentials(path, password_path):
    """Upgrade a private legacy verifier using the existing private password file."""
    credentials = json.loads(path.read_text())
    if not isinstance(credentials, dict):
        raise ValueError("Invalid sharing credentials")
    value = credentials.get("password_hash", "")
    if isinstance(value, str) and len(value) == 64:
        password = password_path.read_text().strip()
        if not hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), value):
            raise ValueError("Private password file does not match legacy sharing verifier")
        credentials["password_hash"] = hash_password(password)
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
            temporary = type(path)(output.name)
            output.write(json.dumps(credentials) + "\n")
        try:
            temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    validate_credentials(credentials)
    path.chmod(0o600)
    return credentials


class LoginThrottle:
    """Global failure window: proxies must not bypass it via forged forwarding headers."""

    def __init__(self, limit=20, window=60, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.failures = deque(maxlen=limit)
        self.lock = threading.Lock()

    def blocked(self):
        with self.lock:
            now = self.clock()
            while self.failures and self.failures[0] <= now - self.window:
                self.failures.popleft()
            return len(self.failures) >= self.limit

    def fail(self):
        with self.lock:
            self.failures.append(self.clock())
