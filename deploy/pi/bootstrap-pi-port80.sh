#!/usr/bin/env sh
# One-shot Pi operator bootstrap: sudoers (passwordless deploy) + nginx :80 proxy.
# Requires one interactive sudo password on first run:
#   ssh -t ar-local-pi5 'bash /srv/ar-local/AR-local/deploy/pi/bootstrap-pi-port80.sh'
set -eu

repo_dir="${1:-/srv/ar-local/AR-local}"
repo_dir="$(cd "$repo_dir" && pwd)"

sudo bash "$repo_dir/deploy/pi/install-pi-sudoers.sh" "$repo_dir"
sudo bash "$repo_dir/deploy/pi/install-pi-dashboard-proxy.sh" "$repo_dir"
sudo systemctl restart ar-local-dashboard.service
nginx_state="$(systemctl is-active nginx.service)"
dash_state="$(systemctl is-active ar-local-dashboard.service)"
if [ "$nginx_state" != active ] || [ "$dash_state" != active ]; then
  echo "bootstrap-pi-port80: failed nginx=$nginx_state dashboard=$dash_state" >&2
  exit 1
fi
echo "bootstrap-pi-port80: OK — http://<pi-ip>/ and http://<pi-ip>:8808/"
