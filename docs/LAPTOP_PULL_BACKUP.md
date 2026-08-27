# Laptop pull-backup operator notes

Read [`PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md`](PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md)
completely before using these commands. Decisions D-004 and D-005 and the
Phase A gates control this procedure.

The Windows laptop is the receiver. It pulls over SSH, writes only below an
explicit target, and refuses any operation that would leave less than
`53,687,091,200` bytes (50 GiB) free. The Pi receives no laptop credential,
mount, service, timer, or production-checkout change. A reviewed helper is
copied to a content-named `/tmp` path for the duration of one invocation and is
removed afterward.

The exact-size May image remains at its existing path as a historical recovery
candidate. Do not alter it, call it current, or use the known-short failed image
as a restore source. Current data is stored as independently verifiable,
compressed generations below `C:\code\backups\AR-local-pi5`.

## Manual daylight sequence

Use a clean detached checkout of the exact merged `origin/main`. Substitute the
actual merged receiver commit for `<candidate-sha>`; do not use a topic-branch
SHA. Production remains pinned to the protected SHA shown here until the wider
runbook authorizes a deployment.

```powershell
npm run laptop:backup:preflight -- `
  --target C:\code\backups\AR-local-pi5 `
  --recovery-image C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21 `
  --candidate-code-sha <candidate-sha> `
  --protected-code-sha 9302890fcc752cbf90da97d597e972c157d913e3 `
  --plan-git-commit 8efefe10890a295ef87f97b46d3cb981193cfddc

npm run laptop:backup:latest -- `
  --target C:\code\backups\AR-local-pi5 `
  --recovery-image C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21 `
  --candidate-code-sha <candidate-sha> `
  --protected-code-sha 9302890fcc752cbf90da97d597e972c157d913e3 `
  --plan-git-commit 8efefe10890a295ef87f97b46d3cb981193cfddc
```

`backup-latest` first preserves and independently restores the latest completed
observation, preserves every retained terminal/unfinished run as non-publishable
diagnostic evidence, then captures current control state, `runs-archive`,
predeploy evidence, both Git repositories, systemd definitions, package
inventory, and secret metadata without secret bytes. `runs-archive` and
predeploy files stream directly from their immutable namespaces with post-stream
change detection; they are never duplicated into Pi tmpfs. A separate macro
generation is created with SQLite's online backup API. Observation, diagnostic,
control, and macro components have separate receipts and freshness pointers; an
already verified observation never suppresses a new control or macro check. It
is successful only after source-manifest identity,
archive readability, exact tar type/mode/mtime/UID/GID verification, complete
extracted SHA-256 comparison, SQLite
`PRAGMA quick_check`, daily export reconciliation, completion/contract/ledger
binding, Git-bundle validation, and the free-space floor all pass.

After that current-generation pass is accepted, backfill every completed
observation after the historical image date. Diagnostic runs are included even
when they predate `--after-date`, because failure evidence is not treated as a
publishable observation and must not disappear through date filtering:

```powershell
npm run laptop:backup:backfill -- `
  --target C:\code\backups\AR-local-pi5 `
  --recovery-image C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21 `
  --after-date 2026-05-21 `
  --candidate-code-sha <candidate-sha> `
  --protected-code-sha 9302890fcc752cbf90da97d597e972c157d913e3 `
  --plan-git-commit 8efefe10890a295ef87f97b46d3cb981193cfddc
```

Backfill is incremental. A completed content-addressed observation is rehashed
and skipped rather than retransferred. Each new archive is streamed to a unique
`.partial`, read back into a unique restore-drill directory, verified, and only
then promoted. On Windows, promotion uses an atomic write-through move; on
POSIX it uses an atomic rename plus directory fsync. The order is archive,
manifest, receipt, hash-linked catalog, then latest pointer. Each completed file
is flushed before its metadata is promoted. Failure evidence is immutable, and
only the exact partial created by the failed invocation may be removed.

## Stop conditions

Stop without retrying ingest if any of these occur:

- local time is in the 00:30–03:30 Australia/Hobart quiet window;
- the Pi checkout is dirty or differs from the protected SHA;
- the ingest lock exists, the daily service is active, or a failed service lacks
  append-only hash-verified terminal-failure evidence bound to the protected
  production SHA; or the timer/dashboard preflight is unhealthy;
- the laptop target is non-canonical, symlinked, already locked, or lacks the
  worst-case source-plus-restore capacity above the 50 GiB floor;
- a source path is unsafe on Windows, collides by case, is a symlink/special
  file/hard link, or changes while being hashed or streamed;
- a manifest, archive, extracted hash, SQLite check, export reconciliation,
  marker/contract/ledger binding, Git bundle, secret-exclusion record, receipt,
  or catalog chain fails.

Do not use `--force`, delete a prior generation, edit a receipt, or advance the
catalog conversationally. Preserve the failure record and record any revised
decision through runbook change control.

## Scheduling gate

Do not schedule the receiver until one manual `backup-latest`, one backfill, and
their restore evidence pass. The eventual laptop task runs at 05:00
Australia/Hobart and at startup when stale, never in the quiet window. Laptop
backup is physically separate but not geographically separate; the A4 boot test
and later independent-site copy remain mandatory.

After those gates pass, use an Administrator PowerShell owned by the laptop
operator to install the task from a durable clean checkout of the exact
candidate. The installer first performs a read-only freshness check and refuses
registration unless the Pi's current completion generation is already bound to
a locally verified archive and hash-linked catalog entry. Registration or
read-back failure is terminal and must never be accepted from a printed summary:

```powershell
.\install_laptop_backup_task.ps1 `
  -Target C:\code\backups\AR-local-pi5 `
  -RecoveryImage C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21 `
  -CandidateCodeSha <candidate-sha> `
  -ProtectedCodeSha 9302890fcc752cbf90da97d597e972c157d913e3 `
  -PlanGitCommit 8efefe10890a295ef87f97b46d3cb981193cfddc
```

The task runs with the laptop operator identity, at 05:00 local time and five
minutes after startup. A no-data-write result requires independently current
observation, control, macro, diagnostic, and historical-coverage gates from the
exact scheduled receiver. A missing historical date selects `backfill`; other
staleness selects `backup-latest`. Every invocation writes an immutable status
record and updates `catalog/latest-scheduled.json`; failures retry three times
at 30-minute intervals and send a best-effort Windows operator message. Receiver
locking, quiet-window, Pi health, restore verification, and the 50 GiB floor
remain mandatory. `MultipleInstances=IgnoreNew` prevents overlap.
