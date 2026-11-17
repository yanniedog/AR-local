# Held optional delivery freeze and complete inventory

These APIs are source-only adapters. They do not enable flags, change selection,
write financial or optional pending state, reserve a revision, publish, or back up
data. Existing diagnostic package markers retain their original false authority
fields. Daily callers and authenticated delivery are not connected yet.

## Frozen private intent

`cdr_product_evidence_runtime.freeze_delivery` requires a finalized source proof,
its independently pinned preparation receipt, an explicit enabled lane set,
exact writer revision, and caller-pinned prepared packages. It runs the existing
complete adoption proof before producing canonical immutable bytes. Disabled
delivery returns before source/path access. An enabled missing package remains
pending; any supplied claimed-ready package must verify completely.

`ar-product-evidence-frozen-delivery-v1` contains:

- `candidate` and `preparation`: original bytes encoded as base64 plus SHA-256;
  each decoded document is at most 64 KiB.
- `snapshot_root` and `packages`: literal descendant directory locators relative
  to an independently supplied canonical existing evidence root; each package
  retains its exact original prepared marker SHA-256.
- `publication_authorized=false` and `selection_verified=false`.

The whole descriptor is at most 256 KiB. Its SHA-256 must be retained externally
by the future owning transaction. Resumption cannot infer authority from a digest
inside the descriptor or a moving latest pointer. `resume_delivery` requires
fresh independently pinned finalized source/base/selection, expected writer
revision and lane set, then repeats original source, snapshot and package
verification. The resumed candidate must equal the original canonical bytes.
Newly appearing optional packages cannot silently enrich an existing retry.

Resumption uses a new source proof with its existing finite lifetime/phase
budgets; it never resets an existing proof's allowance. No source or package is
modified, repaired or locked for writing. This cannot replace the future caller's
exclusive ownership, exact-code admission or final source/predecessor fence.

## Complete publication inventory

`resolve_publication_inventory` takes root manifest bytes, an externally retained
manifest SHA-256, and a bounded capability reader. Root size remains 64 KiB.
Evidence references require the explicit versioned optional status protocol;
available states and references must agree. The resolver reads at most two
capabilities, validating their actual gzip bytes, hashes, inflation limits,
schemas and manifest source/core/details bindings. It enumerates all declared
indexes and shards with unique names and a maximum of 1,024 assets. Existing
per-lane size limits and the 16 MiB eager financial budget remain unchanged.

The immutable internal receipt is at most 512 KiB and reports
`asset_bytes_verified=false`: descriptor resolution is not asset readback.
`verify_local_publication_inventory` additionally verifies every byte, semantic
route and final manifest pin in clean local staging. It does not accept archive
reservation/control documents. Both results retain false publication/selection
authority. Capability readers must independently bound their I/O; outer runtime
supervision remains required. The existing 600-second verification ceiling is
unchanged.

Legacy manifest-only iterators reject these namespaces/statuses before yielding
partial inventories. Pure bundle identity retains the existing exact canonical
algorithm in `app_payload_bundle_identity`; legacy validation remains in place.
Evidence callers validate the financial base and detached references before
using that calculation. A hash or immutable URL alone does not prove all asset
bytes or authorize publication.

Still required: daily/pending serialization, immutable optional retry into a new
revision, authenticated transitive upload/download/archive/prune/no-op/companion
integration, app status adaptation, selected-source/runtime/public/device tests,
and applicable backup/restore qualification. No automatic activation follows
from importing these modules.
