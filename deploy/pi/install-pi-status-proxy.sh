#!/usr/bin/env sh
set -eu

repo_dir="${1:-/srv/ar-local/AR-local}"
repo_dir="$(CDPATH= cd "$repo_dir" && pwd -P)"
src_conf="$repo_dir/deploy/pi/ar-local-status-nginx.conf"
src_map="$repo_dir/deploy/pi/ar-local-status-nginx-netdata-map.conf"
dst_avail="/etc/nginx/sites-available/ar-local-status"
dst_enabled="/etc/nginx/sites-enabled/ar-local-status"
old_avail="/etc/nginx/sites-available/ar-local-dashboard"
old_enabled="/etc/nginx/sites-enabled/ar-local-dashboard"
default_enabled="/etc/nginx/sites-enabled/default"
map_path="/etc/nginx/conf.d/ar-local-netdata-map.conf"
tmp_dir=""

[ -f "$src_conf" ] || { echo "install-pi-status-proxy: missing $src_conf" >&2; exit 1; }
[ -f "$src_map" ] || { echo "install-pi-status-proxy: missing $src_map" >&2; exit 1; }
if ! command -v nginx >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y nginx
fi

tmp_dir="$(mktemp -d)"
case "$tmp_dir" in /tmp/*) ;; *) echo "Unexpected temporary path" >&2; exit 1;; esac
trap 'case "$tmp_dir" in /tmp/*) rm -rf -- "$tmp_dir";; esac' EXIT

[ ! -f "$dst_avail" ] || sudo cp -p "$dst_avail" "$tmp_dir/status.previous"
[ ! -f "$map_path" ] || sudo cp -p "$map_path" "$tmp_dir/map.previous"
if [ -e "$dst_enabled" ] || [ -L "$dst_enabled" ]; then
  sudo cp -a "$dst_enabled" "$tmp_dir/status.enabled.previous"
fi
if [ -e "$old_enabled" ] || [ -L "$old_enabled" ]; then
  sudo cp -a "$old_enabled" "$tmp_dir/old.enabled.previous"
fi
if [ -e "$default_enabled" ] || [ -L "$default_enabled" ]; then
  sudo cp -a "$default_enabled" "$tmp_dir/default.enabled.previous"
fi

rollback_proxy() {
  sudo rm -f "$dst_enabled" "$old_enabled" "$default_enabled"
  if [ -f "$tmp_dir/status.previous" ]; then
    sudo cp -p "$tmp_dir/status.previous" "$dst_avail"
  else
    sudo rm -f "$dst_avail"
  fi
  if [ -f "$tmp_dir/map.previous" ]; then
    sudo cp -p "$tmp_dir/map.previous" "$map_path"
  else
    sudo rm -f "$map_path"
  fi
  [ ! -e "$tmp_dir/status.enabled.previous" ] && \
    [ ! -L "$tmp_dir/status.enabled.previous" ] || \
    sudo cp -a "$tmp_dir/status.enabled.previous" "$dst_enabled"
  [ ! -e "$tmp_dir/old.enabled.previous" ] && \
    [ ! -L "$tmp_dir/old.enabled.previous" ] || \
    sudo cp -a "$tmp_dir/old.enabled.previous" "$old_enabled"
  [ ! -e "$tmp_dir/default.enabled.previous" ] && \
    [ ! -L "$tmp_dir/default.enabled.previous" ] || \
    sudo cp -a "$tmp_dir/default.enabled.previous" "$default_enabled"
}

if ! sudo install -m 0644 "$src_conf" "$dst_avail" || \
   ! sudo install -m 0644 "$src_map" "$map_path" || \
   ! sudo rm -f "$default_enabled" "$old_enabled" || \
   ! sudo ln -sfn "$dst_avail" "$dst_enabled"; then
  rollback_proxy
  exit 1
fi
if ! sudo nginx -t; then
  rollback_proxy
  exit 1
fi
if ! sudo systemctl enable nginx.service; then
  rollback_proxy
  exit 1
fi
if ! sudo systemctl reload-or-restart nginx.service; then
  rollback_proxy
  sudo nginx -t >/dev/null 2>&1 && sudo systemctl reload-or-restart nginx.service || true
  exit 1
fi

proxy_ready=false
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS --max-time 5 http://127.0.0.1/healthz >/dev/null; then
    proxy_ready=true
    break
  fi
  sleep 1
done
if [ "$proxy_ready" != true ]; then
  rollback_proxy
  sudo nginx -t >/dev/null 2>&1 && sudo systemctl reload-or-restart nginx.service || true
  echo "install-pi-status-proxy: proxy readiness check failed; prior proxy restored" >&2
  exit 1
fi
sudo rm -f "$old_avail" || true

echo "Status API: http://<pi-ip>/"
echo "Netdata (if installed): http://<pi-ip>/netdata/"
