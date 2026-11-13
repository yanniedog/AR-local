# Coverage report schema repair — 2026-11-13

Source-only task; no Pi mutation. Parent owns controlled activation and acceptance.

## Confirmed failure

Hosted report run 43412528732 read November 13 ingest-status with total=11,
eight by_provider entries and eleven unresolved_requests, but printed zero
failures and an empty provider table for fourteen days. Recursive scanning only
recognized bank/provider/brand fields; current status uses provider_dir and
provider_uid, with brand_name in provider_states and keyed aggregate maps.

Authoritative failure-record counts and the bounded, deduplicated recovery queue
are different populations. Adding them double-counts; counting only the queue
can undercount. Parse the current aggregate schema explicitly, map identities
through provider_states, and display request samples separately. Unknown or
inconsistent schema must print UNKNOWN rather than a successful zero.

## Evidence and next steps

The separately captured sanitized live-runtime-20261113.jsonl confirms eleven
current failures: Aussie index404; DDH Graham index401; Thriday transport599;
MoveBank conflicting product identity; Bank of Sydney detail422; three CommFCU
inactive400; two Bank of Queensland and one ME Go detail500. Raw evidence lives
in the root task's private `.work/ingest-resilience-20261113/` directory. Tests
will use a field-only projection of that real status, with no response bodies,
URLs, credentials or invented products.

Preserve standalone stdlib execution over SSH stdin, bounded reads/output,
read-only behavior and redaction. Validate extraction, overlapping views,
schema mismatch, incomplete/capped samples, sanitization and CLI output before
publishing a separate PR. Actual provider error diagnosis remains pending raw
attempt evidence; HTTP codes alone do not prove the underlying cause.

## Implemented and verified

The standalone report now reads authoritative counts and category maps once,
resolves directory/UID aliases through provider_states, and separately prints
the bounded request sample with its completeness flag and phase/status detail.
Provider-state counts are a fallback only when the aggregate map is absent.
Missing/inconsistent totals return UNKNOWN and exit2. Journal fallback reads
only the primary capture, so revisions cannot be added to the same population.
Reads, sample size and output remain bounded; URL/long-token/control-character
redaction applies to displayed fields, and unknown metadata is not traversed.

Real sanitized fixture `tests/fixtures/coverage-report-20261113.json` is a
field-only projection of November13 DAY_STATUS, UNRESOLVED and the eight failed
PROVIDER_STATES from the runtime capture. The complete/provenance booleans are
copied from hosted run43412528732 STATUS_SHAPE. No response bodies, URLs or
credentials are included. After integrating merged coverage PR1130, 38 focused
report/status/change tests pass on Python3.10.9, including standalone isolated
stdin execution matching the hosted transport;
the existing requests dependency warning remains unrelated. `git diff --check`
passes. CI, reviewed main merge and a fresh hosted read remain outstanding.

The live MoveBank conflict also exposed an owning producer bug: overall category
counts honored the recorded failure_category, but per-provider counts discarded
it and reclassified the synthetic status as unknown_internal. The rollup now
uses the same recorded-or-derived category for both maps. A regression replays
all eleven retained terminal requests through summarize_failures and preserves
the MoveBank invalid_response classification. Identity-conflict handling and
fetch/recovery behavior are unchanged. The original captured fixture remains
unchanged so the historical discrepancy is still reproducible.

Final focused validation after the producer correction: 83 report, ingest-status,
product-change and compatibility tests passed; `git diff --check` passed.
Review correction: aggregate acceptance requires explicit true failure
provenance; a missing field cannot establish zero failures. Present provider-state
counts must reconcile with the aggregate. Missing provenance and contradictory
zero-count summaries are covered by the existing schema-drift regression.

## Current upstream diagnosis (retained November13 capture)

The read-only runtime extraction inspected 23 matching raw attempts from session
`ingest-20261112T140604080483Z-8b2a76250285`. Each extracted record retains the
event/body digest, version, host/path, status and bounded sanitized error body.
These are captured-source findings; no new upstream request was made for this
diagnosis. The original failures remain evidence, not repaired acceptance.

| Provider | Terminal requests | Captured cause and implication |
|---|---:|---|
| Aussie Home Loans | 1 index | v6 HTTP404, Resource not found at the registered product path. No product body; verify a replacement only from authoritative discovery. |
| DDH Graham | 1 index | v6 unsupported406 negotiated to v5; v5 HTTP401 EBAU001 says its upstream tenant authorization-token fetch failed. This is not a request for an AR-local customer credential. |
| Thriday | 1 index | v6 transport599, dns_resolution_failed for the public CDR hostname. Keep bounded transport retry and rediscover official endpoint changes; do not bypass public-network/host safeguards. |
| Bank of Sydney | 1 detail | usd_fccy_account v7 HTTP422 PCUA008: the provider's response validator requires depositRates[1].applicationType. The error contains no replacement rate/details. |
| Bank of Queensland Limited | 2 details | HTTP500 PCBS021; retained v6/v7 attempts expose MIN_DEPOSIT_AMOUNT additionalValue failing AmountString validation. Retries cannot reconstruct the absent product body. |
| ME Bank - ME Go | 1 detail | v7 HTTP500 PCBS021 with the same deposit-rate-tier AmountString validation error. |
| CommFCU | 3 details | v7 HTTP400 explicitly reports the indexed product inactive (2.6141). Preserve the index/detail inconsistency and avoid presenting a fabricated current offer. |
| MoveBank | 1 index diagnostic | v6 unsupported406 negotiates to v5 HTTP200. Same credit-card ID occurs twice with differing effectiveFrom/lastUpdated; both say unavailable to new customers. This is outside mortgages/savings/term deposits. The honest identity-conflict guard retains the warning and continues unrelated products/pages; no evidence supports choosing one conflicting row. |

The recorded errors explain all eleven terminal requests. They do not establish
that every upstream product is unavailable, nor that current target-product
coverage is complete. Retained failure categories must stay separate from
provider population checks and requested product scope. Broader financial
register discovery, terms-document capture, current runtime deployment, natural
daily acceptance and Drive read-back verification remain coordinated parent work.
