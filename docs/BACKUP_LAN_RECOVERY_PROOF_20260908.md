# September 8 ordinary-user backup recovery

Windows failed to resolve `ar.local` at the natural 06:00 trigger. PR646 installed a bounded, hash-configured LAN fallback while retaining the existing SSH pins. The task update and recovery used the ordinary Windows account with no UAC prompt.

- Natural 06:00 run: **FAIL**, preserved.
- First operator attempt at 08:42:12 Hobart: **FAIL** after observation/control verification, due to an SSH banner timeout.
- Operator retry after SSH recovered: **PASS / UP_TO_DATE**; earlier verified components preserved.
- Independent current observation, control and macro archive restoration: **PASS**.
- Catalog: **140 entries**, prior prefix preserved and every receipt hash verified.
- Interactive/Limited principal, daily/logon triggers and settings: unchanged.
- Pi production, legacy task and prior recovery evidence: preserved.

Receiver: `cbf920eceedcfd5cc19bd75d86351ddbc7b39e2e`. Production: `2607ed681d5d3c1da66f9c3c0109cff524e02338`.
Configuration SHA256: `4b7a812f01c4f3f027bcb5298f2a5aa5c53a7f9e345504fd78b80da53ea34bbf`.
Scheduled receipt SHA256: `4d5362fa501be158855b1f065e41c02dd1b60a49fb507b6238952f4127d652ca`.

[Original evidence packet](evidence/backup-lan-recovery-20260908/5778f5a2995eeb2166dcfd62b6fc976d44657a15d2fcd942518f3ec971620708.zip) contains 181 source files plus a manifest with exact original paths, byte counts and SHA256 values. Bulk data archives remain at the private paths recorded in the component receipts. Every packet entry was rehashed after ZIP creation; the independent restore script and exact invocation are included.

September 8 rates were published by the natural 01:00 ingest and the live dashboard/publication checks passed. The failed laptop backup was separate from publication.

Final-receiver natural backup proof remains due after September 9 06:00. A3 consolidation, guarded A4 physical recovery and PR607 simplification remain unfinished. This completed proof is immutable; later verification uses new files.
