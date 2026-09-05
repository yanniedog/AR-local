# September 6 ordinary-user backup acceptance

Status: **operator-triggered backup verification PASS; D-015/A3 natural-scheduled-backup gate RUNNING; physical recovery boot BLOCKED and UNPROVEN**.
Authority: ARL-OPS-001 v1.5, as amended by D-015 and the operator's D-016
instruction to execute immediately instead of waiting for 06:00. No Windows
elevation, consent prompt, policy change or stored administrator credential was
used. These executions were operator-triggered; they are not natural-trigger
proof. D-016 changed the timing of the requested execution; it did not retire
D-015's natural scheduled-backup requirement. This report accepts the restored
backup data only. A3 has not reached terminal PASS, and writable A4 preparation
or boot must not begin on the strength of this report.

## Exact evidence

- Installed receiver: `3f8b8a7c4b51fef8eeb370f747f2dc51c73a1afa`.
- Protected production: `9302890fcc752cbf90da97d597e972c157d913e3`.
- Configuration SHA256: `e414c065c70e16fa2a8bcef1e3b4502f51c66cff7e747567321de26e881f3c07`.
- Acceptance report: `backup-acceptance-20260906.json`, adjacent to the installed
  source; SHA256 `91a48ab11a5fdc084455e2f6a07de61716f94935ab44e7992f749cb2e15105f0`.
- Final scheduled record: `catalog/scheduled-runs/20260905T232359Z-e2e6b5a1711c4a6389403a85ffe3ae88.json`;
  SHA256 `37b4e75bbeffad54c4fe96d448791328a23618070e49d8c83b533fb571dcd4af`.
- Task Scheduler returned `0`. The receiver completed at
  `2026-09-06T09:23:59+10:00` with `PASS` and `UP_TO_DATE` for observation,
  control, macro and retained inventory. Missing completed dates and stale
  diagnostic inventories were empty.

All evidence is in the separate `AR-local-pi5-user` target and its adjacent
immutable release. Legacy task, catalog, dispatcher and quarantine evidence
remain preserved.

## Verification and recovery of the failed attempts

111 accepted generations comprise 107 observations, two control snapshots and
two macro snapshots. The receiver restored 392,245 files and 106,134,154,555
bytes across these generations. All 116 restored SQLite databases passed
`quick_check`, `integrity_check` and `foreign_key_check`. The independent final
audit rehashed every receipt, source manifest and archive, covering
8,792,147,826 compressed archive bytes. No partial archive or receiver lock
remained. Latest observation identity is September 6; backing up its incomplete
source collection does not make it eligible for app publication.

The early failures were retained. The first-run catalog defect was repaired
without altering accepted history or the legacy target. The long backfill
then preserved every accepted generation but correctly returned `FAIL` when
its final configuration freshness check detected a changed capacity report.
An ordinary-user refresh reused accepted history, restored the current
configuration and macro snapshots, and appended a hash-bound successor `PASS`
record. The earlier failure remains the successor's explicit predecessor.

The separate implementation repair is merged in PR #622 at
`982692c69ff821c76d2a9bfcc5857ce0df7d0992`; 155 focused checks and both applicable
product CI jobs passed. The active installed source was never edited during
backup. Its existing catalog has now been initialized; a future receiver
transition must preserve validated lineage rather than rewriting receipts.

## Remaining physical recovery requirement

First, observe an actual natural trigger of the unchanged ordinary-user task,
its completed execution and current restore/freshness evidence. The September 6
06:00 attempted trigger was suppressed by IgnoreNew while the operator-requested
backfill was running; it is not a successful natural backup. Do not manufacture
that proof by relabelling a manual start or substituting a test trigger. Record
terminal A3 acceptance only after its remaining requirements are met.

The current production root is NVMe partition `nvme0n1p2`, UUID
`4cbd4874-d326-4496-bee2-7fda775a3c4c`. Read-only inspection identified the
unmounted SD card `mmcblk0`, 31,902,400,512 bytes, serial `0xfa922545`, root UUID
`ed6c7f1b-238b-41a1-b4b6-7bcdef3270fe`, PARTUUID `1a36a1cc-02`. The saved May 21
image has the same partition geometry and root UUID. This is identification,
not yet a full-device equality or boot claim. USB disk `sda` is outside this
test's writable scope.

Physical A4 must still establish a real boot from the identified recovery
media, current restored data, isolated ingest/publication, working network and
dashboard, then return to the exact protected production root and verify its
services and next 01:00 timer. No source-map freeze, PR #607 merge gate or
physical-boot requirement is retired by this backup report.
