#!/usr/bin/env sh
set -eu

repo_dir="${1:-/home/pi/AR-local}"
site_dir="${2:-/home/pi/australianrates}"

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

sudo install -m 0644 "$repo_dir/deploy/pi/ar-local-dashboard.service" /etc/systemd/system/ar-local-dashboard.service
sudo install -m 0644 "$repo_dir/deploy/pi/ar-local-daily.service" /etc/systemd/system/ar-local-daily.service
sudo install -m 0644 "$repo_dir/deploy/pi/ar-local-daily.timer" /etc/systemd/system/ar-local-daily.timer
sudo systemctl daemon-reload
sudo systemctl enable ar-local-dashboard.service
sudo systemctl enable --now ar-local-daily.timer

echo "Installed AR-local Pi services. Run a real ingest before starting ar-local-dashboard.service."
