# Legacy manual ingest admission

The legacy `cdr-ingest` command starts `ar-local-ingest-now.service`. Its generic
shared queue reserves 00:30–02:00 Hobart; that alone previously allowed an idle
manual job at02:30. The ordinary `--force` child did not invoke recovery's03:30
guard. The dedicated manual guard now checks before service startup, before
runtime data work, and again after queue/ingest-lock waiting.

Both manual unit definitions pass `--manual-ingest`. The child also recognizes
the exact service component in its own Linux cgroup, so an older installed argv
cannot silently omit the new guard once the source is deployed. Unreadable or
malformed Linux service context fails closed. Natural01:00 ingest and separately
claimed03:00 repair keep their existing admission paths; global queue hours are
unchanged. The manual template's stop hook uses the existing idle/quiet-aware
dashboard restorer, including when a direct service start fails admission.

The long manual route must fit its existing maximum lifetime before00:30:
21600s execution +3600s inherited hook allowance +900s stop grace =26100s
(7h15min). These bounds come from `shared-queue-ingest-now.conf` and the fixed-unit
limits in `pi_shared_queue_store.Supervisor.current`; they also cover the direct
template's shorter6h15min startup plus45s stop. The six-hour queue wait is not
charged again when the child begins; admission is rechecked then. With the current
bounds,03:30 and17:14:59 are eligible;17:15 and later are refused. Shorter controlled
maintenance/recapture routes retain their own budgets until the daily00:30 cutoff.

Source/CI proof is not runtime installation. Unit/helper deployment and acceptance
must follow the exact-source runbook. Existing installed hooks remain unchanged
until their ordinary reviewed update. Do not use the legacy command while that
runtime qualification is pending; preserve the current qualified candidate and
sole Pi operation owner.
