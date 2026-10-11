#!/usr/bin/env python3
"""Monitor public Funnel DNS and HTTPS; notify locally, never call EA."""

import base64
import http.client
import ipaddress
import json
import socket
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = (
    (ROOT / "data/funnel-host.txt").read_text().strip()
    if (ROOT / "data/funnel-host.txt").exists()
    else ""
)
STATE = ROOT / "data/funnel-watch.json"
ENABLED = ROOT / "data/funnel-watch.enabled"


def addresses():
    found = []
    for kind in ["A", "AAAA"]:
        url = f"https://dns.google/resolve?name={HOST}&type={kind}"
        with urllib.request.urlopen(url, timeout=10) as response:
            answer = json.load(response)
        for record in answer.get("Answer", []):
            if record.get("type") not in [1, 28]:
                continue
            address = ipaddress.ip_address(record["data"])
            if address.is_global:
                found.append(str(address))
    return list(dict.fromkeys(found))


class PublicHTTPS(http.client.HTTPSConnection):
    def __init__(self, address):
        super().__init__(HOST, timeout=10)
        self.address = address

    def connect(self):
        # Bypass private MagicDNS, preserving TLS hostname/certificate verification.
        sock = socket.create_connection((self.address, 443), timeout=10)
        try:
            self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=HOST)
        except Exception:
            sock.close()
            raise


def reachable(address):
    credentials = json.loads((ROOT / "data/sharing.json").read_text())
    password = (ROOT / "data/sharing-password.txt").read_text().strip()
    token = base64.b64encode(f"{credentials['username']}:{password}".encode()).decode()
    connection = PublicHTTPS(address)
    try:
        connection.request("GET", "/health", headers={"Authorization": "Basic " + token})
        response = connection.getresponse()
        body = response.read(4096)
        return response.status == 200 and json.loads(body).get("status") == "ok"
    finally:
        connection.close()


def notify(title, message):
    return (
        subprocess.run(
            [
                "notify-send",
                "--app-name=Pro Clubs Stats",
                "--urgency=normal",
                "--expire-time=0",
                title,
                message,
            ],
            capture_output=True,
            timeout=10,
        ).returncode
        == 0
    )


def main():
    if not ENABLED.exists() or not HOST:
        return
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["checked_at"] = int(time.time())
    try:
        ips = addresses()
        state["addresses"] = ips
        state["status"] = "dns-pending" if not ips else "https-pending"
        if ips and not state.get("dns_notified"):
            state["dns_notified"] = notify(
                "Funnel public DNS is ready",
                f"{HOST} now has a public address. Checking public HTTPS next.",
            )
        for address in ips[:3]:
            try:
                ready = reachable(address)
            except (OSError, ValueError, http.client.HTTPException):
                ready = False
            if ready:
                state["status"] = "ready"
                if not state.get("ready_notified"):
                    state["ready_notified"] = notify(
                        "Club dashboard is publicly reachable",
                        f"https://{HOST}/\nSign in with the shared club login.",
                    )
                break
        state.pop("error", None)
    except (OSError, ValueError) as exc:
        state["status"] = "check-failed"
        state["error"] = type(exc).__name__
    if (
        state.get("escalate_after")
        and time.time() >= state["escalate_after"]
        and state["status"] != "ready"
        and not state.get("escalation_notified")
    ):
        state["escalation_notified"] = notify(
            "Funnel still unavailable — contact Tailscale support",
            "The extra one-hour wait has elapsed. Public access is still unverified.\n"
            "Support details: your machine knowledge repository (Funnel diagnostics)\n"
            "No support ticket has been submitted automatically.",
        )
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    STATE.chmod(0o600)
    print(json.dumps(state), flush=True)
    if state.get("ready_notified") and state.get("dns_notified") and state["status"] == "ready":
        ENABLED.unlink(missing_ok=True)
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "pro-clubs-funnel-watch.timer"], check=True
        )


if __name__ == "__main__":
    main()
