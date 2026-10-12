#!/usr/bin/env sh
# Runs once per boot (ar-local-boot-recovery.service) to self-heal after an
# unexpected power cycle:
#   1. ensure the dashboard backend is actually running,
#   2. observe the daily CDR ingest if a scheduled run was missed while the
#      Pi was powered off (e.g. the 01:00 slot),
#   3. email a "Pi rebooted" alert so an unexpected reboot is never silent.
# Every step is best-effort: a failure in one must not block the others.
set -u

REPO_DIR="${AR_LOCAL_CODE_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
log() { printf '[boot-recovery] %s\n' "$*"; }

# 1. Dashboard up? (Restart=always should handle it, but make boot deterministic.)
if ! systemctl is-active --quiet ar-local-dashboard.service; then
  log "dashboard not active; starting"
  sudo systemctl start --no-block ar-local-dashboard.service || log "WARN: dashboard start failed"
fi

# 2. Observe only; repair belongs to the once-daily bounded controller.
if [ -f "$REPO_DIR/pi_ingest_observe.py" ]; then
  log "running daily watchdog observation"
  /usr/bin/python3 "$REPO_DIR/pi_ingest_observe.py" || log "WARN: watchdog observation returned nonzero"
fi

# 3. Notify that the Pi rebooted (non-fatal; needs /etc/ar-local/notify.env).
if [ -f "$REPO_DIR/pi_ingest_alert.py" ]; then
  uptime_str="$(uptime -p 2>/dev/null || echo unknown)"
  # --force: every reboot is worth knowing about, even several within the alert
  # cooldown window (e.g. a power-cycle loop).
  /usr/bin/python3 "$REPO_DIR/pi_ingest_alert.py" \
    --reason boot-recovery --force \
    --details "Pi booted/rebooted ($uptime_str). Boot-recovery ran dashboard check + ingest observation." \
    || log "boot alert not sent (SMTP not configured?)"
fi

log "done"
exit 0
