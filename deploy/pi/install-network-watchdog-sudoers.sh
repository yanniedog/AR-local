#!/usr/bin/env sh
# Install only exact interface reconnect arguments for the selected account.
set -eu

run_user="${1:-}"
case "$run_user" in
  ''|[!A-Za-z_]*|*[!A-Za-z0-9_-]*)
    echo "A simple existing non-root account name is required" >&2
    exit 1
    ;;
esac
run_uid="$(id -u "$run_user")"
if [ "$run_uid" -eq 0 ] || [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer as root for a non-root service account" >&2
  exit 1
fi
if [ ! -x /usr/bin/nmcli ] || [ ! -x /usr/sbin/visudo ]; then
  echo "NetworkManager nmcli and visudo are required before watchdog activation" >&2
  exit 1
fi

tmp_file="$(mktemp)"
trap 'rm -f "$tmp_file"' EXIT
printf '# AR-local: validated Wi-Fi interface reconnects only\n' > "$tmp_file"
interfaces=0
for device in /sys/class/net/*; do
  [ -d "$device/wireless" ] || [ -d "$device/phy80211" ] || continue
  interface="${device##*/}"
  # Avoid sudoers separators, wildcards, escapes and option-shaped names.
  case "$interface" in
    ''|-*|*[!A-Za-z0-9_.-]*)
      echo "Unsupported Wi-Fi interface name for exact sudoers permission" >&2
      exit 1
      ;;
  esac
  printf '%s ALL=(root) NOPASSWD: /usr/bin/nmcli --wait 20 device connect %s\n' \
    "$run_user" "$interface" >> "$tmp_file"
  interfaces=$((interfaces + 1))
done
if [ "$interfaces" -eq 0 ]; then
  echo "No validated Wi-Fi interface found; watchdog permission was not installed" >&2
  exit 1
fi

/usr/sbin/visudo -cf "$tmp_file"
destination=/etc/sudoers.d/ar-local-network-watchdog
if [ -L "$destination" ]; then
  echo "Refusing a symlinked network watchdog sudoers destination" >&2
  exit 1
fi
install -d -m 0750 /etc/sudoers.d
install -o root -g root -m 0440 "$tmp_file" "$destination"
/usr/sbin/visudo -cf "$destination"
echo "Installed exact Wi-Fi reconnect permissions for $run_user ($interfaces interfaces)"
