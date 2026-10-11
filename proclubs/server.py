"""Bounded, authenticated read-only HTTP viewer. No HTTP route collects EA data."""

import csv
import io
import json
import re
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .decode import decode_player
from .security import LoginThrottle, authenticate, validate_credentials
from .store import Store

WEB = Path(__file__).resolve().parent.parent / "web"
STATIC = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/stat-help.js": ("stat-help.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
}
PUBLIC_FIELDS = (
    "club",
    "overall",
    "labels",
    "activity",
    "endpoint_times",
    "archive",
    "match_trend",
    "trend",
    "division_history",
    "tracking",
    "members",
    "career",
    "initial_player_history",
)
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'"


def query_filters(query):
    params = parse_qs(query, keep_blank_values=True, max_num_fields=8)
    if any(
        key not in {"kind", "start", "end"} or len(values) != 1 for key, values in params.items()
    ):
        raise ValueError("Invalid filter parameters")
    kind = params.get("kind", ["all"])[0]
    if kind not in {"all", "league", "friendly", "playoff"}:
        raise ValueError("Invalid match type")
    bounds = []
    for key in ("start", "end"):
        raw = params.get(key, [None])[0]
        if raw is not None and not re.fullmatch(r"\d{1,11}", raw):
            raise ValueError("Invalid date filter")
        value = int(raw) if raw is not None else None
        if value is not None and value > 253402300799:
            raise ValueError("Invalid date filter")
        bounds.append(value)
    start, end = bounds
    if start is not None and end is not None and start >= end:
        raise ValueError("End date must follow start date")
    return kind, start, end


def public_dashboard(data):
    data = {key: data[key] for key in PUBLIC_FIELDS}
    for key in ("unknown_events", "problems", "ea_aggregate"):
        data["archive"].pop(key, None)
    for player in data["archive"]["players"]:
        player.pop("unknown", None)
    for player in data["tracking"]["players"]:
        for key in ("baseline", "captured", "link"):
            player.pop(key, None)
    data["members"] = [{"current": member["current"]} for member in data["members"]]
    return data


def safe_csv_name(name):
    # Spreadsheet importers can ignore leading whitespace/control characters.
    return (
        "'" + name
        if name.lstrip().startswith(("=", "+", "-", "@")) or name.startswith(("\t", "\r", "\n"))
        else name
    )


def player_csv(data):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "player",
            "games",
            "goals",
            "assists",
            "average_rating",
            "pass_completion_percent",
            "tackle_success_percent",
            "interceptions",
            "second_assists",
        ]
    )
    for player in data["archive"]["players"]:
        writer.writerow(
            [
                safe_csv_name(player["name"]),
                player["games"],
                player["named"].get("goals", 0),
                player["named"].get("assists", 0),
                player["rating"],
                player["pass_completion"],
                player["tackle_success"],
                player["events"].get("interceptions", 0),
                player["events"].get("second_assists", 0),
            ]
        )
    return output.getvalue()


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, *args, max_workers=16, **kwargs):
        self.workers = threading.BoundedSemaphore(max_workers)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.workers.release()


def handler(db_path, config, sharing=None):
    if sharing is not None:
        validate_credentials(sharing)
    throttle = LoginThrottle()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ClubsTracker"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format, *args):
            # Never log queries or arbitrary user-controlled request lines.
            if format.startswith('"%s"'):
                print(f"HTTP {args[1]}", flush=True)

        def send(
            self, data, content_type="application/json", status=200, filename=None, headers=None
        ):
            if not isinstance(data, bytes):
                data = (
                    data.encode()
                    if isinstance(data, str)
                    else json.dumps(data, ensure_ascii=False).encode()
                )
            self.send_response(status)
            for key, value in {
                "Content-Type": content_type + "; charset=utf-8",
                "Content-Length": str(len(data)),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": CSP,
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "X-Frame-Options": "DENY",
                "Cross-Origin-Resource-Policy": "same-origin",
            }.items():
                self.send_header(key, value)
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def parse_request(self):
            if not super().parse_request():
                return False
            if self.command != "GET":
                self.close_connection = True
                self.send(
                    {"error": "This dashboard is read-only"},
                    status=405,
                    headers={"Allow": "GET", "Connection": "close"},
                )
                return False
            if len(self.path) > 2048:
                self.send({"error": "Request target too long"}, status=414)
                return False
            return True

        def do_GET(self):
            if sharing is not None:
                header = self.headers.get("Authorization")
                if throttle.blocked():
                    self.send(
                        {"error": "Try signing in again shortly"},
                        status=429,
                        headers={"Retry-After": "60"},
                    )
                    return
                if not authenticate(header, sharing):
                    # Missing credentials are a normal browser challenge, not a failed guess.
                    if header:
                        throttle.fail()
                    self.send(
                        {"error": "Sign in to view club stats"},
                        status=401,
                        headers={
                            "WWW-Authenticate": 'Basic realm="Clubs Tracker", charset="UTF-8"'
                        },
                    )
                    return
            try:
                parsed = urlsplit(self.path)
                if parsed.path in STATIC:
                    filename, mime = STATIC[parsed.path]
                    content = (WEB / filename).read_bytes()
                    if sharing is not None and filename == "index.html":
                        content = re.sub(
                            rb'<a\s+href="/api/export"[^>]*>.*?</a\s*>',
                            b"",
                            content,
                            flags=re.DOTALL,
                        )
                    self.send(content, mime)
                    return
                if parsed.path == "/health":
                    self.send({"status": "ok"})
                    return
                if parsed.path == "/api/export" and sharing is not None:
                    self.send({"error": "Not found"}, status=404)
                    return
                match_route = re.fullmatch(r"/api/matches/([\w-]{1,80})", parsed.path)
                if not match_route and parsed.path not in {
                    "/api/export",
                    "/api/dashboard",
                    "/api/players.csv",
                    "/api/trends",
                }:
                    self.send({"error": "Not found"}, status=404)
                    return
                filters = query_filters(parsed.query)
                store = Store(db_path, config, readonly=True)
                try:
                    if match_route:
                        raw = store.match(match_route[1])
                        if not raw:
                            self.send({"error": "Match not found"}, status=404)
                            return
                        self.send(
                            {
                                "raw": raw,
                                "decoded_players": {
                                    cid: {
                                        pid: decode_player(player)
                                        for pid, player in players.items()
                                    }
                                    for cid, players in raw.get("players", {}).items()
                                },
                            }
                        )
                    elif parsed.path == "/api/export":
                        self.send(store.export(), filename="clubs-archive.json")
                    elif parsed.path == "/api/trends":
                        self.send(store.trends(*filters))
                    else:
                        data = store.dashboard(*filters)
                        if sharing is not None:
                            data = public_dashboard(data)
                        if parsed.path.endswith(".csv"):
                            self.send(player_csv(data), "text/csv", filename="clubs-players.csv")
                        else:
                            self.send(data)
                finally:
                    store.close()
            except ValueError:
                self.send({"error": "Invalid request parameters"}, status=400)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                traceback.print_exc()
                self.send({"error": "Could not read archive"}, status=500)

    return Handler


def serve(db_path, config, port=None, sharing=None, host=None):
    host = host or config["dashboard"]["host"]
    if host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        raise ValueError("Unsupported listen address")
    if host == "0.0.0.0" and sharing is None:
        raise ValueError("Network binding requires --shared credentials")
    server = BoundedHTTPServer(
        (host, config["dashboard"]["port"] if port is None else port),
        handler(db_path, config, sharing),
    )
    print(f"Dashboard: http://{host}:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
