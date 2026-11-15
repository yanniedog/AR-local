# Unpublished current-fact snapshots (`ar-product-fact-snapshot-v1`)

Offline snapshot of normalized facts from one byte-verified retained `local-cdr.sqlite` export. Not a release manifest, publication authorization, or terms projection.

## CLI

```sh
python app_payload_product_evidence.py --database <local-cdr.sqlite> --contract <export-contract-v2.json> --output <new-private-dir>
```

Requires Python 3.11+ (`sqlite3.Connection.setlimit`).

## Trust & Source Binding

| Check | Requirement |
|---|---|
| Source files | Regular files; no symlinks; non-empty WAL/rollback journals refused |
| Contract & DB | `contract_digest`, `source_generation_digest`, `contract_file_sha256`, `database.sha256`, and `database.bytes` must match before and after read |
| SQLite mode | `mode=ro&immutable=1`, `query_only=ON`, `cache_size=-2048`, `mmap_size=0`, cooperative deadline |
| Schema & index | `schema_meta.version` in `{8, 9, 10}`, `normalization_version = cdr-product-facts-2`, exact columns, `sqlite_autoindex_bank_product_facts_1` (`BINARY`, `ASC`, no temp B-tree sort) |
| Destination | New private directory (`0700`/`0600` on POSIX), non-overlapping, parent/output fsynced around atomic `snapshot.json` link |

## Snapshot Format (`app_payload_product_evidence_contract.py`)

| Object | Required Fields / Rules |
|---|---|
| Manifest (`snapshot.json`) | `schema`, `source`, `scope`, `publication_authorized=false`, `selection_verified=false`, `coverage=complete_for_bound_fact_table_only`, `products`, `totals` |
| Page (`facts-<sha256>.json.gz`) | Deterministic gzip (`mtime=0`), `schema`, `source`, `product`, `sequence` (0-based), `facts` |
| Fact | `fact_id` (`[0-9a-f]{20}`), `kind` (`attribute`, `bundle`, `condition`, `constraint`, `eligibility`, `feature`, `fee`, `rate`, `tier`), `canonical_key`, `value_type`, `unit`, `mapping`, `source_path`, `source_pattern`, `value`, `source_value`, `qualifiers`, `min_value <= max_value` |

## Default `Limits` (Hard Maxima)

| Limit | Default |
|---|---|
| `database_bytes` | 4 GiB |
| `raw_bytes` / `compressed_bytes` | 1 GiB / 256 MiB |
| `page_raw_bytes` / `page_compressed_bytes` | 512 KiB / 1 MiB |
| `index_bytes` | 8 MiB |
| `page_rows` / `products` / `pages` | 1,024 / 20,000 / 20,000 |
| `facts` / `product_facts` | 3,000,000 / 50,000 |
| `seconds` | 600 |
