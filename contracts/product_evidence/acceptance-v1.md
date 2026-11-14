# Held complete optional acceptance

This source slice is disabled with the existing delivery flags. It does not
install a job, publish, enable optional delivery, or authorize Pi/Drive operations.

`cdr_product_evidence_acceptance.verified_inventory` independently verifies the
exact private manifest and every capability, index and shard through the complete
publication adapter. Its inventory contains unchanged financial keys plus
`<lane>_capability` and `<lane>_asset_000` (index), then ordered shard keys `001+`.
No optional namespace may pass by verifying financial assets alone.

The app's `optional_product_evidence` receipt has the exact schema
`ar-product-evidence-audit-v1`, status `PASS|FAIL|UNSUPPORTED`, `manifest_sha256`,
scope `private_candidate|public_selected`, and `lanes`. Each of the two known lanes
contains only `state`, `reason`, `verified_asset_count`; descriptive counts belong
outside this receipt. Its remaining fields are `namespace_validation_complete`,
`selected_head_verified`, `public_transport_verified`,
`rendered_coverage_verified`, `population_completeness_verified`, and
`original_wire_bytes_verified`. The last three are false: complete declared
transport bytes do not independently prove source population, original journal
authenticity or rendered consumer coverage.

D027 requires the exact private receipt, namespace validation true, all authority
bits false, and exact asset keys/hashes/lengths with PASS. Unknown/unsupported,
missing, contradictory or corrupt optional proof blocks acceptance. Known pending,
disabled or unavailable status requires zero lane assets; app metadata validation
may pass with a visible availability warning. Existing raw CI/Jest/candidate/source
pins remain required. Financial-only receipts retain their previous behavior.

The public source audit requires all immutable optional bytes through the existing
encrypted transport, a matching selected revision and stable encrypted root/index
readbacks. It reports the complete inventory separately from financial-source
findings. A matching source/audit receipt alone is not public selection evidence.
The old retained diagnostic package without explicit lane status remains useful
for app backward-compatible byte inspection; it is not admissible to the current
producer publication/D027 contract. New protocol controls use new manifests and
preserve those original bytes.

## Backup placement

Externally pinned ready base, snapshot/package and detached-capability directories
must be canonical descendants of `data/state`, outside existing backup exclusions.
Wire locators retain their data-root-relative encoding. The original preparation
guard still forbids output beneath the original contract's directory; use the
actual dated `state/export-contracts-v2/<date>/...` layout and a separate state
namespace. No unknown top-level data directory is implicitly backed up.

The existing full snapshot recursively freezes state, including optional intents,
prepared packages, frozen financial candidates and retry records. Local tests
exercise its real inventory and restore verifier with captured package bytes;
they do not certify cloud writes or a production source restoration. The daily
capture archive precedes publication and intentionally excludes later derived
payloads. Its immutable scope remains unchanged.

## Remaining rollout boundaries

Legacy report readers now explicitly reject optional scope rather than presenting
an exhaustive financial-only report. They are CLI/report entrypoints, not called by
daily publication or D027; optional report export remains unsupported until a
bounded streaming report is implemented. Existing public canary binders likewise
retain failure findings; financial fallback rows do not remove the failure.

The existing D027 worker builds a financial-only candidate. Its success does not
exercise enabled optional preparation/adoption. Actual selected-source optional
resource qualification, installed dispatch/retry, service/public readback,
full-backup cloud restore and device journeys remain separate rollout gates.
