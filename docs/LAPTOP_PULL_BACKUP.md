# Laptop pull-backup operator notes

Read [`PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md`](PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md)
completely before using these commands. Decision D-004 and the Phase A gates
control this procedure.

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
  --plan-git-commit 281c99d290361e779c8b6ed4fc7ccb3f67fa2672

npm run laptop:backup:latest -- `
  --target C:\code\backups\AR-local-pi5 `
  --recovery-image C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21 `
  --candidate-code-sha <candidate-sha> `
  --protected-code-sha 9302890fcc752cbf90da97d597e972c157d913e3 `
  --plan-git-commit 281c99d290361e779c8b6ed4fc7ccb3f67fa2672
```

`backup-latest` first preserves and independently restores the latest completed
observation, then captures control state, online-backed-up macro SQLite, both
Git repositories, systemd definitions, package inventory, and secret metadata
without secret bytes. It is successful only after source-manifest identity,
archive readability, complete extracted SHA-256 comparison, SQLite
`PRAGMA quick_check`, daily export reconciliation, completion/contract/ledger
binding, Git-bundle validation, and the free-space floor all pass.

After that current-generation pass is accepted, backfill every completed
observation after the historical image date:

```powershell
npm run laptop:backup:backfill -- `
  --target C:\code\backups\AR-local-pi5 `
  --recovery-image C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21 `
  --after-date 2026-05-21 `
  --candidate-code-sha <candidate-sha> `
  --protected-code-sha 9302890fcc752cbf90da97d597e972c157d913e3 `
  --plan-git-commit 281c99d290361e779c8b6ed4fc7ccb3f67fa2672
```

Backfill is incremental. A completed content-addressed observation is rehashed
and skipped rather than retransferred. Each new archive is streamed to a unique
`.partial`, read back into a unique restore-drill directory, verified, and only
then promoted. A receipt is created last; the hash-linked catalog and latest
pointer advance only after the receipt exists. Failure evidence is immutable,
and only the exact partial created by the failed invocation may be removed.

## Stop conditions

Stop without retrying ingest if any of these occur:

- local time is in the 00:30–03:30 Australia/Hobart quiet window;
- the Pi checkout is dirty or differs from the protected SHA;
- the ingest lock exists, the daily service is active, or the timer/dashboard
  preflight is unhealthy;
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
