# Product suitability, rate ranking, refinance & monetisation — implementation plan

Status legend: ✅ shipped · 🟡 in progress · ⬜ planned

This plan turns the "broadly-applicable products by default" brief into staged,
implementation-ready work. It is deliberately built on the app's existing
**ledger-derived compact assets** and one **shared classifier**, per the locked
RateWatch direction. Each phase is a small PR that ships behind sensible defaults.

---

## 0. Design principle: one classifier, used everywhere

The reported bug ("filtered products still appear") was caused by **two disjoint
classification systems**:

- `format.isNonStandard()` — backend `account_class==='non_standard'` +
  curated names (`accountClass.ts`). The only thing the default filter removed.
- `access.assessAccess()` — the richer staff/occupation/membership/business/
  student/geographic classifier — was **only rendered as a badge**, wired into
  zero filters. Staff-only/business/industry/membership products therefore leaked
  into search, headline, calculator, rankings and the ribbon.

**Rule going forward:** every surface that hides, ranks, sorts, aggregates or
"best-rate"s a product MUST go through **one** predicate. Phase 1 introduced it:

- `access.nameRestrictsAccess(name)` — cheap, name-only restriction test.
- `format.isBroadlyAvailable(row)` — `!isNonStandard(row) && !nameRestrictsAccess(row.product_name)`.

Do not add a new local `account_class !== 'non_standard'` (or similar) check
anywhere. If a surface needs different behaviour, extend the classifier, not the
call site.

---

## Phase 1 — Unified suitability filter + setting rename ✅ (this PR)

**Shipped.** Directly closes the brief's "Core objective" and "Fix current
filtering bug" sections.

- `nameRestrictsAccess` + `isBroadlyAvailable` added; `visibleAccountRows`,
  `selectors.filterRows`, `taxonomy.statsFor`, `calculator.tsx` and
  `historySelectors.ts` all routed through the one predicate.
- Setting renamed to **"Show broadly applicable products by default"**
  (default **on**; the persisted `includeNonStandard` flag is its inverse), moved
  to a dedicated **Product filtering** section.
- **App update** section moved to the top of Settings.
- Tests: `nameRestrictsAccess`, `isBroadlyAvailable`, `filterRows` exclusion +
  `bestRow` consistency. Full suite green (435), tsc clean, 0 new lint warnings.

**Follow-up tuning (cheap, Phase 1.1):** `OCCUPATION_RE` currently matches
`health|medical|education`, which can catch a few mainstream names (e.g.
"Education Saver"). Tighten with a small allow-list, and add a telemetry counter
of rows excluded per category so we can watch false-positive rate on live data.

---

## Phase 2 — Classification depth & product validation ⬜

Goal: make the classifier accurate and auditable, and record the validated
attributes the brief lists — from real CDR data only (no mock/synthetic values).

### Data model

Prefer **server-side** classification so web + app + payload agree. Extend the
Pi payload build (`app_payload.py` / `cdr_taxonomy.py`) to emit per product:

| Field | Source |
| --- | --- |
| `access_class` (`open` \| `staff` \| `occupation` \| `membership` \| `business` \| `student` \| `investor` \| `foreign_investor` \| `geographic`) | `cdr_taxonomy` structured `eligibilityType` + name/description regex (port of `access.ts`) |
| `access_verify` (bool) | name implies restriction not encoded in structured eligibility |
| `broadly_available` (bool) | `account_class==='standard' && access_class==='open'` |
| `rate_kind` (`base` \| `bonus` \| `intro` \| `promo`) + `intro_months` | `rateQualifier` port; already partly on the wire (`ribbon_deposit_kind`, `ribbon_rate_structure`) |
| Fees: `monthly_fee`, `account_keeping_fee`, `establishment_fee`, `exit_fee`, `discharge_fee`, `overdraft_fee` | CDR `fees[]` by `feeType` |
| Features: `offset`, `redraw`, `split`, `repayment_holiday`, `line_of_credit` (bool) | CDR `features[]` `featureType` |
| `owner_occupier` / `investor` availability | CDR `loan_purpose` / `lendingRates` |
| `source_url`, `validated_at` | CDR `additionalInformation` URIs + ingest run timestamp |

- The app already surfaces `details.links` (overview/eligibility/fees/terms) and
  `assessAccess`; this phase moves the truth server-side and adds the fee/feature
  booleans to the compact core so filtering/validation needs no per-product
  detail download.
- **Validation gate:** a build-time check (extend `tests/test_app_payload.py`)
  asserting every ranked product has a non-null `comparison_rate` **or** an
  explicit `rate_source` and a `validated_at`; products failing validation are
  flagged, never silently dropped or fabricated (respects the ledger invariant).

### Acceptance

- Dashboard, app and payload return identical `broadly_available` for the same
  product+date. Client `access.ts` becomes a thin fallback for old payloads.

---

## Phase 3 — Rate-ranking preferences (savings / mortgage / TD) 🟡

**Shipped (v1):** savings & term deposits rank by the **base ongoing rate** by
default everywhere via `rankFraction` / `RankMetric` in `selectors.ts` (a
bonus/intro deposit row ranks on the `ongoing_rate` it reverts to; `null` when
unpublished, so a conditional promo rate can't top the list). New
`depositRankMetric` pref (default `base`) + a **Rate ranking** settings section
let advanced users switch to `max` (the headline/bonus rate); the override is
wired into Search and the Home hero. **Follow-ups:** propagate the override to
Browse/calculator/Banks A–Z; per-section metrics (intro/bonus/effective, TD
maturity/term); `statsFor`/ribbon on the base metric; availability overrides.

Default behaviour ("Core objective") with advanced overrides.

### Prefs (extend `store.ts` `Prefs`, all defaulted to the broadly-applicable choice)

```ts
rankMetrics: {
  savings: 'base' | 'max' | 'intro' | 'bonus' | 'effective';   // default 'base'
  mortgage: 'comparison' | 'advertised' | 'effective_offset' | 'total_cost'; // default 'comparison'
  td: 'standard' | 'maturity_return' | 'shortest' | 'longest' | 'monthly' | 'at_maturity'; // default 'standard'
}
availability: {                    // advanced include/exclude (all default excluded-from-default)
  business, staff, industry, foreignInvestor, investorOnly, ownerOccOnly,
  narrowMembership, unusualEligibility: boolean
}
```

### Logic

- Introduce `rankValue(row, section, metric)` in `selectors.ts` returning the
  fraction to sort/aggregate by. `bestRow`, `sortRows`, `statsFor` take the
  metric (default from prefs). Savings default = **base ongoing** rate, not the
  bonus/intro rate; bonus/intro shown as clearly-labelled secondary (reuse
  `rateQualifier` badge — already built).
- Mortgage default already = comparison rate via `effectiveRate`; expose the
  `advertised`/`effective_offset`/`total_cost` options.
- `availability` overrides map to `isBroadlyAvailable` exceptions: an advanced
  user who enables "Business products" removes that category from the default
  filter (parameterise the predicate: `isBroadlyAvailable(row, allow)`).

### UI

- **Rate ranking** settings section (segmented controls per section).
- Product cards show headline = default-metric rate, secondary = alt rate,
  labelled ("intro 5.50% for 4 mo", "bonus if conditions met").

### Acceptance

- With defaults, no savings account is ranked #1 on a bonus/intro rate; a
  staff/business product never appears as headline unless its availability
  override is on.

---

## Phase 4 — Mortgage offset in the calculator ⬜

Build on `calc.ts` + `calculator.tsx` (already has LVR + persisted `calc`).

- Add `offsetBalance` to `CalcInputs`; field appears only when the user selects
  "I want/need an offset" (or has an `OFFSET`-featured product selected).
- Simulation (`calc.ts`, pure): effective interest-bearing balance =
  `max(0, principal - offset)`; recompute interest per period, interest saved,
  term reduction, forecast principal curve, and nominal-vs-effective cost.
- Only offer offset comparables that actually have the `offset` feature (Phase 2
  boolean) — no assumed features.

### Acceptance

- Offset field hidden unless relevant; interest-saved and term-delta match a
  closed-form check in `calc.test.ts`.

---

## Phase 5 — Refinance calculator + projection ⬜

New, distinct from the basic calculator. New pure module `refinance.ts` + screen
`app/refinance.tsx`.

### Inputs (persist under `prefs.refi`)

Original purchase price, original loan amount, loan start date, current balance,
current value, current repayment, current rate, current loan type, current
lender, current offset, occupancy, rental income + frequency, state, remaining
term, proposed product, expected refinance date.

### Cost estimation (mark each estimate vs validated)

Discharge/exit fee, new establishment fee, valuation, settlement, legal, broker
(optional), government + mortgage registration fees (state tables), stamp-duty
note where relevant. Establishment/discharge fees come from Phase 2 product data
where available (**validated**); statutory fees are **estimates** from a small
per-state table, clearly labelled.

### Projection logic

Amortisation for: stay, refinance, refinance+offset, refinance−offset, N offset
assumptions, N repayment assumptions, N terms. Outputs: forecast balance,
principal vs interest paid, equity over time, payoff date, total-cost delta,
**break-even month** after switching costs, balance at key dates.

### Acceptance

- Break-even and total-cost deltas verified against a spreadsheet fixture in
  `refinance.test.ts`; costs visibly tagged estimate/validated.

---

## Phase 6 — Refinance visualisation (portrait-mobile) ⬜

Reuse the existing charting stack (`BankHistoryChart` SVG primitives + scrub
overlay; ECharts on dashboard). Add `RefiProjectionChart`:

- Stacked balance/equity area, principal-vs-interest bands, scenario lines
  (stay vs refi vs offset), break-even marker, payoff-date marker.
- Portrait-first: vertical scenario toggles, swipe between metrics, no wide
  tables — a compact "scenario summary" card replaces tabular dumps.
- All series derived on-device from `refinance.ts` (no new payload assets).

### Acceptance

- 360×640 portrait renders without horizontal scroll; scrub shows per-month
  values; scenario toggle < 16 ms recompute for a 30-yr projection.

---

## Phase 7 — Settings cleanup ⬜ (Phase 1 already did the two highest-value moves)

Target grouping (brief §"Settings screen cleanup"): 1) Updates 2) Product
filtering 3) Rate ranking 4) Calculator preferences 5) Advanced product filters
6) Advertising & premium 7) About / data sources. Ordinary users see one switch
("Show broadly applicable products by default"); everything granular lives under
a collapsible **Advanced / Customise product filtering** disclosure.

---

## Phase 8 — Advertising framework ⬜

**Network:** Google AdMob via `react-native-google-mobile-ads` (best Android
fill, works with the existing Firebase project).

- **Placements (only):** bottom banner on list/search pages, one inline banner
  between result groups, one banner below charts. **No** interstitials, **no**
  pop-ups, clearly labelled "Ad", never mixed into the ranked list.
- **Config:** ad unit IDs in `app.json` `extra.ads` (+ `AndroidManifest`
  APPLICATION_ID); Google **test unit IDs** in `__DEV__`; a single
  `<AdBanner slot=…/>` component that renders `null` when `hasProAccess(prefs)`
  or when `extra.ads` is empty (ads dormant until configured, like the auth/key
  services already are).
- **Perf/safety:** lazy-mount below the fold; never inside chart/calculator
  compute paths; respects `wifiOnly` for preload.

### Account setup (runbook to add to `docs/`)

AdMob account → link Firebase app → create banner ad units → put IDs in
`extra.ads` → build → verify with test IDs → flip to live IDs. Premium users:
`AdBanner` early-returns on `hasProAccess`.

---

## Phase 9 — Premium roadmap ⬜

Reuse the built auth/tier scaffolding (`proAccess.ts` `rateIntelligencePro`
stub, Firebase Auth + `issueContentKeys`, `ProPaywall`).

- **Free tier (stays genuinely useful):** all broadly-applicable rates, search,
  basic calculator, 1 alert, current ribbon.
- **Premium:** no ads · advanced calculators (offset) · refinance projections ·
  advanced filtering/ranking · full history explorer + per-product history ·
  exports / saved scenarios.
- **Billing:** Google Play Billing via `react-native-iap` **or RevenueCat**
  (recommended — handles receipt validation + entitlements, less server work);
  entitlement flows into `hasProAccess`. Suggested pricing: ~A$3.99/mo or
  A$24.99/yr, with a 7-day trial; one-off "lifetime" optional.
- Avoid hostility: never paywall the core compare/calculator; ads are the free-
  tier cost, premium removes them + unlocks projections.

---

## Phase 10 — Google Play access (advisory) ⬜

Practical options while the developer account is blocked:

- **Check in Play Console:** identity verification (Google now requires legal
  name + address + phone, and for new **personal** accounts a **14-day / 20-tester
  closed test** before production); payment profile country/tax; app content
  declarations.
- **Common blockers:** identity mismatch vs government ID; unverifiable
  address/phone; prior policy strikes on a linked account; org account missing a
  **D-U-N-S** number.
- **Organisation account** helps if publishing as a business (D-U-N-S, verified
  website) — often smoother than personal for a data/finance app, and exempt from
  the personal-account closed-testing gate.
- **Interim distribution (already supported):** the app ships a **direct APK**
  with an in-app updater (`appUpdate.ts`, `mobile-android-apk` pipeline, QR in
  Settings). Also viable: Amazon Appstore, Samsung Galaxy Store, F-Droid
  (needs FOSS deps), Huawei AppGallery.
- **Sideloading risks:** users must enable "install unknown apps"; no Play
  auto-update (mitigated by the in-app updater); Play Protect warnings; no Play
  billing (premium would need an alternative processor off-Play).
- **Before public release:** privacy policy URL, Data Safety form, content
  rating, target-API compliance, financial-disclaimer copy (already in About),
  and a signed release keystore in EAS.

---

## Cross-cutting testing checklist

- [ ] One classifier: grep shows no `account_class !== 'non_standard'` or ad-hoc
      restriction checks outside `format`/`access`.
- [ ] Default view excludes staff/business/industry/membership/foreign-investor;
      opting in restores them — across search, lists, calculator, rankings,
      compare, ribbon, hierarchy, and any payload bundle.
- [ ] Savings never ranked on bonus/intro by default; mortgage default =
      comparison; TD default = standard broadly-available.
- [ ] Offset field appears only when relevant; math verified.
- [ ] Refinance break-even/total-cost verified vs fixture; estimate vs validated
      labelled.
- [ ] Charts render in 360-px portrait with no horizontal scroll.
- [ ] Ads never show for premium users; no interstitials; ads visually distinct
      from rankings; dormant when unconfigured.
- [ ] No mock/synthetic product data; every ranked product has validated fields
      + `validated_at`.

## Acceptance criteria (brief → done)

1. Ordinary users see broadly-available, least-restrictive rates by default,
   everywhere, from one classifier. ✅ (Phase 1)
2. One simple default switch; advanced overrides hidden under Advanced. 🟡
   (switch + section shipped; granular overrides = Phase 3/7)
3. Savings/mortgage/TD default ranking as specified. ⬜ (Phase 3)
4. Offset + refinance projection with slick portrait charts. ⬜ (Phases 4–6)
5. Non-intrusive ads + premium upgrade path. ⬜ (Phases 8–9)
6. Google Play path documented with interim distribution. ⬜ (Phase 10)
