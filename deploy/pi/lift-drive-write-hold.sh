#!/bin/bash
# Explicit operator-approved Google Drive write-hold lift (plan option 1B).
# Records hashes, removes hold markers, re-enables Restic backup timers.
# Does NOT start a backup by itself.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi

RECEIPT_DIR="${1:-/var/lib/ar-local-day-archives/hold-lift}"
mkdir -p "$RECEIPT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RECEIPT="$RECEIPT_DIR/hold-lift-$STAMP.json"

echo "Recording hold lift receipt to $RECEIPT"

hash_if_present() {
  local path="$1"
  if [[ -e "$path" || -L "$path" ]]; then
    sha256sum "$path" | awk '{print $1}'
  else
    echo ""
  fi
}

MARKER="/etc/ar-local/drive-write-hold.json"
LOCK="/etc/ar-local/.drive-write-hold-activation.lock"
SPOOL_HOLD="/var/lib/ar-local-drive-backup/write-hold.json"

MARKER_SHA="$(hash_if_present "$MARKER")"
LOCK_SHA="$(hash_if_present "$LOCK")"
SPOOL_SHA="$(hash_if_present "$SPOOL_HOLD")"

systemctl is-active ar-local-drive-backup.service >/tmp/ar-drive-backup-active.txt 2>&1 || true
ACTIVE="$(cat /tmp/ar-drive-backup-active.txt)"
if [[ "$ACTIVE" == "activating" || "$ACTIVE" == "active" ]]; then
  echo "refusing hold lift while backup service is $ACTIVE" >&2
  exit 2
fi

python3 - <<'PY' "$RECEIPT" "$MARKER" "$LOCK" "$SPOOL_HOLD" "$MARKER_SHA" "$LOCK_SHA" "$SPOOL_SHA" "$STAMP"
import json, sys
receipt, marker, lock, spool, marker_sha, lock_sha, spool_sha, stamp = sys.argv[1:]
payload = {
  "schema": "ar-local-drive-write-hold-lift-v1",
  "lifted_at_utc": stamp,
  "reason": "operator authorized full Drive write resume + daily CDR day-archives (1B)",
  "markers": {
    marker: marker_sha or None,
    lock: lock_sha or None,
    spool: spool_sha or None,
  },
}
with open(receipt, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
print(receipt)
PY

# Remove hold markers after receipt is durable.
rm -f "$MARKER" "$LOCK" "$SPOOL_HOLD"

# Drop hold-role symlink locks in the spool if present (best-effort inventory).
if [[ -L /var/lib/ar-local-drive-backup/backup.lock ]]; then
  target="$(readlink /var/lib/ar-local-drive-backup/backup.lock || true)"
  if [[ "$target" == *drive-write-hold* || "$target" == *hold-activation* ]]; then
    rm -f /var/lib/ar-local-drive-backup/backup.lock
  fi
fi

systemctl enable ar-local-drive-backup.timer ar-local-drive-backup-queue.timer
systemctl start ar-local-drive-backup.timer ar-local-drive-backup-queue.timer
systemctl list-timers 'ar-local-drive-backup*' --no-pager

echo "Drive write hold lifted. Receipt: $RECEIPT"
