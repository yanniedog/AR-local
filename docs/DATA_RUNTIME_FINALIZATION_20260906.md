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

## Terminal verification, September 6 at 23:53 Hobart

The D-019 data repair is complete. The Pi is clean at exact runtime
`6ee30d7aaadcd1ddd9bdda98157a6b87f71a51c2`; its six-file activation completed
at 23:22 and the daily 01:00 timer remains scheduled. The ordinary-user receiver
is installed at merged commit `835067f474e8a771f7cbf710c08d5cde835f2618`.

Fresh public downloads independently verified September 6 dated v1, rolling v1,
the dates index and v2. All nine assets match their sizes and SHA-256 values;
v2 JSON/schema and core/details base identities pass. V2 has advanced from
August 21 to September 6. `npm run verify:pi` passes against the Pi URL.

The operator-requested incremental backup completed at 23:31:53 with PASS.
Catalog generations 112, 113 and 114 preserve the revised observation, current
control state and macro store. The catalog now has 114 accepted generations.
Independent closeout rehashed these three archives, manifests and receipts,
validated catalog integrity and the scheduled-receipt digest, and checked that
all recorded SQLite restore results are `ok`. The original primary observation
and all earlier receipts remain preserved.

The existing task is Ready, Interactive/Limited, with its next run at 06:00 on
September 7. Its configuration SHA-256 remains
`14e71e6569bc4cab7d4e2c4f7c80ba0272e24a5cd3cba1455c0999bcc6e38318`.
This is operator-triggered backup proof. The next natural ingest, a genuine
scheduled backup and physical boot proof remain distinct, unproven events.
They are outside this completed D-019 repair; PR #607 remains a separate draft.

The late #629 review concerned `laptop_backup_transition.validate_backup_state`.
That unchanged legacy harness permits only `AR-local laptop backup` and the
legacy target, with one fixed production identity. It does not run the new
ordinary-user task or its separate catalog. The installed route calls
`scheduled_status`, which supplies the validated predecessor identity. Extending
the retired harness is unnecessary for this release; its rejection of a
different production identity remains intentional. All 188 focused legacy,
ordinary-user and predecessor-transition tests pass.

Evidence: [final closeout archive](https://github.com/yanniedog/AR-local/releases/download/diagnostic-quality-20260906/september6-finalization-closeout-20260906T135034Z.zip).
The archive is 7,577 bytes, SHA-256
`220ca80a96932fe74ce2c3ee953ce9ebe56826c47d73bf19c33d9fe7b98d8fee`.
Its terminal receipt SHA-256 is
`8a7b0f019c641ec33bd7fa4159c85568c19ea8ed68049994cf318b67efda9aa0`.
The local complete verification report is under
`C:\code\backups\AR-local-user-session\data-runtime-20260906\closeout-20260906T135034Z`,
SHA-256 `ccef99bffeb35f1f5d6b8ed4d20ffd88e9167e59e5ac46fafc6003ad3bdbd633`.
Earlier diagnostic evidence remains unchanged; this terminal receipt supersedes
its stale-v2 and blocked-runtime status only.

## Evidence clarification, September 7 at 00:03 Hobart

The prior archive's `20260906T135034Z` suffix names the verification directory's
start time, 23:50:34 Hobart. Its authenticated terminal receipt records creation
at `2026-09-06T13:53:35.252204+00:00`; the archive was also created at 23:53:35,
after the recorded checks. The directory name is not the terminal timestamp.
No earlier receipt, archive or handoff entry has been rewritten.

The [immutable evidence addendum](https://github.com/yanniedog/AR-local/releases/download/diagnostic-quality-20260906/september6-evidence-addendum-20260906T140341Z.zip)
contains `artifact-manifest.json`: the exact authoritative path, byte size and
SHA-256 of all nine public assets; every archive, source manifest and receipt
for backup generations 112-114; the catalog and scheduled pointer/receipt; and
the before/after task XML, installation receipt and receiver configuration.
The backup entries include their kind and catalog sequence. Public assets also
include their download URLs. This explicitly binds the closeout claims to a
reproducible inventory; it does not expose backup contents or credentials.

The addendum was recorded at `2026-09-06T14:03:41.616908+00:00`, is 9,391 bytes,
and has SHA-256
`2a93b8a51aee01ed67b600560d2a9d6fa697a44cd81578f0ac1ac674a618a7d5`.
The contained artifact manifest is 10,215 bytes, SHA-256
`20fd3d8358b44d52fbecc5e400bc144929a481f63f325d3a10ebce48385243d9`.
Its local root is
`C:\code\backups\AR-local-user-session\data-runtime-20260906\evidence-addendum-20260906T140341Z`.
It also retains the executed one-shot receiver updater and installation receipt.

Four later #628 findings concern mixed predecessor identities, old-runtime
orphan recovery, predecessor validation during a future installation probe and
a reusable checked-in updater. They are deferred in [issue #631](https://github.com/yanniedog/AR-local/issues/631)
before another receiver transition. The completed installation independently
checked its predecessor digest and both identities; its live pointer now names
the successful current-runtime receipt. No old-runtime orphan recovery was
needed. This is evidence for the completed D-019 execution, not a claim that
every future receiver-transition edge case is fixed.
