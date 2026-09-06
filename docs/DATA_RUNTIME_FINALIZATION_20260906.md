# September 6 data runtime finalization

## Operator decision D-019

The operator instructed: "Finalise everything! I'm sick of this pi backup shit".
This authorizes completion of the current data-reliability repair and its bounded
runtime activation. It does not authorize erasing history or claiming that a
manual backup is a natural execution or physical boot proof.

For this limited release, D-019 supersedes the blanket A3/A4 and moving-main
prerequisites in the old recovery handoff and Pi deployment skill. The referenced
`pi-deploy-canary` workflow and `pi-production` environment do not exist. The
replacement acceptance requirements are an exact reviewed file set, isolated
runtime tests, an independently restored current off-device snapshot, a clean
known production baseline, the existing ingest lock, rollback proof and live
publication/runtime checks. No environment protection is removed or bypassed.

This is a one-release exception. It does not promote PR #607 or authorize the
large unrelated main-to-production diff. Existing backup archives, scheduled
tasks, historical evidence and original observations remain preserved. A3's
natural-trigger and A4's physical-boot results remain unproven facts; neither
is relabelled PASS or used as a prerequisite for these six reviewed runtime files.

## Exact release and rollback

- Source fixes: merged PRs #626 and #627, source commit
  `5518f0af63447209a10ddc2d9c8f6cd423f81395`.
- Production baseline and rollback:
  `9302890fcc752cbf90da97d597e972c157d913e3`.
- Exact runtime commit: `6ee30d7aaadcd1ddd9bdda98157a6b87f71a51c2`.
- Immutable release tag: `runtime-data-quality-20260906`.
- Runtime files: `cdr_ingest_support.py`, `pi_daily_watchdog.py`,
  `pi_payload_freshness.py`, `app_payload_publish.py`, `app_payload_v2.py`,
  `scripts/pi_ingest_manifest_check.py`.
- Three accompanying regression-test files are copied from the same reviewed
  source. Every other runtime file is byte-identical to the protected baseline.
- Exact backport suite: 876 passed, 10 optional-dependency skips, on Windows.
  Linux checks run in an isolated Pi checkout and isolated test environment.

The release is a detached, reproducible backport of already merged code, not a
moving branch deployment. It changes no schema, observation, publication threshold,
data path, service definition, timer schedule, credential or unrelated workload.

Before activation, preserve September 6 primary/revision observations and current
state. The off-device archive must match its Pi SHA-256 and restore successfully;
each restored SQLite must pass quick, full-integrity and foreign-key checks.
Preserve the original production commit and all changed-file preimages.

Activation requires the clean exact baseline, inactive ingest/manual-ingest and
watchdog services, healthy dashboard, adequate space/memory, and no existing
ingest lock. Hold `DailyIngestLock` during checkout. Pause only the daily watchdog
timer briefly, restore its prior enabled/active state, and leave the 01:00 daily
timer untouched. Verify exact HEAD and file hashes, imports, public manifest/index
checks and the dashboard. A failed acceptance check restores the exact baseline;
all observation and receipt history remains untouched. Do not begin activation
after 23:30 Hobart; all runtime work must finish before the 00:30 ingest freeze.

V2 repair retries only the already-built September 6 sidecar after matching its
base hashes against fresh public v1. Preserve the prior v2 manifest and assets,
then independently verify new public hashes, sizes, base identity and JSON/schema.
No source recapture or v1 date/threshold manipulation is involved.

## Backup continuity across a code deployment

The ordinary-user receiver previously required every historical receipt and its
predecessor to carry the current production commit. A valid deployment therefore
stranded the scheduled backup despite the archived data being unchanged.

The receiver now accepts an optional `previous_runtime` in its hash-pinned
ordinary-user configuration. It binds exactly the prior production SHA, receiver
SHA and scheduled-receipt SHA-256. The current source must still match the new
production SHA. Old history remains accepted only for that explicitly named prior
runtime, and the first new scheduled receipt must link to the exact pinned
predecessor. Later receipts use the new identity. A bare CLI switch provides no
authority: the existing ordinary-token, config-hash, executable, clean-receiver,
transport, target, operator, mutex, restore and lineage checks still apply.

Install the new receiver in a separate immutable local release. Update only the
existing ordinary-user task's action after a successful no-write probe; preserve
its principal, triggers and settings. Keep the old action/config for rollback.
The legacy administrator-owned task and backup target are outside this change.

Evidence is append-only under
`/srv/ar-local/canary/evidence/ARL-OPS-001/FINALIZE-20260906` and the corresponding
local off-device backup/evidence directory. Terminal results distinguish the
deployed data repair, v2 publication, verified backup and next natural execution.
