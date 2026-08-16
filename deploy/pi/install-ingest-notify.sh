#!/usr/bin/env sh
set -eu

repo_dir="${1:-/srv/ar-local/AR-local}"
run_group="${2:-${AR_LOCAL_GROUP:-$(id -gn "${SUDO_USER:-$(id -un)}")}}"
env_file="/etc/ar-local/notify.env"

sudo mkdir -p /etc/ar-local
if [ ! -f "$env_file" ]; then
  sudo install -o root -g "$run_group" -m 0640 "$repo_dir/deploy/pi/notify.env.example" "$env_file"
  echo "Created $env_file from example — edit SMTP credentials before alerts will send."
else
  echo "Keeping existing $env_file"
  sudo chown "root:$run_group" "$env_file"
  sudo chmod 0640 "$env_file"
fi

echo "Ingest notify env: $env_file"
echo "Re-run deploy/pi/install-pi-systemd.sh to install ar-local-ingest-alert.service."
