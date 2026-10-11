#!/usr/bin/env bash
# Explicit, temporary sharing fallback. Never enabled by normal setup.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
unit=pro-clubs-cloudflare-day.service
case "${1:-status}" in
  start)
    [[ -f "$project_dir/data/sharing.json" ]] || { echo 'Configure the protected viewer first.'; exit 1; }
    systemctl --user is-active --quiet pro-clubs-share.service
    if systemctl --user is-active --quiet "$unit"; then
      echo 'Temporary tunnel already running; its deadline is unchanged.'
      exit 0
    fi
    python3 - "$project_dir" <<'PY'
import hashlib, pathlib, sys, urllib.request

binary = pathlib.Path(sys.argv[1]) / "data/tools/cloudflared"
expected = "d33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db"
if not binary.exists() or hashlib.sha256(binary.read_bytes()).hexdigest() != expected:
    url = "https://github.com/cloudflare/cloudflared/releases/download/2026.10.0/cloudflared-linux-amd64"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read(64 * 1024 * 1024 + 1)
        if len(payload) > 64 * 1024 * 1024:
            raise SystemExit("cloudflared release exceeds download limit")
    if hashlib.sha256(payload).hexdigest() != expected:
        raise SystemExit("cloudflared release checksum mismatch")
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(payload)
    binary.chmod(0o700)
PY
    systemctl --user reset-failed "$unit" 2>/dev/null || true
    systemd-run --user --unit="$unit" --collect \
      --description='Temporary Pro Clubs Cloudflare tunnel (24 hours maximum)' \
      --property=RuntimeMaxSec=24h --property=Restart=no \
      --property=NoNewPrivileges=yes --property=UMask=0077 \
      "$project_dir/data/tools/cloudflared" tunnel --no-autoupdate \
      --protocol http2 --url http://127.0.0.1:8766
    ;;
  stop) systemctl --user stop "$unit" ;;
  status)
    systemctl --user status "$unit" --no-pager || true
    journalctl --user -u "$unit" -n 60 --no-pager | rg 'https://[a-z0-9-]+\.trycloudflare\.com' || true
    ;;
  *) echo 'Usage: cloudflare-day.sh start|status|stop'; exit 2 ;;
esac
