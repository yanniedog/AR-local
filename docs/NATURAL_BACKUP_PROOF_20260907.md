# September 7 natural backup verification

The unchanged ordinary-user task started at 06:00:01 Hobart and completed at
06:08:07 with exit zero. This satisfies the natural scheduled-backup requirement
for the recorded receiver/runtime pair. It does not establish a physical boot,
authorize a moving-main deployment, or make this snapshot current after another
runtime or source-data change.

## Scheduler and identity evidence

- Receiver: `835067f474e8a771f7cbf710c08d5cde835f2618`.
- Protected runtime: `6ee30d7aaadcd1ddd9bdda98157a6b87f71a51c2`.
- Configuration SHA256: `14e71e6569bc4cab7d4e2c4f7c80ba0272e24a5cd3cba1455c0999bcc6e38318`.
- Scheduled record: `catalog/scheduled-runs/20260906T200807Z-002965c1cc1440979f2bbaaaae5b7176.json`;
  SHA256 `a35d3ad599892c56717fc84ddb94cc20741c26f2ed55bba8b9e962a89cb69d03`.
- Ordinary-token execution record SHA256:
  `56d37275a667b67507e98a26d34fca391ce673ca5e78ccb2d15f4fe3d579db38`.
  It records the exact operator SID, `elevated: false`, and exit zero.

Before-run and after-run scheduler snapshots bracket the normal 06:00 trigger.
The current action, principal, settings and triggers exactly match the preserved
post-installation task XML. The standard installed entrypoint and log began at
06:00:03. This continuation did not issue a manual start or alter a trigger.
Task Scheduler's Operational event log is disabled, so no event-ID evidence is
claimed. The evidence uses the task readbacks, unchanged definition, standard
entrypoint and hash-bound execution records. No Windows prompt was used.

## Restored data

The scheduled run accepted generations 115 (September 7 observation), 116
(control), and 117 (macro). Its terminal freshness check reports all categories
UP_TO_DATE, no missing completed dates and no stale diagnostics. Its predecessor
is the preserved September 6 operator-requested backup, rather than a rewritten
history or fabricated natural execution.

The exact immutable archives are:

| Generation | Kind | Archive SHA256 |
|---|---|---|
| 115 | Observation | `fb11de085bbb6de112df02246de2f70d37e19d4f875c79b9211217b9ea809fd0` |
| 116 | Control | `b8d6205337d3063679ae31747703a6231f8423703131209ef6cbe708ca1dbf99` |
| 117 | Macro | `9fb0f80d3e8bc6d561111e11c71bb2f5c0f60eed4fbd65eeeaee60c11a14b845` |

Independent re-verification passed: all 117 catalog entries and receipt hashes,
the three current source manifests and archive hashes, and a fresh extraction of
9,933 files totalling 2,768,231,227 bytes. All four SQLite databases passed
`quick_check`, `integrity_check` and `foreign_key_check`; both Git bundles and
secret-exclusion metadata passed. No partial backup archive remained. The audit
used the ordinary-user and receiver locks, retained the 50 GiB free-space floor,
and removed only its own validated restore scratch directories.

The independent report is `independent-restore.json`, SHA256
`f4b5541fb6a410106a9a1e5721e53223e7fd458085095dc349996da0bb512702`.
The separate trigger/identity readback is `trigger-and-identity.json`, SHA256
`c6a742f933373a3dcc7a90bb012e1c0a81d0bf22c511f99771529baa33ac5dd6`.
Local evidence is under
`C:\code\backups\AR-local-user-session\natural-proof-20260907`; the backup
catalog remains in the separate ordinary-user target.

## Production and continuation boundary

The September 7 natural ingest ran from 01:00:00 to 01:16:49 and exited zero.
At 08:18, the Pi's own manifest check reported September 7 v1 and dates-index,
`publication_current: true`, and no publication issues. Dashboard smoke passed
with 16,013 rates. At 08:22:44, production was still clean at the recorded runtime,
both ingest services were inactive, and root was the protected NVMe UUID
`4cbd4874-d326-4496-bee2-7fda775a3c4c`. The next natural ingest remains 01:00.

A separate operator-directed data-reliability task is preparing further runtime
work. Do not perform a physical recovery reboot concurrently. Before A4, settle
that work, revalidate the actual approved production identity and matching
current backup, consolidate A3's remaining acceptance controls, and finalize the
guarded media/boot/return procedure. Preserve the existing SD baseline and all
legacy evidence. Physical boot remains UNPROVEN; PR #607 remains draft.
