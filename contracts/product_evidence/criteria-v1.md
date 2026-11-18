# Optional comparable product criteria, version 1

The initial financial release retains its existing core and detail bytes. A
separate admitted enrichment retry may add `product_criteria_index` and
`product_criteria_shard_NNN` ordinary manifest files. They are part of the new
immutable bundle, complete publication inventory and asset readback. They are
excluded only from the comparison with the already published financial base.
No criteria error may block or roll back that initial financial publication.

## Wire and integrity

Index: `{schema_version:1,run_date,scope:product-filter-facets-v1,source:{generation_id,contract_digest},
products:{productKey:shardFileKey},coverage:{productsExpected,productsObserved,
complete:true}}`. Shards carry the same header and
`products:{productKey:{facts,sourceDocuments}}`.

The compact scope contains global product-filter facts: feature, eligibility,
constraint, fee, condition and bundle. Current rate/tier filtering uses existing
exact core rows; original rate/tier facts remain in the full lazy fact archive.
This avoids duplicate prices and unbounded full-evidence work on global filters.
Coverage concerns all captured database product routes, including products
without rates; it does not certify upstream population, semantic interpretation,
document acquisition or legal completeness. Missing facts remain unknown.

Preparation verifies the original contract-bound SQLite bytes before and after
read-only immutable access. The source is not migrated. Complete package readback
precedes the completion marker. Maximums: 20,000 products, 256 shards, 1 MiB gzip
per file, 4 MiB decoded per shard, 8 MiB decoded index, 16 MiB gzip and 32 MiB
decoded in aggregate. Exhaustion refuses optional preparation without truncation.

## Facts and sources

Existing conservative feature facts remain unchanged. Additional criteria retain
the existing fact fields plus `criteriaVersion:1`, `valueType`, `evidenceState`,
`sourcePath`, and `sourcePathBasis`. Decimal values/bounds are exact strings.
Source code, units, fee cadence, parent groups and condition text remain separate.
Scoped rates/tiers are conditional; a missing constraint value is unknown, never
an affirmative eligibility claim. The full source/fact archives remain available
for fields without a reviewed comparable projection.

New cleaning records an internal `_sourcePaths` entity map before empty-array
compaction. Its facts use `sourcePathBasis:raw-cdr`. Older exports without this
map use `cleaned-cdr`: matching that index to a raw document reference is forbidden.
Original immutable exports do not acquire retrospective pointer evidence.

Consumers require the exact selected generation/contract and every hash-bound
index/shard route before calling a whole-catalogue filter complete. Loading,
missing routes, conflicting values, unsupported units and conditional criteria
remain unknown. Documents need their own specificity/relevance/check evidence;
presence in this transport alone grants no legal applicability.

Document descriptors classify the preserved raw URI references before any
rediscovery of cleaned fields. Reviewed provider-adapter candidates supplement
them without claiming retrieval. When `AR_LOCAL_TERMS_ROOT` is configured, the
optional retry reads only the completed terms archive for the exact accepted
generation and export-contract digest; unrelated/newer products cannot supply
current document checks. No fetch, interpretation or writable evidence-store
initialization occurs during optional packaging. Corrupt optional archives fail
only that optional attempt. Captured availability is distinct from applicability.

Optional feature facts preserve the legacy ID and every semantic field. Only a
unique exact featureType match with an existing raw `_sourcePaths` entity
locator gains sourcePath/sourcePathBasis metadata. Repeated feature types and
legacy exports without the map remain unannotated. The primary detail asset
and its conservative feature-presence guards remain unchanged.

## Version 2 lossless wire encoding

Readers accept index/shard schema_version1 or2; writers emit2. Header source,
scope, coverage and raw product route keys retain the version1 meanings. Each
version2 shard additionally declares `keyTable` and `stringTable`. Only nested
product detail trees use dictionaries. Every object field name is replaced by
its keyTable index in canonical lowercase base36 (zero is `0`, no leading zeros).
A string beginning with `~` is escaped by one leading `~`; a beneficial repeated
string may instead be `~` followed by its canonical stringTable index. Table
entries are literal strings and are never interpreted recursively. Other values
and array ordering remain exact. No field or citation is dropped.

Tables are bounded to256 unique field names of at most256 UTF8 bytes and65536
unique string entries of at most8192 UTF8 bytes. Longer ordinary string values
remain untruncated literals within the existing wire budget. Object field names
`__proto__`, `prototype` and `constructor` are forbidden. Indices must be canonical
and in range. Decoding uses safe own objects, with depth at most64 and500000
value nodes per shard, counting its products root as depth0/node1. The complete
catalogue is bounded to4000000 value nodes. Pooled text is reused, not expanded
into a serialized JSON copy. Headers and dictionaries have their separate wire
budgets; string pooling never grants semantic authority.

The existing32MiB total decoded wire,16MiB compressed,4MiB per shard and1MiB
compressed-per-file limits remain unchanged. The writer encodes bounded logical
batches once and halves oversized encoded batches; ordinary encoded shards stay
below the512KiB write target, with whole large products still subject to the
4MiB hard bound. Verification reconstructs and validates every detail tree after
hash and source checks, then validates complete routing and aggregate budgets.
