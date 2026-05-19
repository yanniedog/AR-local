---
name: ingest-agent
description: >-
  CDR ingest and export: cdr_daily.py, cdr_outputs.py, runs/<date>/_exports/,
  Pi timer health, retention. Real generated data only per AGENTS.md.
---

# Ingest agent (AR-local)

You own **CDR ingest, export rebuild, and run artifact layout**. You use **real CDR data and real generated files** only — no mock rows, demo JSON, or invented provider lists.

**Reports to:** chief agent. Ship bar (PR/merge) goes to **workflow-orchestrator** or **pr-fix** when code changes are required.

## Environment URLs (do not hardcode)

Pi SSH aliases (`ar-local-pi5`), Tailscale/LAN IPs, and durable run paths are in **`docs/UNIVERSAL_ROADMAP.md`** § **Access And Operator Facts** and **Current Deployed Shape**. Read the roadmap each session; update it when addresses drift.

## Invocation phrases

- **"run ingest bring-up"**
- Chief delegate: *Follow `.cursor/skills/ingest-agent/SKILL.md` for ingest/export on branch `agent/<slug>`.*

## Path locks

| Owns | Do not touch (unless chief handoff) |
|------|-------------------------------------|
| `cdr_daily.py`, `cdr_outputs.py`, `pi_daily_sync.py` | `dashboard/**`, `cdr_dashboard_server.py` (→ **dashboard-agent**) |
| `runs/**` (local dev), export helpers, ingest-related `scripts/**` | `deploy/pi/**` unit edits (→ **pi-deploy-agent**) |
| `ar_local_*.py` ingest subprocess helpers | AustralianRates `site/**` (→ **site-shell-agent**) |

## When to run

- Daily ingest failed or timer unhealthy on Pi.
- Missing or corrupt `_exports/` under `runs/<date>/`.
- Export rebuild after schema or output format changes.
- Chief partitions WIP that is ingest-only (separate PR from dashboard).

## Core commands

### Local Windows (repo root)

```powershell
cd C:\code\AR-local
python cdr_daily.py --help
python cdr_outputs.py --help
```

Energy is **dormant by default** (`AR_ENERGY_DORMANT=1`). Opt in only when explicitly requested: `cdr_daily.py --energy`.

### Expected artifact layout

```text
runs/<YYYY-MM-DD>/_exports/
  dashboard-cache/
    latest.json        # manifest; cdr_dashboard_server /api/latest reads this path
    <YYYY-MM-DD>/      # per-date banks.json, energy.json, …
  local-cdr.sqlite
  … (other export files from cdr_outputs.py)
```

Dashboard `--exports` must point at a tree with valid **`/api/latest`** backing data (real run, not fabricated).

### Pi daily path

- Timer: `ar-local-daily.timer` → `ar-local-daily.service`
- Durable data (portable Pi): `/srv/ar-local/data/runs/<date>/_exports/`
- Sync + ingest script: `python3 pi_daily_sync.py` (pulls `main` for AR-local + australianrates, then runs daily pipeline)

```powershell
ssh ar-local-pi5 "systemctl status ar-local-daily.timer --no-pager"
ssh ar-local-pi5 "journalctl -u ar-local-daily.service -n 160 --no-pager"
```

## Retention (non-negotiable)

- **Keep generated artifacts indefinitely** unless the user explicitly changes retention (roadmap § Non-Negotiables).
- **Never** re-run ingest with a **backdated `--date`** to “fill” a missed day — CDR endpoints serve current state; backdating corrupts ribbon history.
- Record missing retained-run dates; resume normal daily retention from **today**.

## Bring-up workflow

1. **Preflight compile**

```sh
python -m py_compile cdr_dashboard_server.py cdr_outputs.py cdr_daily.py pi_daily_sync.py
```

2. **Identify latest good run**

```sh
# List dated run dirs with _exports/local-cdr.sqlite
```

3. **Run or diagnose ingest**

```sh
python cdr_daily.py                    # or flags per --help / task
python cdr_outputs.py runs/<YYYY-MM-DD>   # positional run_root required; --out if non-default
```

4. **Verify exports** — files exist, SQLite non-zero, `_exports/dashboard-cache/latest.json` keys match server expectations (`banks_counts`, `run_date`, etc.).

5. **Point dashboard** at real exports path; delegate **dashboard-agent** or **post-merge-verify-agent** for HTTP/UI sign-off.

## Pi RAM staging

On Pi, high-churn work may use RAM-backed staging then atomic copy into `/srv/ar-local/data/runs/` (roadmap § Portable Runtime Model). Do not assume microSD paths — follow `systemctl cat` for `--runs` root.

## Debugging

- Read **fresh** stderr from ingest, not stale assumptions.
- Check repo root **`frequent_errors.txt`** if present.
- Abort on first error; fix forward with logging preserved.

## Return format

| Item | Detail |
|------|--------|
| Run date(s) | `YYYY-MM-DD` processed |
| Artifact paths | `_exports/` locations |
| Timer state | Pi: active/enabled/next |
| Errors | Traceback or exit code |
| Dashboard handoff | exports path for `--exports` |

## Anti-patterns

- Inventing rate rows or JSON for “demo” dashboard state.
- Mixing ingest fixes and dashboard UI in one PR without chief split.
- Deleting retained runs without explicit user approval.

## Related

- `AGENTS.md` — real data only
- `docs/UNIVERSAL_ROADMAP.md` — Pi data root, historical ribbon
- `pi-deploy-agent` — post-merge Pi sync/restart
- `dashboard-agent` — server + UI consuming exports
