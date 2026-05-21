#!/usr/bin/env sh
# Install passwordless sudo for user pi (full NOPASSWD for agent automation).
# Run once on the Pi with one interactive sudo password:
#   sudo bash /srv/ar-local/AR-local/deploy/pi/install-pi-sudoers.sh
# Or from Windows: ssh -t ar-local-pi5 'bash /srv/ar-local/AR-local/deploy/pi/bootstrap-pi-port80.sh'
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
