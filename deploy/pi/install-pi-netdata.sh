#!/usr/bin/env sh
# Install Netdata on the Pi (127.0.0.1:19999) for nginx /netdata/ (strip-prefix proxy).
# Persistent cache/lib/log live under the portable SSD root (default /srv/ar-local/data/netdata).
# Run on the Pi: sudo bash deploy/pi/install-pi-netdata.sh
set -eu

PORTABLE_ROOT="${PORTABLE_ROOT:-/srv/ar-local}"
NETDATA_DATA_ROOT="${NETDATA_DATA_ROOT:-$PORTABLE_ROOT/data/netdata}"
NETDATA_CACHE="${NETDATA_CACHE:-$NETDATA_DATA_ROOT/cache}"
NETDATA_LIB="${NETDATA_LIB:-$NETDATA_DATA_ROOT/lib}"
NETDATA_LOG="${NETDATA_LOG:-$NETDATA_DATA_ROOT/log}"
NETDATA_BIND="${NETDATA_BIND:-127.0.0.1}"
NETDATA_PUBLIC_BASE="${NETDATA_PUBLIC_BASE:-http://100.78.28.10/netdata}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"

MARKER="# AR-local nginx proxy (install-pi-netdata.sh)"
SSD_MARKER="# AR-local portable SSD data (install-pi-netdata.sh)"
CLOUD_MARKER="# AR-local local-only UI (install-pi-netdata.sh)"
conf="/etc/netdata/netdata.conf"
CLOUD_DROPIN="/etc/netdata/netdata.conf.d/ar-local-cloud.conf"
CLOUD_D_CONF="$NETDATA_LIB/cloud.d/cloud.conf"
SYSTEMD_DROPIN="/etc/systemd/system/netdata.service.d/ar-local-ssd.conf"

if ! command -v netdata >/dev/null 2>&1; then
  echo "install-pi-netdata: downloading kickstart..."
  tmp_kick="/tmp/netdata-kickstart.sh"
  curl -fsSL https://get.netdata.cloud/kickstart.sh -o "$tmp_kick"
  sh "$tmp_kick" --non-interactive --dont-wait --no-updates
fi

if ! id netdata >/dev/null 2>&1; then
  echo "install-pi-netdata: netdata user missing after install" >&2
  exit 1
fi

if [ ! -f "$conf" ]; then
  echo "install-pi-netdata: missing $conf" >&2
  exit 1
fi

mkdir -p "$NETDATA_CACHE" "$NETDATA_LIB" "$NETDATA_LOG"
chown -R netdata:netdata "$NETDATA_DATA_ROOT"

migrate_dir() {
  src="$1"
  dst="$2"
  [ -d "$src" ] || return 0
  [ -L "$src" ] && return 0
  [ "$(ls -A "$src" 2>/dev/null || true)" ] || return 0
  if [ -d "$dst" ] && [ "$(ls -A "$dst" 2>/dev/null || true)" ]; then
    echo "install-pi-netdata: skip migrate $src -> $dst (destination not empty)"
    return 0
  fi
  echo "install-pi-netdata: migrate $src -> $dst"
  mkdir -p "$dst"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "$src/" "$dst/"
  else
    cp -a "$src/." "$dst/"
  fi
  chown -R netdata:netdata "$dst"
}

link_var_dir() {
  var_path="$1"
  ssd_path="$2"
  [ -e "$var_path" ] || mkdir -p "$var_path"
  if [ -L "$var_path" ]; then
    target="$(readlink -f "$var_path" 2>/dev/null || readlink "$var_path")"
    if [ "$target" = "$ssd_path" ]; then
      return 0
    fi
    rm -f "$var_path"
  elif [ -d "$var_path" ]; then
    migrate_dir "$var_path" "$ssd_path"
    rm -rf "$var_path"
  fi
  ln -sfn "$ssd_path" "$var_path"
  echo "install-pi-netdata: symlink $var_path -> $ssd_path"
}

systemctl stop netdata.service 2>/dev/null || true
migrate_dir /var/lib/netdata "$NETDATA_LIB"
migrate_dir /var/cache/netdata "$NETDATA_CACHE"
migrate_dir /var/log/netdata "$NETDATA_LOG"
link_var_dir /var/lib/netdata "$NETDATA_LIB"
link_var_dir /var/cache/netdata "$NETDATA_CACHE"
link_var_dir /var/log/netdata "$NETDATA_LOG"

# Debian package reads /etc/netdata/netdata.conf only (not netdata.conf.d/).
if ! grep -qF "$SSD_MARKER" "$conf" 2>/dev/null; then
  cat >>"$conf" <<EOF

$SSD_MARKER
[directories]
    cache = $NETDATA_CACHE
    lib = $NETDATA_LIB
    log = $NETDATA_LOG
EOF
else
  sed -i \
    -e "s|^[[:space:]]*cache =.*|    cache = $NETDATA_CACHE|" \
    -e "s|^[[:space:]]*lib =.*|    lib = $NETDATA_LIB|" \
    -e "s|^[[:space:]]*log =.*|    log = $NETDATA_LOG|" \
    "$conf" 2>/dev/null || true
fi

if ! grep -qF "$MARKER" "$conf" 2>/dev/null; then
  if ! grep -qF 'bind to' "$conf" 2>/dev/null; then
    cat >>"$conf" <<EOF

$MARKER
[web]
    bind to = $NETDATA_BIND
EOF
  fi
fi

# Subpath /netdata/ is nginx-only (strip prefix). Agent must not use web server prefix.
for f in "$conf"; do
  [ -f "$f" ] || continue
  if grep -qF 'web server prefix = /netdata/' "$f" 2>/dev/null; then
    sed -i '/web server prefix = \/netdata\//d' "$f"
  fi
done
if [ -d /etc/netdata/netdata.conf.d ]; then
  for f in /etc/netdata/netdata.conf.d/*.conf; do
    [ -f "$f" ] || continue
    if grep -qF 'web server prefix = /netdata/' "$f" 2>/dev/null; then
      sed -i '/web server prefix = \/netdata\//d' "$f"
    fi
  done
fi

mkdir -p "$(dirname "$CLOUD_DROPIN")" "$NETDATA_LIB/cloud.d"
if [ -f "$SCRIPT_DIR/ar-local-netdata-cloud.conf" ]; then
  install -m 0644 "$SCRIPT_DIR/ar-local-netdata-cloud.conf" "$CLOUD_DROPIN"
else
  echo "install-pi-netdata: missing $SCRIPT_DIR/ar-local-netdata-cloud.conf" >&2
  exit 1
fi

cat >"$CLOUD_D_CONF" <<EOF
$CLOUD_MARKER
[global]
    enabled = no
    cloud base url = $NETDATA_PUBLIC_BASE
EOF
chown netdata:netdata "$CLOUD_D_CONF"
chmod 0644 "$CLOUD_D_CONF"

mkdir -p "$(dirname "$SYSTEMD_DROPIN")"
cat >"$SYSTEMD_DROPIN" <<EOF
# AR-local: allow metrics DB under portable root ($NETDATA_DATA_ROOT)
[Service]
ReadWriteDirectories=$NETDATA_DATA_ROOT
EOF
chmod 0644 "$SYSTEMD_DROPIN"

systemctl daemon-reload
systemctl enable netdata.service
systemctl restart netdata.service

if ! systemctl is-active --quiet netdata.service; then
  echo "install-pi-netdata: netdata.service not active" >&2
  systemctl status netdata.service --no-pager || true
  exit 1
fi

echo "install-pi-netdata: active (bind ${NETDATA_BIND}:19999)"
echo "install-pi-netdata: SSD data root ${NETDATA_DATA_ROOT}"
echo "  cache=${NETDATA_CACHE}"
echo "  lib=${NETDATA_LIB}"
echo "  log=${NETDATA_LOG}"
echo "Browser URL (local metrics, no Cloud account): ${NETDATA_PUBLIC_BASE%/}/v3/"
echo "  (nginx redirects /netdata/ and /netdata/spaces/... to /v3/)"
