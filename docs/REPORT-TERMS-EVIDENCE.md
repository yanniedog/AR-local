# Optional report evidence v1

The baseline product report remains unchanged without `--terms-evidence`.
Produce a separate immutable local attachment, then admit it into a new report:

```sh
python cdr_report_terms.py --bundle SELECTED_BUNDLE --store EXISTING_TERMS_STORE --output NEW_EVIDENCE
python cdr_product_report.py --bundle SELECTED_BUNDLE --output NEW_REPORT --terms-evidence NEW_EVIDENCE
```

The exporter opens an existing SQLite database with `mode=ro`, `query_only`, and
one read transaction. It does not construct EvidenceStore, migrate, collect,
activate or publish. The selected finalized capture and retained export contract
must match the manifest's generation, contract and date. Historical queries use
that exact generation; a current observation is never substituted. Missing
capture/observation yields unavailable; malformed or contradictory evidence fails.

`seal.json` binds the exact `evidence.json` bytes. The latter binds manifest,
edition (or explicitly legacy exact manifest), core/details, source generation,
export contract, and complete selected product-key inventory. Snapshot row/blob
identities and exporter source hashes record the read operation. The seal is an
integrity check, not a signature or bank acceptance credential.

All evidence defaults to `unclassified`; `--technical` can only downgrade it.
This version has no bank acceptance promotion path. Bank-approved counts and
unknown legal/material denominators remain null. Recorded private review is
neither currently revalidated approval nor proof of delivery. Delivered scopes
come only from separately verified assets in the exact selected bundle. Mortgage
and Savings both use wire 3 with closed capability dispatch; benchmark wire 4
does not imply a registry schema version 4. Future registry versions are explicit
unavailable records.

Each reported product includes document-reference identities, separate latest
fetch status and retained successful version, extraction identities, graph nodes
and edges, term/review dispositions, recorded executable scope/publication
inventory, and delivered scopes. Free-form source paths/context and raw
applicability/coverage metadata are omitted; metadata hashes preserve identity.
No customer scenario inputs are queried. Capture, extraction, graph,
interpretation, review, executable review and delivery have separate inventory
bases. A recorded extraction is not complete extraction; a delivered scope is
not all required scopes. Known-reference counts do not establish a complete
official document inventory.

Admission validates closed nested structures and recomputes inventory counts.
JSON, CSV and HTML use the same admitted rows; formula escaping applies only to
CSV rendering, and HTML creates text nodes. Evidence and report output use
separate temporary directories and rename only after successful admission.
Existing output directories are refused.

## Resource bounds

These are independent named operation limits, not a peak-memory guarantee:

- Existing baseline bundle reader: 16 MiB per encoded asset, 96 MiB per decoded
  asset, with its existing manifest limits.
- Optional executable namespace: 24 MiB total encoded bytes and 24 MiB total
  actual inflated bytes, including whitespace, across all routes.
- Store verification I/O: existing 512 MiB total processed bytes and 16 MiB per
  blob. Source, document, extraction and review blobs are hashed in 64 KiB chunks;
  no raw blob cache is retained. Every reread is verified and counted. Only
  finalized capture/contract JSON is materialized (16 MiB each, existing 32 MiB
  combined capture bound), then released by the parser. These byte bounds do
  not bound Python object/JSON-parser overhead or total process peak memory.
- Store rows: separate 24 MiB cumulative fetched row JSON bytes, 1 MiB SQLite
  row/value limit, 4,096 rows per query, 100,000 rows and 10 million SQLite VM
  instructions per operation. Queries are parameterized and identifiers fixed.
  Snapshot receipts distinguish processed I/O, row bytes, largest requested read,
  largest materialized blob, and zero retained raw-cache bytes. Large real stores
  can still exceed these limits; technical tests do not prove actual corpus fit.
- Attachment: 24 MiB, 20,000 selected products, closed per-product collections
  bounded to 4,096 entries. Seal: 4 KiB.

Technical controls cover absent-input preservation, exact historical selection,
failed-fetch/prior-success separation, manifest/core/details/generation mismatch,
provenance downgrade and nested tampering, populated TD and retained Savings and
Mortgage assets, mixed registry capabilities, interrupted/oversized admission,
shared budgets and concurrent append isolation. They are engineering proof;
real-store binding and bank acceptance remain separate evidence requirements.
