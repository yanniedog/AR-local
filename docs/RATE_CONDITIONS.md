# Rate condition source disclosures v1

New bank JSON exports capture `rate_conditions_json` alongside each product's
`details_json`, before source-array cleaning. The optional mobile product-details
field `rateConditions` carries that envelope. Existing exports without the
companion stay unchanged; it is never reconstructed from cleaned or historical
records. Fixed-column SQLite exports do not persist this new JSON companion.

The contract is [rate-conditions-v1.schema.json](../contracts/product_terms/rate-conditions-v1.schema.json).
`sourceSha256` hashes the exact original product-detail document bytes, including
whitespace. It is not the downloaded details asset hash. Each entry's `id` is
SHA-256 of UTF-8 compact JSON `[sourceSha256,sourcePointer]`, without a newline.
This identifies an occurrence within one source document, not a semantic change
across observation dates. The containing details payload supplies `run_date`.

`rateFamily` is deposit or lending. `rateIndex` is the existing flattened rate's
one-based ordinal after filtering non-object array items; empty objects still
count. Source pointers retain original zero-based array indexes, including gaps.
`rateSourcePointer`, optional `tierSourcePointer`, and `sourcePointer` refer to
the original wrapped `/data/...` or unwrapped document. Only fixed schema keys
and decimal indexes occur, so these RFC 6901 pointers need no escaped keys.

Only nonblank `additionalInfo` strings at the rate, tier, or their object/list
`applicabilityConditions` are included, verbatim. Duplicate quotes remain separate
occurrences. Numeric bounds, eligibility, rate selection, and calculations do not
change. In particular, MONTH tier bounds are not interpreted as account balances.
The original record retains other source fields outside this disclosure channel.

Limits are 1,024 entries per product, 16,384 UTF-8 bytes per quote, 512 ASCII
characters per pointer, and 1 MiB of compact UTF-8 envelope JSON. Packaging rejects
invalid or oversized present metadata; it never truncates quotes. Source export
capture retains the full envelope even when a later package must reject its size.
The unchanged v1 transfer limits also reject details exceeding 4 MiB of compressed
(or encrypted compressed) asset bytes and total assets exceeding 8 MiB. A failed
budget leaves candidate assets for diagnosis but does not write a new manifest.

Old clients can ignore the optional field; all existing product fields and the
v1 payload schema version remain unchanged. New consumers must verify asset
integrity and match the enclosing core/details generation and run date before
joining selected rate family/index to disclosures. Missing metadata means
unavailable evidence, not unconditional eligibility. No source hash is a claim
that the source was observed on a particular historical date.

The checked-in Macquarie regression is the authorized fresh public response from
2026-09-15: 5,018 bytes, SHA-256
`d387b14ea2d803cb6e8b52acacf9d0e0089623d345fa390c1d05cc047f5feb64`.
Its eight projected tier quotes distinguish two balance cohorts without parsing
the prose. This fixture is not historical ingest evidence or authority to repair
or republish retained observations. Full-population size measurement, activation,
and Pi acceptance remain separate gates. If a real candidate exceeds v1 limits,
a future lazy disclosure asset needs its own measured design and consumer contract.
