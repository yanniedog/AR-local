#!/usr/bin/env sh
# Install passwordless sudo rules for AR-local deploy (nginx + systemd restarts).
# Run once on the Pi with an interactive sudo session:
#   sudo bash /srv/ar-local/AR-local/deploy/pi/install-pi-sudoers.sh
set -eu

repo_dir="${1:-/srv/ar-local/AR-local}"
repo_dir="$(cd "$repo_dir" && pwd)"
src="$repo_dir/deploy/pi/ar-local-pi.sudoers"
dst="/etc/sudoers.d/ar-local-pi"

if [ ! -f "$src" ]; then
  echo "install-pi-sudoers: missing $src" >&2
  exit 1
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sudo install -m 0440 "$src" "$tmp"
sudo visudo -cf "$tmp"
sudo install -m 0440 "$tmp" "$dst"
echo "install-pi-sudoers: installed $dst (passwordless deploy for user $(id -un))"
