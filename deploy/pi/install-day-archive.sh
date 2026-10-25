#!/bin/bash
# Install day-archive spool, env, and timer/service. Does not start timers
# unless --enable is passed. Does not lift the Drive write hold.
set -euo pipefail

ROOT="${1:-/srv/ar-local/AR-local}"
ENABLE=0
if [[ "${2:-}" == "--enable" ]]; then
  ENABLE=1
fi

run_user="${AR_LOCAL_USER:-pi}"
run_group="${AR_LOCAL_GROUP:-$run_user}"

install -d -m 0755 /var/lib/ar-local-day-archives
# Ingest and the day-archive oneshot both run as the application account.
install -d -m 0775 -o "$run_user" -g "$run_group" /var/lib/ar-local-day-archives/requests
install -d -m 0775 -o "$run_user" -g "$run_group" /var/lib/ar-local-day-archives/work
install -d -m 0775 -o "$run_user" -g "$run_group" /var/lib/ar-local-day-archives/verify
install -d -m 0775 -o "$run_user" -g "$run_group" /var/lib/ar-local-day-archives/locks
chown -R "$run_user:$run_group" /var/lib/ar-local-day-archives

# System python used by ar-local-daily / day-archive oneshot needs zstandard.
if ! /usr/bin/python3 -c 'import zstandard' 2>/dev/null; then
  /usr/bin/python3 -m pip install --break-system-packages 'zstandard==0.25.0'
fi

if [[ ! -f /etc/ar-local/day-archive.env ]]; then
  install -d -m 0755 /etc/ar-local
  install -m 0644 "$ROOT/deploy/pi/day-archive.env.example" /etc/ar-local/day-archive.env
fi

rendered=$(mktemp)
trap 'rm -f -- "$rendered"' EXIT
for unit in ar-local-day-archive.service ar-local-day-archive.timer; do
  sed -e "s|{{AR_LOCAL_REPO}}|$ROOT|g" \
      -e "s|{{AR_LOCAL_USER}}|$run_user|g" \
      -e "s|{{AR_LOCAL_GROUP}}|$run_group|g" \
      "$ROOT/deploy/pi/$unit" > "$rendered"
  install -m 0644 -o root -g root "$rendered" "/etc/systemd/system/$unit"
done
systemctl daemon-reload

if [[ "$ENABLE" -eq 1 ]]; then
  systemctl enable --now ar-local-day-archive.timer
  systemctl list-timers ar-local-day-archive.timer --no-pager
fi

echo "day-archive install complete (enable=$ENABLE user=$run_user)"
