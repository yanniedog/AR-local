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
install -d -m 0700 -o "$backup_user" -g "$backup_group" "$spool" "$spool/requests" "$spool/credentials"
install -d -m 0750 /etc/ar-local
if [ ! -f /etc/ar-local/drive-backup.env ]; then
  printf 'AR_LOCAL_DATA_ROOT=%s\nAR_LOCAL_DRIVE_BACKUP_SPOOL=%s\nRESTIC_REPOSITORY="rclone:ar_local_drive:AR-local Pi Backups/restic"\nRESTIC_PASSWORD_FILE=%s/credentials/restic.password\nRCLONE_CONFIG=%s/credentials/rclone.conf\n' "$data_root" "$spool" "$spool" "$spool" > /etc/ar-local/drive-backup.env
  chmod 0644 /etc/ar-local/drive-backup.env
fi
for unit in ar-local-drive-backup.service ar-local-drive-backup.timer ar-local-drive-backup-queue.timer; do
  sed -e "s|{{AR_LOCAL_REPO}}|$repo|g" -e "s|{{AR_LOCAL_USER}}|$backup_user|g" \
      -e "s|{{AR_LOCAL_GROUP}}|$backup_group|g" -e "s|{{AR_LOCAL_DATA_ROOT}}|$data_root|g" \
      -e "s|{{AR_LOCAL_DRIVE_BACKUP_SPOOL}}|$spool|g" "$repo/deploy/pi/$unit" > "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/ar-local-drive-backup.service /etc/systemd/system/ar-local-drive-backup.timer /etc/systemd/system/ar-local-drive-backup-queue.timer
echo 'Installed; no timers enabled by this installer. Complete OAuth, init, first backup and full restore, then enable both timers.'
