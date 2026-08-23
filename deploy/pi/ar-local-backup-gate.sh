#!/usr/bin/env sh
set -eu

trusted="/usr/local/lib/ar-local-backup"
manifest="/etc/ar-local/backup-gate.sha256"
[ -d "$trusted" ] && [ -f "$manifest" ] || {
  echo "Trusted backup gate is not installed" >&2
  exit 1
}
(cd "$trusted" && sha256sum -c "$manifest") >/dev/null
export PYTHONPATH="$trusted"
exec /usr/bin/python3 "$trusted/pi_backup_foundation.py" "$@"
