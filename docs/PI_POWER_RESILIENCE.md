# Pi power-loss resilience & recovery

The AR-local CDR ingest + dashboard run on a single Raspberry Pi 5
(`ar-local-pi5`, root on NVMe, Wi-Fi only — `eth0` normally unplugged). It is
**headless** and reached over Wi-Fi + Tailscale.

**Actual root cause of the 2026-06-27 outage:** after a power cut the Pi booted
fine but **Wi-Fi never auto-reconnected**, so the headless box was invisible on
both the LAN and Tailscale and the daily CDR run was missed. The cause was
**NetworkManager's default `autoconnect-retries` (4)**: it gave up permanently
when the access point was slow to return after the shared power outage. The
default systemd target was also `graphical.target` (wrong for a headless
server). It was **not** SD/disk corruption — the NVMe rootfs recovered its
journal cleanly.

> Note: the Pi's Broadcom Wi-Fi is a **self-managed** regulatory driver
> (`iw reg get` shows `country 99: DFS-UNSET`), so the regulatory domain is
> taken from the AP, not from `iw reg set` / the `cfg80211.ieee80211_regdom`
> kernel arg. `Nikipedia` runs on 5 GHz ch36 (legal in US and AU), so regdom
> was not the blocker. `do_wifi_country AU` is still set (correct for the
> location) but is effectively cosmetic on this driver.

This doc covers (1) how to find and recover the Pi after a power event, and
(2) the hardening that now makes it self-heal and stay reachable on the next
boot.

---

## 1. Recovery runbook (Pi unreachable after a power cycle)

### Step 1 — find the Pi on the LAN
DHCP often hands the Pi a **new IP** after a reboot, which makes the old
Tailscale/LAN address look dead. Find it by MAC:

```bash
# From a Linux machine on the same LAN (e.g. 10.0.0.0/24). On Windows use
# `ping -n 1 -w 250` instead of `ping -c 1 -W 1`.
for i in $(seq 1 254); do ping -c 1 -W 1 10.0.0.$i >/dev/null 2>&1 & done; wait
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
- Root mounted `ro` → `sudo fsck -y "$(findmnt -no SOURCE /)"` from a clean
  state — this Pi's root is **NVMe** (`/dev/nvme0n1p2`), not the SD card (or
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
| **Tailscale auto-start + tailnet SSH** | `enable --now tailscaled`, `tailscale set --ssh` | Remote access returns automatically after a reboot; tailnet SSH is a key-independent recovery path. |
| **Wi-Fi autoconnect forever** | NM `autoconnect-retries=0`, `priority=100`, `powersave=2` | **The actual fix:** re-joins the AP indefinitely even if the router is slow to return after an outage; no power-save dropouts. |
| **Wi-Fi country (best-effort)** | `raspi-config do_wifi_country AU` | Sets AU for the location; cosmetic on this self-managed driver (regdom comes from the AP). |
| **Headless boot** | `systemctl set-default multi-user.target` | Boots without waiting on a display/keyboard. |
| **Ethernet auto + preferred** | NM wired `autoconnect`, `priority=200`, DHCP | Plugging in a cable "just works" and is preferred over Wi-Fi while connected; unplug falls back to Wi-Fi. |
| **Network self-heal** | `ar-local-net-watchdog.timer` (every 3 min) | If the default gateway is unreachable, restarts NetworkManager + re-ups Wi-Fi (kicks a wedged driver). |

> Wi-Fi credentials are **never** stored in this repo — the script only hardens
> the autoconnect settings of existing NetworkManager profiles. Configured
> networks (highest priority first): **`Nikipedia`** (100) → **`ASUS_2.4`** (50)
> → **`Slow`** (10). NetworkManager prefers the highest-priority visible network
> and `ar-local-net-watchdog.sh` fails over through them in that order. Add or
> replace a network with:
> `sudo nmcli connection add type wifi con-name <SSID> ssid <SSID>` then
> `sudo nmcli connection modify <SSID> wifi-sec.key-mgmt wpa-psk wifi-sec.psk <PSK> connection.autoconnect yes connection.autoconnect-priority <N>`.

Service-level resilience (in the unit files, applied by `install-pi-systemd.sh`):

- **`ar-local-dashboard.service`**: `Restart=always` (was `on-failure`) so the
  backend on :8808 / nginx upstream never stays dead after an unexpected exit.
- **`ar-local-boot-recovery.service`** (oneshot, every boot):
  1. starts the dashboard if it isn't active,
  2. runs `pi_daily_watchdog.py` to catch up a daily ingest missed while powered off,
  3. emails a "Pi rebooted" alert (`pi_ingest_alert.py --reason boot-recovery`).
- Existing `ar-local-daily-watchdog.timer` (`Persistent=true`, `OnBootSec=10min`)
  remains the backstop for any still-missing run.

## Manual CDR ingest

To fetch fresh CDR data on demand (forced run → publish to GitHub → refresh the
dashboard → verify), SSH to the Pi and run:

```bash
cdr-ingest
```

It follows the live log and reports success/failure; press Ctrl-C to stop
watching (the ingest keeps running). Backed by `ar-local-ingest-now.service`.

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
