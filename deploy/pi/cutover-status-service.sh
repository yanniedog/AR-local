#!/usr/bin/env sh
set -eu

health_url="${1:-http://127.0.0.1:8808/healthz}"
new_unit="ar-local-status.service"
old_unit="ar-local-dashboard.service"
old_was_active=false
old_exists=false

if systemctl cat "$old_unit" >/dev/null 2>&1; then
  old_exists=true
  if systemctl is-active --quiet "$old_unit"; then
    old_was_active=true
    sudo systemctl stop "$old_unit"
  fi
fi

rollback() {
  sudo systemctl stop "$new_unit" >/dev/null 2>&1 || true
  if [ "$old_was_active" = true ]; then
    sudo systemctl start "$old_unit" >/dev/null 2>&1 || true
  fi
}

if ! sudo systemctl restart "$new_unit"; then
  rollback
  echo "cutover-status-service: status service failed; legacy service restored" >&2
  exit 1
fi

ready=false
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS --max-time 5 "$health_url" >/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
if [ "$ready" != true ]; then
  rollback
  echo "cutover-status-service: status health check failed; legacy service restored" >&2
  exit 1
fi

if [ "$old_exists" = true ]; then
  sudo systemctl disable "$old_unit" >/dev/null 2>&1 || true
fi
sudo rm -f /etc/systemd/system/ar-local-dashboard.service
sudo systemctl daemon-reload
