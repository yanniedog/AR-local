# Documented product-index request routes

Bank of Melbourne and St.George document their public product-index endpoints
with a terminal slash:

- https://www.bankofmelbourne.com.au/online-services/open-banking/product-api
- https://www.stgeorge.com.au/online-services/open-banking/product-api

Their register entries provide bare hosts. Register normalization continues to
produce the existing endpoint identity, preserving derived provider UIDs and
population-hold bindings. `product_index_request_url` applies the documented
slash only to HTTPS requests for the exact `/cds-au/v1/banking/products` path
(with or without its terminal slash) on those two hosts. When no query is
present, it adds `page=1&page-size=100` for Melbourne and
`page=1&page-size=1000` for St.George. Explicit query parameters, including
pagination and filters, are preserved. Other hosts, detail paths,
credentials/ports and general URL normalization are unchanged.

Initial ingest and same-day recovery use this request route. Subsequent ingest
pages follow the provider's validated next link. Reuse verification binds the
first journaled request to the same route and explicit default query. The
same-day selection verifier uses that binding too, while retaining acceptance
of the exact registered endpoint for legacy captured proofs and Melbourne
proofs captured with the former `page=1&page-size=1000` default. Both continue to
require the exact subsequent pagination chain. This does not relax holder identity,
pagination, detail-body, source-integrity or publication gates.

Index version negotiation remains `[6, 5, 4, 3, 2, 1]`, independently of detail
versions. A supported v5 response is reused as the holder's preference for the
remaining pages; v5 is not an unconditional version lock.

The retained November 4 first-page fixtures were collected at approximately
22:18 UTC on November 3 using the documented slash route and x-v5. Each contains
25 products; declared totals are 40 for Melbourne and 42 for St.George, across
two pages each. They prove successful first-page responses, not a completed
capture. An earlier unslashed Melbourne request returned an empty page about
22 minutes earlier. This was not a simultaneous comparison, so timing is not
excluded as a contributing factor. No prior failure receipt is reclassified.

At approximately 01:29 UTC on November 4, a fresh collection using default
pagination retained 25 detail responses for each bank but failed to complete
the indexes: Melbourne page 2 returned HTTP 422 `InvalidPage`, while St.George
page 2 returned HTTP 200 with repeated product IDs. Those failed responses and
the partial collection remain evidence, not a completed catalogue.

At approximately 01:39 UTC, the separate supervised `coverage-20261104-tick05`
probe used the same registered hosts and official slash routes with explicit
`page=1&page-size=1000` and x-v5. Melbourne returned 40 unique IDs matching
40 declared records; St.George returned 42 unique IDs matching 42 records.
Each declared one page and had no next link. The new fixtures retain these
original bodies and the fresh register, bound by SHA256 in `provenance.json`.
This establishes index membership for those responses. It does not establish
complete product details, rates, successor selection, or publication.

Tests verify the documented route/default query, unchanged identity, version fallback,
explicit-query preservation, seeded-detail reuse, complete single-page counts,
incomplete-page failure and real journal-to-contract selection binding. Deployment,
complete live capture, successor selection and publication require their own
verified runtime results.

At 02:30 UTC, a later Melbourne request with the same page-size 1000 and x-v5
returned HTTP 422 `InvalidPage`; its subsequent x-v4 response was HTTP 406.
At 03:00 UTC, a separate page-size 100, x-v5 probe returned 40 unique products,
40 declared records, one page and no next link. Its IDs match the earlier
1000 response. These separately timed observations do not establish page size
as the sole cause. The default now uses the observed 100 for Melbourne only;
St.George retains 1000. No automatic size fallback or extra request budget is
introduced. Explicit 1000 requests and all failure evidence remain unchanged.

The added `cdr-bom-page100-2026-11-04` fixtures preserve the successful 100 body
and both later 1000 error bodies with their original journal events and byte
hashes. Offline replays test membership, retained failure classification and
attempt limits; they are not a new live capture or publication acceptance.
