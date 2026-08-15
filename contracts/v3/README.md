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
- every asset and manifest URL uses the canonical AR-local GitHub release
  origin and contains its declared byte SHA-256;
- identity-encoded assets have identical compressed and uncompressed byte counts;
- the rolling pointer carries the exact producer contract-set SHA-256.

`contract-lock.json` records that deterministic schema-set digest. Any schema
change must intentionally update the lock and the vendored AR-app validator
before activation.

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
