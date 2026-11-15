# AR-app handoff — 2026-11-15

Source: device audit `audit-e03d6fb91a1ab9e2` (app 1.0.277 / build 333, Android, run date 2026-11-15, outcome `failed`: 194 pass / 2496 warn / 56 fail) plus a product-screen screenshot ("Simple Home Loan"). AR-local causes were checked first; everything below is app-side unless marked **Data**.

## 1. Product screen shows "Unavailable" + Retry for content that was never published (bug)
`EligibilityAssessment.tsx` ("Recorded criteria") and `MortgagePeriodCalculation.tsx` ("Mortgage · History") render `Unavailable` + `Retry` whenever `loadEligibilitySelections` / `loadMortgageSelections` return `[]`. They return `[]` when the manifest has no `executable_v2` block, which is the normal state today: AR-local does not publish reviewed executable contracts (its terms-interpretation worker is operator-gated; permit expired). Retry can never succeed, and "Eligibility: Unassessed / Source: Unverified" follow from the same absence.
- Distinguish three states: not published for this publication (no Retry; say "Not yet available"), not available for this product (index lacks the product), and genuine load/verification error (keep Retry).
- Consider hiding both disclosures entirely when the manifest carries no executable contracts.

## 2. Journey failures: 54 `check-failed`, 2 `step-limit-exceeded` (55 counted as timing failures)
- Affected: cold/warm rates, savings, TD, watchlist, market journeys; `rates.search.*` (open, query clear, sort, filters, compare); `rates-sheets`, `rates-mortgage-scope`, `compare.dismiss`, `outlook.snapshot.browse`, all `redirect.*.verify`, `sample.catalogue.*.lender.open`.
- `route.not-found.home` exceeds the 10 s step limit on both passes with `rates.results / search.list` probe still pending (`catalogueAllLoaded: false`).
- Health `display-visible` fails for surface role `rates.results`. Max event-loop lag 754 ms, max frame gap 758 ms. The common factor is the rates results list not becoming ready/visible in time after navigation.

## 3. Audit instrumentation gaps
- `display-model` unavailable for 12 of 22 surfaces; `display-logo` unavailable for 2 of 8.
- 2,340 `external-link-*` checks are `warn` (links unverified) and `external-link-47` timed out at 12 s. These dominate the warn count and hide real warnings; verify them or report them as one aggregate.
- 2 target-probe defects, 3 pending probes.

## 4. Bank-response coverage (mixed)
1,495 windows checked, 507 displayed, 141 known moves, 1,321 unknown.
- App-side: 1,058 are `filtered-history` (the app's own history filter removes the baseline). Review whether that filter is too strict.
- **Data**: 84 `missing-history`, 77 missing baseline, 191 history gaps. These follow the six source-gap days below and cannot be fixed in the app.

## 5. Data facts the app must tolerate (AR-local side, no app defect)
- Six dates have no capture at all and never will: 2026-05-14, 06-26, 10-07, 10-08, 10-09, 10-10. CDR exposes current state only, so they cannot be back-filled.
- Every day is a disclosed partial capture: roughly 8 of 115 providers fail upstream daily (Thriday, DDH Graham, Aussie Home Loans, CommFCU, MoveBank, plus single products at BoQ, ME Go, Bank of Sydney). `coverage-reconciliation` will stay `warn` (2 failed / 8 partial on this run). Treat disclosed partial coverage as informational, not a warning.
- Published 2,667 products / 16,183 rates versus 2,809 / 16,339 in the source, and 116 `historical-quarantined-tiers` on 2026-11-15. Not yet attributed to app or publisher; needs a joint look.
- The optional packed bank-history asset is omitted when it exceeds its size budget (it did on 2026-11-15); the app must keep working from the per-date history assets.
