# Product document discovery and classification

Every configured `capture_finalized` records an immutable `product_document_discovery`
obligation for each retained product before enqueueing the existing acquisition
requests. Repeating a generation is idempotent; a new generation receives new
checks even when the bank's product bytes are unchanged. The hook performs no
network, parsing, model calls or publication. It cannot enable a worker.

Declared CDR references retain their original pointers. If references are absent
or all are provider navigation/collections, discovery adds a bounded same-origin
`sitemap.xml` task from the declared host or explicit website field. No domain is
invented from a provider name, and a CDR API endpoint does not establish the public
website. Reviewed exact-provider/product adapters provide additional candidates;
the initial adapter uses the actual Up Home booklet page and direct PDF. Its
2026-11-18 link capture is retained as a short verbatim anchor plus source/hash
metadata, without distributing the bank's full document.

The existing supervised acquisition queue, accepted leases, conditional checks,
per-host throttling, DNS/IP protection, graph host grants and production-priority
controls govern all requests. XML sitemaps produce at most 256 retained links;
additional links and graph frontiers remain explicit unresolved work. Neither a
queue entry nor a successful response proves exhaustive discovery or legal scope.
Products with no authoritative seed remain `missing-official-source`.

`cdr_terms.product_documents.describe_references(record, product_key=...)` returns
legacy reference fields plus `productKey`, `documentType`, `specificity`,
`relevance`, `verification`, `checkedAt`, `effectiveFrom`, `effectiveTo` and
`citations`. Specificity is a navigation classification; even an exact name match
is a candidate, not independently reviewed applicability. Provider roots are
background/navigation, never verified document evidence. Shared/general terms
are kept separately and never labelled exclusive to one product.

`cdr_terms.document_discovery_queue.discovery_inventory(store, product_key)` adds
only current source-bound acquired roots and their valid graph children, with
accepted check times, media type and content/version hashes. Successful retrieval
changes `verification` to `captured`; it does not change candidate relevance to
verified applicability. Raw pointers and graph edge identities remain available.
Existing reviewed terms and page-qualified clause locators remain the authority
for legal interpretation; no new automatic interpretation approval is introduced.

Current limitations remain explicit: unresolved providers need additional verified
adapters, graph limits do not establish full-catalogue closure, scanned pages need
separately qualified OCR, and current documents cannot supply historical terms.
This source change does not commission Pi workers, deliver public optional assets,
relax financial publication gates, or resume Drive writes. Root's separate optional
delivery integration owns the non-blocking release boundary and consumer adoption.


`describe_product_sources(record, product_key, provider)` also exposes reviewed
adapter candidates in current payloads, with `origin=reviewed-provider-adapter`
and `verification=discovery-candidate`. It never mislabels that adapter location
as a raw CDR pointer, a completed fetch or verified applicability.

`publication_document_inventory(evidence_root, generation_id, product_keys,
expected_contract_digest=...)` opens SQLite in `mode=ro` and query-only mode; it
never calls the writable store initializer or applies a migration. It verifies
the complete capture receipt and each current product's original hash/observation,
then checks retained document bytes. Missing/noncurrent sources return empty
lists. Present corrupt or ambiguous evidence fails only the optional operation.
Shared PDFs are hash-verified once per operation with a file-signature recheck on
every use, without retaining the full PDF corpus in memory. Limits remain 60s,
16MiB/blob, 512MiB verification work, 256 scoped descriptors/product and 50,000
scoped descriptors/operation. Excess is an explicit optional failure, not silent
truncation or permission to expand mobile budgets.

A repeated pre-upgrade completed capture can reconcile absent obligations from
its verified retained bytes without rewriting its old receipt. The new obligation
and acquisition request use today's actual reconciliation timestamp, while the
source observation retains its original date. No historical capture is redated.
