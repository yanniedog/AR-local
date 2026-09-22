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
accounting mismatches remain blocked. Legacy bounded admission is unchanged.

Publication retains every gap and the original partial observation identity.
The coverage carries a conservative `severe` policy disclosure for admission
outside the legacy failure budget. It does not infer the size of an unknown
missing-product population, approve financial calculations, or make v3 promotion
complete. No observations, bytes or dates are replaced or relabelled.

This predicate does not authorize arbitrary input files. The scheduled wrapper
still verifies the completion marker, finalized ledger event and original
artifact hashes under the ingest/publication lock. Reconciled backfills verify
the exact export path, marker, contract, finalized ledger and artifacts under
that same lock, including rolling refresh. `--force` cannot override a failed
reconciled-source check. Both paths also verify the original status histogram:
old contracts can label internal worker crashes as upstream rejections, so
provider categories alone are insufficient. New unknown/internal statuses have
their own refused classification. A missing or untrustworthy source cannot
be manufactured merely to fill a calendar date.

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
Independent private copies do not share the scheduled production lock.

Local protocol tests use retained September22 accounting in freshly sealed test
contracts. They are not source captures. Exact production-contract, artifact,
payload and installed-runtime verification remain separate execution receipts.
