# Local Manual CDR Ingest

Real public CDR product-reference ingest for local analysis.

Agent workflow (Git/PR/bots/local verify — aligned with AustralianRates, no Cloudflare): **`WORKFLOW.md`** and **`AGENTS.md`**.

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

Schedule option 5: on Windows it registers a Task Scheduler job at the **local**
time that matches **20:00 UTC** each day. On Linux/Pi it installs a **user**
crontab block with `CRON_TZ=UTC` and `20:00` daily, running `cdr_daily.py
--workers 8` from this repo.

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
default; override with env `AR_LOCAL_DB` if needed.

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
prefer menu option 5 in `start_here.py`):

```powershell
.\install_daily_task.ps1 -At "20:00" -ExtraArgs "--workers 8"
```
