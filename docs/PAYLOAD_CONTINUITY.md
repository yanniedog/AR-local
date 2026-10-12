# Daily payload continuity

The daily watchdog checks every calendar date from the first publicly indexed
day through the expected daily date. `publication_current` continues to describe
the latest manifest/index pair. `publication_continuous` describes the calendar
history, and `publication_healthy` requires both. A current feed with historical
gaps reports `incomplete_history` and a failing watchdog check; it does not turn
today's successful publication into a failed capture.

After today's capture/recovery and the existing publication retry have priority,
an idle watchdog can reconcile missing public dates into the existing publication
queue. It inspects at most seven retained sources per pass, outside the protected
ingest window, and holds the production lease while changing queue state. The
next ordinary retry publishes a recorded observation; it never starts a historical
ingest. Latest queued dates are tried before older dates.

Reconciliation uses immutable historical selection decisions, publication policy,
and the marker/event/contract/status bindings. The ordinary publisher still
verifies the complete source artifacts, builds the versioned payload, and checks
public delivery before clearing the original pointer. Invalid public revision
heads, ambiguous source evidence, corrupt queue state, or an occupied lease stop
reconciliation. Existing pending pointers and historical artifacts remain intact.

Historical revision promotion also refreshes the public operational receipt
against the unchanged current rolling manifest and its selected revision. The
receipt must bind the changed index ciphertext; a failure keeps publication
pending, including when a retry finds the historical revision already selected.

`state/app-payload-continuity.json` records the latest inspected missing dates,
queued sources, and explicit unavailable/unverified source outcomes. Missing or
rejected sources are revisited no more than once in six hours, allowing later
recoverable dates to progress. The report's timestamp matters: public status is
always read independently. A dry run writes neither this report nor retry intent.

A past date without retained acceptable source cannot be recovered by relabelling
today's rates, copying another day's payload, or pretending an incomplete capture
was full. Such a date remains an explicit source gap until genuine source evidence
is recovered. This code does not change timers, enable scheduled tasks, or grant
deployment authority; the controlled Pi runbook still governs runtime activation.
