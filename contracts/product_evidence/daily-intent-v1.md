# Held daily intent and separate optional retry

Source-only integration. No scheduler, enabled flag, public publication, Pi,
Drive, Android release or device acceptance is established by these modules.
Dependency: the full frozen-delivery stack and recursive publication adapters.

## Initial financial transaction

Both delivery flags remain strict `0` by default. Disabled ordinary publication
keeps its existing manifest and bundle identity. The ordinary source pointer is
recorded in financial pending **before** optional setup, unchanged. Setup runs
inside `maybe_publish_app_payload`'s existing nonfatal error boundary.

`admit_financial_intent` creates one immutable intent per original
`publication_source_key` in `optional_product_evidence_intents`. It records the
enabled lanes, exact clean writer revision and original source-pointer digest.
Invalid flags or an unverifiable writer create no valid intent: publication
returns `PUBLISH_FAILED`, financial pending survives, and successful ingest still
reaches terminal backup scheduling. Existing valid intents never reread changed
flags or replace their writer. Writer drift blocks publication.

Ordinary enabled delivery initially records truthful pending/disabled lane
status. It does not discover a new prepared package. An explicit prepared caller
can supply `persist_delivery`'s externally pinned descriptor: exact original
financial base manifest hash, data-root-relative base/evidence/capability paths,
and state-relative frozen-delivery hash/bytes. Full fresh selected-source and
prepared-package verification remains required. Claimed-ready failures never
silently become missing/pending evidence.

After base construction, `FinancialEvidence.freeze` copies the original manifest
and every declared financial asset into a new private immutable attempt. The
candidate adds the fixed lane status and, where verified, the original capability
gzip bytes plus every index/shard. It does not recompress identity-bound assets.
Clean complete inventory verification precedes a create-once `freeze.json`.
Its external hash is atomically bound in `optional_candidate_pins`, keyed by the
**original financial pointer**, before any revision reservation.

Resume reads that exact candidate before computation or packaging. New files,
changed flags and mutable staging cannot upgrade an existing pending revision.
Source/writer/control/pin fences remain active before promotion. Settling a source
removes only its matching intent and candidate-pin references; immutable attempt
files remain retained. No automatic scratch retention/deletion policy is added.

Finite staging limits are 320 MiB written, 2,048 files, 600 seconds per attempt
and eight retained attempts per intent. Existing source proof, asset, manifest,
eager network and outer execution/resource limits remain independent. No
unbounded-growth or current-scale Pi acceptance is claimed.

## Explicit optional enrichment retry

`register_optional_retry` requires an explicit ready pointer, exact original
financial base, verified published predecessor bytes and an external dates-index
hash. It retains a create-once request under `product-evidence-retries-v1`.
The predecessor's financial bundle must equal the original base, while source
generation/date/state and all revision identities agree. Legacy predecessors'
actual asset bytes are checked too. No remote permission follows from a local
receipt. Runtime selection is checked again by the revision transaction.

`publish_optional_retry` is an explicitly invoked API, not a scheduled task. Its
caller must already provide bounded exclusive AR-local queue admission and the
documented outer resource/timeout supervisor. It rechecks the maintenance window
after acquiring the ordinary ingest lock and defers while **any** financial
publication is pending. It never creates, clears or changes financial pending.
Separate durable attempt IDs reserve cooldown before work; terminal state uses
attempt CAS. A failed/aborted retry retains its candidate and cooldown.

The retry uses original base bytes, an independently pinned ready descriptor and
fresh source proof. It requires a changed optional bundle and cannot remove an
already available lane. `expected_predecessor` reaches the revision transaction
before reservation. A different selected predecessor fails closed. If this
exact child was already selected before alias interruption, recovery requires
full selected bytes and the retained exact predecessor index/head; it does not
reserve another revision. Dated and rolling alias confirmation (or a legitimately
newer rolling date) is required before marking the optional request published.

## Remaining rollout gates

No preparation dispatcher, automatic retry scheduler or operator CLI is installed
here. Exact-source real-scale qualification, full consumer/API/route wiring,
reviewed flags, deployment, public encrypted readback and device journeys remain
separate. Technical selection/transport controls in tests use captured product
bodies and rates; they do not prove current national coverage or public selection.
