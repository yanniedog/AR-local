# Pi power-loss resilience & recovery

The AR-local CDR ingest + dashboard run on a single Raspberry Pi 5
(`ar-local-pi5`). An **unexpected power cut** is the highest-risk event for
this box: a cut mid-write can corrupt the SD card, and on the next boot the Pi
may halt at an fsck prompt, come up read-only, lose its SSH host keys /
`authorized_keys`, or simply not restart the CDR services — so packages stop
and the Pi can look "offline".

This doc covers (1) how to find and recover the Pi after such an event, and
(2) the hardening that now makes the Pi self-heal on the next boot.

---

## 1. Recovery runbook (Pi unreachable after a power cycle)

### Step 1 — find the Pi on the LAN
DHCP often hands the Pi a **new IP** after a reboot, which makes the old
Tailscale/LAN address look dead. Find it by MAC:

```bash
# From a machine on the same LAN (e.g. 10.0.0.0/24):
for i in $(seq 1 254); do ping -n 1 -w 250 10.0.0.$i >/dev/null 2>&1 & done; wait
arp -a | grep -iE 'd8-3a-dd|2c-cf-67|e4-5f-01|dc-a6-32|b8-27-eb'   # Raspberry Pi OUIs
```

`ar-local-pi5` is a **Pi 5** → MAC prefix `d8:3a:dd` (or `2c:cf:67`).
Confirm it's the AR-local box: port 80 open (nginx) and the backend on 8808.

> A Pi-5-OUI host whose port 80 returns an *empty reply* and whose port 8808
> is *closed* is the AR-local Pi with the dashboard backend **down** — that is
> the "no CDR packages" symptom.

### Step 2 — get in
If SSH fails with `Permission denied (publickey)` **and** the host key
changed, the SD card lost `~/.ssh/authorized_keys` and `/etc/ssh/*` (corruption
or a re-flash). You need the **console (monitor + keyboard)**. Then re-add your
key:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'ssh-ed25519 AAAA... your-key' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

On the *client* side, drop the stale host key so you can reconnect:
```bash
ssh-keygen -R 10.0.0.92      # old IP / HostKeyAlias
ssh-keygen -R ar-local-pi5
```

### Step 3 — assess corruption vs re-flash
```bash
cat /etc/os-release | grep PRETTY; uname -a
findmnt / -o SOURCE,FSTYPE,OPTIONS          # is root 'ro'?
dmesg | grep -iE 'ext4|corrupt|fsck|read-only|I/O error' | tail -20
ls /srv/ar-local/AR-local                   # repo still present?
```
- Root mounted `ro` → `sudo fsck -y /dev/mmcblk0p2` from a clean state (or
  `sudo touch /forcefsck && sudo reboot`) then remount rw.
- `/srv/ar-local/AR-local` missing → fresh OS; re-run the full install
  (`deploy/pi/install-pi-systemd.sh`).

### Step 4 — restart services & rectify any data gap
```bash
cd /srv/ar-local/AR-local
sudo systemctl start ar-local-dashboard.service
python3 pi_daily_watchdog.py            # catches up a missed daily ingest (grace-gated, idempotent)
# If the watchdog declines but today's run is genuinely missing:
python3 pi_daily_sync.py --banks-only --date "$(date +%F)"
# Verify:
python3 verify_local.py --base-url=http://127.0.0.1:8808/ --require-banks-rates --expect-run-date "$(date +%F)"
```

### Step 5 — restore remote access
```bash
sudo systemctl enable --now tailscaled
sudo tailscale up         # re-auth if needed
```

### Step 6 — apply hardening (if not already current)
```bash
cd /srv/ar-local/AR-local && git pull --ff-only origin main
sudo sh deploy/pi/install-power-resilience.sh
sudo reboot               # cmdline.txt/config.txt changes need a reboot
```

---

## 2. What the hardening does

`deploy/pi/install-power-resilience.sh` (run automatically by
`install-pi-systemd.sh`, and safe to re-run):

| Mechanism | File | Effect |
|---|---|---|
| **fsck auto-repair** | `cmdline.txt` `fsck.mode=force fsck.repair=yes` | Boot self-repairs an unclean filesystem instead of halting at a prompt. |
| **Hardware watchdog** | `config.txt` `dtparam=watchdog=on` + `RuntimeWatchdogSec=20` | A hung kernel/boot auto-reboots. |
| **Bounded reboot** | `RebootWatchdogSec=2min` | A hung shutdown is force-completed. |
| **Persistent, capped logs** | journald `Storage=persistent`, `SystemMaxUse=200M` | Boot logs survive for diagnosis; logs can't fill the disk. |
| **Tailscale auto-start** | `systemctl enable --now tailscaled` | Remote access returns automatically after a reboot. |

Service-level resilience (in the unit files, applied by `install-pi-systemd.sh`):

- **`ar-local-dashboard.service`**: `Restart=always` (was `on-failure`) so the
  backend on :8808 / nginx upstream never stays dead after an unexpected exit.
- **`ar-local-boot-recovery.service`** (oneshot, every boot):
  1. starts the dashboard if it isn't active,
  2. runs `pi_daily_watchdog.py` to catch up a daily ingest missed while powered off,
  3. emails a "Pi rebooted" alert (`pi_ingest_alert.py --reason boot-recovery`).
- Existing `ar-local-daily-watchdog.timer` (`Persistent=true`, `OnBootSec=10min`)
  remains the backstop for any still-missing run.

## 3. Recommended (manual / router-side)

- **DHCP reservation** for the Pi's MAC on the router so the IP never moves.
  (Tailscale already makes the LAN IP irrelevant once `tailscaled` is up, but a
  fixed lease keeps console-free LAN recovery simple.)
- Consider a small **UPS / supercapacitor HAT** to convert hard cuts into clean
  shutdowns — the only way to eliminate corruption rather than recover from it.
- Optionally move root to **overlayfs** (`raspi-config` → Performance → Overlay
  File System) so the SD card is read-only at runtime and power loss cannot
  corrupt it. Not enabled by default because it requires a writable data
  partition for `/srv/ar-local/data` and disables in-place `git pull` deploys.
