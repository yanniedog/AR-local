#!/usr/bin/env sh
set -eu

portable_root="${1:-/srv/ar-local}"
repo_dir="${2:-$portable_root/AR-local}"
site_dir="${3:-$portable_root/australianrates}"
data_dir="${4:-$portable_root/data}"
run_user="${AR_LOCAL_USER:-${SUDO_USER:-$(id -un)}}"
run_group="${AR_LOCAL_GROUP:-$(id -gn "$run_user")}"

sudo apt-get update
sudo apt-get install -y git python3 nodejs npm gh rsync avahi-daemon nginx

sudo mkdir -p "$portable_root"
sudo chown "$run_user:$run_group" "$portable_root"
sudo mkdir -p "$(dirname "$repo_dir")" "$(dirname "$site_dir")"
sudo chown "$run_user:$run_group" "$(dirname "$repo_dir")" "$(dirname "$site_dir")"

if [ ! -d "$repo_dir/.git" ]; then
  git clone https://github.com/yanniedog/AR-local.git "$repo_dir"
fi
if [ ! -d "$site_dir/.git" ]; then
  git clone https://github.com/yanniedog/australianrates.git "$site_dir"
fi

git -C "$repo_dir" checkout main
git -C "$repo_dir" pull --ff-only origin main
git -C "$site_dir" checkout main
git -C "$site_dir" pull --ff-only origin main

repo_dir="$(cd "$repo_dir" && pwd)"
site_dir="$(cd "$site_dir" && pwd)"
site_root="$site_dir/site"
sudo mkdir -p "$data_dir/runs" "$data_dir/state"
sudo chown -R "$run_user:$run_group" "$data_dir"
portable_root="$(cd "$portable_root" && pwd)"
data_dir="$(cd "$data_dir" && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

render_unit() {
  src="$1"
  dst="$2"
  sed \
    -e "s|{{AR_LOCAL_USER}}|$run_user|g" \
    -e "s|{{AR_LOCAL_GROUP}}|$run_group|g" \
    -e "s|{{AR_LOCAL_PORTABLE_ROOT}}|$portable_root|g" \
    -e "s|{{AR_LOCAL_REPO}}|$repo_dir|g" \
    -e "s|{{AR_LOCAL_DATA_ROOT}}|$data_dir|g" \
    -e "s|{{AR_SITE_ROOT}}|$site_root|g" \
    "$src" > "$dst"
}

render_unit "$repo_dir/deploy/pi/ar-local-dashboard.service" "$tmp_dir/ar-local-dashboard.service"
render_unit "$repo_dir/deploy/pi/ar-local-daily.service" "$tmp_dir/ar-local-daily.service"
render_unit "$repo_dir/deploy/pi/ar-local-daily-watchdog.service" "$tmp_dir/ar-local-daily-watchdog.service"
render_unit "$repo_dir/deploy/pi/ar-local-ingest-alert.service" "$tmp_dir/ar-local-ingest-alert.service"

sudo install -m 0644 "$tmp_dir/ar-local-dashboard.service" /etc/systemd/system/ar-local-dashboard.service
sudo install -m 0644 "$tmp_dir/ar-local-daily.service" /etc/systemd/system/ar-local-daily.service
sudo install -m 0644 "$tmp_dir/ar-local-daily-watchdog.service" /etc/systemd/system/ar-local-daily-watchdog.service
sudo install -m 0644 "$tmp_dir/ar-local-ingest-alert.service" /etc/systemd/system/ar-local-ingest-alert.service
sudo install -m 0644 "$repo_dir/deploy/pi/ar-local-daily.timer" /etc/systemd/system/ar-local-daily.timer
sudo install -m 0644 "$repo_dir/deploy/pi/ar-local-daily-watchdog.timer" /etc/systemd/system/ar-local-daily-watchdog.timer
chmod +x "$repo_dir/deploy/pi/ar-local-deploy-watchdog.sh"
render_unit "$repo_dir/deploy/pi/ar-local-deploy-watchdog.service" "$tmp_dir/ar-local-deploy-watchdog.service"
sudo install -m 0644 "$tmp_dir/ar-local-deploy-watchdog.service" /etc/systemd/system/ar-local-deploy-watchdog.service
sudo install -m 0644 "$repo_dir/deploy/pi/ar-local-deploy-watchdog.timer" /etc/systemd/system/ar-local-deploy-watchdog.timer
sudo systemctl daemon-reload
sudo systemctl enable ar-local-dashboard.service
sudo systemctl enable --now ar-local-daily.timer
sudo systemctl enable --now ar-local-daily-watchdog.timer
sudo systemctl enable --now ar-local-deploy-watchdog.timer
if [ -f "$repo_dir/deploy/pi/install-ingest-notify.sh" ]; then
  sh "$repo_dir/deploy/pi/install-ingest-notify.sh" "$repo_dir"
fi
if [ -f /etc/avahi/avahi-daemon.conf ]; then
  if sudo grep -q '^host-name=' /etc/avahi/avahi-daemon.conf; then
    sudo sed -i 's/^host-name=.*/host-name=ar/' /etc/avahi/avahi-daemon.conf
  else
    sudo sed -i '/^\[server\]/a host-name=ar' /etc/avahi/avahi-daemon.conf
  fi
  sudo systemctl enable --now avahi-daemon.service
  sudo systemctl restart avahi-daemon.service
fi

echo "Installed AR-local Pi services for $run_user using portable root $portable_root."
echo "Repo: $repo_dir"
echo "Site assets: $site_root"
echo "Data root: $data_dir"
echo "LAN dashboard (no port in URL): http://<pi-ip>/ or http://ar.local/ when mDNS is available."
echo "Direct backend (optional): http://<pi-ip>:8808/"
echo "Run a real ingest before starting ar-local-dashboard.service."
sudo bash "$repo_dir/deploy/pi/install-pi-dashboard-proxy.sh" "$repo_dir"
