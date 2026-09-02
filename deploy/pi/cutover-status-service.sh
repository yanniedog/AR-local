#!/usr/bin/env sh
set -eu

health_url="${1:-http://127.0.0.1:8808/healthz}"
script_dir="$(CDPATH= cd "$(dirname "$0")" && pwd -P)"
proxy_installer="${2:-$script_dir/install-pi-status-proxy.sh}"
repo_dir="${3:-$(CDPATH= cd "$script_dir/../.." && pwd -P)}"
new_unit="ar-local-status.service"
old_unit="ar-local-dashboard.service"
new_was_active=false
new_was_enabled=false
old_was_active=false
old_exists=false

[ -f "$proxy_installer" ] || {
  echo "cutover-status-service: missing proxy installer $proxy_installer" >&2
  exit 1
}

if systemctl is-active --quiet "$new_unit"; then
  new_was_active=true
fi
if systemctl is-enabled --quiet "$new_unit"; then
  new_was_enabled=true
fi

if systemctl cat "$old_unit" >/dev/null 2>&1; then
  old_exists=true
  if systemctl is-active --quiet "$old_unit"; then
    old_was_active=true
    sudo systemctl stop "$old_unit"
  fi
fi

rollback() {
  if [ "$new_was_active" = true ]; then
    sudo systemctl restart "$new_unit" >/dev/null 2>&1 || true
  else
    sudo systemctl stop "$new_unit" >/dev/null 2>&1 || true
  fi
  if [ "$new_was_enabled" != true ]; then
    sudo systemctl disable "$new_unit" >/dev/null 2>&1 || true
  fi
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

if ! sudo systemctl enable "$new_unit"; then
  rollback
  echo "cutover-status-service: status enable failed; legacy service restored" >&2
  exit 1
fi

if ! sudo sh "$proxy_installer" "$repo_dir"; then
  rollback
  echo "cutover-status-service: proxy cutover failed; legacy service restored" >&2
  exit 1
fi

if [ "$old_exists" = true ]; then
  sudo systemctl disable "$old_unit" >/dev/null 2>&1 || true
fi
sudo rm -f /etc/systemd/system/ar-local-dashboard.service
sudo systemctl daemon-reload
