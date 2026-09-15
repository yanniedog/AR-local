# Reviewed fixed-maturity template foundation

This is an explicit, default-off controller API. It does not register a banking
template, approve a product, configure ingestion, publish a release, or activate
an app calculation. The existing terms-v1 evidence contract remains unchanged.

## Source and execution scope

`executable-template-v1.schema.json` defines `fixed_aud_td_maturity_v1`, adapter
`fixed-aud-td-v1`, evaluator `product-terms-engine-v8` for new approvals. The supported pattern is
AUD, a fixed rate, ACT/365 fixed, explicit rounding, noncompounding interest paid
on calendar-day maturity, no business-day adjustment, funded-day inclusion and
maturity-day exclusion, and independently complete no-fee treatment. Early exit,
rollover, variable-rate changes and other conventions require another reviewed
pattern. `funded_date` applicability must cover the fixed rate and fee treatment
through the declared term; it is not permission to extrapolate a spot offer.

The source manifest hash is provenance, not the destination manifest identity.
Templates bind the finalized source observation/generation, retained export
contract, original product bytes, selected document versions and validated term
revisions. Tier, package, cohort and calendar-date endpoints must exactly match
the revisions. Unknown/null scope and mixed timestamp precision cannot become
unrestricted applicability. Every semantic field has explicit source clause
references, including principal bound inclusivity/unboundedness, no fees, and
calendar conventions. `none_source_declared` is a source-reviewed value, never
a default inferred from absence.

The selected TD row is bound by the exact adopted compressed core asset hash,
zero-based TD array index, canonical row hash and one-based `rate_index`.
Mobile core `rate` is already a fraction. Rate and exact `PnD`/`PnM` term must
agree; every present core balance bound must match the template. An absent core
bound does not establish unbounded eligibility. The consumer independently
checks actual deposited principal against the explicit bounds and eligibility.

Customer principal, funding/maturity confirmations, tax confirmation and profile
answers stay local. Typed input definitions distinguish scenario-owned facts
from customer facts; the adapter derives scenario facts from the actual local
input, rather than accepting editable profile substitutes. Public templates
contain no instantiated customer contract or scenario.

## Controller workflow

1. `stage_template(store, template, interpreter=..., staged_at=...)` validates
   schema, identity, exact current source/row and independently validated revisions.
2. `review_template(..., decision=..., reviewer=..., reviewer_kind=..., ...)`
   appends an independent human/deterministic decision. A model second pass or
   the interpreter cannot approve. Review evidence binds the exact template,
   adapter/evaluator, latest source-review snapshot, required semantic checks,
   and a retained typed benchmark result. Staged `verified` flags are forbidden.
3. `build_executable_asset` derives public approval flags from the latest review.
   `publish_executable_asset` checks previous publication identity and exact
   observation, then rebuilds the projection inside an immediate transaction.
4. `build_payload(..., source_observation=..., executable_root=...)` builds local
   assets from already published controller projections. The production entry
   point `build_and_publish_dual(..., executable_root=...)` additionally requires
   immutable revision mode. These options are not enabled by this change.

Benchmark evidence is private controller material. A run binds actual adapter
and evaluator code artifacts, exact instantiated evaluator input, complete typed
result receipts, and an independently authored expectation/derivation. It must
contain a successful result and a refusal control. Empty/unrelated matching
blobs and self-asserted digest-only passes are rejected. Controller capture and
independent review remain the authority for execution and semantic truth; hash
checks do not magically prove an arbitrary actor ran code or reviewed a source.

The new SQLite tables are additive and append-only, with foreign keys and
latest-slot/review/publication indexes. Existing archive rows are not migrated
into templates. Rejection/revocation can be recorded even after sources change.
Later loading rebuilds against current sources and latest reviews; stale stored
publications fail until the controller publishes their replacement/removal.

## Wire, edition and limits

`executable_index` maps product keys to manifest keys such as
`executable_shard_000`. Both index and shard have `schema_version: 1`, `run_date`,
`core_asset_sha256`, and `products`. Shard values are the closed
`executable-asset-v1.schema.json` envelope. `approval.templateId` must equal its
template's identity. Source generation means `manifest.source_observation.generation_id`,
not a newly generated publication revision ID.

Template IDs hash canonical UTF-8 JSON without `id`; asset IDs omit
`identitySha256`. Schema keys are ASCII, keys are sorted, separators are compact,
Unicode and decimal strings are preserved, and there is no trailing newline.
The shared Unicode/decimal fixture is a serialization/protocol vector, not
banking evidence or an approved calculation contract.

Limits: 256 KiB per template, 32 variants per current product, 512 KiB per
product asset/shard, 20,000 products and 24 MiB raw snapshot. Existing per-asset,
manifest and aggregate transfer budgets remain enforced. Source core decoding
is operation-local and bounded to four core identities/64 MiB total expanded
bytes; it never caches authorization across operations. Invalid metadata fails
the optional build rather than silently dropping a quote or approval.

Approval is **as of the adopted edition**. New current claims require the latest
adopted manifest/template-index identity. Changes, removal or negative review
invalidate dependent current calculations even when core bytes are unchanged.
An offline retained edition can replay a clearly dated prior-approval receipt;
it cannot assert current approval or instantaneous offline revocation detection.

The retained `tests/fixtures/executable-templates/actual-v7-bridge.json` records
real AR-app transport, instantiation and evaluator execution at commit
`a12b7b3f5fb7c521893010c2c8a222d9c114e7e3`. Its positive and refusal receipts
are checked through the producer benchmark validator, with separate Python
Decimal/calendar checks for all 29 accrual days, maturity settlement and totals.
The fixture is technical protocol evidence, not approval of any bank product.
The initial Windows diagnostic read omitted UTF-8 and produced a false identity
mismatch; byte-based JSON reads preserve the original Unicode identities.

Every `review_template` call supplies `expected_previous_review_id` (null for
the first review). Approval evidence also contains that exact `previousReviewId`.
The transaction rejects stale approvals arriving after a rejection or revocation;
intentional reapproval requires new evidence naming the observed negative review.

New staging and positive approval require evaluator `product-terms-engine-v8`.
The v8 local benchmark confirmation includes the actual opened `annualRate` as
an exact decimal fraction, equal to the approved template and instantiated
contract rate. Complete receipts without it are invalid. The shared schema
continues to read v7 templates and their original confirmation shape for
immutable historical replay; no retained template or receipt is upgraded.

The separate `actual-v8-bridge.json` fixture retains real adapter/evaluator v8
execution, including a confirmed-rate mismatch refusal. Both v7 and v8 fixtures
pass the producer benchmark gate and independent Decimal/calendar expectations.
Re-executing historical inputs with a newer runner identifies that newer runner;
it does not claim to reproduce an older execution identity byte for byte.

## Review integrity and retained implementation evidence

Approval snapshots bind the whole current product evidence projection, including
newly discovered documents and material revisions. Any inventory or coverage
change requires fresh review. Every disposition identity includes its observed
predecessor; the additive `executable_review_predecessors` table retains that
association without changing existing rows. Existing approvals made with the
older snapshot format fail current approval validation and require fresh review;
their original evidence remains available for retrospective inspection.

New benchmark admission compares the instantiated contract's rate, term,
rounding, fees, eligibility, applicability, source evidence and lifecycle with
the exact template. Complete scenarios also bind actual amount, dates and typed
scenario-owned facts. Refusal controls may deliberately mismatch amount or rate,
but cannot substitute a different source contract or arbitrary scenario events.

Code artifacts have exactly these manifest fields: `schemaVersion: 1`,
`role: adapter|evaluator`, exact `version`, `entrypoints`, `files`, `packageLock`,
`externalPackages`, and `scope: local_literal_import_closure_with_locked_external_metadata`.
Each file has exactly `path`, `sha256`, and `bytes`; each external package has
exactly `name` and `version`. Adapter entrypoint is
`mobile/src/data/executableContracts/instantiate.ts`; evaluator entrypoint is
`mobile/src/lib/productTermsEngine/ledger.ts`. Package lock path is
`mobile/package-lock.json`.

Every normalized relative path is unique; every referenced blob's length and
SHA-256 are verified. Literal relative imports, reexports and require calls must
resolve within the retained files. Dynamic expressions, including a quoted
prefix plus concatenation, are refused. External package names and versions must
match the retained lock. That metadata does **not** prove external runtime package
bytes or execution: controller execution records and independent review remain
trust authorities.

Limits are 256 files and 8 MiB source bytes per code artifact, eight artifacts
and 32 MiB per operation. Finalized captures allow four receipts and 32 MiB
combined receipt/contract bytes per operation, with at most 20,000 source members
each. Caches last only for the current operation. Both source generation and
contract digests are recomputed before caching. Present non-maturity interest
cadence is incompatible with this adapter.

The compressed technical code fixture retains the e181 historical local source
closure: 87 files plus a separate copy of every original bridge-listed artifact
with its exact recorded hash. Comparison harness files outside the single-deposit
entrypoint closure are retained as provenance, not claimed as runtime imports.
The closure includes the dependency lock. Additional files preserve Git blob
bytes and identify that representation explicitly. Original v7/v8 execution
fixtures remain unchanged. `legacy_descriptor_replay=True` is solely an explicit
retrospective benchmark-reader option; new approval never enables it.
