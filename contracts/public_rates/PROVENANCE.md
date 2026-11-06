# Public source clocks and verification boundaries

This is a provenance inventory and a dormant consumer-contract boundary. It
creates no wire capability, source check, schedule, activation or publication.
Collection/publication flags remain absent and the reviewed programme list empty.
The natural-shadow, independent reproduction, compatible release/native journeys
and operator/canary requirements in [ROLLOUT.md](ROLLOUT.md) remain mandatory.

## What the retained clocks establish

| Evidence | Scope and meaning | Does not establish |
| --- | --- | --- |
| Original product response bytes and SHA-256 | The retained product detail and its exact source representation | A successful check at its filesystem modification time |
| Raw attempt event `response.completed_at` | The completion of that particular network attempt; provider, product, phase, URL, status, body identity and successful parsing still require validation | A complete bank check or a successful response merely because the attempt ended |
| Product-index pages and pagination/accounting receipts | The observed product-list population for the bounded request scope | Fresh detail, rate or fee verification for each listed product |
| Lender `lastUpdated`, `effectiveFrom` and `effectiveTo` | Source-authored change/effective dates, with their original meaning retained | When AR-local successfully verified the source |
| Export contract `observed_at`, run date and generation | The finalized source snapshot and its calendar/identity binding | A fresh per-product network request, especially for reused bodies |
| Terms capture `captured_at` | When the derived archive retained the selected evidence | A new network observation or legal effective time |
| Public document acquisition `checked_at` | The existing attempt timestamp, sampled before the bounded HTTP call | An independently recorded HTTP response-completion instant |
| Acquisition lease/terminal events | Durable admission and acceptance of the request/check relationship | A new network check when a worker settles, interprets or replays work |
| Parser/adapter version, extraction result and result hash | Which reviewed interpretation was applied to which retained document version | A newer source verification time merely because interpretation completed later |
| Candidate `as_of`, generated/package timestamps, payload revision and publication readback | Assessment, construction or delivery of an exact immutable artifact | Successful bank/product source verification at that time |

`cdr_public_rates_source_capture.pricing_capture_for_path` has the original
bytes, product identity and registered endpoint, but no resource-specific HTTP
receipt in its call context. It therefore leaves its internal `checkedAt` empty.
The compiled product/programme freshness remains unknown, and wire evidence
omits missing clocks. Local copies, imports and touches cannot promote it.
`cdr_same_day_reuse.seed_same_day_reuse` deliberately copies prior verified
bodies with `atomic_write_bytes`; that new file's mtime is a copy clock.

Explicit low-level compilation can retain a check time supplied with reviewed
public-source evidence. That API is not authority to substitute a generation,
archive, caller's current time or mtime for missing evidence. Existing immutable
captures/candidates are not retrospectively attested by this correction; review
and rederive them from their retained receipts before any future activation.

Queued collector contexts can also contain bare clocks from older code. Replay
ignores those clocks. When collector-owned immutable product/programme/evidence
rows are projected into current or historical candidate views, the derived
projection removes unsupported check/success times and keeps freshness unknown.
Both inline views and streamed candidate chunks use that rule. The append-only
source rows and programme blobs retain their original bytes; this is not a
database rewrite, migration or activation of a new verification path.

## Existing successful source receipts

The raw attempt journal records sanitized request/response metadata, a body hash,
request/response times and a hash-chained event identity. A detail verification
must select a successful product-detail or classification-detail response,
validate its response shape/product identity, and bind the exact body and URL to
the intended provider/product. A successful product-list page cannot donate that
authority. A failed, malformed, mismatched or missing detail response cannot do so.

`cdr_terms/journal_sources.py` already retains
`JournalSource.response_completed_at` while checking a finalized artifact
inventory, body hash/size, successful 2xx detail phase and provider/product
identity. Its reader explicitly requires callers to bind the contract to the
finalized marker/ledger and retain partial coverage. A selected subset is not
complete bank coverage. No new journal scan or receipt export is added here.

Registered reference documents have a separate acquisition path. A successful
200 receipt must bind its retained bytes/document version, allowed final URL,
request/check and accepted lease. A 304 is accepted only with retained bytes and
validators bound to that URL and prior version; an unbound or unconditional 304
is a failure. Reviewed extraction and its exact source context remain separate
requirements before reference pricing can be current.

The existing internal reference freshness projection combines acquisition and
accepted-workflow evidence. Its `checkedAt` is the attempt timestamp and its
`lastSuccessAt` can reflect the accepted workflow event. These fields must not
be relabelled as the app's per-product `verifiedAt`: neither proves an explicitly
recorded response-completion time for that product. A reference-document check
also cannot verify every product or fee offered by its provider.

## Dormant app boundary

AR-app #412 source `4a366c8d248a02d216fd85dbf6e0173591b012ab` defines an internal
`SuccessfulVerification` with `kind`, `provider`, optional `productKey` and
`verifiedAt`, but `rowVerificationReceipt` deliberately returns `null` for the
shipping row contract. Its coloured status calculation is not a transport or
receipt-authority contract. AR-app #413 source
`6018ae6c9ae30a28d62778a9bf9c7a217943c530` distinguishes audit/delivery outcomes;
verified delivery is not bank/product verification.

A future reviewed receipt capability needs an exact selected manifest/core and
generation binding, stable provider/product identity, source URL and body/version
identity, successful request/response/parse outcome and truthful verification
instant. It must preserve the source receipt identity and distinguish listing,
detail, reference and interpretation scope. A bank-scoped success additionally
needs a defined complete population, complete pagination and all required
resource checks, with explicit failures, exclusions and partial coverage. A
single product, page or reference receipt cannot widen into bank-wide success.
Unknown or unavailable proof stays unknown. This investigation supplies no such
capability and does not open the app adapter.
