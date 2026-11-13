#!/bin/sh
# Definitions only, under the operator's exact-source/idle/queue install gate.
# No daemon reload, service start, scheduler or sudoers changes.
set -eu
repo_dir=${1:?reviewed repository root required}
expected=${2:?reviewed helper SHA256 required}
[ "$(id -u)" = 0 ] || { echo 'root installation required' >&2; exit 1; }
case "$expected" in ''|*[!0-9a-f]*) echo 'invalid SHA256' >&2; exit 1;; esac
[ "${#expected}" -eq 64 ] || exit 1
source="$repo_dir/pi_manual_ingest_restore.py"
[ "$(sha256sum "$source" | cut -d ' ' -f1)" = "$expected" ] || exit 1
bundle=/usr/local/lib/ar-local-manual-ingest
for parent in /usr /usr/local /usr/local/lib; do
  [ -d "$parent" ] && [ ! -L "$parent" ] || exit 1
  [ "$(stat -c %u "$parent")" = 0 ] || exit 1
  [ -z "$(find "$parent" -maxdepth 0 -perm /022 -print)" ] || exit 1
done
if [ -e "$bundle" ] || [ -L "$bundle" ]; then
  [ -d "$bundle" ] && [ ! -L "$bundle" ] || exit 1
  [ "$(stat -c %u "$bundle")" = 0 ] || exit 1
  [ -z "$(find "$bundle" -maxdepth 0 -perm /022 -print)" ] || exit 1
else
  install -d -o root -g root -m 0755 "$bundle"
fi
temporary=$(mktemp "$bundle/.restore-XXXXXXXX")
trap 'rm -f "$temporary"' EXIT
install -o root -g root -m 0555 "$source" "$temporary"
[ "$(sha256sum "$temporary" | cut -d ' ' -f1)" = "$expected" ] || exit 1
# Rename replaces the directory entry, not a symlink target; retain the previous
# installed bytes separately in the operator's rollback bundle before invocation.
mv -fT "$temporary" "$bundle/pi_manual_ingest_restore.py"
sync -f "$bundle"
[ "$(stat -c %u:%a "$bundle/pi_manual_ingest_restore.py")" = 0:555 ]
[ "$(sha256sum "$bundle/pi_manual_ingest_restore.py" | cut -d ' ' -f1)" = "$expected" ]
