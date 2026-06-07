#!/usr/bin/env bash
# Install the GitHub token that enables daily mobile-app payload publishing.
# The token is written to /etc/ar-local/app-payload.env (mode 0600) and is NEVER
# committed. Pass the token as an argument or via the GH_TOKEN env var.
#
#   sudo sh deploy/pi/install-app-payload-token.sh github_pat_xxx
#   GH_TOKEN=github_pat_xxx sudo -E sh deploy/pi/install-app-payload-token.sh
#
# After running this once, (re)render the service units so they pick up the
# EnvironmentFile, then reload:
#   sh deploy/pi/install-pi-systemd.sh /srv/ar-local && sudo systemctl daemon-reload
set -eu

token="${1:-${GH_TOKEN:-}}"
if [ -z "$token" ]; then
  echo "usage: install-app-payload-token.sh <github_pat>   (or set GH_TOKEN)" >&2
  exit 2
fi

dir=/etc/ar-local
file="$dir/app-payload.env"
sudo mkdir -p "$dir"
umask 077
tmp="$(mktemp)"
{
  echo "AR_LOCAL_APP_PAYLOAD=1"
  echo "GH_TOKEN=$token"
} >"$tmp"
sudo install -m 0600 "$tmp" "$file"
rm -f "$tmp"

sudo systemctl daemon-reload 2>/dev/null || true
echo "Wrote $file (mode 0600)."
echo "Ensure the service units reference it (already wired in deploy/pi/*.service):"
echo "  sh deploy/pi/install-pi-systemd.sh /srv/ar-local && sudo systemctl daemon-reload"
echo "Verify with one run:"
echo "  sudo systemctl start ar-local-daily.service && journalctl -u ar-local-daily.service -n 30 --no-pager | grep -i 'app payload'"
