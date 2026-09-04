#!/usr/bin/env bash
# One-shot Pi operator bootstrap: sudoers (passwordless deploy) + nginx :80 proxy.
# Requires one interactive sudo password on first run:
#   ssh -t ar-local-pi5 'bash /srv/ar-local/AR-local/deploy/pi/bootstrap-pi-port80.sh'
set -eu

repo_dir="${1:-/srv/ar-local/AR-local}"
repo_dir="$(cd "$repo_dir" && pwd)"

sudo bash "$repo_dir/deploy/pi/install-pi-sudoers.sh" "$repo_dir"
sudo bash "$repo_dir/deploy/pi/install-pi-status-proxy.sh" "$repo_dir"
sudo systemctl restart ar-local-status.service
nginx_state="$(systemctl is-active nginx.service)"
status_state="$(systemctl is-active ar-local-status.service)"
if [ "$nginx_state" != active ] || [ "$status_state" != active ]; then
  echo "bootstrap-pi-port80: failed nginx=$nginx_state status=$status_state" >&2
  exit 1
fi
curl -fsS --max-time 10 http://127.0.0.1/healthz >/dev/null
echo "bootstrap-pi-port80: OK — http://<pi-ip>/"
