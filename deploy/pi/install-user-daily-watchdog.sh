#!/usr/bin/env sh
set -eu

repo_dir="${1:-/srv/ar-local/AR-local}"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

repo_dir="$(cd "$repo_dir" && pwd)"
portable_root="${AR_LOCAL_PORTABLE_ROOT:-$(dirname "$repo_dir")}"
data_root="${AR_LOCAL_DATA_ROOT:-$portable_root/data}"
python_executable="${PYTHON:-$(command -v python3)}"
mkdir -p "$unit_dir"

cat > "$unit_dir/ar-local-daily-watchdog.service" <<EOF
[Unit]
Description=AR-local daily ingest watchdog catch-up
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$repo_dir
Environment=AR_LOCAL_PORTABLE_ROOT=$portable_root
Environment=AR_LOCAL_DATA_ROOT=$data_root
ExecStart=$python_executable $repo_dir/pi_daily_watchdog.py
EOF

cp "$repo_dir/deploy/pi/ar-local-daily-watchdog.timer" "$unit_dir/ar-local-daily-watchdog.timer"

systemctl --user daemon-reload
systemctl --user enable --now ar-local-daily-watchdog.timer
systemctl --user list-timers --all ar-local-daily-watchdog.timer --no-pager
