# Draft v2 scoped eligibility: controller and migration freeze

**Review draft only.** Base 47a4117dbd960a37b99accf402961b617f7bcdcf. None of these
files is imported by the application, executed against SQLite, or published.
The initial v2 kind is `scoped_eligibility_v1`, capability `eligibility_only`,
adapter `scoped-eligibility-v1`, evaluator `product-terms-engine-v8`. Existing
TD/terms-v1 schema bytes and canonical fixtures are unchanged. Other monetary
family kinds require subsequent closed-schema and adapter additions.

## 1. Exact identities and scope

Use existing canonical UTF-8 JSON: ASCII property keys sorted, compact separators,
Unicode/string decimals retained, no trailing newline; bounded iterative preflight
before recursion. `subject.id = digest(subject without id)` includes `scopeId`.
`scopeId = digest(["executable-scope-v2", capability, scope])`. Scope includes
product, family, cohort, tier, package, full effective interval, assessment-date
meaning, product versus variant coverage, and the sorted unique rate-index set.
Source observation/core hashes are **not** slot identity: source changes append
another subject for the same semantic scope. Changing scope creates another slot.
Both slot IDs and canonical scope JSON are compared, never caller-accepted hashes.
Rate indexes are within-observation pointers, not persistent semantic variant IDs:
if indexes shift, the new observation has a new scope/subject and the old one cannot
resolve because every current lookup is observation-filtered. No cross-observation
slot equivalence is inferred from an ordinal. A same-scope successor is exact-slot
supersession; changed/overlapping intervals are distinct slots, never supersession.

There is one current subject per exact slot, selected by highest sequence; staging
requires its observed predecessor. Different exact scopes cannot be silently
ranked or fall back to one another. The first resolver requests a full exact scope;
product-wide/variant overlap or multiple matching scopes at an assessment date
cannot imply an automatically selected/combined approval without source-reviewed
precedence. Independently assess every distinct candidate with its own source/scope;
show the overlap and allow explicit candidate choice. Selection itself never proves
that the customer qualifies. Only implicit selection or merging is refused. "none" or
unrestricted scope requires source evidence; null, absent and arbitrary placeholders
are not admitted. Do not manufacture a rate index for product-wide eligibility.
Reserved keys `none_source_declared` (tier/package) and `all_source_declared`
(cohort) require affirmative clauses and matching independently reviewed revision
applicability. Missing/null revision scope cannot be replaced with those values.

`intervalBasis=reviewed_assessment_coverage` explicitly labels effectiveFrom and
effectiveToExclusive as the narrower interval this approval covers, **not** an
assertion of the bank policy's start/end date. Positive temporal review must show
the source/revision supports assessments throughout that interval; source-declared
limits contain it. An unstated source end never becomes a fabricated bank end or
unrestricted future coverage. Where only the captured as-of state is supported,
approval may cover only that observed assessment day (exclusive next-day endpoint
is the review coverage boundary, not a policy expiry). A wider interval needs
independent source support; unknown/mixed timestamp scope cannot be silently
treated as open-ended. Consumers label the approval coverage separately from any
bank-declared effective dates and preserve as-of-edition freshness semantics.

The closed `source` object binds original product-document bytes, finalized capture
generation/export contract, current observation, approved document/revision inventory,
provenance manifest, core asset and **details asset** hashes. Product occurrence is
`details.products[scope.productKey]`, whose canonical hash equals
`productRecordSha256`. There is no fictitious core product row. Product-wide scope
has empty rate sets; variant scope has exact real rows from the scope's family,
including core array index, canonical row hash and original rate_index. Sorted
rate indexes must equal the row set, with no duplicate positions/indexes. Product
coverage must be affirmatively established by the source/revisions; it is not
permission to apply one selected variant's restriction to every variant.

Family identifiers map through a fixed controller section map to actual core
sections; no user-controlled JSON path. Every bound row must match product/family
and the source-selected variant. Source and destination packaging independently
verify both adopted compressed core/details hashes and record hashes. The provenance
manifest is not required to equal the new destination manifest, avoiding a cycle.

## 2. Input/rule semantics and limits

Input keys are safe, unique and schema-bounded; labels/types/units/roles and all
rules require clause references. Each non-customer role is unique. Supported roles:

| Role | Required type/unit; authority |
|---|---|
| `scenario_amount` | decimal/AUD; selected actual amount |
| `assessment_date` | date/null unit; selected local assessment day |
| `scenario_purpose`, `scenario_security_type`, `scenario_ownership` | text/null unit; actual selected scenario fact |
| `scenario_security_value` | decimal/AUD; actual selected security valuation |
| `customer_fact` | reviewed primitive type/unit; scoped local customer fact |

Assessment date is mandatory and equals the request date inside the effective
interval. Other scenario roles are required exactly when referenced by rules;
they cannot be filled from editable profile answers. No derived LVR or financial
formula is introduced: a later derived-role adapter must bind source-supported
numerator/denominator semantics. A definition cannot disguise a scenario-owned
fact as a reusable customer answer; independent input-binding review checks this.
This prohibition includes amount, security value/type, purpose, ownership and
assessment date: none may fall back to profile answers when the selected scenario
is missing its value. Derived LVR is also prohibited as a `customer_fact` workaround.

Reuse AND/OR/NOT and typed comparisons, exact decimal/date rules and ordered
three-valued reasons/trace. Require references and rule expected types/units to
match definitions; safe unique rule IDs, depth <=16, nodes <=512. Reject unused
definitions except the required assessment-date role. Quotes and document/revision
inventories must match exact retained occurrences; every field reference is known.
Complete eligibility coverage concerns the declared scope only. It does not mean
credit approval or monetary completeness. Public subjects contain no account IDs,
answers, balances, private offers, dated obligations or instantiated scenarios.

Preserve 256 KiB subject, 32 current slots/product, 512 KiB asset/shard, 20,000
products and 24 MiB snapshot bounds plus existing aggregate transfer budgets.
Source core/details decoding is per-operation and shares a bounded byte/count
budget; adding details must not double an unbounded cache. No automatic budget
increase, truncation, quote omission or catch-and-skip approval.

## 3. One controller; two immutable storage adapters

Proposed public controller facade (existing TD APIs become compatibility wrappers):

* `lookup_subject(subject_id)` resolves exactly one row in
  `executable_registry_subjects`, then invokes that wire version's validator.
  A legacy TD row remains a legacy TD calculation subject; it is not re-approved
  or advertised as a separately reviewed eligibility capability.
* `stage_subject(subject, expected_previous_subject_id, interpreter, staged_at)`:
  bounded schema/hash/semantic checks, exact current source/revision validation,
  full-product evidence snapshot, then `BEGIN IMMEDIATE`, repeat source/predecessor
  checks and append scope/subject/term/document links. Existing identical subject
  returns only after byte equality; an old ID replay never becomes current again.
* `review_subject(subject_id, decision, reviewer, reviewer_kind,
  expected_previous_review_id, evidence_sha256, reviewed_at, reason)`:
  lookup the version, use one independent-actor/decision/CAS policy, and dispatch
  only the capability-specific semantic and benchmark checks. Human/deterministic
  reviewers must differ from interpreter and model second passes cannot approve.
  Positive approval requires the latest subject/source and a timestamp >= staging.
  Negative review remains possible after source changes and needs no positive
  source snapshot or benchmark. Its evidence must match decision, subject,
  predecessor and reason. The immutable review ID hashes all record fields and
  predecessor, so a stale positive result cannot append after revocation.
* `current_approval(subject_id)` reloads latest review and actual predecessor,
  current source/full product inventory and typed benchmark; it derives only the
  five eligibility checks in the v2 envelope. No staged verified flags and no
  fabricated fee/rate coverage. V1 retains its existing exact checks and output.
* `build_projection(product, wire_version, observation, core_sha, details_sha)`
  uses the DDL's current-observation/latest-slot query, LIMIT 33 as a rejection
  sentinel, then validates every selected approval. Historical slots do not count.
  A new unapproved staged successor blocks the older approved slot. Invalid current
  approvals fail the build; explicit negative reviews remove subjects. Empty v2
  subjects permits a reviewed-current-edition removal without legacy mutation.
* `publish_projection(..., expected_previous_publication_id,
  expected_observation_id)` repeats the build inside `BEGIN IMMEDIATE`, checks the
  exact preceding same-version publication and appends. V1's existing identity-CAS
  argument is preserved by its storage adapter. No cross-version sequence ordering
  or equality of publication identities is assumed.

Approval evidence binds subject, adapter/evaluator, source snapshot, exact benchmark,
predecessor and capability checks. Snapshot hashes subject + latest selected term
review IDs + complete current product projection identity + exact core/details
bindings. Changes to unselected relevant documents still change that projection.
Benchmark dispatch must bind actual scoped input, actual result and independent
expected trace/status/reasons; require meets, does-not-meet and needs-information
controls, a separate holdout and explicit scope/variant/input refusal. Bounded
retained source manifests use exact capability-selected adapter/evaluator entrypoints
(planned scoped eligibility adapter and existing eligibility.ts), verified local
bytes/literal dependency closure and locked external metadata. No caller-selected
entrypoint or arbitrary equal blob is execution proof. Actual execution capture
and independent semantic review retain their present authority boundary.

## 4. Additive DDL and transaction safety

`001_executable_registry_v2.sql` is the proposed SQLite extension. New subjects
reference scopes/observations; new reviews and same-subject predecessors have real
FKs; subject predecessors share a scope; publication predecessors share a product.
CAS triggers reject stale append attempts even inside raw INSERT paths. Shared
cross-version lookup views and collision triggers create one identity namespace.
Existing v1 tables, rows, IDs, FKs and schema files are not rewritten or backfilled.
The new physical tables are a storage adapter, not a second approval authority.

On eventual implementation, a named migration marker records the exact frozen DDL
digest once. Run checked-in DDL in one explicit migration transaction, then install
EvidenceStore's UPDATE/DELETE denial triggers on every added table, run foreign-key
checks and write the marker before commit. Failure rolls back the whole extension.
Do not set `PRAGMA user_version=2`: the current store's version 1 is independent of
wire version and rejects other values. No source archive is migrated. Existing
applications remain able to read v1; new v2 writers require the migrated controller.
Rollback means stop v2 writes/read v1; never delete appended approvals as rollback.

Before applying after freeze: exercise migration on an isolated representative
evidence-store fixture; compare old row canonical values/counts and original v1
file hashes, duplicate/foreign-subject predecessors, two-writer stale CAS, late
approval after revocation, identity collision, missing JSON members, interrupted
migration and query plans. No migration execution is part of this draft.

## 5. Descriptor and consumer compatibility

Use new `executable_v2_index` / `executable_v2_shard_NNN` manifest keys and closed
schema-version-2 index/shard/asset objects. Existing executable v1 descriptors,
TD context and terms-v1 bytes stay unchanged; mixed editions can carry both.
The existing old consumer iterates arbitrary valid file descriptors, but prove
acceptance against an actual retained old-consumer fixture rather than assume it.
It must keep TD behavior and ignore the new capability, never parse v2 as v1.

The new consumer requires the adopted manifest's core/details/index identities.
`detailsIdentity.ts` exposes `verifiedDetailsSha(parsedObject)` via its WeakMap;
that must equal the adopted details descriptor and the product canonical hash
must match the subject. Arbitrary parsed/profile objects cannot mint authority.
The existing TD context remains v1 and does not suddenly require details.
Both producer and consumer asset validators require approval.subjectId to equal
the contained subject.id and approval capability to equal subject capability.
Every subject's product, observation, generation, runDate, core and details
identities must equal the enclosing asset; the product key must also equal its
index/shard map key. Recompute each subject ID and scope ID, and reject duplicate
subject IDs OR scope IDs within an asset even when other bytes differ. JSON
uniqueItems is not a substitute for these explicit semantic checks. Resolve all
schema references through the bundled closed registry, with no ambient network
resolution; enforce calendar formats and bounds in both language validators.
New current eligibility requires the latest adopted edition and exact capability
approval. Replacement/removal invalidates dependent current handles; offline
retained receipts are dated prior-edition evidence, not current revocation claims.
Future monetary variants may reference exact v2 eligibility subjects only through
an explicit dependency schema and transitive current-approval validation.
