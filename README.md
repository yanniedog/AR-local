# AR-local

AR-local captures Australian Consumer Data Right banking products, reconciles
every selected product, stores one immutable SQLite v9 observation, and
publishes a deterministic mobile payload.

## Data path

```text
CDR register + product details
  -> immutable raw-attempt journal
  -> ProductAccountingV1 reconciliation
  -> ObservationV1 + SQLite v9
  -> deterministic v1 mobile payload
```

Publication fails closed when source identity, accounting, canonical JSON, or
SQLite verification disagrees. Product-scoped upstream failures may produce a
fully disclosed `degraded` observation; control-plane failures produce no
observation.

## Run

```powershell
python cdr_daily.py --runs runs --state state
python cdr_outputs.py runs\YYYY-MM-DD
python cdr_outputs.py runs\YYYY-MM-DD --xlsx
python app_payload_build.py --help
```

`START_HERE.cmd` provides a small interactive wrapper. Scheduled Pi operation
uses `pi_daily_sync.py` and the units under `deploy/pi/`.

## Canonical output

Each completed `runs/YYYY-MM-DD/_exports/` contains:

- `observation-v1.json` — canonical public observation
- `product-accounting-v1.json` — every selected product and disposition
- `local-cdr.sqlite` — immutable, sidecar-free SQLite v9 projection
- optional XLSX exports created only with `--xlsx`

Historical dashboard-cache files are read only for old observation recovery.
Current ingest and payload publication never create or select them.

## Status API

The Pi exposes only verified observation metadata:

```powershell
python cdr_status_server.py --runs runs --host 127.0.0.1 --port 8808
python verify_local.py --base-url http://127.0.0.1:8808/
npm run verify:pi
```

Routes: `/healthz`, `/status`, and `/api/status`. The former dashboard and
`/api/latest` are removed. On the Pi, `ar-local-status.service` binds loopback;
nginx provides port 80.

## Verify

```powershell
python -m pytest -q
python -m compileall -q .
npm run pi:deploy:dry-run -- --expected-commit <origin-main-sha>
```

Pi acceptance is `http://100.78.28.10/`, not a local mock. Never deploy over a
dirty Pi checkout. Deployment remains gated by a fresh verified backup,
restore drill, exact commit, service checks, and rollback evidence.

The first deployment from the retired dashboard runtime also needs one explicit
canonical ingest:

```powershell
npm run pi:deploy -- --expected-commit <origin-main-sha> --bootstrap-observation
```

`/healthz` is process liveness. `/api/status` is the fail-closed data-readiness
contract and is required for deployment acceptance.

Backup operating controls are documented in
`docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md` and
`docs/LAPTOP_PULL_BACKUP.md`.
