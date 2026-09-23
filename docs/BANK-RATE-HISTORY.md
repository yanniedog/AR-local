# Embedded bank-rate history

The normal core download now carries all retained bank-rate observations in
`bank_rate_history` (schema 1). Each current rate row has a section-local
`bank_rate_tier` ID. A section contains one array of spans per tier ID; each span
is `[first_date_index, observed_date_count, rates_in_percent]`. Equal consecutive
observations share a span. Missing dates have no span and are never filled.

Tier identity includes every compact non-observation field. Rate, comparison
rate, ongoing rate, update time, row index and alert eligibility are excluded.
Thus a client can first apply its current catalogue eligibility and profile
filters, then aggregate only admitted tier IDs without another history request.
Duplicate matching rows retain their statistical weight through each span's
rate list. Matching current duplicates reference the same tier ID.

The extension shares the core's existing immutable hash, publication revision,
encryption, and offline cache. It is produced when building history-enabled
payloads and does not change rate facts or require a new release namespace.
Legacy clients ignore the extension; new clients show current rates for legacy
catalogues. Deploy/publish the producer and release the matching AR-app reader.

Measured against 131 verified published daily cores through 2026-09-22: 16,314
current rows; 133 calendar dates including gaps; compressed core grew from
348,306 to 453,080 bytes. Inputs were verified against the selected immutable
manifest and core hashes. Private benchmark data is not committed.
