# Backup failure-evidence follow-up, September 8

This repository change addresses three late PR646 findings. It does not install
a receiver, change Task Scheduler or mutate the Pi. The installed receiver stays
at `cbf920eceedcfd5cc19bd75d86351ddbc7b39e2e`, and production stays at
`2607ed681d5d3c1da66f9c3c0109cff524e02338` while natural-run acceptance remains
pending.

- The updater now uses the existing shared latest-pointer validator before
  authenticating predecessor ancestry. A pointer whose result differs from the
  hash-bound record, or whose result is missing, is rejected before task changes.
- Once the task updater creates its evidence directory, failures saving the
  baseline, rechecking ancestry, constructing the action or detecting a task
  race now create `installation-failed.json`. Before any mutation attempt,
  rollback is `NOT_NEEDED` and no task write occurs. After a mutation attempt,
  the existing rollback and readback controls remain in effect.
- Route-selection and terminal user-session records now share an execution ID.
  The terminal record also names its original immutable route record. Caught
  failures in argument construction, lock acquisition, catalog initialization
  or the scheduled receiver append a correlated FAIL before propagating the
  original exception. Nonzero returns also remain FAIL. The original RUNNING
  record is retained as the start event, not rewritten.

These controls cover caught exceptions when evidence storage is writable; they
cannot promise a terminal write after a killed process, power loss or unwritable
storage. Existing crash/recovery and stderr evidence remain necessary.

Verification uses isolated failures and mocked Task Scheduler calls in both
Windows PowerShell 5.1 and PowerShell 7. No elevation or real task update is used.

```text
python -m pytest tests/test_laptop_backup_user_update.py tests/test_laptop_backup_user_terminal.py tests/test_laptop_backup_user_session.py tests/test_laptop_backup_runtime_ancestry.py -q
```

## Historical review clarifications

The following is an append-only clarification; the completed source entries and
packets remain unchanged.

- PR644's `artifact_count=33` describes the original manifest with SHA-256
  `599fb0479c10cb4ae750c42282968ed9a5a6f66bce3b16b1266954586508a7f9`.
  The later `evidence_artifacts` array contains 36 entries because it also
  enumerates the catalog-prefix and watchdog additions. Both populations were
  counted directly on September 8. Neither count replaces the other.
- PR635 used the ordinary-user 06:00 route under the explicit
  `D-015-USER-SESSION-NO-UAC` continuation authority, confirmed by D-018's
  instruction to observe the unchanged daily 06:00 or genuine sign-in trigger.
  Its empty receipt deviation list means no additional departure from that
  authorized route; it is not evidence of using the retired S4U/05:00 path.
- The original PR635 handoff omitted its authoring timestamp. That exact time
  remains unrecorded; do not substitute the backup completion time. GitHub
  records PR635 creation at `2026-09-06T22:25:46Z` and merge at
  `2026-09-06T22:26:17Z`, commit
  `a3291d3d0209639f7fef093c539bef92e5cab0b2`. Those are publication bounds,
  not invented original authoring timestamps. The new handoff timestamps this
  clarification independently.
- PR635's natural-run observation uses before/after task readbacks, unchanged
  definitions, the expected 06:00 start and the explicit absence of a manual
  invocation by that continuation. The disabled Operational log limitation is
  disclosed; no event-ID attribution or exclusion of every hypothetical other
  actor is claimed. D-018 prohibits substituting a manual or artificial trigger;
  it does not require enabling an administrator-controlled event channel.
  That historical tuple never accepts the current receiver or physical A4.
- PR632's original inventory-verification command provenance is not fully
  retained in its cited summary. This remains an explicit historical limitation
  tracked in [issue 650](https://github.com/yanniedog/AR-local/issues/650).
  Do not replay collectors or manufacture an original command to fill the gap.
  Current September 8 backup/restore and receipt/runtime checks are separate.

The reason for these clarifications is to prevent confusion between inventory
populations, route authority, assertion/publication times and reproducible
command evidence. Compensating controls are immutable source retention, explicit
population and scope labels, the tracked historical provenance gap and fresh
independent current evidence. Revised acceptance requires the actual current
runtime, backup and remaining natural/physical gates; none of these historical
summaries alone grants A3/A4 acceptance or deployment authority.
