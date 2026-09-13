#!/bin/bash
# Install only these units. OAuth and first full restore are separate gates.
set -euo pipefail
if [ "$EUID" -ne 0 ]; then
  echo 'Run this bounded installer through sudo.' >&2
  exit 2
fi
repo=${1:?Usage: install-drive-backup.sh REPO USER DATA_ROOT SPOOL}
backup_user=${2:?Missing service user}
data_root=${3:?Missing data root}
spool=${4:?Missing backup spool}
for path in "$repo" "$data_root" "$spool"; do
  if [[ ! "$path" =~ ^/[a-zA-Z0-9_./-]+$ ]]; then
    echo 'Installer paths must be absolute and contain only letters, digits, underscore, dot, slash and hyphen.' >&2
    exit 2
  fi
  if [ "$(realpath -m -- "$path")" != "$path" ]; then
    echo 'Installer paths must be canonical and must not resolve through symlinks.' >&2
    exit 2
  fi
done
if [[ ! "$backup_user" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
  echo 'Service user must be a conventional local account name.' >&2
  exit 2
fi
case "$spool/" in "$data_root/"*) echo 'Spool must be outside data root.' >&2; exit 2;; esac
case "$data_root/" in "$spool/"*) echo 'Data root must be outside spool.' >&2; exit 2;; esac
backup_group=$(id -gn "$backup_user")
if [ "$data_root" != /srv/ar-local/data ]; then
  echo 'The fixed root reclaim control requires /srv/ar-local/data.' >&2; exit 2
fi
# The privileged helper is copied out of the user-owned producer checkout. Its
# CLI accepts only fixed actions; it never imports producer code or credentials.
for control_path in /usr/local/lib/ar-local-drive-reclaim /var/lib/ar-local-drive-reclaim; do
  if [ -L "$control_path" ]; then
    echo 'Reclaim control directories must not be symlinks.' >&2
    exit 2
  fi
done
require_idle_controls() {
  local control_unit properties key value load active pid job enabled
  for control_unit in ar-local-drive-backup.service ar-local-drive-reclaim.service ar-local-drive-backup.timer ar-local-drive-backup-queue.timer; do
    load= active= pid=0 job= enabled=
    properties=$(systemctl show "$control_unit" --property=LoadState,ActiveState,MainPID,Job,UnitFileState) || {
      # A first installation may have no unit yet; other read errors fail closed.
      [[ "$properties" == *'LoadState=not-found'* ]] || return 2
    }
    while IFS='=' read -r key value; do
      case "$key" in LoadState) load=$value;; ActiveState) active=$value;; MainPID) pid=$value;; Job) job=$value;; UnitFileState) enabled=$value;; esac
    done <<< "$properties"
    case "$load:$active" in loaded:inactive|loaded:failed|not-found:inactive) ;; *) return 2;; esac
    [[ "$pid" == 0 && ( -z "$job" || "$job" == 0 ) ]] || return 2
    if [[ "$control_unit" == *.timer && "$load" != not-found ]]; then
      case "$active:$enabled" in inactive:disabled|inactive:masked) ;; *) return 2;; esac
    fi
  done
}
if ! require_idle_controls; then
  echo 'Disable and stop both backup timers, then stop/reconcile backup controls before installation.' >&2
  exit 2
fi
if [ -e /var/lib/ar-local-drive-reclaim/current.json ] || [ -L /var/lib/ar-local-drive-reclaim/current.json ]; then
  echo 'Reconcile the existing backup lease before installing controls.' >&2; exit 2
fi
# The operator retains prior timer states and restores them only after acceptance.
# Disabled/inactive timers cannot enqueue work during the replacement window.
require_idle_controls || { echo 'Backup controls changed before replacement.' >&2; exit 2; }
install -d -m 0755 -o root -g root /usr/local/lib/ar-local-drive-reclaim
install -d -m 0700 -o root -g root /var/lib/ar-local-drive-reclaim
install -m 0644 -o root -g root "$repo/pi_drive_reclaim.py" /usr/local/lib/ar-local-drive-reclaim/pi_drive_reclaim.py
install -d -m 0700 -o "$backup_user" -g "$backup_group" "$spool" "$spool/requests" "$spool/credentials"
install -d -m 0750 /etc/ar-local
if [ ! -f /etc/ar-local/drive-backup.env ]; then
  printf 'AR_LOCAL_DATA_ROOT=%s\nAR_LOCAL_DRIVE_BACKUP_SPOOL=%s\nRESTIC_REPOSITORY="rclone:ar_local_drive:AR-local Pi Backups/restic"\nRESTIC_PASSWORD_FILE=%s/credentials/restic.password\nRCLONE_CONFIG=%s/credentials/rclone.conf\n' "$data_root" "$spool" "$spool" "$spool" > /etc/ar-local/drive-backup.env
  chmod 0644 /etc/ar-local/drive-backup.env
fi
rendered=$(mktemp)
trap 'rm -f -- "$rendered"' EXIT
for unit in ar-local-drive-backup.service ar-local-drive-backup.timer ar-local-drive-backup-queue.timer ar-local-drive-reclaim.service ar-local-drive-reclaim-reconcile.service ar-local-drive-reclaim-reconcile.timer; do
  sed -e "s|{{AR_LOCAL_REPO}}|$repo|g" -e "s|{{AR_LOCAL_USER}}|$backup_user|g" \
      -e "s|{{AR_LOCAL_GROUP}}|$backup_group|g" -e "s|{{AR_LOCAL_DATA_ROOT}}|$data_root|g" \
      -e "s|{{AR_LOCAL_DRIVE_BACKUP_SPOOL}}|$spool|g" "$repo/deploy/pi/$unit" > "$rendered"
  install -m 0644 -o root -g root "$rendered" "/etc/systemd/system/$unit"
done
for unit in ar-local-daily.service ar-local-ingest-now.service ar-local-daily-watchdog.service ar-local-boot-recovery.service; do
  install -d -m 0755 "/etc/systemd/system/$unit.d"
  printf '[Service]\nEnvironmentFile=-/etc/ar-local/drive-backup.env\n' > "/etc/systemd/system/$unit.d/drive-backup.conf"
done
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/ar-local-drive-backup.service /etc/systemd/system/ar-local-drive-backup.timer /etc/systemd/system/ar-local-drive-backup-queue.timer /etc/systemd/system/ar-local-drive-reclaim.service /etc/systemd/system/ar-local-drive-reclaim-reconcile.service /etc/systemd/system/ar-local-drive-reclaim-reconcile.timer
# This timer restores host state only. It cannot start a backup or contact Drive.
systemctl enable --now ar-local-drive-reclaim-reconcile.timer
echo 'Installed; only host-state reconciliation is enabled. Complete OAuth, init, first backup and full restore, then enable both backup timers.'
