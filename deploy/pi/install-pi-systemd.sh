#!/usr/bin/env sh
set -eu

repo_dir="${1:-/home/pi/AR-local}"
site_dir="${2:-/home/pi/australianrates}"
data_dir="${3:-/srv/ar-local-data}"
run_user="$(id -un)"
run_group="$(id -gn)"

sudo apt-get update
sudo apt-get install -y git python3 nodejs npm gh

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
data_dir="$(cd "$data_dir" && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

render_unit() {
  src="$1"
  dst="$2"
  sed \
    -e "s|{{AR_LOCAL_USER}}|$run_user|g" \
    -e "s|{{AR_LOCAL_GROUP}}|$run_group|g" \
    -e "s|{{AR_LOCAL_REPO}}|$repo_dir|g" \
    -e "s|{{AR_LOCAL_DATA_ROOT}}|$data_dir|g" \
    -e "s|{{AR_SITE_ROOT}}|$site_root|g" \
    "$src" > "$dst"
}

render_unit "$repo_dir/deploy/pi/ar-local-dashboard.service" "$tmp_dir/ar-local-dashboard.service"
render_unit "$repo_dir/deploy/pi/ar-local-daily.service" "$tmp_dir/ar-local-daily.service"

sudo install -m 0644 "$tmp_dir/ar-local-dashboard.service" /etc/systemd/system/ar-local-dashboard.service
sudo install -m 0644 "$tmp_dir/ar-local-daily.service" /etc/systemd/system/ar-local-daily.service
sudo install -m 0644 "$repo_dir/deploy/pi/ar-local-daily.timer" /etc/systemd/system/ar-local-daily.timer
sudo systemctl daemon-reload
sudo systemctl enable ar-local-dashboard.service
sudo systemctl enable --now ar-local-daily.timer

echo "Installed AR-local Pi services for $run_user using $repo_dir, $site_root, and data root $data_dir."
echo "Run a real ingest before starting ar-local-dashboard.service."
