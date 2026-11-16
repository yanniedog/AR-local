#!/usr/bin/env bash
# Remove leftover /srv/ar-local/data/.daily-export-stage/<date> directories
# ONLY when every staged file is byte-identical to the finalized copy recorded
# in that date's completion or revision marker. Default mode changes nothing.
#
#   bash pi_export_stage_dedupe.sh                    # dry run (read-only)
#   bash pi_export_stage_dedupe.sh --delete-verified  # delete VERIFIED only
#
# Never touches data/runs, data/state or runs-archive. Never follows symlinks.
# Governing document: docs/PI_LEAN_REFACTOR_HANDOFF.md (task P1).
set -euo pipefail
export LC_ALL=C
DATA=/srv/ar-local/data
STAGE=$DATA/.daily-export-stage
STATE=$DATA/state
LOCKNAME=._exports.attempt-evidence-promotion.lock
MODE=dry
case "${1:-}" in
  "") ;;
  --delete-verified) MODE=delete ;;
  *) echo "STOP: unknown argument"; exit 2 ;;
esac

stop() { echo "STOP: $1"; exit 2; }

guard() {
  [ "$(id -un)" = pi ] || stop "run as user pi, not $(id -un)"
  [ "$(hostname)" = pi5 ] || stop "wrong host $(hostname)"
  local hm; hm=$((10#$(date +%H%M)))
  if [ "$hm" -ge 30 ] && [ "$hm" -lt 330 ]; then stop "ingest quiet window 00:30-03:30"; fi
  local u
  for u in ar-local-daily.service ar-local-ingest-now.service \
           ar-local-queue-task-daily-repair.service ar-local-day-archive.service; do
    case "$(systemctl is-active "$u" 2>/dev/null || true)" in
      active|activating|deactivating|reloading) stop "$u is running" ;;
    esac
  done
}

out_dirs() { # print every finalized out_dir recorded for day $1
  python3 - "$STATE" "$1" <<'PY'
import glob, json, os, sys
state, day = sys.argv[1], sys.argv[2]
paths = [os.path.join(state, day + ".done.json")]
paths += sorted(glob.glob(os.path.join(state, day + ".revision.*.json")))
for p in paths:
    try:
        v = json.load(open(p)).get("out_dir")
    except (OSError, ValueError):
        continue
    if isinstance(v, str) and v.startswith("/srv/ar-local/data/runs/" + day + "/"):
        print(v)
PY
}

identical_subset() { # every regular file under $1 equals the same path under $2
  local src=$1 dst=$2 rel
  [ -d "$dst" ] && [ ! -L "$dst" ] || return 1
  while IFS= read -r -d '' rel; do
    [ -f "$dst/$rel" ] && [ ! -L "$dst/$rel" ] || return 1
    cmp -s -- "$src/$rel" "$dst/$rel" || return 1
  done < <(cd "$src" && find . -type f -print0)
  return 0
}

guard
[ -d "$STAGE" ] && [ ! -L "$STAGE" ] || stop "$STAGE missing or a symlink"
today=$(date +%F); yesterday=$(date -d yesterday +%F)
verified=0; kept=0; freed_kb=0

for dir in "$STAGE"/*; do
  day=$(basename "$dir")
  reason=""
  if [[ ! $day =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then reason=not-a-date
  elif [ "$day" = "$today" ] || [ "$day" = "$yesterday" ]; then reason=too-recent
  elif [ -L "$dir" ] || [ ! -d "$dir" ]; then reason=not-a-plain-directory
  elif [ ! -f "$STATE/$day.done.json" ]; then reason=no-completion-marker
  elif [ -n "$(find "$dir" -mindepth 1 -maxdepth 1 ! -name _exports ! -name "$LOCKNAME" -print -quit)" ]; then reason=unexpected-children
  elif [ ! -d "$dir/_exports" ] || [ -L "$dir/_exports" ]; then reason=no-exports-directory
  elif [ -n "$(find "$dir" ! -type f ! -type d -print -quit)" ]; then reason=contains-symlink-or-special-file
  elif [ -z "$(find "$dir/_exports" -type f -print -quit)" ]; then reason=empty-exports
  else
    match=""
    while IFS= read -r cand; do
      if identical_subset "$dir/_exports" "$cand"; then match=$cand; break; fi
    done < <(out_dirs "$day")
    [ -n "$match" ] || reason=no-byte-identical-finalized-copy
  fi

  if [ -n "$reason" ]; then
    echo "KEEP      $day  $reason"; kept=$((kept + 1)); continue
  fi
  kb=$(du -sk "$dir" | cut -f1)
  verified=$((verified + 1)); freed_kb=$((freed_kb + kb))
  if [ "$MODE" = delete ]; then
    guard
    rm -rf --one-file-system -- "$STAGE/$day"
    echo "DELETED   $day  $((kb / 1024)) MB  identical-to $match"
  else
    echo "VERIFIED  $day  $((kb / 1024)) MB  identical-to $match"
  fi
done

echo "SUMMARY mode=$MODE verified=$verified kept=$kept reclaim_mb=$((freed_kb / 1024))"
