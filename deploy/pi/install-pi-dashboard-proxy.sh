#!/usr/bin/env sh
# Install nginx reverse proxy so the dashboard is reachable on port 80 (no :8808 in URLs).
# Run on the Pi with sudo after ar-local-dashboard.service binds 127.0.0.1:8808 / 0.0.0.0:8808.
set -eu

repo_dir="${1:-/srv/ar-local/AR-local}"
repo_dir="$(cd "$repo_dir" && pwd)"
src_conf="$repo_dir/deploy/pi/ar-local-dashboard-nginx.conf"
dst_name="ar-local-dashboard"
dst_avail="/etc/nginx/sites-available/$dst_name"
dst_enabled="/etc/nginx/sites-enabled/$dst_name"

if [ ! -f "$src_conf" ]; then
  echo "install-pi-dashboard-proxy: missing $src_conf" >&2
  exit 1
fi

if ! command -v nginx >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y nginx
fi

sudo install -m 0644 "$src_conf" "$dst_avail"
if [ -e /etc/nginx/sites-enabled/default ]; then
  sudo rm -f /etc/nginx/sites-enabled/default
fi
sudo ln -sf "$dst_avail" "$dst_enabled"

sudo nginx -t
sudo systemctl enable nginx.service
sudo systemctl restart nginx.service

echo "Dashboard proxy: http://<pi-ip>/  (nginx :80 -> 127.0.0.1:8808)"
echo "Netdata (if installed): http://<pi-ip>/netdata/  (nginx :80 -> 127.0.0.1:19999)"
echo "Direct backend (optional): http://<pi-ip>:8808/"
