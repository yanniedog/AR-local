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
  # Tailnet SSH: a key-independent recovery path so a lost ~/.ssh/authorized_keys
  # can't lock us out again. Best-effort: 'set --ssh' aborts if it would drop the
  # current tailscale-routed session, which is fine (re-run from a LAN console).
  if command -v tailscale >/dev/null 2>&1; then
    tailscale set --ssh 2>/dev/null \
      && log "tailscale: tailnet SSH enabled" \
      || log "tailscale: enable tailnet SSH manually: sudo tailscale set --ssh"
  fi
else
  log "tailscale not installed; skipping (install + 'sudo tailscale up' for remote access)"
fi

# --- 6. WiFi: country + bullet-proof autoconnect on every wifi profile -------
# Root cause of the 2026-06-27 outage: after a power cut the Pi booted but WiFi
# never came up, so the headless box was invisible. The fix that matters is
# autoconnect-retries=0 (NM's default gives up after 4 tries, so a router slow
# to return after a shared outage is never rejoined). do_wifi_country AU is set
# for correctness but is cosmetic on the Pi's self-managed brcmfmac driver
# (the regulatory domain is taken from the AP, not from iw / cfg80211).
wifi_country="${AR_LOCAL_WIFI_COUNTRY:-AU}"
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_wifi_country "$wifi_country" 2>/dev/null \
    && log "wifi country set to $wifi_country (raspi-config)" || true
fi
command -v iw >/dev/null 2>&1 && iw reg set "$wifi_country" 2>/dev/null || true
if command -v nmcli >/dev/null 2>&1; then
  nmcli radio wifi on 2>/dev/null || true
  # Harden every saved wifi connection WITHOUT touching credentials (the PSK
  # stays in the existing NetworkManager profile; never store it in this repo).
  nmcli -t -f NAME,TYPE connection show 2>/dev/null | while IFS=: read -r name type; do
    [ "$type" = "802-11-wireless" ] || continue
    nmcli connection modify "$name" \
      connection.autoconnect yes \
      connection.autoconnect-priority 100 \
      connection.autoconnect-retries 0 \
      802-11-wireless.powersave 2 \
      ipv4.may-fail yes ipv6.may-fail yes 2>/dev/null \
      && log "wifi '$name': autoconnect=forever, powersave=off, priority=100" \
      || log "WARN: could not harden wifi profile '$name'"
  done
else
  log "nmcli not found; cannot harden wifi autoconnect (is NetworkManager installed?)"
fi

# --- 7. Headless: boot to multi-user (no display manager waiting on a screen) -
if [ "$(systemctl get-default 2>/dev/null)" != "multi-user.target" ]; then
  systemctl set-default multi-user.target 2>/dev/null \
    && log "default target -> multi-user.target (headless)" \
    || log "WARN: could not set multi-user.target"
else
  log "default target already multi-user.target"
fi

# --- 8. Network self-heal watchdog: kick NM if the link wedges --------------
# autoconnect-retries=0 makes NM retry forever, but a wedged wifi driver can
# need a nudge. This timer pings the default gateway every 3 min and, if it is
# unreachable, restarts NetworkManager + re-ups the wifi profiles.
cat > /usr/local/sbin/ar-local-net-watchdog.sh <<'WD'
#!/usr/bin/env sh
# Re-establish networking if the default gateway is unreachable.
gw="$(ip route show default 2>/dev/null | awk '/default/{print $3; exit}')"
[ -n "$gw" ] && ping -c1 -W3 "$gw" >/dev/null 2>&1 && exit 0
logger -t ar-local-net-watchdog "no network (gw='${gw:-none}'); restarting NetworkManager"
systemctl restart NetworkManager 2>/dev/null || true
sleep 8
if command -v nmcli >/dev/null 2>&1; then
  # Try wifi profiles in autoconnect-priority order (highest first), stop on the
  # first that brings up a default gateway. Gives Nikipedia -> ASUS_2.4 -> Slow
  # failover even if NetworkManager's own autoconnect fixates on one SSID.
  nmcli -t -f AUTOCONNECT-PRIORITY,TYPE,NAME connection show 2>/dev/null \
    | awk -F: '$2=="802-11-wireless"{print $1":"$3}' | sort -t: -k1 -rn | cut -d: -f2- \
    | while IFS= read -r n; do
        nmcli connection up "$n" 2>/dev/null || continue
        ngw="$(ip route show default 2>/dev/null | awk '/default/{print $3; exit}')"
        [ -n "$ngw" ] && ping -c1 -W3 "$ngw" >/dev/null 2>&1 && break
      done
fi
WD
chmod +x /usr/local/sbin/ar-local-net-watchdog.sh
cat > /etc/systemd/system/ar-local-net-watchdog.service <<'WS'
[Unit]
Description=AR-local network self-heal (re-establish wifi if gateway unreachable)
After=NetworkManager.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/ar-local-net-watchdog.sh
WS
cat > /etc/systemd/system/ar-local-net-watchdog.timer <<'WT'
[Unit]
Description=Run AR-local network self-heal every 3 minutes
[Timer]
OnBootSec=3min
OnUnitActiveSec=3min
Persistent=true
[Install]
WantedBy=timers.target
WT
systemctl daemon-reload
systemctl enable --now ar-local-net-watchdog.timer 2>/dev/null \
  && log "net-watchdog timer enabled (every 3 min)" \
  || log "WARN: could not enable net-watchdog timer"

log "done. cmdline.txt / config.txt changes require a reboot to take effect."
