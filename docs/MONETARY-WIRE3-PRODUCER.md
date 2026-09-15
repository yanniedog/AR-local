# Monetary wire 3 producer foundation

The first capability is `savings_calculation` / `aud_savings_base_period_v1`.
It supports a source-reviewed historical base-interest holding period, explicit
posting and rounding, complete no-fee coverage, and private user-confirmed
account inputs. It does not approve any actual product or activate publication.

## Storage and approval

`migrate_executable_registry(store, wire_version=3, applied_at=...)` explicitly
applies frozen additive migration 002 after 001. No import or normal v1/v2 read
applies it. The migration retains original schema objects and hashes affected
executable rows/views within a write transaction. It does not scan unrelated
source history. Cancellation rolls back; repeated migration verifies its receipt.

The existing `stage_subject` / `review_subject` controller dispatches by exact
stored wire version, capability, kind, adapter and evaluator tuple. New monetary
subjects bind current product routing separately from historical authority.
Independent human/deterministic reviews bind the complete policy projection,
original evidence, completion proof, actual benchmark and observed predecessor.
Staged flags cannot establish approval. Latest negative reviews invalidate reuse.

A later source-backed policy does not revoke an earlier historical interval.
Successor applicability is compared with the actual selected field intervals
using the old revision. Overlapping changes, extraction corrections and negative
reviews refuse. Adjacent evidence ranges may jointly cover a field; explicit
supersession is required only over the conflicting authority intersection.

## Resource and transport boundaries

Historical graph members remain limited to 2 MiB each, 32 MiB raw and 24 MiB
decoded per operation. Current adopted core/details and fetched monetary bodies
use a separate 24 MiB expanded public-snapshot budget. The manifest inventory
retains its existing 8 MiB compressed aggregate limit. Decoded historical bytes
are reused once; no global source or authorization cache is introduced.

Full historical core/details larger than 2 MiB are unsupported as retained
observation members. This does not make dated-clause authority sufficient:
actual complete source evidence and independent review remain mandatory.

`build_payload(..., executable_v3_root=...)` and `build_and_publish_dual` expose explicit
default-off packaging. Publishing requires immutable revisions and refuses
encryption. Capability routes live in URL-free top-level `executable_v3`, outside
legacy `files`; archive, upload, readback and network budgets use the shared
asset iterator. Old v1/v2 bytes and absent-namespace behavior stay unchanged.

An internal append-only `removed` publication has NULL payload. The next current
index omits the product and omits empty capability routes; no empty public subject
asset is manufactured. Current routing and predecessor CAS still apply.

## Verification limits

The retained app bridge is engineering-only. Benchmark validation binds actual
compressed assets, exact raw adapter inputs, generated contract/scenario, local
facts, independent eligibility and Fraction arithmetic, holdout and actual
rate/period/cleared-funds/target refusals. Code manifests verify bounded retained
literal local-import closure and locked external metadata, not installed package
execution. Private historical source bytes are never sent to the app.

The focused controller unit test substitutes its benchmark boundary. A separate
no-stub connected regression regenerates the exact engineering description source
and finalized capture, matches the subject executed by the retained app adapter,
then verifies benchmark, independent review, publication, revocation and removal.
Neither is bank approval or end-to-end approval of a real multi-clause product. No production database,
source acquisition, publication, deployment or account scenario is changed.
