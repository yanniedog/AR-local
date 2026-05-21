#!/usr/bin/env sh
# Install Netdata on the Pi (127.0.0.1:19999) and set web prefix for nginx /netdata/.
# Run on the Pi: sudo bash deploy/pi/install-pi-netdata.sh
set -eu

# Subpath /netdata/ is handled by nginx (strip prefix); do not set web server prefix here.
NETDATA_BIND="${NETDATA_BIND:-127.0.0.1}"
MARKER="# AR-local nginx proxy (install-pi-netdata.sh)"

if ! command -v netdata >/dev/null 2>&1; then
  echo "install-pi-netdata: downloading kickstart..."
  tmp_kick="/tmp/netdata-kickstart.sh"
  curl -fsSL https://get.netdata.cloud/kickstart.sh -o "$tmp_kick"
  sh "$tmp_kick" --non-interactive --dont-wait --no-updates
fi

conf="/etc/netdata/netdata.conf"
if [ ! -f "$conf" ]; then
  echo "install-pi-netdata: missing $conf" >&2
  exit 1
fi

if ! grep -qF "$MARKER" "$conf" 2>/dev/null; then
  cat >>"$conf" <<EOF

$MARKER
[web]
    bind to = ${NETDATA_BIND}
EOF
fi

# Older installs appended web server prefix = /netdata/; that breaks API paths behind nginx.
if grep -qF 'web server prefix = /netdata/' "$conf" 2>/dev/null; then
  sed -i '/web server prefix = \/netdata\//d' "$conf"
fi

systemctl enable netdata.service
systemctl restart netdata.service

if ! systemctl is-active --quiet netdata.service; then
  echo "install-pi-netdata: netdata.service not active" >&2
  systemctl status netdata.service --no-pager || true
  exit 1
fi

echo "install-pi-netdata: active (bind ${NETDATA_BIND}:19999; browser URL via nginx /netdata/)"
echo "Browser URL (via nginx): http://<pi-tailscale-ip>/netdata/"
