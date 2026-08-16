#!/usr/bin/env bash
# On-Pi deploy watchdog: verify sync + smoke; deploy on drift (no GitHub SSH required).
set -euo pipefail
REPO="${AR_LOCAL_REPO:-/srv/ar-local/AR-local}"
export AR_PI_VERIFY_LOCAL=1
export AR_PI_BASE_URL="${AR_PI_BASE_URL:-http://127.0.0.1/}"
cd "$REPO"
if python3 pi_deploy_verify.py --verify; then
  exit 0
fi
exec python3 pi_deploy_verify.py --deploy
