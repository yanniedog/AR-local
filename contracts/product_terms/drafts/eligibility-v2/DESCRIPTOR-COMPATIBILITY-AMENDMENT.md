# Proposed descriptor amendment — pending root freeze

Supersedes section 5's placement of v2 descriptors in manifest.files, not the
frozen subject/asset/index/shard bodies or DDL. Actual shipped app eeb20f1021a268ec34a7690c53ba58c7eec0182a
eagerly fetches every manifest.files member, including unknown keys. No descriptor
packaging/publication wiring will be implemented until this amendment is approved.

Place the closed `executable-namespace-v2.schema.json` object at optional top-level
`manifest.executable_v2`: `{schema_version:2,index:{name,bytes,sha256},shards:{
executable_v2_shard_NNN:{name,bytes,sha256}}}`. Do not add any v2 entry to `files`.
The index body's existing product-to-shard keys resolve against this namespace's
shards. Subject/asset/index/shard bodies and their existing source bindings stay
byte-compatible with the previous freeze.

Descriptors are URL-free. New consumers derive the exact immutable release URL
from the adopted trusted repository + manifest.tag + validated basename; reject
v2 on a manifest without a valid immutable payload_revision. No rolling alias,
arbitrary descriptor URL, path segment, query, encoded traversal or cross-release
fallback is permitted. Name kind/date/hash prefix must agree with its namespace
key, adopted run_date and descriptor SHA. Names must be globally unique across
legacy files and this namespace. Missing/corrupt v2 data affects only a requested
v2 capability; it cannot prevent core adoption or alter legacy TD execution.

The existing bundle_sha256 hashes arbitrary top-level fields and therefore binds
this complete namespace. With no URLs here, archive retagging adds no URL cycle
and requires no additional hash normalization. When the namespace is absent,
the exact old canonical manifest/bundle hashing and packaging paths stay unchanged.
Do not insert an empty namespace into every existing build.

Implement one producer iterator yielding descriptor key/name/size/hash plus a
derived same-release URL for optional v2 entries. Use it in revision validation,
source download, archive copying, release upload/readback, recovery verification
and aggregate network budgets (`app_payload_revisions_state.py`,
`app_payload_revisions.py`, `app_payload_revisions_github.py`,
`app_payload_publish.py`, `app_payload_network_budget.py`). Existing legacy entries
retain their exact URL semantics. V2 bytes count toward the same aggregate budgets,
including descriptor count and expanded JSON limits; no per-namespace reset.
The namespace permits one index and at most 999 shards, each at most 512 KiB
compressed; these are ceilings, not a promised feasible catalogue. The existing
64 KiB complete manifest and 8 MiB all-declared-transfer limits still apply.
The v2 24 MiB expanded snapshot limit remains additional to existing operation
limits. Empty shards are allowed only as an empty map for an empty index;
every declared shard must be referenced and every index reference must resolve.
Continue existing source observation/core/details CAS and immutable publication
guards, manifest-last promotion, symlink/traversal refusal and content hashes.

Before integration, a retained actual shipped-reader compatibility check
must show: top-level namespace accepted; unavailable v2 index/shard triggers no
old-reader request; old core/TD adoption succeeds; no-namespace bundle identity
unchanged. New-reader checks cover explicit lazy fetch, exact tag/name/hash/bytes,
wrong source core/details, missing namespace, corrupt shard, removal/new edition
invalidation and aggregate budgets. This is a compatibility route, not an assumed
mandatory app upgrade and not authorization to populate or publish a product.

The compatibility fixture will extract the exact shipped commit's manifest
validator and refresh dependency closure without editing that checkout, retain
its source commit/file hashes, and run its actual refresh path with bounded
technical transport responses. The request recorder must show zero namespace
asset requests even when those names would return errors. A paired files-member
control must demonstrate the original eager-download behavior, so merely testing
an unrelated parser cannot satisfy compatibility. Synthetic records are protocol
tests only and confer no source or business acceptance.
