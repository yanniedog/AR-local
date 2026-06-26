#!/usr/bin/env sh
# Harden the AR-local Pi against unexpected power loss.
#
# Root cause this addresses: a power cut mid-write corrupts the SD card.
# On the next boot the Pi then either (a) halts at an fsck prompt, (b) comes
# up read-only, or (c) loses regenerated SSH host keys / app state — so the
# CDR ingest+dashboard silently stop and the box may be unreachable.
#
# This script is idempotent. cmdline.txt / config.txt edits only take effect
# after a reboot; everything else applies immediately.
#
# Usage (on the Pi):  sudo sh deploy/pi/install-power-resilience.sh
set -eu

log() { printf '[power-resilience] %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo sh $0" >&2
  exit 1
fi

# --- locate the boot firmware partition (Bookworm+ = /boot/firmware) ---------
if [ -d /boot/firmware ]; then
  boot_dir=/boot/firmware
elif [ -d /boot ]; then
  boot_dir=/boot
else
  boot_dir=""
  log "WARN: no /boot or /boot/firmware found; skipping cmdline/config edits"
fi

# --- 1. fsck: auto-repair on boot instead of halting at a prompt -------------
# Without this, an unclean ext4 filesystem can stop boot waiting for a manual
# 'fsck -y'. With it, the Pi self-repairs and continues unattended.
if [ -n "$boot_dir" ] && [ -f "$boot_dir/cmdline.txt" ]; then
  cmdline="$boot_dir/cmdline.txt"
  changed=0
  for opt in fsck.mode=force fsck.repair=yes; do
    if ! grep -qw "$opt" "$cmdline"; then
      # cmdline.txt MUST stay a single line: append to the existing line.
      sed -i "1 s|\$| $opt|" "$cmdline"
      changed=1
    fi
  done
  if [ "$changed" -eq 1 ]; then
    log "cmdline.txt: enabled fsck.mode=force fsck.repair=yes (reboot to apply)"
  else
    log "cmdline.txt: fsck auto-repair already enabled"
  fi
fi

# --- 2. hardware watchdog: auto-reboot a hung kernel / hung boot -------------
if [ -n "$boot_dir" ] && [ -f "$boot_dir/config.txt" ]; then
  config="$boot_dir/config.txt"
  if ! grep -qE '^[[:space:]]*dtparam=watchdog=on' "$config"; then
    printf '\n# AR-local: enable BCM hardware watchdog (auto-reboot on hang)\ndtparam=watchdog=on\n' >> "$config"
    log "config.txt: enabled dtparam=watchdog=on (reboot to apply)"
  else
    log "config.txt: hardware watchdog already enabled"
  fi
fi

# --- 3. systemd watchdog: pet the hardware watchdog + bounded reboot ---------
# RuntimeWatchdogSec arms the hardware watchdog via systemd so a frozen
# userspace triggers a reboot. RebootWatchdogSec caps how long a shutdown can
# hang before being forced. ShutdownWatchdogSec is the legacy alias.
mkdir -p /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/ar-local-watchdog.conf <<'EOF'
# Managed by AR-local install-power-resilience.sh
[Manager]
RuntimeWatchdogSec=20
RebootWatchdogSec=2min
EOF
log "systemd: RuntimeWatchdogSec=20, RebootWatchdogSec=2min"

# --- 4. journald: persistent + bounded so logs survive but never fill disk ---
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/ar-local.conf <<'EOF'
# Managed by AR-local install-power-resilience.sh
[Journal]
Storage=persistent
SystemMaxUse=200M
SystemKeepFree=300M
EOF
systemctl restart systemd-journald 2>/dev/null || true
log "journald: persistent, capped at 200M"

# --- 5. tailscale: ensure it auto-starts so remote access returns on boot ----
# This incident: after the reboot the Pi was reachable on the LAN but offline
# on the tailnet. If tailscaled is installed it MUST be enabled to come back.
if command -v tailscaled >/dev/null 2>&1 || systemctl list-unit-files 2>/dev/null | grep -q '^tailscaled\.service'; then
  systemctl enable --now tailscaled 2>/dev/null \
    && log "tailscaled: enabled + started" \
    || log "WARN: could not enable tailscaled (check 'sudo tailscale up')"
else
  log "tailscale not installed; skipping (install + 'sudo tailscale up' for remote access)"
fi

systemctl daemon-reload
log "done. cmdline.txt / config.txt changes require a reboot to take effect."
