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
sudo systemctl is-active nginx.service ar-local-dashboard.service
echo "bootstrap-pi-port80: OK — http://<pi-ip>/ and http://<pi-ip>:8808/"
