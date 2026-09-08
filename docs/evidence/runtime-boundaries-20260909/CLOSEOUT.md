# Requested early backup: completed

The user requested "Do it now rather than 6am." The ordinary-user task was
invoked at 05:32 on September 9 and rejected its pre-06:00 start. Date-bounded
manual wrappers then ran without Windows elevation. No installed source,
configuration, scheduled task definition, production checkout, firmware or media
was changed.

The final backup check passed at **06:19:29 Hobart**. Observation, control,
macro and completed-date inventory were all `UP_TO_DATE`, with no backfill or
missing completed dates. Terminal record SHA256:
`f99598f2314ff13abcc7ba7be61be5a4d35daab654e3ccbeaf1b17c5f368d980`.
An independent receipt binding passed at **06:21:39**, covering observation
catalog sequence 141, macro 144 and control 145. The reader used temporary
coordination locks after the live job and 06:00 trigger had finished. Its first
invocation rejected a relative expectations path; the corrected absolute-path
invocation and both outputs are preserved.

`backup-result.json` records the exact component archives and verification.
The observation archive contains 9,110 verified files and 2,677,583,521 source
bytes; SQLite integrity, foreign-key and reconciliation checks passed. The
72-file metadata ZIP contains the catalog, terminal and earlier scheduled
records, failure records, user executions, and the current component receipts
and manifests. Its `_manifest.json` binds each entry's literal bytes. Archive
payloads remain under `C:\code\backups\AR-local-pi5-user`.

The initial isolated execution could not import the installed user-site
jsonschema dependency. Subsequent executions used the installed launcher's
normal `-B` environment. SSH failures were retained, including failures after
verified components had already committed. The final wrappers increased SSH
connection deadlines to 60 seconds and bounded helper calls to 90 seconds,
preserving endpoint, executable, key, host-key and ordinary-token checks. Cleanup
used the same generated-path guard and exact file removal plus empty-directory
removal in one connection. The two identified leftover helper directories were
separately removed after checking ownership and exact contents; that command and
output are saved in `known-helper-cleanup.json`.

The check-only pass at 06:12 confirmed observation and macro current but control
stale. New recovery-state records and capacity-monitor state had changed between
the earlier control snapshots. The installed content-revision logic already
excludes runtime-health summaries and Git-bundle byte variation; no exclusions
or freshness rules were relaxed. The final control-only wrapper required the
original preflight to prove observation, macro and inventory current before
selecting control. The original post-backup verification still checked every
component and returned PASS. No observation or macro copy was requested by that
final refresh.

The unchanged 06:00 task triggered while the manual run held its whole-job lock
and exited 1 without a competing backup. This is **not** natural successful-run
proof. A3 remains RUNNING, A4 remains BLOCKED and PR607 remains draft. The normal
task is Ready with its next trigger September 10 at 06:00. The timeouts, cleanup
and selective-refresh wrappers are one-time process-local mitigations, not
installed changes; preserve this distinction for the next natural run.

Today's app publication was independently downloaded and verified:
`publication-check.json` records rolling v1/v2, dated v1 and the dates index for
September 9, with both core checksums matching. The core contains 7,996 mortgage,
2,077 savings and 6,226 term-deposit rows. No phone was connected, and the user's
displayed date/error was not supplied. Device refresh is therefore unverified;
the backup does not gate app publication.

Source fixes merged separately: PR658 (`483dcc243`), PR659 (`16d949536`) and the
late version-advertisement correction PR660 (`f58b7107e`). Their applicable Linux
and Windows checks passed, and originating review findings were resolved. These
repository changes were not deployed to the Pi or installed in the receiver.
