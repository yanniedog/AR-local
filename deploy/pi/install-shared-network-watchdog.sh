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
bundle=/usr/local/lib/ar-local-shared-host
install -d -o root -g root -m 0755 "$bundle" /etc/systemd/system/ar-local-net-watchdog.service.d
for module in pi_shared_network_watchdog ar_local_operation_lock ar_local_backup_policy cdr_file_lock process_safety; do
  install -o root -g root -m 0555 "$repo_dir/$module.py" "$bundle/$module.py"
done
temporary=$(mktemp)
trap 'rm -f "$temporary"' EXIT
sed "s|{{AR_LOCAL_DATA_ROOT}}|$data_dir|g" "$repo_dir/deploy/pi/shared-host-network.conf" > "$temporary"
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
