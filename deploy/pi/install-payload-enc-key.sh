#!/usr/bin/env bash
# Install (or generate) the AES-256-GCM key for app payload asset encryption
# (Phase A of docs/SECURITY_CDR_PIPELINE.md). The key is written to
# /etc/ar-local/payload.key (mode 0600, 64 hex chars) and is NEVER committed.
#
#   sudo sh deploy/pi/install-payload-enc-key.sh            # generate a new key
#   sudo sh deploy/pi/install-payload-enc-key.sh <64-hex>   # install an existing key
#
# This script does NOT enable encryption. Once the app ships decrypt support
# (Phase B), turn it on by adding to /etc/ar-local/app-payload.env:
#   AR_LOCAL_PAYLOAD_ENC=1
#   AR_LOCAL_PAYLOAD_KEY_FILE=/etc/ar-local/payload.key
set -eu

dir=/etc/ar-local
file="$dir/payload.key"

if [ -e "$file" ] && [ -z "${1:-}" ]; then
  echo "$file already exists; refusing to overwrite. Pass a key to replace it." >&2
  exit 2
fi

key="${1:-$(openssl rand -hex 32)}"
case "$key" in
  *[!0-9a-fA-F]*) echo "key must be 64 hex chars" >&2; exit 2 ;;
esac
if [ "${#key}" -ne 64 ]; then
  echo "key must be 64 hex chars (32 bytes), got ${#key}" >&2
  exit 2
fi

sudo mkdir -p "$dir"
umask 077
tmp="$(mktemp)"
printf '%s\n' "$key" >"$tmp"
sudo install -m 0600 "$tmp" "$file"
rm -f "$tmp"

echo "Wrote $file (mode 0600)."
echo "Key id (non-secret, appears in manifests once enabled):"
python3 - "$file" <<'PY'
import sys
sys.path.insert(0, "/srv/ar-local/AR-local")
from pathlib import Path
import payload_crypto
print(" ", payload_crypto.key_id(payload_crypto.load_key(Path(sys.argv[1]))))
PY
echo "Encryption stays OFF until AR_LOCAL_PAYLOAD_ENC=1 is set (see header)."
