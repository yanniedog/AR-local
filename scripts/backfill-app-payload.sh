#!/usr/bin/env bash
# Backfill per-date app-payload GitHub releases on the Pi (or any host with exports + gh auth).
#
# Usage (Pi, from repo root):
#   sudo -E bash scripts/backfill-app-payload.sh
#   sudo -E bash scripts/backfill-app-payload.sh --from-date 2026-05-13 --to-date 2026-06-08
#   sudo -E bash scripts/backfill-app-payload.sh --dry-run
#   sudo -E bash scripts/backfill-app-payload.sh --latest-only
#
# Requires GH_TOKEN (or gh auth) with contents:read+write. On the Pi, load
# /etc/ar-local/app-payload.env before running (sudo -E preserves EnvironmentFile vars
# when invoked from systemd; for manual runs, source the env file first).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f /etc/ar-local/app-payload.env ]]; then
  # shellcheck disable=SC1091
  set -a
  source /etc/ar-local/app-payload.env
  set +a
fi

export AR_LOCAL_DATA_ROOT="${AR_LOCAL_DATA_ROOT:-/srv/ar-local/data}"
exec python3 "$ROOT/scripts/backfill_app_payload.py" "$@"
