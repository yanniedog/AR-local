# Local Manual CDR Ingest

Real public CDR product-reference ingest for local analysis.

Agent workflow (Git/PR/bots/local verify — aligned with AustralianRates, no Cloudflare): **`WORKFLOW.md`** and **`AGENTS.md`**.

## Easiest Start

Double-click:

```text
START_HERE.cmd
```

That opens a menu:

```text
1. Run/update today's CDR data
2. Force rerun today's CDR data
3. Rebuild Excel/JSON/SQLite for latest run
4. Open dashboard
5. Install daily scheduled task
0. Exit
```

The first full run can take a while because it fetches public CDR detail JSON
from every discovered provider. Later runs resume and skip completed detail
files.

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

Install the daily scheduled task:

```powershell
.\install_daily_task.ps1 -At 03:15 -ExtraArgs "--workers 8"
```
