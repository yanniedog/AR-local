# September 11 observed backup

The unchanged ordinary-user task started at 06:00:01 and completed at 06:10:16
Hobart. Native receipt, guard and Task Scheduler exit status all passed. The
observation, control and macro archives were each restored and checked by the
receiver; the current catalog has 155 entries. Independent verification of the
frozen receipt metadata passed at 08:19:48. It did not re-extract archives.

Task Scheduler Operational history is disabled. The start time aligns with the
configured daily trigger, but that observation does not establish trigger
attribution. `natural_trigger` therefore remains `UNVERIFIED`; A3 remains
`RUNNING` and A4 `BLOCKED`. This inspection did not start a task, alter its
definition or configuration, enable logging, contact Pi over SSH, elevate,
write physical media, or deploy source. The next daily trigger is September 12
at 06:00. Another matching start time alone will not resolve the attribution gap.

`terminal-summary.json` and its content-addressed ZIP preserve 252 captured
files plus the manifest, including the native terminal and original restore
checks. Older manual intent files in the activation packet are historical
September 10 evidence, not the origin of this September 11 execution.
`task-observation.json` and `observed-task.xml` capture current task/history
state; `binding-current/` contains exact independently checked expectations.

The initial collector stopped because the new output parent directory did not
exist. A premature verifier call consequently found no snapshot. Neither call
changed backup data. The collector now creates its output parents while still
refusing an existing snapshot; the successful capture and verification followed.

All seven rolling v1 files and both v2 files were downloaded and verified for
compressed size, hash, bounded gzip decode and JSON. Core, details and product
history run dates and economic-outlook generation date matched September 11;
the v2 base hashes matched v1 and the dates index listed September 11 latest.
The manifests and index were re-fetched unchanged. The dated release and the
user's device were not verified by this publication inspection.

The live Pi browser at 08:20 showed September 11, 7,342 current mortgage rows
and a loaded hierarchy/history view. `npm run verify:local --
--base-url=http://100.78.28.10/` passed. This is a dated dashboard check, not
full ingest-journal, provider-completeness or physical recovery acceptance.

No original source, configuration, evidence or archive has been rewritten.
