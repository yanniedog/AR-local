#!/bin/bash
# Bounded component installation. Does not start ingest, backup, or dashboard.
set -euo pipefail
test "$EUID" = 0 || { echo 'Run installer through sudo.' >&2; exit 2; }
repo=${1:?Usage: install-issue-alerts.sh REPO USER DATA_ROOT ALERT_SPOOL}
alert_user=${2:?Missing service user}
data_root=${3:?Missing data root}
spool=${4:?Missing alert spool}
for path in "$repo" "$data_root" "$spool"; do
  [[ "$path" =~ ^/[a-zA-Z0-9_./-]+$ ]] && [ "$(realpath -m -- "$path")" = "$path" ] || exit 2
done
[[ "$alert_user" =~ ^[a-z_][a-z0-9_-]*$ ]] || exit 2
case "$spool/" in "$data_root/"*|"$repo/"*) echo 'Alert spool must be outside data and code.' >&2; exit 2;; esac
alert_group=$(id -gn "$alert_user")
install -d -m 0700 -o "$alert_user" -g "$alert_group" "$spool"
temporary=$(mktemp -d /tmp/ar-local-issue-units.XXXXXX)
trap 'rm -rf -- "$temporary"' EXIT
for unit in ar-local-issue-watchdog.service ar-local-issue-watchdog.timer ar-local-issue-failure@.service; do
  sed -e "s|{{AR_LOCAL_REPO}}|$repo|g" -e "s|{{AR_LOCAL_USER}}|$alert_user|g" \
      -e "s|{{AR_LOCAL_GROUP}}|$alert_group|g" -e "s|{{AR_LOCAL_DATA_ROOT}}|$data_root|g" \
      -e "s|{{AR_LOCAL_ALERT_SPOOL}}|$spool|g" "$repo/deploy/pi/$unit" > "$temporary/$unit"
done
systemd-analyze verify "$temporary/ar-local-issue-watchdog.service" \
  "$temporary/ar-local-issue-watchdog.timer" "$temporary/ar-local-issue-failure@.service"
for unit in ar-local-issue-watchdog.service ar-local-issue-watchdog.timer ar-local-issue-failure@.service; do
  install -m 0644 "$temporary/$unit" "/etc/systemd/system/$unit"
done
for unit in ar-local-daily.service ar-local-ingest-now.service ar-local-daily-watchdog.service ar-local-drive-backup.service; do
  install -d -m 0755 "/etc/systemd/system/$unit.d"
  printf '[Unit]\nOnFailure=ar-local-issue-failure@%%n.service\n' > "/etc/systemd/system/$unit.d/github-issues.conf"
done
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/ar-local-issue-watchdog.service \
  /etc/systemd/system/ar-local-issue-watchdog.timer /etc/systemd/system/ar-local-issue-failure@.service
echo 'Installed. Verify --checks-only and --delivery-test under the service environment, then enable ar-local-issue-watchdog.timer.'
