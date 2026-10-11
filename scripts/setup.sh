#!/usr/bin/env bash
# Primary, idempotent provisioning entrypoint. No downloads or EA requests.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$(command -v python3)"
"$python_bin" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
data_dir="$project_dir/data"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$data_dir" "$unit_dir"
chmod 700 "$data_dir"
cd "$project_dir"
if [[ ! -f config.toml ]]; then
  cp config.example.toml config.toml
  printf 'Created config.toml. Set your club ID, name and platform, then rerun setup.\n'
  exit 0
fi
if [[ ! -f "$data_dir/stats.sqlite3" ]]; then
  if [[ -f "$data_dir/seed/manifest.json" ]]; then
    "$python_bin" -m proclubs import-seed
  else
    "$python_bin" -m proclubs init
  fi
fi
cat > "$unit_dir/pro-clubs-collect.service" <<EOF
[Unit]
Description=Archive EA FC Clubs stats

[Service]
Type=oneshot
WorkingDirectory=$project_dir
ExecStart="$python_bin" -m proclubs collect
UMask=0077
TimeoutStartSec=300
NoNewPrivileges=yes
MemoryMax=256M
TasksMax=16
LimitNOFILE=256
EOF
cat > "$unit_dir/pro-clubs-collect.timer" <<'EOF'
[Unit]
Description=Check adaptive EA FC Clubs collection schedule

[Timer]
OnCalendar=*-*-* *:*:00
AccuracySec=10
Persistent=true
Unit=pro-clubs-collect.service

[Install]
WantedBy=timers.target
EOF
# Retire the former unprotected home-network viewer.
if [[ -f "$unit_dir/pro-clubs-dashboard.service" ]]; then
  systemctl --user disable --now pro-clubs-dashboard.service
  rm -- "$unit_dir/pro-clubs-dashboard.service"
fi
if [[ -f "$data_dir/sharing.json" ]]; then
  "$python_bin" - <<'PYCODE'
from pathlib import Path
from proclubs.security import migrate_credentials

migrate_credentials(Path("data/sharing.json"), Path("data/sharing-password.txt"))
PYCODE
  cat > "$unit_dir/pro-clubs-share.service" <<EOF
[Unit]
Description=EA FC Clubs password-protected shared viewer

[Service]
Type=simple
WorkingDirectory=$project_dir
ExecStart="$python_bin" -m proclubs serve --port 8766 --shared
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=yes
MemoryMax=512M
TasksMax=48
LimitNOFILE=256

[Install]
WantedBy=default.target
EOF
  systemd-analyze --user verify "$unit_dir/pro-clubs-share.service"
fi
if [[ -f "$data_dir/funnel-watch.enabled" ]]; then
  cat > "$unit_dir/pro-clubs-funnel-watch.service" <<EOF
[Unit]
Description=Check public Pro Clubs Funnel DNS and HTTPS

[Service]
Type=oneshot
WorkingDirectory=$project_dir
ExecStart="$python_bin" "$project_dir/scripts/funnel-watch.py"
TimeoutStartSec=90
UMask=0077
NoNewPrivileges=yes
EOF
  cat > "$unit_dir/pro-clubs-funnel-watch.timer" <<'EOF'
[Unit]
Description=Watch for public Pro Clubs Funnel DNS every five minutes

[Timer]
OnActiveSec=10
OnUnitActiveSec=5min
AccuracySec=15
Unit=pro-clubs-funnel-watch.service

[Install]
WantedBy=timers.target
EOF
  systemd-analyze --user verify "$unit_dir/pro-clubs-funnel-watch.service" "$unit_dir/pro-clubs-funnel-watch.timer"
fi
systemd-analyze --user verify "$unit_dir/pro-clubs-collect.service" "$unit_dir/pro-clubs-collect.timer"
systemctl --user daemon-reload
systemctl --user enable --now pro-clubs-collect.timer
if [[ -f "$data_dir/sharing.json" ]]; then
  systemctl --user enable pro-clubs-share.service
  systemctl --user restart pro-clubs-share.service
fi
if [[ -f "$data_dir/funnel-watch.enabled" ]]; then
  systemctl --user enable --now pro-clubs-funnel-watch.timer
fi
printf 'Adaptive collector timer enabled (hourly idle, ten-minute active match checks). Protected viewer uses loopback port 8766 when configured. Setup made no EA requests.\n'
