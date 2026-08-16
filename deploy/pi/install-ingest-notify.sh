#!/usr/bin/env sh
set -eu

repo_dir="${1:-/srv/ar-local/AR-local}"
env_file="/etc/ar-local/notify.env"

sudo mkdir -p /etc/ar-local
if [ ! -f "$env_file" ]; then
  sudo install -m 0600 "$repo_dir/deploy/pi/notify.env.example" "$env_file"
  echo "Created $env_file from example — edit SMTP credentials before alerts will send."
else
  echo "Keeping existing $env_file"
fi

echo "Ingest notify env: $env_file"
echo "Re-run deploy/pi/install-pi-systemd.sh to install ar-local-ingest-alert.service."
