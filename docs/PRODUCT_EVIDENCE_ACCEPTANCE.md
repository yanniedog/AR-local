# Product evidence acceptance

Status: **IN_PROGRESS — code foundations tested; complete pipeline not accepted.**
Updated 2026-09-14 for the operator's approved plan. The current evidence table
below supersedes the original all-unimplemented baseline. PASS applies only to its
stated narrow scope; checklist items retain their complete original acceptance
scope. Untested live operation, full-catalogue legal coverage and historical
publication must not inherit a PASS from local tests.

Scope is every retained and currently discovered Mortgage, Savings and TD product,
including linked accounts and packages that affect them. Standalone expansion into
other product categories is outside this scope. Unknown source populations remain
unknown. "All" below means the complete inventoried in-scope population, with every
unrecoverable or inaccessible item explicitly accounted for.

The operator's current instruction freezes Google Drive backup writes until the
operator explicitly approves resumption. The accepted backup is the recovery
fallback. This supersedes the daily Drive-write instruction in
[CDR_QUALITY_PIPELINE.md](CDR_QUALITY_PIPELINE.md) for this work. Root owns live Pi
operations and records the operative hold and ownership evidence separately.

## Current evidence and limits (2026-09-14)

| Verified scope | Status | Evidence and remaining boundary |
| --- | --- | --- |
| Status separation and authority record (A-001, A-004, A-005) | PASS | This checklist, implementation document, public evidence schema and app coverage fields distinguish capture, acquisition, interpretation, calculation and publication. Controlled historical runbook/handoff remain unchanged. |
| Public historical asset integrity | PASS | `runs/product-audit-20260914/history-audit-002/summary.json`: all 123 indexed dates' manifest/core/details bytes and schemas checked; 319,013 product-section-days across 111 historical banks. This proves integrity of published assets, not full source population or accurate historical terms. |
| Current bank/product/field reporting | PASS, report boundary only | `runs/product-audit-20260914/reports/baseline-005/report.html`, CSV/JSON companions: 110 current banks, 2,708 products, 16,546 rates, 276,979 current detail parameters and 3,039,408 historical parameter baseline/change rows. `report-repair-final-tests.xml` covers 30 report/repair regressions. Full fine print, unknown source denominators and unimplemented executable semantics remain disclosed gaps. |
| Evidence acquisition, source binding, immutable store and queue code | PASS, foundation tests only | `terms-integration-all-tests.xml` and `terms-ingest-tests.xml`; real retained CDR fixtures exercise original-byte retention, acquisition gating, stale leases, whole-generation capture and exact values. Merged producer CI (Actions 34838689487) completed 3,172 passed / 49 skipped / 4 warnings. No whole-catalogue archive or running Pi collector is accepted. |
| Worker transport, acquisition and resource guards | PASS, isolated controller/protocol tests only | `product-evidence-final-tests.xml`: 243 passed, 7 skipped across evidence, worker, report, repair and existing ingest/payload regressions, with a complete hidden-runner summary. Saved subscription only; one acquisition plus one interpreter; global cooldown; source/lease binding; protected-source nonoverlap; no-call gates and own-cgroup priority yield. Historical jobs bind their original evidence and cannot promote current terms. Live Codex/Pi calls were not used as test substitutes. |
| Declarative eligibility and dated exact ledger | PASS, supported helper tests only | AR-app `mobile/src/lib/productTermsEngine/__tests__`: 47 tests, source-quote hashes, official clause benchmarks and independent holdouts. Exact decimal/rational arithmetic, explicit event order, leap/month-end boundaries and three-valued eligibility tested. No full-product rule adapter is enabled; mortgage principal allocation, complex savings/TD rules and unverified material fees remain unsupported. |
| Candidate AR-app CI | PASS, candidate code only; native BLOCKED_EXTERNAL | Current candidate `80a7e1d12e87ee03b8f87639fd6710ca31440ada`: 167 Jest suites / 1,635 tests and 120 script tests; GitHub mobile CI succeeded at 2026-09-14 11:42:46 UTC (Actions 34839034334). `runs/product-audit-20260914/baseline/app-candidate-80a7e1d-packaging-receipt.json` binds the development-signed 87,773,085-byte APK, SHA-256 `938622767c058948f7ae0e8ed6dfdf6d3b07934e69fab4741a7bbfc0be4c93d1`. The earlier `8008d96` APK was superseded after a confirmed rollback defect. Native execution was not performed; this is not an updater release or deployed-consumer proof. |
| Incorporated-document graph (D-002) | IN_PROGRESS, bounded local implementation | Append-only root/scope/node/edge/expansion records preserve exact raw references, parent versions, extraction anchors and shared URL identities. One retained-node expansion plus a bounded sequential acquisition batch uses existing worker guards. Usable child extractions now atomically queue candidate-only interpretation with pinned ancestry/product scopes; worker staging cannot create reviewed applicability or current terms. Explicit host grants, redirect/304 binding, bounds, cycles, stale-source and transaction rollback controls remain. Full PDF/OCR/reference closure, reviewed applicability, runtime proof and measured daily acquisition capacity remain unfinished. See `INCORPORATED_INTERPRETATION.md`. |
| May 19 fee recovery | PASS for independently verified candidate; publication IN_PROGRESS | `runs/product-audit-20260914/fee-repair-20260519-003/receipt.json`: CANDIDATE_ONLY, 1,360 products / 17,372 fee corrections (16,678 additive and 694 narrowly evidenced variable-zero corrections); 1,544 retained raw records verified and 121 unresolved records preserved. The independent review receipt verifies every changed source pointer/hash, original core bytes, fee counts and unrelated fields. A higher immutable revision and app acceptance remain required; publication NOT_ATTEMPTED. |
| May 31 AMP duplicate disposition | PASS for unresolved evidence accounting | `runs/product-audit-20260914/may31-amp-disposition-001`: 2 `AMP_LAND_HL` observations, 68 retained rows forming 34 identical pairs, 8 public rate rows / 4 profiles and no value conflicts. The retained source filename names `AMP_FIRST_HL`, but the archive lacks raw responses needed to prove an identity correction. 113 assertions and 730 independent type-strict comparisons passed. Core/details match public bytes; manifests differ only in generation time. No rename, deletion or candidate repair; original identity remains unresolved. |
| Persistent Drive hold implementation | BLOCKED_EXTERNAL for live protection | Hold PRs 723, 724, 725 and 727 merged, including strict-lock and protected installation hardening. Pi installation/readback is not established while Pi access awaits authentication. The existing continuation now supervises critical windows only, with its previous backup-writing scope disabled. The Pi's independent timers remain unverified. No backup writes are authorized by this document. |
| Critical-window supervision | PASS for local schedule configuration; live protection BLOCKED_EXTERNAL | On the user's explicit request, the existing continuation was repurposed without creating another owner. It checks the 22:00 cutoff, 00:25/00:58 preflights around the known 01:00 ingest and subsequent progress. The same target thread and active schedule were read back. Windows/Codex availability and SSH access remain dependencies; missed preflights cannot be called successful. The 00:30 quiet window and all ingest/reclaim protections remain binding. |
| Existing Pi dashboard baseline | PASS for pre-deployment HTTP smoke only | `npm run verify:pi` passed after an initial history timeout. External Chrome inspected Mortgage, Savings and TD against `http://100.78.28.10/`. The dashboard's 90-day history window differs from the 123 published dates; this does not establish candidate deployment or native acceptance. |
| Native/Pi/account/scheduler acceptance | BLOCKED_EXTERNAL or IN_PROGRESS as listed below | Installed Codex flag compatibility, saved subscription auth/refresh, real quota receipts, unit isolation/resource/yield canary, Pi dashboard smoke and a natural cycle without Windows remain unverified. Candidate emulator work can continue independently; it cannot prove these Pi gates. |
| Full legal corpus, registry and reviewed comparisons | IN_PROGRESS | No claim of complete PDS/terms archive, fixed-point reference traversal, complete clause interpretation or exact comparisons for every product. Unknown sources and unsupported rules remain explicit. |

The paths above are workspace evidence under the task's ignored `runs/` folder,
except the named source/test files. They are not new public payloads or backup
uploads. Root owns final commit identities, live hold readback, PR disposition,
native evidence and final report release.

## Evidence and status rules

- [x] **A-001 PASS** Use `unimplemented`, `in_progress`, `pass`, `fail`,
  `blocked_external` and `not_applicable` with reasons and artifact references for
  every acceptance item. Do not infer PASS from code existence, process exit,
  commissioning, a parser audit or an AI confidence score.
- [ ] **A-002 IN_PROGRESS** Each execution receipt binds source manifest/hash,
  exact code and contract versions, commands, timestamps/time zone, outputs/hashes,
  independently checked outcomes, resource evidence, operator and deviations.
- [ ] **A-003 IN_PROGRESS** Preserve original evidence and append linked
  corrections. Report bank amendments separately from extraction/classification
  corrections and changes in observation coverage.
- [x] **A-004 PASS** Distinguish source capture, finalization, document
  acquisition, interpretation, public publication, app acquisition/rendering and
  scheduled runtime proof. Neither one nor their combined count implies another.
- [x] **A-005 PASS** Record current effective authority and supersessions
  without editing the controlled historical runbook or completed handoff evidence.

## Stage 1: protection and baseline

- [x] **P-001 PASS** Pause the existing continuation automation, obtain the
  prior owner's explicit safe-idle acknowledgment, retain one owner and record the
  transfer. Do not create a second competing daily audit owner.
- [ ] **P-002 BLOCKED_EXTERNAL** Inventory actual Drive daily, queue, terminal-event,
  manual, watchdog and recovery dispatch routes. Enforce a persistent hold before
  product-data mutations; disable relevant write schedules. Verify service-level
  and application-level refusal, including after restart/reboot, without a test
  upload. Retain queued requests as held, not successfully backed up.
- [ ] **P-003 BLOCKED_EXTERNAL** If a write is already in flight, wait for and reconcile
  its terminal result before applying the hold. Preserve backup receipts, accepted
  snapshot identities and reclaim controls. Confirm temporary resource controls are
  restored. Never terminate another owner's write or clear an unknown lock.
- [ ] **P-004 IN_PROGRESS** Confirm no task path indirectly runs a backup, prune,
  forget, restore-write or cloud-lock mutation. The analysis worker has no Drive
  credentials. Record final hold verification and explicit non-resumption.
- [ ] **P-005 BLOCKED_EXTERNAL** Capture live producer/deployed component identities,
  active services/timers, source/state locations, ingest/publication generations,
  public manifests, exact asset bytes/hashes, consumer release/APK/signing identity,
  storage and resource baseline. Hash evidence; do not copy secrets into reports.
- [ ] **P-006 IN_PROGRESS** Inventory every retained date, generation, failed
  attempt, log, source projection, register record and public revision. Account for
  duplicate/parallel variants and missing dates without counting a failed attempt
  as the selected day's observation. Build a bank/product/date coverage matrix.
- [ ] **P-007 IN_PROGRESS** Run the released APK in the agreed Android emulator
  against real current and historical assets. Record acquisition, filters,
  comparison, product details, history gaps, errors, offline behavior and data
  quality disclosures. Preserve emulator and user data appropriately.

## Stage 2: complete current evidence discovery and acquisition

- [ ] **D-001 IN_PROGRESS** Discover document references from complete raw CDR
  before lossy cleaning: top-level and nested additional information, supplementary
  overview/terms, eligibility, fees, tiers, bundles and linked products. Preserve
  their original JSON pointers and scope.
- [ ] **D-002 IN_PROGRESS** Traverse incorporated official documents and references
  to a fixed point or an explicit unresolved frontier. Retain discovery reasons,
  parent references, bank/product/tier/package/cohort applicability and cycles.
  Dedupe identical bytes without discarding distinct applicability or source URLs.
- [ ] **D-003 IN_PROGRESS** Retain full original document bytes, HTTP metadata,
  effective/issue/version dates where evidenced, final URL, observation timestamp,
  media type and content hash privately on the Pi. Capture page text, tables,
  footnotes, definitions, annexes and cross-references, including scans requiring
  OCR. Parsing success is not complete extraction proof.
- [ ] **D-004 IN_PROGRESS** At every ingest recheck all applicable references even
  when the CDR product `lastUpdated` field is unchanged. Conditional requests may
  prove unchanged content only against a retained matching prior entity. Record
  every success, 304, redirect, timeout, rejection, unsupported format and absence.
- [ ] **D-005 IN_PROGRESS** A failed fetch or disappearing link never generates a
  removed-fee/clause event. Retain prior evidence with stale/pending status and an
  acquisition gap. Validate replacement scope and completeness before removal.
- [ ] **D-006 IN_PROGRESS** Enforce official-source provenance, bounded redirects,
  public-network destination validation on every hop, response and decompression
  limits, per-host throttling, timeouts and retry budgets. Reject traversal, unsafe
  files, credential-bearing URLs and access to private service/metadata addresses.
- [ ] **D-007 IN_PROGRESS** Keep raw archives and full extracted documents private.
  Public assets carry validated structured facts and safe source citations, with
  no credentials, arbitrary errors, request headers or customer data.
- [ ] **D-008 IN_PROGRESS** Reconcile every current in-scope product to its expected
  evidence graph and every discovered document/clause to acquired, pending,
  unsupported, excluded-with-reason or unavailable disposition. Report unknown
  denominators rather than claiming percentage completeness for an unknown corpus.

## Stage 3: interpretation, durable rules and change tracking in shadow mode

- [ ] **T-001 IN_PROGRESS** Version and validate `DocumentVersion`, `SourceClause`,
  `ProductApplicability`, `TermRevision`, `RuleSet`, `TermChange`, `TermsCoverage`
  and `CalculationReceipt`. Bind immutable identities and reject duplicate IDs,
  orphan references, contradictory scope and unsupported schema/rule versions.
- [ ] **T-002 IN_PROGRESS** Use a dedicated append-only SQLite evidence/rule store
  plus content-addressed files. Enable constraints/foreign keys and explicit
  transaction boundaries. Preserve exact decimal values, units, operators,
  inclusivity, cadence, exceptions and provenance. Original observation databases
  receive no in-place schema or row changes.
- [ ] **T-003 IN_PROGRESS** Record observed time and legally effective time
  independently. Resolve new/existing customer, application/settlement/account
  opening dates, fixed-term cohorts, package dependencies and jurisdiction only
  from evidence. Unknown effective dates or cohorts never become guessed defaults.
- [ ] **T-004 IN_PROGRESS** Use a reviewed canonical parameter registry with
  aliases, types, units, applicability and supported rule patterns. Retain source
  wording and evidence locator for every normalized value; preserve all unmatched
  fine print with an explicit interpretation status.
- [ ] **T-005 BLOCKED_EXTERNAL** Run one durable Pi Codex CLI worker using the existing
  subscription and private authentication. No separate paid API, credit purchase,
  Windows dependency, AI-generated executable code or customer-profile upload.
- [ ] **T-006 IN_PROGRESS** Queue jobs by document content, extraction version,
  relevant applicability and rule context. Prioritize current changed evidence,
  unfinished current evidence, then historical work. Every ingest queues due work;
  a guarded 15-minute retry timer runs only in the allowed operating window. No
  Codex request for unchanged/no-due work; honor authentication/quota retry times.
- [ ] **T-007 IN_PROGRESS** Separate collector, interpreter, validator and
  publisher. The model only writes schema-bound staging output. It cannot change
  production pointers, source evidence, GitHub releases, deployment or backup.
  Treat document text as untrusted data and prevent embedded instructions from
  changing tools, credentials, rules or execution privileges.
- [ ] **T-008 IN_PROGRESS** Promote only validated supported patterns. Semantic
  review checks source numbers, units, negation, exceptions, cross-references,
  precedence and cohort scope. A second model pass alone never satisfies this gate.
  Unknown patterns remain visible/pending until reviewed real-source regressions
  and executable rule support exist through the normal PR process.
- [ ] **T-009 IN_PROGRESS** Track explicit addition, removal, value, range,
  cadence, condition, wording, source and interpretation changes. Preserve old
  revisions and distinguish publisher amendment from parser correction. A change
  in source URL alone is not a financial-term change.
- [ ] **T-010 IN_PROGRESS** Invalidate every dependent calculation on shared
  document changes. Unknown impact scope marks all dependants pending while
  independently verified current rates remain available. Compare-and-swap against
  current dependencies rejects stale worker completion and duplicate promotion.
- [ ] **T-011 IN_PROGRESS** Prove durable queue leases, crash/interruption/reboot
  recovery, bounded retries, idempotent replay, out-of-order completion, auth/quota
  deferral, publication failure and safe no-work exits. Preserve first failures.

## Stage 4: eligibility and exact scenario calculation

- [ ] **C-001 IN_PROGRESS** Build annotated real-source benchmarks covering every
  enabled material pattern across Mortgage, Savings, TD and shared packages. Keep a
  separate holdout. Report clause/field coverage, false eligibility, omitted costs,
  wrong scope, wrong dates and wrong numeric/unit outcomes; require zero known
  material errors in the accepted benchmark/holdout. Uncovered patterns stay off.
- [ ] **C-002 IN_PROGRESS** Ship one deterministic declarative evaluator used by
  AR-app and the audit harness. Support reviewed AND/OR/NOT, exact inequalities,
  ranges, counts, dates, calendar periods and linked-product dependencies with
  bounded expression depth. Reject arbitrary code and unsupported operators.
- [ ] **C-003 UNIMPLEMENTED** Provide dynamic encrypted on-device customer profiles
  with safe migration of existing scenarios. Ask only for applicable missing
  inputs; distinguish unknown, unavailable, not applicable and explicit zero/false.
  Keep manual negotiated terms marked as user inputs with their own provenance.
- [ ] **C-004 IN_PROGRESS** Evaluate each product/tier/cohort as meets published
  criteria, does not meet, or needs information, with reasons and evidence.
  Unknown matches remain visible separately and never count as eligible. Meeting
  published criteria is not represented as credit approval or a guaranteed offer.
- [ ] **C-005 IN_PROGRESS** Implement an actual dated cashflow/event ledger with
  bank-defined day count, balance basis, accrual/payment timing, calendar periods,
  event ordering and rounding. Do not use annual/12 or average-month conversions
  for an exact ongoing-cost/return claim. Existing approximations remain clearly
  labelled illustrative if retained.
- [ ] **C-006 IN_PROGRESS** Mortgage scenarios cover applicable loan amount,
  purpose, LVR/security, repayment type, remaining term, fixed/reversion periods,
  offset/redraw, extra repayments, settlement/switch/exit costs and their funding.
  Principal, interest and charges are separate; outstanding debt is not a fee.
- [ ] **C-007 UNIMPLEMENTED** Savings scenarios cover tier boundaries, base/bonus/
  introductory components, deposit/withdrawal/purchase/balance-growth conditions,
  assessment windows, caps, linked account fees and effective changes. Terms must
  establish whether a tier rate applies marginally or to the entire balance.
- [ ] **C-008 IN_PROGRESS** TD scenarios cover term units/ranges, start/maturity
  dates, payment cadence, reinvestment/rollover, notice periods, early withdrawal
  adjustments and applicable account fees. No unsupported 12-month fallback or
  promise of an unknown future rollover rate.
- [ ] **C-009 IN_PROGRESS** Capture all fee types and schedules, fixed/percentage/
  variable/conditional amounts, maxima/minima/caps, waivers, discounts, thresholds,
  indexed costs and package/account dependencies. Charge a shared package once
  under evidenced rules. Resolve discount precedence; preserve unpriced costs.
- [ ] **C-010 IN_PROGRESS** Compare equal dates/horizons/cashflows and disclose
  assumptions. Separate principal, interest, fees, net return, remaining debt,
  savings and break-even. Unknown material inputs/rules/fees block complete totals
  and cheapest/best claims, while showing known subtotals or justified ranges.
- [ ] **C-011 IN_PROGRESS** Future unannounced changes remain scenario assumptions.
  Apply evidenced announced changes to the correct cohort/date. Preserve a receipt
  of inputs, model/rule/dependency versions, assumptions, unknowns, event trace and
  calculation result; allow reproducible recalculation after term changes.
- [ ] **C-012 IN_PROGRESS** Verify exact threshold edges, zero/negative values
  where allowed, leap years, month ends, partial periods, holidays if relevant,
  date/time-zone boundaries, rounding, simultaneous events, rate changes, bonus
  windows, waiver precedence, package dedupe, cohort transitions and early exit.
  Use arithmetic invariants and independently derived expected results bound to
  real rule evidence, not tests that merely mirror implementation.

## Stage 5: app, historical repair and catalogue completion

- [ ] **U-001 IN_PROGRESS** Replace truncated two-item fee/eligibility/feature
  summaries in comparison with complete grouped parameter comparison and drilldown.
  Show equal canonical parameters across banks with units, conditions, applicability,
  source/effective dates, interpretation status and links to supporting evidence.
- [ ] **U-002 IN_PROGRESS** Provide complete product term/document inventories,
  granular change logs, gaps, customer eligibility and calculation traces. Preserve
  full fine print behind concise progressive disclosure. Support search, saved
  products, large text, screen-reader semantics, 48dp targets and long tables.
- [ ] **U-003 IN_PROGRESS** Deliver immutable optional term assets lazily. Verify
  hash, bounds, schema and dependency identities before adoption; keep prior trusted
  data on interrupted/corrupt refresh. Missing terms assets show pending/unavailable
  while verified rates remain available. Measure APK and cache/storage impact.
- [ ] **U-004 IN_PROGRESS** Make history caches depend on each date's selected
  revision/manifest/core identity, current catalogue identity and evaluator version,
  not merely the current core and list of dates. Pin one verified dates index per
  synchronization. Refetch corrected dates and fill newly restored product cells;
  preserve genuine null gaps and avoid cross-gap change alerts.
- [ ] **U-005 IN_PROGRESS** Ship and verify the consumer before producer activation.
  Terms-only changes create new immutable bundle identities and refresh affected
  app state. Future/unsupported term contracts fail safely in old consumers.
- [ ] **H-001 IN_PROGRESS** Inventory all retained history and official dated
  evidence using a new explicitly versioned correction contract outside the dormant
  92-date corpus. Every correction binds source role/date/variant/row, transformation,
  evidence and prior derived revision. Original raw files/SQLite/releases stay intact.
- [ ] **H-002 IN_PROGRESS** For May 13, recover taxonomy only from retained same-day
  product/rate detail and supported semantics; label it derived, not originally
  observed. Preserve unknown branches. Never apply present-day product terms to it.
- [ ] **H-003 IN_PROGRESS** For May 19, separately retain the broken undated archive
  and the two valid parallel projections. Explain 1,632/10,554 versus 1,618/10,514
  product/rate populations. Do not merge variants or call the whole day missing.
- [ ] **H-004 IN_PROGRESS** For May 31 AMP_LAND_HL, preserve duplicate row identities
  and use exact same-day raw detail to resolve only proven source distinctions.
  Quarantine unresolved conflicts; never overwrite a map entry or invent a product.
- [ ] **H-005 IN_PROGRESS** Reevaluate legacy term fallbacks and semantic collisions
  against explicit retained evidence. Preserve exact ISO terms, ranges and text
  separately; no-evidence terms are null. Same-value duplicates retain multiplicity;
  conflicting indistinguishable tiers remain withheld from exact history/alerts.
- [ ] **H-006 BLOCKED_EXTERNAL** Investigate May 14 and June 26 in all named verified
  retained sources and official dated evidence. Distinguish recovered publication,
  reconstructed dated facts and an unrecoverable live-observation gap. Never create
  an empty successful day or copy a neighbouring/current date into the gap.
- [ ] **H-007 IN_PROGRESS** Keep the August 16 failed RAM attempt and logs separate
  from any successful same-day generation; missing database means incomplete
  attempt. Reconcile all other discovered historic defects with equally explicit
  dispositions, including unavailable original register/attempt denominators.
- [ ] **H-008 IN_PROGRESS** Historical corrections publish only after field/row/
  membership accounting and a reviewed new correction contract pass. Preserve old
  immutable revisions, advance a corrected date to a higher verified revision,
  and never let a historical correction replace a newer rolling date. A bad new
  revision is repaired with another higher corrective revision, not pointer rollback.

## Final verification and report

- [ ] **V-001 IN_PROGRESS** Complete applicable AR-local Python/portable schema,
  integrity, interruption and resource tests, AR-app `mobile/npm run ci`, public
  payload parser audit and substantive PR review disposition. Bind exact heads.
  Windows process-control evidence includes a complete JUnit/pytest summary from
  the hidden isolated runner; exit zero alone is insufficient.
- [ ] **V-002 BLOCKED_EXTERNAL** Canary and deploy only the exact approved candidate
  through controlled activation, with verified rollback and resource results.
  Preserve 01:00 Hobart ingest priority, 00:30 freeze, actual terminal-job checks,
  03:30–22:00 recovery limits, capacity and memory/swap safeguards.
- [ ] **V-003 BLOCKED_EXTERNAL** Inspect the actual Pi dashboard in external Chrome at
  `http://100.78.28.10/` and pass `npm run verify:pi` against that deployment. Record
  timestamp, commit and actual result; localhost/public-site checks do not substitute.
- [ ] **V-004 IN_PROGRESS** Verify the exact candidate and released APK in the
  agreed emulator: clean install/upgrade, current and repaired historical acquisition,
  terms-only update, multi-product comparisons, personal criteria, exact calculations,
  pending/unknown states, offline/cache recovery and complete term rendering.
  Record APK/signing hash, source commit, screenshots, logs and payload identities.
- [ ] **V-005 BLOCKED_EXTERNAL** Observe at least one natural Pi collection/queue/analysis/
  validation/publication cycle without the Windows machine or app running. Prove
  actual scheduler attribution, no overlapping worker, no paid API, resource limits,
  preserved next ingest and enforced Drive hold. Manual starts are commissioning only.
- [ ] **R-001 IN_PROGRESS** Deliver a searchable HTML report, CSV tables and JSON
  evidence. Include bank/product/date coverage, every tabulated field and metric,
  definitions/formulas/units, source and effective times, unknown denominators,
  current versus historical availability, document/clause status, repairs and gaps.
- [ ] **R-002 IN_PROGRESS** Enumerate all rate/tier/LVR/balance/term/repayment/purpose
  fields, comparison/ongoing/base/bonus rates, fees/features/eligibility/constraints,
  raw normalized facts and links, provider attempts/failures, product dispositions,
  historical observations/changes, bank distribution statistics, RBA/pass-through
  metrics and customer scenario outputs. Distinguish measured, normalized, inferred,
  modeled and unavailable values; define the denominator of every summary.
- [ ] **R-003 IN_PROGRESS** Complete processing/accounting for the entire inventory,
  including retired products and historical variants. Unsupported/inaccessible
  clauses remain explicit external or interpretation gaps, not hidden backlog.
  Report verification boundaries and any remaining material incorrectness plainly.
- [ ] **R-004 BLOCKED_EXTERNAL** Final evidence confirms the accepted Drive fallback
  preserved, no task-induced backup writes and the hold still active. Resumption
  requires a new explicit operator instruction.

## Completion rule

Completion requires every item above to have evidence-backed disposition and every
in-scope bank/product/date/document/clause accounted for. A prototype, the first
few banks, passing local tests or an empty work queue after errors is not complete.
Externally unrecoverable evidence is reported as a limitation with its search
record; unsupported implementation remains unfinished work. Physical-phone,
native-v2 and physical-boot acceptance are not inferred from the agreed emulator
or this pipeline's tests.
