# Consumer completeness — retained implementation and remaining rollout

2026-11-14. Review of existing handoffs only; no new source/flag/merge/release or
Pi action. Operational health→provider repair/qualification takes priority.
Read final chronological checkpoints in linked sibling handoffs: their earlier
pending statements are superseded by later local commits. No held commit below
is evidence of selected public delivery, deployed UI or background alerts.

## Preserve these dependency tips

| Slice | Exact retained source / proof | Status |
|---|---|---|
| Snapshot | AR-local PR1154 `bc68d124c17cdeee7bd1ce06ddcf5eb8af680daa`; `C:/code/AR-local-current-product-evidence-20261114` | Reviewed writer/fsync/contract;104 focused tests. Earlier exact CI passed; merge held and will need fresh base/gates. |
| Producer full stack | `C:/code/AR-local-product-evidence-adoption-20261114`, branch `agent/product-evidence-adoption-20261114`, tip `89a03f321d1549e3c03972866ef8f12584069881` atop `cac760a976b8153af106232cc146178111071f33` | Includes traceable held snapshot/normalized/raw/reference dependencies.107 unique focused controls; read-only finalized-source/adoption/status libraries, no daily caller. |
| App full stack | `C:/code/AR-app-product-evidence-ui-20261114`, branch `agent/product-evidence-ui-20261114`, tip `1e011e5d5b3544cd136229c3e54ea2c83b0c93ef` atop detached adapter `08d26ce2b99528cde70c9a773f6ab3edaa1cc760` | Includes normalized reader879ac4a6 and raw9739b789 provenance;240 Jest +132 UI-copy controls, typecheck/lint, independent reviews clear. Local only. |
| Worker route | `C:/code/AR-local-product-evidence-delivery-routes-20261114`, branch `agent/product-evidence-delivery-routes-20261114`, `1ecbd4ca0d132280c8c2e2e2dc0fc80738f08547` | `services/app-data/worker.mjs`,87 controls; immutable valid revision routes only. Undeployed. |

Reconcile these dependency histories deliberately onto final operational producer
and current released app; do not cherry-pick duplicate implementations or replace
intervening repairs. Original commit provenance is retained in cherry-pick notes.
Detailed maps: detached-evidence-adapter-handoff.md,
detached-evidence-integration-handoff.md, product-evidence-adoption-handoff.md,
product-evidence-ui-handoff.md, raw-response-app-handoff.md.

Actual retained protocol proof: detached-evidence-retained-v1/measurement.json
and verification-final.json —2966products/648625facts/3176original bodies,
152assets/51,456,373gzip bytes,4902B rootmanifest,218.2s/163.6MB Windows peak.
detached-evidence-consumer-measurement-v1.json verifies5698facts and239180B raw
body against independent originals. Actual manifest remained latest/no selected
revision; selected_wrapper_tested=false. Expanded3508product/1109392fact scope
and phone memory/performance still need separate evidence-feature measurements.

## Next implementable integration: deliver existing held facts/raw UI

1. **Daily source/adoption transaction.** Wire new `cdr_product_evidence_runtime.py`
   using held `cdr_product_evidence_{delivery_policy,source,preparation}.py`.
   Extend `pi_daily_sync.current_publication_pointer`/pending serialization and
   `maybe_publish_app_payload`→`app_payload_build.build_and_publish_dual` with a
   frozen prepared descriptor. Bind finalized pointer/marker/contract/ledger,
   actual base core/details, lane set/status, prepared hashes and writer receipt
   pin. Do not resolve mutable optional state behind a reserved financial retry.
2. **Complete authenticated inventory.** Connect held
   `app_payload_product_evidence_reference.py` and `_inventory.py` through
   `app_payload_revisions.py`, `app_payload_revisions_github.py`,
   `app_payload_revision_transport.py`, `app_payload_publish.py`,
   `app_payload_archive.py`, staging prune/equality and retained/companion paths.
   Existing manifest-only iterators cannot see detached capability/index/shards.
   Every upload/archive/no-op/prune/readback must use complete bounded inventory
   or explicitly reject the new namespace. Add exact hash-name classification
   to `app_payload_secure_upload.py`; retain outer ARE2/authenticated service.
3. **Optional retry/status.** Strict delivery flags default0. Rates/details may
   publish with explicit pending/failed/unavailable optional status; malformed
   claimed-ready evidence fails the whole candidate. Keep optional pending state
   separate from financial pending. Later readiness produces a NEW revision
   copying financial bytes unchanged, with predecessor CAS/source fence and
   full encrypted readback. No automatic schedule or hidden environment enablement.
   External preparation receipt/resume loader remains unimplemented; current
   adoption contract is trusted same-process with independently retained pin.
4. **App status + real adoption.** Held `productEvidencePublication.ts` and
   `productEvidencePublicationTransport.ts` already bind selected edition and
   lazily fetch capabilities; raw modules are `productResponse{Wire,Index,Transport}.ts`.
   Held UI already wires priced/unpriced/compare disclosure with cancellation,
   actual core/details membership and literal paginated source text. Still wire
   reviewed `optional_product_evidence_status` states into validation/disclosure;
   absent/pending/failed must not all become an unexplained missing pane.
   No eager evidence fetch, persisted huge bodies or pricing-authority promotion.

Keep root manifest/capability64KiB, eager16MiB, separate lazy lane/per-product
budgets, one active/four waiting acquisitions and bounded caches. Raw-only index
8MiB; shards4MiBdecoded/1MiBgzip. Do not force51MB optional transfer through eager
budgets, silently omit over-budget data, or confuse original decoded UTF8 body
with HTTP headers/wire bytes or external-document completeness.

Acceptance: final source CI/reviews; compatible app paired APK/public proof and
Worker immutable-route deployment before opt-in; real finalized selected source
preparation/adoption; all transitive authenticated public readback; phone
on-demand/memory/cancellation journey; actual backup inventory/remote hash+restore.
Use existing product-evidence-runtime-wiring-plan.md for exact seams and tests.

## Still missing after that UI ships

| User objective | Required work and exact starting seam |
|---|---|
| Search/compare every relevant criterion | Generic normalized/raw disclosure does not populate filters or establish applicability. Expand conservative `app_payload_feature_facts.py` / `app_payload_mobile.build_search_index` and app `productFactsCore.ts`, `productFacts.ts` by typed scope; retain conditional/negative/unknown values and unpriced products. Test fees/limits/eligibility exceptions across mortgages/savings/TD without claiming unknown means false. |
| External terms completely available | `cdr_terms` discovery/acquisition/extraction/review and `app_payload_terms.py` exist, but daily `pi_daily_sync` does not supply terms_root. Capture configuration is not delivery authority. Need explicit exact-generation prepared terms/status/retry, validated publication applicability and encrypted-mode compatibility; never add a bare env fallback. Current clauses cap2000chars with truncation disclosed; full document evidence and superseded revision hydration remain gaps. Extend existing `ProductTermsDisclosure.tsx`, `CanonicalTermsComparison.tsx`, `productTermsTransport.ts` without inventing earlier text. |
| Longitudinal arbitrary changes | Transport `bank_product_changes` from existing `cdr_product_changes.py` via bounded product index/pages, source observation+edition+event identity, before/after references, dates, normalization and capture-coverage uncertainty. Existing published activity/rate history is not this ledger. Quarantine historical false removals when capture absence is unverified; ceased CDR is not product withdrawal. Test fee-only/limit-only/quiet condition changes, cosmetic wording, repeated transitions, same-day corrections, missing providers and offline skipped editions. |
| Watchlist alerts for those changes | Extend `notifications.computeChanges`, `subscriptions.computeSubscriptionChanges`, `resolvedRateNotifications` and existing notification permission/deep-link lifecycle with product-change categories, durable edition/event cursor+delivery reservation, retries/dedup and before/after evidence. Fetch compact changed-product indexes first, then watched evidence only. Test restart/offline/multiple revisions/revoked watches/permission and actual background delivery. A diff alone cannot label bank conduct deceptive. |

Operational ingest/publish repair, held facts/raw source access, typed comparison,
terms completeness, change transport and watchlist notifications are separate
completion milestones. Preserve consumer-completeness-next-steps.md for the
original detailed gap trace; no headless D027/old APK/local pack proof closes the
new rendered/background/Drive acceptance requirements.
