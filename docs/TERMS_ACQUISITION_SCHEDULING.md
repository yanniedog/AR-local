# Terms acquisition scheduling

This dormant local controller change does not activate a Pi service, authorize
network work or permit Google Drive writes. Its processing and capture evidence
remains private. Live resource, quiet-window, authenticated-host and exact-version
activation gates remain separate.

## Deferrals and failure budgets

A live request guard raises a distinct `OperationalDeferral`. Acquisition records
the existing `deferred` check status and a canonical `operational_deferral_v1`
marker naming the exact document, check and guard error. A failed string beginning
with `operational_guard:` is still a failure. Manual checks do not inherit a queue
lease merely by supplying the same marker.

The acquisition queue validates its current owner, check time, document identity,
and the digest of request plus lease before acknowledging the deferral. It records
the existing `retry_wait` event with `operational_deferral_v1` as its cause and a
five-minute delay. Only that sole, exact, timely acknowledgement exempts its own
running lease from the four-attempt budget. Malformed markers, ambiguous/changed
terminal dispositions and unacknowledged crashed owners conservatively count.
Four genuine failures or expired unacknowledged leases still block the request.
Expired leases use bounded exponential backoff; no immediate crash retry loop.
Every original check, lease and disposition remains retained.

Deferral receipts retain conservative unknown-transfer byte charging. A guard
can change after redirects, so a deferral does not prove no network bytes moved.
The existing `network_called` field indicates an acquisition attempt, not a packet
counter. Manual observation acquisition preserves every supplied policy field and
clips its caller deadline against the helper's cumulative deadline.

## Selecting processing work

Direct/current product captures keep their generic interpretation task. A request
is omitted from generic processing only when it has no direct current observation
and a verified graph-only scope. The bounded graph frontier registers each exact
required node independently. Existing redundant generic rows receive a retained
`blocked` disposition, without a lease or a claimed interpretation/graph output;
claim can skip up to64 such maintenance items without spending a parser slot.
Shared direct scope and distinct graph nodes are not collapsed.

Changed or first current captures receive priority0 before dequeue for both
direct interpretation and graph nodes. Unchanged captures retain request
priority. Graph node identity and its pinned check remain unchanged. The previous
version must have a completed source capture and a full
accepted acquisition lease/check binding; orphan and historical-priority checks
cannot confer current priority. Current scope and the original acquisition are
checked again before any parser lease. Source or owner changes still refuse work.

Two explicitly **derived mutable** tables select work:
`acquisition_processing_schedule` and
`acquisition_processing_schedule_migration`. All other evidence tables retain
their existing UPDATE/DELETE protection. Every authoritative processing event and
its schedule projection update in one transaction, with an inner savepoint so a
caught projection failure cannot leave a new unmatched event. Neither a cached
priority nor its explanation grants source, lease, interpretation or publication
authority. A selected hint is re-derived from the exact latest immutable event
and current source; any mismatch is reconciled before selection is retried.

The partial schedule index contains only queued/retry_wait rows and is ordered
by priority, due time, creation time and processing ID. Claim makes at most three
priority-specific indexed due-range lookups per selection. Terminal history and
future priority0 retries do not obstruct ready lower-priority tasks. Equal
priority/due/creation values use the processing ID as deterministic tie-break.
No SQLite progress handler is installed or replaced by scheduling.

## Existing stores and recovery

Opening an existing store creates empty derived tables/indexes without scanning
or rebuilding indexes on old evidence. A persistent keyset cursor backfills at
most64 original processing rows per claim; its updates share the transaction.
It resumes after interruption/reopen. New enqueues are projected immediately.
Incomplete migration keeps work explicitly pending, including when the indexed
subset has no ready task. Unknown older priorities are not treated as complete;
their ordering becomes available as the bounded cursor reaches them. Existing
events, receipts and task identities are not rewritten.

The unpublished initial scheduling implementation used request priority for
graph nodes. A derived cache produced by that implementation cannot claim the
corrected graph ordering without a separately controlled rebuild of only the
two derived schedule/migration tables, preserving immutable events and evidence.
Refreshing a selected hint is not a global priority migration for hidden rows.
No such cache was deployed or activated in this work, and no runtime rebuild is
performed or authorized here. Existing stores from before either schedule table
use the bounded migration above, which computes the corrected graph priority.

Controlled activation requires a sole controller running the same reviewed
version. An older concurrent writer or arbitrary out-of-band corruption/deletion
of derived tables is unsupported; do not treat such a database as a healthy idle
queue. Stop and reconcile/rebuild the derived state against retained evidence
under a separate controlled recovery. A selected stale hint is repaired safely,
but this is not a universal corruption detector for every hidden cache row.

Protocol verification covers the previous failures, genuine failure/crash budgets,
exact marker rejection, policy preservation, graph-only reconciliation, changed
capture priority, atomic event/capture failures, migration rollback/reopen and
index selectivity with thousands of terminal rows. These tests are not native Pi
activation, natural scheduling, full document coverage or legal completeness.
