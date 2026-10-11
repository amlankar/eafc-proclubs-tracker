#!/usr/bin/env bash
# Ongoing sharing administration; credentials stay in ignored data/.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
action="${1:-start}"
funnel_admin() {
  local result
  if result="$(tailscale funnel "$@" 2>&1)"; then
    printf '%s\n' "$result"
  elif [[ "$result" == *"Access denied: serve config denied"* ]]; then
    printf 'Tailscale requires local administrator permission for this change.\n'
    sudo tailscale funnel "$@"
  else
    printf '%s\n' "$result" >&2
    return 1
  fi
}
case "$action" in
  start|rotate)
    python3 - "$action" <<'PY'
import json, secrets, sys, os
from proclubs.security import hash_password, migrate_credentials
from pathlib import Path

os.umask(0o077)
folder = Path("data")
folder.mkdir(exist_ok=True, mode=0o700)
credentials = folder / "sharing.json"
if not credentials.exists() or sys.argv[1] == "rotate":
    password = secrets.token_urlsafe(18)
    credentials.write_text(
        json.dumps({"username": "club", "password_hash": hash_password(password)}) + "\n"
    )
    (folder / "sharing-password.txt").write_text(password + "\n")
    credentials.chmod(0o600)
    (folder / "sharing-password.txt").chmod(0o600)
else:
    migrate_credentials(credentials, folder / "sharing-password.txt")
PY
    bash scripts/setup.sh
    if [[ "$action" == start ]]; then
      if ! funnel_admin --bg --https=443 http://127.0.0.1:8766; then
        printf 'Viewer is ready. Funnel requires account enablement or administrator access; follow the message above.\n' >&2
        exit 1
      fi
    fi
    printf 'Username: club\nPassword is stored in data/sharing-password.txt (private, ignored by Git).\n'
    ;;
  stop)
    funnel_admin --https=443 off
    systemctl --user disable --now pro-clubs-share.service
    ;;
  status)
    tailscale funnel status
    systemctl --user is-active pro-clubs-share.service
    ;;
  *) printf 'Usage: bash scripts/share.sh [start|rotate|stop|status]\n' >&2; exit 2 ;;
esac
