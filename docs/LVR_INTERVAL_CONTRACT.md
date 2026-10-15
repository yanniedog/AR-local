# Mortgage LVR intervals

The schema-1 flattened/core `lvr_tier` remains one string on each original rate
row. Rates, rate indices and source observations are not duplicated or rewritten.
The producer intersects the rate's LVR interval with product `MIN_LVR`/`MAX_LVR`
limits. Missing maxima remain open; contradictory or malformed explicit limits
remain unspecified.

Existing canonical bands retain their `(lo, hi]` meaning at 0.01% steps:
`lvr_=60%`, `lvr_60-70%`, `lvr_70-80%`, `lvr_80-85%`, `lvr_85-90%`, and
`lvr_90-95%`. A source interval spanning multiple bands is preserved, for
example `lvr_>=80.01-95%`. The `>=` preserves an inclusive structured minimum;
`>` preserves an exclusive textual minimum. Without an upper limit these become
`lvr_>=80.01%` or `lvr_>80%`. An upper-only interval is `lvr_=95%`. Taxonomy
tokens use `p` for a decimal point so the dot-delimited path stays intact, for
example `LVR_GE80p01_95`.

The public NAB Tailored Home Loan response captured on 2026-10-14 with API
version 7 has `minimumValue=0.8001`, no tier `maximumValue`, and product
`MAX_LVR=0.95`. It therefore exports `lvr_>=80.01-95%`, covering the saved
80–85%, 85–90% and 90–95% bands. Explicit narrower rate/product maxima still win.
The public response and its compact owner-occupier variable P&I projection are
retained in the regression fixtures. They contain public catalogue data only.

AR-app must support interval containment in its profile, Search, mandatory
eligibility and prepared-history filters before publishing these corrected
facets. A selected numeric band requires coverage of its whole interval; an
interval capped at 92% cannot satisfy a 90–95% requirement. Unknown LVR remains
excluded from numeric selections. Numeric lookup rejects values outside all
published intervals instead of clamping them to the highest band.

The prepared-history compiler and receipt must be regenerated from that reviewed
consumer and copied byte-for-byte into `contracts/history_ready`. The new receipt
is a compatibility boundary: existing prepared assets with a previous compiler
receipt are not treated as equivalent. Core and retained/raw history contracts
remain independent. Deploying, rebuilding or publishing a corrected payload
requires separate authorization and consumer compatibility verification.
