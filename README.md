# Local Manual CDR Ingest

Real public CDR product-reference ingest for local analysis.

Agent workflow (Git/PR/bots/local verify - aligned with AustralianRates, no Cloudflare): **`WORKFLOW.md`** and **`AGENTS.md`**.

Before squash merge: `npm run pr:bot-feedback-check -- --pr <n>` (exit 0 required). CI required checks: **`bot-presence-gate`**, **`bot-feedback-gate`**. Apply branch protection: `npm run branch-protection:apply` (see **`WORKFLOW.md`** → Branch protection).

Future agents should also start with **`docs/UNIVERSAL_ROADMAP.md`**. It
captures the Pi/LAN/SSD portability model, the banks-first scope, and the
AustralianRates dashboard parity contract.

## Easiest Start

Double-click:

```text
START_HERE.cmd
```

Or from a terminal (Windows, Linux, Raspberry Pi):

```powershell
python .\start_here.py
```

The launcher detects the host (Windows PC vs Raspberry Pi vs other Linux) and
shows a short header. Menu:

```text
1. Run/update today's CDR data
2. Force rerun today's CDR data
3. Rebuild Excel/JSON/SQLite for latest run
4. Open dashboard
5. Install or adjust daily schedule (20:00 UTC)
6. Check GitHub / git: update available and pull
7. Show database summary
8. Boot ingest service (systemd user): enable / disable / status  [Linux/Pi when systemd is available]
0. Exit
```

Schedule option 5: on Windows it registers a Task Scheduler job with a **UTC
calendar trigger** at **20:00 UTC** (DST-stable via XML). On Linux/Pi it installs a **user**
crontab block with `CRON_TZ=UTC` and `20:00` daily, running `cdr_daily.py`
with the shared worker count from `ar_local_launcher_constants.py`.

`START_HERE.cmd` only falls back to `py -3` when `python` is missing (**errorlevel
9009**), not when `start_here.py` exits with an error.

Boot option 8: installs a **systemd user** oneshot unit that runs `cdr_daily.py`
on boot. Ingest is skipped for the current local day if `.daily-state/<date>.done.json`
already exists (same rule as a normal daily run). User units run at boot only if
lingering is enabled for your account, e.g. `loginctl enable-linger $USER` on
the Pi.

Non-interactive shortcuts (same as before):

```powershell
.\START_HERE.ps1 -Action daily
python .\start_here.py --action dashboard
```

The first full run can take a while because it fetches public CDR detail JSON
from every discovered provider. Later runs resume and skip completed detail
files.

Database summary (menu 7) uses `runs/<latest>/_exports/local-cdr.sqlite` by
default; override with env `AR_LOCAL_DB` if needed. `PRAGMA quick_check` is **skipped**
by default (large DBs); set `AR_LOCAL_DB_QUICK_CHECK=1` or `DB_QUICK_CHECK=1` to run it.

## Raspberry Pi 5 deployment

The Pi runtime is designed to keep high-churn ingest/build writes off the
microSD card. On Raspberry Pi, `cdr_daily.py` automatically stages raw ingest
and export building under `/dev/shm/ar-local-<uid>`, then copies only the
completed `_exports` tree into the configured data root. Completed generated
artifacts are not pruned.

The Pi deployment is self-contained under one portable root:

- portable root: `/srv/ar-local`
- app repo: `/srv/ar-local/AR-local`
- AustralianRates shell assets repo: `/srv/ar-local/australianrates`
- durable data: `/srv/ar-local/data`
- durable runs and SQLite exports: `/srv/ar-local/data/runs/<date>/_exports`
- daily state: `/srv/ar-local/data/state`

`/srv/ar-local` can be a normal microSD directory during initial setup, then
later be replaced by a USB SSD or Pi 5 SSD HAT mount. The service paths stay the
same, so copying the whole `/srv/ar-local` tree to the SSD and mounting the SSD
at `/srv/ar-local` keeps the app, site assets, runs, state, and database files
together without reconfiguration.

The app reads `AR_LOCAL_PORTABLE_ROOT` and `AR_LOCAL_DATA_ROOT`. If
`AR_LOCAL_DATA_ROOT` is not set on Raspberry Pi, durable data defaults to
`/srv/ar-local/data`.

Install system packages and systemd units from any bootstrap checkout:

```sh
cd /home/pi/AR-local
sh deploy/pi/install-pi-systemd.sh /srv/ar-local
```

The installer clones or updates the runtime repos inside `/srv/ar-local`; the
bootstrap checkout is not used by the installed services.

To use a different portable root or explicit repo/data paths:

```sh
sh deploy/pi/install-pi-systemd.sh /mnt/ar-local-ssd
sh deploy/pi/install-pi-systemd.sh /mnt/ar-local-ssd /mnt/ar-local-ssd/AR-local /mnt/ar-local-ssd/australianrates /mnt/ar-local-ssd/data
```

The installer renders the systemd units for the current Linux user, repo path,
adjacent AustralianRates checkout, portable root, and data root before
installing them under `/etc/systemd/system`. It also installs and enables
Avahi with mDNS host name `ar`, so the dashboard is available as
`http://ar.local:8808/` on LANs that pass mDNS. Keep the Pi IP stable with a
router DHCP reservation or equivalent static-IP setup.

The Pi daily timer (`deploy/pi/ar-local-daily.timer`) runs banking ingest at
**20:00 UTC** each day via `pi_daily_sync.py --banks-only`. The service exits
non-zero when the banking export has zero rates, so systemd records a failed
unit instead of treating an empty export as success.

`deploy/pi/ar-local-daily-watchdog.timer` runs every 15 minutes and checks
whether the most recent scheduled daily ingest has produced a valid banking
export. If the 20:00 UTC run is missing after a 30-minute grace period and the
daily service is not already active, it runs the same `pi_daily_sync.py
--banks-only` path directly as the Pi app user.

When sudo is not available for installing root units, install the catch-up
watchdog as the lingering Pi user with:

```sh
sh deploy/pi/install-user-daily-watchdog.sh /srv/ar-local/AR-local
```

```sh
python3 pi_daily_sync.py --banks-only
```

Use `python3 pi_daily_sync.py --banks-only --force` for a one-off same-day
banking rerun after the daily marker exists. A marker is ignored when it records
zero rates or the on-disk `latest.json` manifest is empty. Remove `--banks-only`
from `deploy/pi/ar-local-daily.service` before reinstalling the unit if you want
daily banking and energy again.

`--exports latest` skips run folders whose dashboard manifest has
`banks_counts.rates == 0`, so a same-day empty export cannot hide an older valid
run.

SSD migration later:

```sh
sudo systemctl stop ar-local-dashboard.service ar-local-daily.timer
sudo rsync -aHAX --numeric-ids /srv/ar-local/ /mnt/new-ssd/
sudo mount /dev/disk/by-uuid/<ssd-uuid> /srv/ar-local
sudo systemctl start ar-local-daily.timer
sudo systemctl start ar-local-dashboard.service
```

Add the SSD mount to `/etc/fstab` after confirming the UUID and filesystem.
Because the deployed unit paths point at `/srv/ar-local`, no service rewrite is
needed when the SSD replaces the microSD directory.

After the first real ingest succeeds, the dashboard can run continuously on the
LAN:

```sh
sudo systemctl start ar-local-dashboard.service
npm run verify:local -- --base-url=http://127.0.0.1:8808/
curl -fsS http://<pi-ip>:8808/api/latest
curl -fsS http://ar.local:8808/api/latest
```

The dashboard service serves the newest completed export with:

```sh
python3 cdr_dashboard_server.py --exports latest --runs /srv/ar-local/data/runs --host 0.0.0.0 --port 8808 --site-root /srv/ar-local/australianrates/site --preload
```

## One-Click Shortcuts

Double-click these when you know what you want:

```text
run_daily.cmd       fetch CDR data, then build exports
open_dashboard.cmd  open the latest local dashboard
rebuild_exports.cmd rebuild exports from the latest run without fetching
```

The dashboard opens in your browser with the same public AustralianRates shell:
dark/light mode, Mortgage, Savings, Term Deposits, and Energy tabs; clear
banking section cards; selected-section lender logos; the familiar hero metrics;
the chart workspace; export links; and the same compact drill-down hierarchy
tree used by the AustralianRates report ribbon. If the usual port is busy, the
launcher automatically uses the next free localhost port.

## Outputs

Outputs are written to:

```text
runs\<date>\_exports\
```

Files:

- `banks-<date>.json`
- `energy-<date>.json`
- `banks-<date>.xlsx`
- `energy-<date>.xlsx`
- `local-cdr.sqlite`
- `dashboard-cache\`

Generated JSON strips CDR links, URI/URL fields, and URLs embedded in text while
retaining rates, fees, constraints, eligibility, features, contract sections, and
cleaned full detail JSON.

## Command Line

From this folder:

```powershell
python .\cdr_daily.py --workers 8
python .\cdr_daily.py --force --workers 8
python .\cdr_outputs.py .\runs\2026-05-06
python .\cdr_dashboard_server.py --exports .\runs\2026-05-06\_exports
```

Install the daily scheduled task (local clock time; for 20:00 UTC on Windows,
prefer menu option 5 in `start_here.py`). The script uses `python` when on PATH,
otherwise the Windows `py -3` launcher (same as `start_here.py`).

```powershell
.\install_daily_task.ps1 -At "20:00" -ExtraArgs "--workers 8"
```
