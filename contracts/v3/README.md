# AustralianRates payload v3 contracts

This directory is the additive, dormant producer boundary for AR-app. It does
not replace the deployed v1 rolling manifest and deliberately does not reuse
the retired `manifest-v2` name.

The schemas use JSON Schema Draft 2020-12. `generation-pointer-v3` carries two
independent immutable heads: the newest finalized observation and the newest
finalized complete observation. A generation manifest binds its ledger ancestry,
reconciled coverage, normalization version, producer commit, and
content-addressed capability assets. `canonical-core-v3` carries stable identity,
typed rates, classification status, eligibility, fee evidence, and source hashes.

Normative invariants that cannot be expressed completely in JSON Schema are
enforced by `cdr_domain.contract_validation`:

- provider and product populations reconcile exactly;
- product exclusions plus eligible products equal discovered products;
- authoritative coverage has complete failure provenance and no corrupt failure
  records;
- a complete observation proves every configured register source was attempted
  and completed;
- the latest observation cannot predate the latest complete generation;
- same-date pointer heads cannot regress their immutable revision number;
- generation IDs bind the observation date, revision, and first 12 hex digits
  of `generation_digest`;
- `generation_digest` is SHA-256 of canonical JSON (UTF-8, sorted keys, compact
  separators, no NaN) after omitting only `generation_id` and
  `generation_digest`;
- pointer heads separately bind the SHA-256 of the serialized generation
  manifest bytes as `manifest_sha256`;
- every identity capability URL is exactly `app-payload-gen/<sha256>.json`, every
  gzip capability URL is exactly `app-payload-gen/<sha256>.json.gz`, and every
  pointer/index manifest URL is exactly
  `app-payload-v3-candidate-<generation_id>/<manifest_sha256>.json` on the
  canonical AR-local GitHub release origin;
- identity-encoded assets have identical compressed and uncompressed byte counts;
- the rolling pointer carries the exact producer contract-set SHA-256.

`contract-lock.json` records that deterministic schema-set digest. Any schema
change must intentionally update the lock and the vendored AR-app validator
before activation. Promotion also requires an explicit reviewed producer/app
contract-parity tuple in `app_payload_v3_github.py`. That tuple is intentionally
unset: the current AR-local pointer uses `contract_sha256`,
`generation_revision`, and `observation_date`, while the frozen AR-app v3 reader
expects its own `schema_id`, `run_date`, and `manifest_bytes` shape. Therefore
even a correctly authorized `--execute` fails before remote access. Contract
convergence and exact SHA-256 pins for both reviewed schema sets are separate
activation prerequisites; this promoter must never publish bytes the app rejects.

Only the `core` capability is negotiable in this first dormant contract slice.
The descriptor schema reserves the approved size ceilings for later
capabilities, but runtime generation validation rejects those capabilities until
their payload schemas and golden fixtures are added. This prevents a producer
or consumer from treating a familiar capability name as a validated payload.

JSON Schema validation is necessary but not sufficient for a core asset. Every
producer and consumer must also run the version-locked semantic validator whose
reference implementation is `cdr_domain.validate.validate_canonical_product`.
That validator recomputes product/rate/fee/evidence identities, checks evidence
references and lineage timestamps, enforces fee method exclusivity and numeric
range ordering, and applies the metric/unit/basis magnitude contract. An asset
is unsupported—not partially trusted—when that semantic validator version is
unavailable.

Pointer installation is one combined operation: validate the exact manifest
bytes named by each head, match their byte SHA-256 and semantic generation
fields, then compare the candidate against the exact prior pointer bytes and
expected prior SHA-256. The pure validator proves the transition; the promoter
must still perform the repository-side compare-and-swap immediately before it
replaces the rolling pointer.

All numeric financial values are canonical decimal strings. Product rates are
fractions per annum, RBA rates are percentage points, changes are basis points,
and fee percentages are fractions of the charged amount. Unknown values remain
null or explicitly unknown; they are never inferred as zero.

## Dormant local candidate builder

`app_payload_v3.py` builds one deterministic, unpublished candidate from a
local canonical-entity document and local generation metadata:

```sh
python app_payload_v3.py \
  --entities <canonical-entities.json> \
  --metadata <generation-metadata.json> \
  --output-root <local-candidate-directory>
```

The builder filters the core to confirmed public products with visible rates,
requires those entities to match exact per-provider discovery counts, and
derives CoverageV2 from explicit provider/register states. It emits deterministic
gzip bytes, binds their exact size and SHA-256 into the immutable generation
manifest, then atomically installs a create-once local directory. Identical
inputs produce identical asset, manifest, and generation bytes.

The entity file must validate as `canonical-core-v3.schema.json`; before the
consumer filter runs it may contain confirmed, quarantined, restricted, closed,
or unpriced canonical products. The metadata object has these exact fields:

- generation identity: `observation_date`, `observed_at`,
  `observation_state`, `generation_revision`, `normalization_version`, and the
  40-hex `producer_commit`;
- finalized ledger binding: nullable `prior_ledger_digest` and 64-hex
  `ledger_event_digest`;
- run coverage: `provider_states`, `products_discovered_by_provider`,
  `register_source_states`, `failure_records_by_provider`, and optional
  `corrupt_failure_records` (default zero).

Provider states are `complete`, `empty`, `partial`, `failed`, or
`not_attempted`; register states are `complete`, `failed`, or `not_attempted`.
Every registered provider must have an exact non-negative discovery count,
and failure-record keys must identify every and only failed provider. The
builder fails closed if entity counts, failure provenance, dates, schemas,
asset limits, or complete-observation coverage do not reconcile.

The installed directory is `<output-root>/<generation_id>/`. It contains only
`<core_sha256>.json.gz` and `<manifest_sha256>.json`; an exact rebuild is
idempotent, while any existing byte mismatch or symbolic-link target is fatal.

This command never performs network I/O, uploads a release, creates or updates a
generation pointer, or changes the v1 rolling payload. Candidate publication is
a separate, dormant operation implemented by `app_payload_v3_promotion.py`.

## Dormant transactional promotion

The promoter validates a local candidate by default and performs no remote
writes unless `--execute` is supplied explicitly. The manual-only
`app-payload-v3-promote.yml` workflow repeats that validation, requires its
boolean execute input, the protected `app-payload-v3-promotion` environment,
and a separately configured environment-scoped approval secret before the
write-capable job can run. The workflow has no push or schedule trigger. This
repository does not configure or dispatch that environment as part of this
dormant contract slice.

Activation is also deliberately blocked until a separate candidate-artifact
producer workflow is reviewed and added at the allowlisted path
`.github/workflows/app-payload-v3-candidate.yml`. That workflow does not exist
in this slice. Before downloading any artifact, the promoter requires a
completed-success run of that exact workflow in `yanniedog/AR-local`, a
canonical head repository, a currently protected `main` branch, and a run head
retained in main's history. The verified run head SHA must exactly equal the
candidate manifest's `producer_commit`; direct `--execute` calls without that
binding and the canonical candidate run ID fail before acquiring the promotion
lock. The CLI independently re-queries that run and requires its verified head
SHA to equal the explicit expected commit; it does not trust the SHA argument
alone. Arbitrary same-repository workflow artifacts are never accepted as
provenance. Both workflow jobs check out the immutable dispatch SHA, so waiting
for protected-environment approval cannot substitute a later `main` tip.

Direct execution is additionally blocked by the intentionally unset
`app_payload_v3_state.CANDIDATE_ARTIFACT_BINDING_CONTRACT`. Its future
activation requires a reviewed
canonical artifact name/workflow, the GitHub-provided archive SHA-256, and a
hash-bound inventory contract that proves the expanded candidate tree came from
those exact archive bytes. The current code deliberately has no boolean escape
hatch: assigning a contract still fails until archive-to-tree verification is
implemented. Matching only `producer_commit` to a successful run is not accepted
as evidence that a caller-supplied candidate directory came from that run.

Execution is independently blocked by the structured, intentionally unset
`CANDIDATE_PUBLICATION_STORE_CONTRACT`, and the write-capable workflow stops
before provenance lookup or candidate download. AR-local's release immutability
is disabled because mutable v1 releases remain a compatibility requirement, so
the same-repository draft/upload path cannot close a publish-between-read-and-
write race. Merely assigning the contract does not enable execution: a separate
review must implement live verification of either a dedicated immutable v3
store/repository or a Git content-addressed commit/branch publication design.

An executed promotion uses create-once candidate tags and content-addressed
release assets. It acquires a two-hour owner-token lease on a dedicated
append-only Git branch; the workflow's one-hour timeout cannot outlive it. An
unexpired owner cannot be displaced. A crashed writer's expired lease can be
 recovered only by non-force compare-and-swap from the exact observed lock head,
 and the successor document records the displaced owner token. A stale owner can
 therefore neither release nor overwrite its successor. The owner renews that
 exact-head lease before draft creation, every asset upload, publication, each
 prepared control commit, and the final control compare-and-swap. Every GitHub
 command is bounded to 60 seconds, and indeterminate release-write outcomes are
 reconciled from exact remote state before retry or failure.

The release adapter below is retained only as dormant integration scaffolding;
it is not a safe activation target in the current mutable release store. Before
creating a tag or draft, the promoter verifies the published census plus
the local candidate as one prospective ordered ledger. A prior exact invoked
draft may be resumed; any unrelated or ambiguous draft fails closed. Candidate
assets are uploaded to that exact draft, checked by size and GitHub SHA-256,
published last, then publicly re-downloaded. A failed draft is retained for an
exact retry or operator inspection and is never deleted. An already-published
candidate must have the exact immutable asset inventory and bytes; the promoter
never appends to it.

The current golden builder still emits capability URLs under the already-
published shared `app-payload-gen` tag. Promotion treats those assets as
verify-only: every referenced name and byte must already exist, and no missing
asset is appended. Before activation, the separately reviewed candidate builder
and converged contract must instead bind newly produced capabilities to the
candidate-owned release so they can be staged in its draft and published
together. The current golden builder is not silently repurposed by this slice.

The promoter re-downloads and semantically validates every referenced manifest
and capability byte, then revalidates every censused release as non-draft,
non-prerelease, with exact create-once title/notes and a direct tag target equal
to that manifest's `producer_commit`. It fails closed if the complete
candidate-release listing or any historical release provenance is missing,
malformed, duplicated, moved, or otherwise uncertain. Ledger order is derived
from ancestry, independently of observation coordinates: exactly one generation
has a null prior, every other generation names the unique preceding event, and
the full chain cannot branch, repeat, disconnect, self-loop, or cycle. Same-date
revisions are append-only: one date/revision coordinate cannot be rebound to
different generation bytes, and the complete-dates index selects the greatest
verified complete revision for each date. Both pointer heads are derived from the full
verified lineage census, not merely the candidate named by the invocation, so a
retry after an interrupted upload cannot publish an older head.

The complete census reuses the paginated release metadata/assets response and
one batched matching-tag-ref response. It therefore preserves direct tag-target
revalidation while keeping authenticated API request count constant rather than
performing several API calls per retained candidate; the public manifest and
capability bytes themselves are still re-downloaded and checked.

Control state lives in append-only commits on `app-payload-v3-control`. The
`complete-dates-index-v3.json` commit is prepared and publicly re-verified
first; the `generation-pointer-v3.json` commit is prepared as its child and
verified last. One non-force ref compare-and-swap then exposes both commits
atomically from the exact expected parent and prior pointer bytes. Concurrent
or stale writers fail without exposing a half-published index. A listing or
pre-CAS verification failure leaves both prior control files intact. The
promoter never deletes, prunes, force-updates, or overwrites an existing release
asset, and it does not modify the deployed v1 payload.
