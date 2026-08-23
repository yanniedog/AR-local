#!/usr/bin/env sh
set -eu

repo="${1:?repo path required}"
site="${2:?site repo path required}"
data="${3:?data root required}"
config="/etc/ar-local/backup.env"
trusted="/usr/local/lib/ar-local-backup"
backup_dir="$(PYTHONPATH="$trusted" python3 -c 'from pathlib import Path; from ar_local_backup_policy import BackupPolicy; print(BackupPolicy.from_env_file(Path("/etc/ar-local/backup.env")).backup_dir)')"
case "$backup_dir" in /*) ;; *) echo "Invalid backup directory" >&2; exit 1;; esac
snapshot_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["snapshot_id"])' "$backup_dir/latest-backup.json")"
exec /usr/local/bin/ar-local-backup-gate restore-drill \
  --config "$config" --repo "$repo" --site-repo "$site" --data-root "$data" \
  --snapshot-id "$snapshot_id" --operator systemd-restore
