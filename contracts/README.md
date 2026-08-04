# Australian Rates app insight contracts

These contracts are additive. Existing clients continue to use `manifest.json`,
`core`, and `details` without understanding any new field.

- `core.coverage` is an optional measured CDR coverage snapshot. Failure entries
  are aggregated by provider, phase, and status; source endpoints and response
  snippets are never published.
- `details.products[*].links` contains only allowlisted HTTPS URLs supplied in
  CDR `additionalInformation` metadata. Absence means the source did not provide
  a usable official link; the producer does not invent or scrape one.
- Legacy `history_banks` and `bank_history` assets now declare the `all` cohort
  they have always represented.
- `manifest-v2.json` is rolling-only, bound to exact v1 core/details hashes, and
  published after all content-addressed assets. Consumers must ignore it when
  the base hashes do not match their verified v1 cache.
- The producer enforces a 64 KiB manifest limit, compressed/uncompressed limits
  of 32/256 MiB for product history and 2/16 MiB for economic outlook, and
  verifies local size, SHA-256, gzip expansion size, and safe filenames before
  upload. Consumers should enforce the same limits before replacing caches.
- `product_history` is a **standard-only**, per-product best-advertised-rate
  aggregate with explicit gaps. It is not exact tier/rate-index history.
- `economic_outlook` contains the two latest observations available in the
  local macro store plus freshness and official source metadata. It is observed
  evidence, labelled for a future `signal_balance`; it is not a forecast or a
  calibrated confidence score.

Exact `product_key + rate_index/cohort` history, normalized deposit conditions,
and client-side negotiation briefs remain later contracts. They must not be
inferred from the aggregated `product_history` series.
