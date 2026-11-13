# Unpublished current-fact snapshots, version 1

This offline format preserves the normalized fact table of one byte-verified
retained export. It is not a release manifest or authorization to publish, select
a generation, acquire documents, ingest, change a ledger, or activate a service.
No existing daily publisher, mobile reader, terms policy or encryption behavior
is changed by this module. Consumer delivery remains a separate implementation.

## Preparation and trust

```
python app_payload_product_evidence.py --database <retained-local-cdr.sqlite> --contract <original-export-contract-v2.json> --output <new-private-directory>
```

Python 3.11+ is required for SQLite limits. The original export contract must pass
its schema, generation and digest checks. Its single `local-cdr.sqlite` artifact
must match the database's exact bytes and SHA256. Nonempty WAL/rollback journals
are refused: supply verified committed bytes with their matching original
contract, never fabricate a replacement contract around arbitrary database bytes.
The connection uses `mode=ro&immutable=1`, query-only, a 2MiB cache, disabled mmap,
bounded SQLite rows and a cooperative deadline. The existing product index drives
streaming in product-key/fact-ID order with its existing primary-key index; no
complete export JSON, fact table or full-table sort is loaded into memory. Database
and contract identities/hashes are rechecked before completion. Symlink paths,
existing destinations and destinations overlapping source trees are refused.

Accepted database schemas 8 and 9 have identical fact columns; the exact columns
and `cdr-product-facts-2` normalization are checked. The broader export contract's
normalization version is a distinct field and can legitimately be `legacy-v1`.
Unknown schema/mapping/typed-value interpretations fail visibly rather than
silently losing evidence. Unknown original scalar fields already retained by
the supported normalizer keep their source values and paths.

## Snapshot shape

The authoritative machine contract is `app_payload_product_evidence_contract.py`.
Every object has an exact field set; JSON duplicate keys/nonfinite values are
rejected. Generation IDs use the canonical `obs-YYYY-MM-DD-<16 lowercase hex>`
contract format. `snapshot.json` is an atomically created, create-once completion
marker. Page files are flushed/fsynced before the marker; on POSIX, the output
directory is synced before and after marker linking and after temporary unlinking.
The existing portable directory-sync helper is a no-op on Windows. Sync errors
propagate. Failure before linking leaves no marker; failure after linking may
retain the complete marker/pages but is not a successful command result. Preserve
that evidence for verification; never overwrite or automatically delete attempts.

Top-level fields are `schema`, `source`, `scope`, `publication_authorized=false`,
`selection_verified=false`, `coverage=complete_for_bound_fact_table_only`,
`products` and `totals`. Source binds the generation, observation date/state,
contract/source-generation/file digests, both normalization versions and database
artifact bytes/hash. A contract's internally consistent hashes alone do not
prove committed-ledger membership or current selection: future publication must
apply the existing independent source/selection/admission checks.

Each product route retains dataset/provider/product ID, exact app product key and
name, total facts and ordered page descriptors. The app key includes name/category
and is not a timeless identity. No unproved provider aliases are introduced.
Pages use `facts-<compressed-sha256>.json.gz`; gzip metadata is deterministic across
platforms. Each page repeats source and product identity, a zero-based sequence,
and facts. Descriptors bind compressed/expanded byte counts, hash and fact count.

Facts retain ID/kind/canonical key, value type, unit, mapping, source path/pattern,
typed value, original source value, qualifiers and numeric range bounds. Redundant
SQLite typed columns are checked against `value_json` before projection; JSON
strings are decoded without conflating numeric strings with numbers. Numeric
normalization remains producer interpretation, distinguishable from original
source values. `canonical_text` is not independently reviewed applicability.

The scope explicitly excludes raw null/empty/envelope inventory: the underlying
normalizer omits these, and this snapshot does not reconstruct them. Raw CDR bodies
and journals remain authoritative. Complete fact-table accounting does not mean
complete providers/products, complete legal terms, accurate applicability, or
permission to infer product withdrawal. Source partial/failed state is retained.

`validate_snapshot` verifies all bounded pages and complete count/identity
accounting. `iter_product_facts` verifies manifest metadata and the selected
product's pages only; a missing route is unknown absence, not product removal.
Neither function authenticates a publication without an external trusted digest.

## Offline ceilings

`Limits` defaults are hard maxima; callers may reduce them but cannot enlarge
them: database4GiB; total raw evidence1GiB/compressed256MiB; page512KiB raw/1MiB
compressed and1,024 facts; index8MiB;20,000 products/pages;3,000,000 total facts;
50,000 facts/product;600 seconds per operation. Oversize individual facts,
products, pages, metadata, cumulative work or expired deadlines fail explicitly.
Database hashing counts actual streamed bytes and refuses growth past the cap,
rather than trusting only the initial file size.
No rows are dropped to satisfy a limit. Limits apply to this offline format only;
they neither raise existing mobile/release budgets nor establish Pi resource
qualification. Resource/size measurements must precede delivery layout selection.

## Next gate

Before any daily activation, integrate a reviewed lazy transport with immutable
bundle identity, full asset enumeration/upload/readback, selected-generation
fencing, backwards compatibility and a shipped matching app reader. Optional
terms projection remains independently opted in with its existing generation,
review, encryption and byte gates. Full product-change history and watchlist
alerts are subsequent work. This snapshot writer alone does not complete that
consumer feature or its rollout.
