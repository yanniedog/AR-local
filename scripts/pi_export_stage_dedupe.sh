#!/usr/bin/env bash
# Remove leftover /srv/ar-local/data/.daily-export-stage/<date> directories
# ONLY when (1) the production verifier accepts that date's completion marker,
# (2) every recorded generation of that date has a PASS raw-day archive, and
# (3) every staged file exists byte-identically in a finalized directory named
# by that date's completion or revision marker (staged is a subset: the
# finalized directory may hold extra post-install reports).
# Default mode changes nothing. Delete mode runs only inside a shared-queue
# job (pi-shared-task) and only 04:00-23:30.
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
PROD=/srv/ar-local/AR-local
RAW_PROGRESS=/var/lib/ar-local-day-archives/meta/raw-progress.jsonl
LOCKNAME=._exports.attempt-evidence-promotion.lock
MODE=dry
case "${1:-}" in
  "") ;;
  --delete-verified) MODE=delete ;;
  *) echo "STOP: unknown argument"; exit 2 ;;
esac

stop() { echo "STOP: $1"; exit 2; }

lease_check() {
  # The ingest lock must be absent for a dry run. For delete it must be the
  # host lease of the queue supervisor that launched this job (a
  # "pi-shared-task --resource host" job): role shared-pi-host-task and a pid
  # in the same queue unit as this process. Any other holder means ingest work.
  local lock=$STATE/daily-ingest.lock holder role
  if [ ! -e "$lock" ]; then
    [ "$MODE" = dry ] && return 0
    stop "no queue host lease: submit with pi-shared-task --resource ar-local --resource host"
  fi
  [ "$MODE" = delete ] || stop "daily-ingest.lock present"
  [ -f "$lock" ] && [ ! -L "$lock" ] || stop "daily-ingest.lock is not a regular file"
  holder=$(grep -E "^pid=[0-9]+$" "$lock" | head -n 1 | cut -d= -f2)
  role=$(sed -n 's/^role=//p' "$lock" | head -n 1)
  case "$role" in shared-pi-host-task:*) ;; *) stop "daily-ingest.lock held by another role" ;; esac
  [ -n "$holder" ] || stop "daily-ingest.lock has no pid"
  # Supervisor and job live in the same queue unit (possibly sub-cgroups).
  local unit='ar-local-queue-task-[0-9a-f]{32}\.service' mine theirs
  mine=$(grep -Eo "$unit" /proc/self/cgroup | head -n 1)
  theirs=$(grep -Eo "$unit" "/proc/$holder/cgroup" 2>/dev/null | head -n 1 || true)
  [ -n "$mine" ] && [ "$mine" = "$theirs" ] && return 0
  stop "daily-ingest.lock is held by a process that is not this job's supervisor"
}

guard() {
  [ "$(id -un)" = pi ] || stop "run as user pi, not $(id -un)"
  [ "$(hostname)" = pi5 ] || stop "wrong host $(hostname)"
  if [ "$MODE" = delete ]; then
    local hm; hm=$((10#$(date +%H%M)))
    if [ "$hm" -lt 400 ] || [ "$hm" -gt 2330 ]; then stop "delete allowed only 04:00-23:30"; fi
    grep -Eq '/ar-local-queue-task-[0-9a-f]{32}\.service$' /proc/self/cgroup \
      || stop "delete mode must run inside a pi-shared-task queue job"
  fi
  lease_check
  local u
  for u in ar-local-daily.service ar-local-daily-watchdog.service \
           ar-local-ingest-now.service ar-local-boot-recovery.service \
           ar-local-queue-task-daily-repair.service ar-local-day-archive.service \
           ar-local-drive-backup.service ar-local-drive-reclaim.service; do
    case "$(systemctl is-active "$u" 2>/dev/null || true)" in
      active|activating|deactivating|reloading) stop "$u is running" ;;
    esac
  done
}

out_dirs() { # print every finalized marker path and its recorded out_dir
  python3 - "$STATE" "$1" <<'PY'
import glob, json, os, sys
state, day = sys.argv[1], sys.argv[2]
paths = [os.path.join(state, day + ".done.json")]
paths += sorted(glob.glob(os.path.join(state, day + ".revision.*.json")))
for p in paths:
    try:
        with open(p, encoding="utf-8") as marker_file:
            marker = json.load(marker_file)
    except (OSError, ValueError):
        continue
    if isinstance(marker, dict) and isinstance(marker.get("out_dir"), str):
        sys.stdout.write(p + "\0" + marker["out_dir"] + "\0")
PY
}

verified_out_dir() { # print canonical out_dir only when its marker verifies
  PYTHONPATH=$PROD PYTHONDONTWRITEBYTECODE=1 python3 - \
    "$STATE" "$1" "$2" "$3" <<'PY'
import json, re, sys
from pathlib import Path
from cdr_finalization import verify_completion_marker

state = Path(sys.argv[1]).resolve(strict=True)
day, marker_name, recorded_path = sys.argv[2:]
if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
    sys.exit(1)
marker_path = Path(marker_name)
if (marker_path.parent != state
        or (marker_path.name != day + ".done.json"
            and not re.fullmatch(re.escape(day) + r"\.revision\..+\.json", marker_path.name))
        or marker_path.is_symlink() or not marker_path.is_file()):
    sys.exit(1)
try:
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if (not isinstance(marker, dict)
            or marker.get("out_dir") != recorded_path
            or verify_completion_marker(marker, state, day) is not True):
        sys.exit(1)
    runs_root = Path("/srv/ar-local/data/runs").resolve(strict=True)
    day_root = (runs_root / day).resolve(strict=True)
    candidate = Path(recorded_path).resolve(strict=True)
    if (day_root.parent != runs_root or candidate == day_root
            or day_root not in candidate.parents
            or not candidate.is_dir()):
        sys.exit(1)
except (OSError, ValueError, TypeError, RuntimeError):
    sys.exit(1)
print(candidate)
PY
}

authorized() { # marker verifies AND every recorded generation archived PASS
  PYTHONPATH=$PROD PYTHONDONTWRITEBYTECODE=1 python3 - "$STATE" "$1" "$RAW_PROGRESS" <<'PY'
import glob, json, sys
from pathlib import Path
state, day, progress = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
try:
    from cdr_finalization import verify_completion_marker
    marker = json.loads((state / (day + ".done.json")).read_text())
    if verify_completion_marker(marker, state, day) is not True:
        sys.exit(3)
    passed = set()
    for line in open(progress, encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            if row.get("result") == "PASS":
                passed.add((row.get("date"), row.get("generation_id")))
    for path in glob.glob(str(state / (day + ".*.ram-stage-ownership.json"))):
        own = json.loads(Path(path).read_text())
        if (own.get("date"), own.get("generation_id")) not in passed:
            sys.exit(4)
except SystemExit:
    raise
except BaseException:
    sys.exit(5)
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
  elif ! authorized "$day"; then reason=marker-unverified-or-archive-not-passed
  else
    match=""
    while IFS= read -r -d '' marker && IFS= read -r -d '' cand; do
      candidate=$(verified_out_dir "$day" "$marker" "$cand") || continue
      if identical_subset "$dir/_exports" "$candidate"; then
        match=$candidate; break
      fi
    done < <(out_dirs "$day")
    [ -n "$match" ] || reason=staged-file-missing-or-different-in-finalized
  fi

  if [ -n "$reason" ]; then
    echo "KEEP      $day  $reason"; kept=$((kept + 1)); continue
  fi
  kb=$(du -sk "$dir" | cut -f1)
  verified=$((verified + 1)); freed_kb=$((freed_kb + kb))
  if [ "$MODE" = delete ]; then
    guard
    rm -rf --one-file-system -- "$STAGE/$day"
    echo "DELETED   $day  $((kb / 1024)) MB  subset-of $match"
  else
    echo "VERIFIED  $day  $((kb / 1024)) MB  subset-of $match"
  fi
done

echo "SUMMARY mode=$MODE verified=$verified kept=$kept reclaim_mb=$((freed_kb / 1024))"
