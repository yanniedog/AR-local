#!/usr/bin/env bash
# On-Pi drift monitor. Deployment is manual and canary-gated; this service never
# pulls, switches branches, restarts services, or mutates runtime data. Verification
# may refresh remote refs so drift evidence is current.
set -euo pipefail
REPO="${AR_LOCAL_REPO:-/srv/ar-local/AR-local}"
export AR_PI_VERIFY_LOCAL=1
export AR_PI_BASE_URL="${AR_PI_BASE_URL:-http://127.0.0.1/}"
cd "$REPO"
if python3 pi_deploy_verify.py --verify; then
  exit 0
fi
echo "ar-local-deploy-watchdog: drift detected; automatic deployment is disabled" >&2
echo "Use the canary-gated pi-deploy-canary workflow with an exact approved commit." >&2
exit 1
