# Daily partial publication

September 22 finalized 2,804 products and 16,471 rates, with 47 attributed
failures across 11 partial providers. The old compatibility policy deducted two
authentication failures, then withheld the entire day because 45/2,804 exceeded
1%. A policy refusal created no pending-upload marker, so the watchdog reported
stale publication without retrying it. No failed upload had occurred.

The shared daily/backfill gate now also admits a partial observation when its
complete export contract validates, all three identities agree, every registered
provider was attempted, every provider state and classified failure reconciles
exactly, register and failure provenance are complete, and products and eligible
rates are nonempty. Quarantines, unknown classifications, security-policy or
recovery-budget failures, corrupt/unattributed records, missing registers and
accounting mismatches remain blocked. The legacy numeric budget remains, with
the same source and original-status verification required for every partial.

Publication retains every gap and the original partial observation identity.
The coverage carries a conservative `severe` policy disclosure for admission
outside the legacy failure budget. It does not infer the size of an unknown
missing-product population, approve financial calculations, or make v3 promotion
complete. No observations, bytes or dates are replaced or relabelled.

This predicate does not authorize arbitrary input files. The scheduled wrapper
still verifies the completion marker, finalized ledger event and original
artifact hashes under the ingest/publication lock. All contract-backed backfills verify
the exact export path, marker, contract, finalized ledger and artifacts under
that same lock, including rolling refresh. `--force` cannot override a failed
partial-source check, including legacy bounded admission. Both paths also verify the original status histogram:
old contracts can label internal worker crashes as upstream rejections, so
provider categories alone are insufficient. New unknown/internal statuses have
their own refused classification. A missing or untrustworthy source cannot
be manufactured merely to fill a calendar date.

Backfills resolve the selected observation before checking or building, so dated
and rolling payloads use its repaired revision exports. A later failed recovery
cannot replace a retained same-day selection. Historical days without the
current selection pointer reconstruct selection from the immutable per-date
decision receipts and their bound ledger events. Multiple generations without
complete, unambiguous decision history are withheld; filename order never
substitutes for selection. A single generation uses its contract-bound source.
Complete observations still require exact artifact verification, while their
empty failure histogram does not undergo the partial-only failure check. A malformed
present pointer or unsafe path is withheld even with `--force`.

For an already withheld observation, retain the original refusal and create a
publication request bound to its verified selected pointer under the operation
lock. Run the existing publication-only retry; do not run ingestion again.
Keep a failed request pending and require encrypted dated, immutable, rolling,
index and consumer readback before declaring the date published. Preserve the
Drive hold, quiet window, original archives and unknown lock owners.

Production backfills and rolling-only refreshes now require an active bounded
systemd service before acquiring the ingest lock. Starts are limited to
03:30-22:00 Hobart. Use `Type=exec`, `RuntimeMaxSec=3600` or less,
`TimeoutStopSec=30` or less, `KillMode=control-group`, `SendSIGKILL=yes` and
`Restart=no`; randomized extra runtime is refused. The guard checks final
SIGKILL, standard stop-failure behavior and empty stop hooks, preventing custom
shutdown commands from extending the lock lifetime. It reads the containing
service rather than trusting a caller's claimed deadline. Its whole
remaining configured lifetime plus shutdown and safety margin must finish before
00:30. Unsupervised production invocations (including the shell wrapper) fail
before taking the lock; launch through the reviewed bounded operator service.
If systemd stops an unfinished operation, the existing lock recovery checks its
dead owner before the next ingest; never delete an unknown lock manually.
Independent private copies do not share the scheduled production lock. A normal
developer repository without a configured runtime root needs no systemd service;
explicit runtime roots, canonical Pi paths and shared-lock aliases remain guarded.

Local protocol tests use retained September22 accounting in freshly sealed test
contracts. They are not source captures. Exact production-contract, artifact,
payload and installed-runtime verification remain separate execution receipts.
