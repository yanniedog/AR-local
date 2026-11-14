# Held optional preparation v1

This is a source-only library. It has no daily, pending-publication, revision,
archive, upload, retry or selection-pointer caller. It grants no Pi or publication
authority. Existing diagnostic snapshot/package markers remain unchanged.

`AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY` and
`AR_LOCAL_PRODUCT_RESPONSE_EVIDENCE_DELIVERY` accept only literal `0`/`1`; absent
means `0`. With both disabled, the pure projection retains the legacy canonical
manifest and bundle identity, and the caller can stop before any source access.

When enabled, `optional_product_evidence_status` has schema
`ar-product-evidence-status-v1`, the exact selected source quartet, and two lanes.
Each lane has `state`/`reason`: disabled/disabled_by_configuration,
pending/not_prepared, unavailable/source_unavailable|source_failed|source_superseded|
source_unverified, unsupported/unsupported_source_schema,
failed/preparation_failed|budget_exceeded, or available/verified.
Only available lanes carry detached references in their established root fields.
Missing preparation is pending. Malformed *claimed-ready* evidence is a fatal
integrity error; callers must not convert it into an optional omission.

The D003 policy for later wiring preserves valid current financial rates/details
when optional preparation is explicitly pending/unavailable/unsupported/failed.
A later successful optional retry must create a new immutable revision; it cannot
rewrite the selected manifest or erase a financial pending obligation. This
library does not implement that transaction or retry policy.

`FinalizedSource` requires externally pinned manifest and selected-pointer bytes.
It follows the existing partial-observation/otherwise-complete selection rule,
checks marker/contract/event/source agreement, current generation and revision
ancestor artifact hashes, complete ledger reachability, and base asset bytes.
Pointers, controls and artifact identities are rechecked before/after preparation
and adoption. There are no write locks, repair calls or automatic pointer advances.
Each full proof phase is bounded to 16 GiB reads and 100,000 charged entries. At
most five phases are permitted: initial observation, preparation pre/post checks,
and adoption pre/post checks. Only a whole `recheck()` begins a new phase; inner
loops cannot reset counters. Failed phases consume their allowance. The original
600-second lifetime deadline never renews, and exceeded/expired phases cannot be
reset. Thus the maximum aggregate ceiling is 80 GiB/500,000 charged entries, not
unlimited retry. Current retained 9,959-file input requires repeated complete
proofs; the old lifetime100k counter would fail before preparation ended. This
accounting control is not an actual Pi I/O benchmark. Large future data/history
may explicitly exceed these limits. The caller still
needs queue ownership, process/resource limits and a final promotion fence.

Preparation writes a NEW private snapshot only. Its separate returned receipt
binds exact writer revision, source selection/control hashes, base manifest,
snapshot hash, contract normalization and fact normalization. It does not change
the snapshot's `selection_verified=false` or `publication_authorized=false`.

Adoption requires that receipt, its separately retained expected hash, and each
supplied package's fixed `prepared.json` hash. An external receipt loader/resume
route is not implemented; a future caller must not derive the expected pin from
untrusted resumed bytes. It verifies the complete bounded package against the actual selected
snapshot and base core/details hashes; raw evidence additionally binds the exact
original journal chain and promotion inventory. Original raw projection variants
remain in the raw index. No path is discovered from an arbitrary prepared/latest
pointer, and no unknown external normalization code is independently rerun.

The caller MUST establish trusted exact writer code independently (reviewed and
tested immutable source revision or equivalent complete module closure). Hashes
supplied by an untrusted self-consistent package do not establish authenticity.
The required `writer_revision` is that caller's pin, not self-attested proof of the
executing checkout. Future longitudinal comparisons must distinguish normalization
code changes from original bank-body changes.

The returned `ar-product-evidence-candidate-v1` is immutable canonical bytes,
limited to 64 KiB, with base byte/bundle hashes, exact writer revision, selection
hashes, enabled lanes and per-lane outcomes. Reload compares all supplied bindings;
caller object mutations cannot alter it. `publication_authorized` remains false.
This candidate is preparation intent, never a selected or published edition.

Tests use retained real financial bodies plus explicitly technical local
finalization/ledger and base-asset controls. The existing restored raw archive
lacks selected observation pointers and completion marker; it cannot demonstrate
actual current-selection adoption. Full selected-source/live publication and
device acceptance remain separate future gates.
