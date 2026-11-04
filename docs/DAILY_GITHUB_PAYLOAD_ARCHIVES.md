# Daily encrypted GitHub payload archives

The October 30 operator request requires retained daily payloads on GitHub even
when incomplete provider coverage prevents app promotion. Retention and app
selection have separate results. An archive is not proof of complete ingestion.

## Archive contract

`app_payload_archive.py` builds a current-observation snapshot containing core
rates, details and the finalized contract's coverage. It does not fetch current
logos/RBA data or mix other dates into a historical snapshot. Every source must
have a valid completion marker, ledger and export contract; the worker verifies
all bound artifacts under the existing production lease. Invalid source bytes
remain blocked. Missing historical observations are never recreated by ingest.

Archives use `app-payload-archive-YYYY-MM-DD-<bundle-sha256>`. This namespace is
separate from app date/revision tags. The manifest records `archive_only`,
`selected_for_app: false`, the original observation state and the normal
promotion gate's decision. Core, details and manifest use the existing encrypted
release transport and key. Assets are immutable, the manifest is uploaded last,
and success requires independently downloaded encrypted bytes to match every
local asset. Retries reuse the same content identity and refuse collisions.

No archive operation changes `app-payload-latest`, `dates-index.json`, legacy
date aliases, numbered selected revisions, the operational publication receipt,
publication-pending state, or Google Drive. App promotion keeps its existing
completeness and integrity checks.

## Pi-owned delivery and backfill

`pi_payload_daily_archive.py --once --since YYYY-MM-DD` finds finalized retained dates, newest
first, and archives at most one source per invocation. A separate service/timer
can retry this worker without enabling the observation-only watchdog's recovery
path. `--date YYYY-MM-DD` restricts an operator backfill to one retained date.
The configured boundary avoids duplicating older already-verified GitHub archives;
an explicit `--once` without `--since` scans all retained finalized dates.
`--dry-run` checks admission and source metadata without upload or state writes;
it is not an artifact verification or publication success.

The worker admits only from 03:30 through 22:00 Australia/Hobart, reserving the
full 30-minute child deadline plus 45-second cleanup allowance. It requires the
current natural ingest to be terminal, both ingest service process trees to be
clear, and the native lease to be absent before acquiring it. Unknown ownership
blocks work. Submit manual work through the installed shared Pi queue with the
`ar-local` resource. Do not reclaim claims manually or reset daily repair claims.

Separate durable attempts and verified receipts live in
`state/app-payload-daily-archive/`. A reservation precedes child launch; interrupted
or failed attempts retain their cooldown. Other dates can proceed while one
source waits. A zero exit without a verified archive receipt is a failure.
Normal SIGTERM termination unwinds the owned lease and reaps child processes.
A forced SIGKILL can leave a lease; admission remains blocked until independent
process/cgroup evidence permits recovery. Unknown leases are never discarded.

## Deployment and acceptance

This source change does not install or enable a timer. Use the controlled
runbook, current recovery handoff, exact-candidate review/CI and deployment
gates. Preserve the configured publisher environment file and existing secret
permissions; never print or copy its credentials. Keep the observation-only
watchdog, natural ingest timer and repair controller unchanged.

Render only the two dedicated units using `pi_payload_archive_units.py`; the
general systemd installer changes unrelated services and is not appropriate.
For the verified October 30 layout, the review-only rendering command is:

```sh
python3 pi_payload_archive_units.py --repo /srv/ar-local/AR-local \
  --data /srv/ar-local/data --portable /srv/ar-local --home /home/pi \
  --user pi --group pi --since 2026-10-29 --output /path/to/private/staging
```

Substitute a separately verified candidate checkout when using an isolated
runtime. Validate the rendered bytes with `systemd-analyze verify`, preserve
any prior unit files, and activate only these units through the authorized
deployment transaction. The renderer never reads credentials or starts units.

Record the installed source SHA, service/timer bytes, rollback copy, queue
admission, source generation and contract digest. First prove a retained-date
archive, authenticated full asset readback, unchanged app selectors and healthy
Pi dashboard. Then verify the first natural scheduled delivery independently.
Prepared code, deployed code, successful archive and natural-cycle acceptance
are distinct evidence categories.
