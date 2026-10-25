#!/bin/bash
# Install day-archive spool, env, and timer/service. Does not start timers
# unless --enable is passed. Does not lift the Drive write hold.
set -euo pipefail

ROOT="${1:-/srv/ar-local/AR-local}"
ENABLE=0
if [[ "${2:-}" == "--enable" ]]; then
  ENABLE=1
fi

install -d -m 0755 /var/lib/ar-local-day-archives
install -d -m 0755 /var/lib/ar-local-day-archives/requests
install -d -m 0755 /var/lib/ar-local-day-archives/work
install -d -m 0755 /var/lib/ar-local-day-archives/verify

if [[ ! -f /etc/ar-local/day-archive.env ]]; then
  install -d -m 0755 /etc/ar-local
  install -m 0644 "$ROOT/deploy/pi/day-archive.env.example" /etc/ar-local/day-archive.env
fi

install -m 0644 "$ROOT/deploy/pi/ar-local-day-archive.service" /etc/systemd/system/ar-local-day-archive.service
install -m 0644 "$ROOT/deploy/pi/ar-local-day-archive.timer" /etc/systemd/system/ar-local-day-archive.timer
systemctl daemon-reload

if [[ "$ENABLE" -eq 1 ]]; then
  systemctl enable --now ar-local-day-archive.timer
  systemctl list-timers ar-local-day-archive.timer --no-pager
fi

echo "day-archive install complete (enable=$ENABLE)"
