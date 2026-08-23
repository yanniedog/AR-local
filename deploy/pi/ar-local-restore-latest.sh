#!/usr/bin/env sh
set -eu

repo="${1:?repo path required}"
site="${2:?site repo path required}"
data="${3:?data root required}"
config="/etc/ar-local/backup.env"
backup_dir="$(sed -n 's/^AR_BACKUP_DIRECTORY=//p' "$config" | tail -n 1)"
case "$backup_dir" in /*) ;; *) echo "Invalid backup directory" >&2; exit 1;; esac
snapshot_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["snapshot_id"])' "$backup_dir/latest-backup.json")"
exec /usr/bin/python3 "$repo/pi_backup_foundation.py" restore-drill \
  --config "$config" --repo "$repo" --site-repo "$site" --data-root "$data" \
  --snapshot-id "$snapshot_id" --operator systemd-restore
