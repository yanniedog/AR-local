# Permanent Pi maintenance window

Operator decision, 2026-11-14: "Permanently make it so that the Pi can be access
and updates until 00:30am each day, on an ongoing basis."

Maintenance admission is **03:30 until the next 00:30 Australia/Hobart**, including
the first thirty minutes after midnight. The protected interval remains
**00:30–03:30** and the natural ingest remains **01:00 daily**. Bounded read-only
access is unaffected. Resource, ownership, source, CI, backup and cleanup gates
still apply; permission to work until 00:30 does not mean a long operation can
start immediately before it.

`ar_local_ingest_schedule.py` owns the common clock and next-cutoff calculation.
Before 00:30, the boundary is today's 00:30, never tomorrow's. This policy is used
by recovery/catch-up budgets, publication retry/archive/backfill, quality
canary/sealing and terms analysis. Terms start admission retains its fifteen
minute reserve; publication retains its full thirty minute child plus cleanup
reserve. Backfill charges its entire configured process-tree lifetime and stop
budget. Existing hash-bound individual authorizations can narrow the deadline
but cannot extend it across the quiet period.

The root-owned restricted CI helper has the same clock admission implemented
locally; it never imports candidate code as root. The shared queue already
reserves the 00:30 boundary, including stop/rollback grace and active ingest
leases. Its generic 02:00 release is not a substitute for the manual operations'
03:30 admission. No timers or queue protection were rescheduled by this change.

Quality activation binds the latest **scheduled ingest date**. At 00:15 Nov14,
the natural Nov14 ingest is not yet due, so the selected Nov13 observation can
still qualify maintenance. It does not manufacture a Nov14 capture or permit
historical live ingestion. Once the next ingest is due, the previous day's
selection fails this gate. Observation generation, hashes and protected inputs
remain bound throughout the canary and activation.

The legacy D-006 laptop receiver transition keeps its independently sealed
deadline; it is not the Pi maintenance admission route. Historical handoff
entries and their original decision dates remain unchanged. This permanent
decision supersedes their older 22:00 **Pi maintenance** limit only.

## Activation and evidence

Source implementation and tests do not prove runtime installation. In particular,
the installed `/usr/local/lib/ar-local-ci/pi_ci_activate.py` must be updated
through its owner-reviewed installer and validated against the exact approved
source before the restricted route gains the new window. Other pinned helper
bundles likewise need their ordinary exact-source installation gates. The
repository source activation route and hosted canary workflow have separate
deployment/CI prerequisites. No Pi access or runtime mutation was performed by
the window implementation worker.

Boundary regressions cover 22:00, late evening, midnight, immediately before and
at 00:30, 03:30, Hobart DST dates, shortened deadlines, process cleanup reserves,
the self-contained root guard and the latest-due selected observation. A single
known Windows interpreter-binary identity test is excluded from the local
focused run; the Linux exact-head producer suite remains required, with its
interpreter pinning unchanged.

Focused local result: **379 passed, 9 platform skips, 1 deselected** in 27.87s,
isolated runner `20261114-001949-7843c505`; complete JUnit is retained privately as
`permanent-window-tests-final.xml`. The first run exposed stale old-window test
expectations and the known Windows executable-identity limitation; the updated
boundary expectations passed without changing the executable guard.

After synchronizing the capacity-state repair, 192 additional checks passed
(2 platform skips), including the actual CI launch descriptor fed through shared
queue admission. Its 1,800-second transaction plus 900-second rollback reserve
admits 23:44:59 and refuses 23:45, midnight and 00:29. A clock-only root guard test
does not imply the mandatory queue permits a new deployment at 00:29.
