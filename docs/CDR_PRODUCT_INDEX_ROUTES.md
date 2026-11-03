# Documented product-index request routes

Bank of Melbourne and St.George document their public product-index endpoints
with a terminal slash:

- https://www.bankofmelbourne.com.au/online-services/open-banking/product-api
- https://www.stgeorge.com.au/online-services/open-banking/product-api

Their register entries provide bare hosts. Register normalization continues to
produce the existing endpoint identity, preserving derived provider UIDs and
population-hold bindings. `product_index_request_url` applies the documented
slash only to HTTPS requests for the exact `/cds-au/v1/banking/products` path
on those two hosts. Query parameters are preserved. Other hosts, detail paths,
credentials/ports and general URL normalization are unchanged.

Initial ingest and same-day recovery use this request route. Subsequent ingest
pages follow the provider's validated next link. Reuse verification binds the
first journaled request to the same documented route and continues to require
the exact subsequent pagination chain. It does not relax holder identity,
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

Tests verify the documented route, unchanged identity, version fallback,
pagination, seeded-detail reuse and incomplete-page failure. Deployment,
complete live capture, successor selection and publication require their own
verified runtime results.
