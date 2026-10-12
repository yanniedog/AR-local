#!/bin/sh
# Install definitions only. Never start, enable or restart a timer.
set -eu
repo_dir=${1:?repository root required}
data_dir=${2:?data root required}
case "$data_dir" in
  /*) ;;
  *) echo 'absolute data root required' >&2; exit 1 ;;
esac
case "$data_dir" in
  *[!a-zA-Z0-9_./-]*|*/../*|*/..) echo 'unsupported data root' >&2; exit 1 ;;
esac
run_user=${3:-${AR_LOCAL_USER:-${SUDO_USER:-}}}
run_group=${4:-${AR_LOCAL_GROUP:-$(id -gn "$run_user")}}
case "$run_group" in
  ''|*[!A-Za-z0-9_-]*) echo 'unsupported service group' >&2; exit 1 ;;
esac
getent group "$run_group" >/dev/null
# Validate account and exact reconnect permissions before replacing definitions.
sh "$repo_dir/deploy/pi/install-network-watchdog-sudoers.sh" "$run_user"
bundle=/usr/local/lib/ar-local-shared-host
install -d -o root -g root -m 0755 "$bundle" /etc/systemd/system/ar-local-net-watchdog.service.d
install -o root -g root -m 0555 "$repo_dir/pi_shared_network_watchdog.py" "$bundle/pi_shared_network_watchdog.py"
temporary=$(mktemp)
trap 'rm -f "$temporary"' EXIT
sed -e "s|{{AR_LOCAL_DATA_ROOT}}|$data_dir|g" -e "s|{{AR_LOCAL_USER}}|$run_user|g" -e "s|{{AR_LOCAL_GROUP}}|$run_group|g" "$repo_dir/deploy/pi/shared-host-network.conf" > "$temporary"
install -o root -g root -m 0644 "$temporary" /etc/systemd/system/ar-local-net-watchdog.service.d/97-shared-host.conf
# This base definition replaces the legacy global NetworkManager restart.
cat > "$temporary" <<'UNIT'
[Unit]
Description=AR-local guarded interface recovery
After=NetworkManager.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I -S /usr/local/lib/ar-local-shared-host/pi_shared_network_watchdog.py
UNIT
install -o root -g root -m 0644 "$temporary" /etc/systemd/system/ar-local-net-watchdog.service
systemctl daemon-reload
