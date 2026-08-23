#!/usr/bin/env sh
set -eu

command="${1:?backup command required}"
repo="${2:?repo path required}"
site="${3:?site repo path required}"
data="${4:?data root required}"

hour="$(TZ=Australia/Hobart date +%H)"
minute="$(TZ=Australia/Hobart date +%M)"
hour="${hour#0}"
minute="${minute#0}"
[ -n "$hour" ] || hour=0
[ -n "$minute" ] || minute=0
minutes=$((hour * 60 + minute))
if [ "$minutes" -ge 30 ] && [ "$minutes" -lt 210 ]; then
  echo "Backup/restore catch-up is blocked during the 00:30-03:30 ingest window" >&2
  exit 75
fi
if systemctl is-active --quiet ar-local-daily.service || systemctl is-active --quiet ar-local-ingest-now.service; then
  echo "Backup/restore is blocked while an ingest service is active" >&2
  exit 75
fi
today="$(TZ=Australia/Hobart date +%F)"
if [ ! -f "$data/state/$today.done.json" ]; then
  if ! PYTHONPATH=/usr/local/lib/ar-local-backup python3 /usr/local/lib/ar-local-backup/pi_ingest_terminal.py validate \
    --state-root "$data/state" --date "$today" --config /etc/ar-local/backup.env >/dev/null; then
    echo "Backup/restore is blocked until today's scheduled ingest has finalized or failed terminally: $today" >&2
    exit 75
  fi
  echo "Backup/restore is preserving terminal failed-ingest evidence for $today" >&2
fi

case "$command" in
  snapshot)
    exec /usr/local/bin/ar-local-backup-gate snapshot --config /etc/ar-local/backup.env \
      --repo "$repo" --site-repo "$site" --data-root "$data" --operator systemd-backup
    ;;
  restore-drill)
    exec /usr/local/bin/ar-local-restore-latest "$repo" "$site" "$data"
    ;;
  *)
    echo "Unknown backup command: $command" >&2
    exit 2
    ;;
esac
