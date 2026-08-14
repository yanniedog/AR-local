# Read-only historical repairability report

## Executive verdict

Every retained AR-local date can be preserved and imported into the new append-only ledger as a hash-bound **legacy partial observation**, but the earlier history cannot be made equivalent to a modern complete observation.

The correct outcome is:

- Reproject the retained product/rate evidence into new versioned canonical revisions.
- Keep every original file, legacy manifest, dated release, backup, and correction byte-identical.
- Mark all 92 retained observations `observation_state=partial`.
- Never select any historical date as `latest_complete`.
- Quarantine ambiguous identities, rate tiers, units, taxonomy, and mixed-generation evidence.
- Record 2026-05-14 and 2026-06-26 as explicit gaps. Neither is repairable.
- Treat the May 20/26 CBA edits as legacy externally asserted revisions, not original same-day evidence.
- Split/quarantine the two inconsistent 2026-05-19 projections.
- Rebuild histories only from preserved observations, never from the old heuristic history sidecars.

This is not a dead end. The retained corpus is unusually rich: all 1,319,589 flattened rate rows can be mapped back to their retained cleaned CDR rate objects. Product IDs, rate semantics, fees, eligibility, constraints, and effective dates are often recoverable. The limitation is provenance and ambiguity, not absence of most financial content.

Evidence labels below:

- **[P] Proven** directly from preserved bytes.
- **[I] Inference** from retained source code or timestamps.
- **[U] Unresolved** and must be gated before migration/promotion.

No files, repositories, Pi services, live CDR endpoints, or GitHub state were changed or contacted during this assessment.

## Preservation and corpus facts

**[P] Preservation passed.** The committed
[`preservation/PRESERVATION_EVIDENCE_V1.json`](preservation/PRESERVATION_EVIDENCE_V1.json)
binds the operator-held snapshot ID, retrieval procedure, and every preservation
manifest's byte size and SHA-256. Its hash-bound
`manifests/preservation-gate-status-20260814.json` records:

- 1,932 critical files
- 25,586,769,110 verified bytes
- zero byte-verification findings
- 1,171 JSON, 806 gzipped JSON, 97 SQLite, and 96 XLSX semantic checks
- zero semantic restore findings
- exact reproduction of all 58 pre-existing legacy-ledger findings

The snapshot status is correctly `VERIFIED_RESTORABLE_WITH_LEGACY_LEDGER_QUARANTINE`; repository implementation was unlocked, but Pi and promotion remained blocked.

**[P] Historical extent.**

- 92 retained run dates from 2026-05-13 through 2026-08-14
- explicit missing dates:
  - 2026-05-14
  - 2026-06-26
- 92 dated GitHub release mirrors plus the rolling release
- 331 dated/rolling payload assets in the release census; 426 GitHub mirror files including metadata
- all retained run directories contain `_exports` only
- no retained raw HTTP-response corpus, response headers, register response, redirect evidence, or holder-attempt journal

The apparent raw path in each flattened row, such as `/dev/shm/ar-local-1000/.../product-detail.json`, is only a dead machine-specific provenance string. The referenced file is not preserved.

**[P] All-date semantic census.**

- 230,852 product observations
- 1,319,589 rate rows
- 8,077 serialized failure records
- zero invalid `details_json` documents
- zero product ID/name mismatches between flattened products and embedded details
- zero failures mapping a flattened rate by provider, product ID, family, and retained array index back to the embedded cleaned rate object

This means the cleaned product/rate projection is reconstructable. It does not mean the original wire response is reconstructable: `clean_value` removes nulls, empty arrays/objects, arbitrary URL fields, and URL text (`cdr_clean_export.py:53-74`, `140-147`).

## Date and era repairability matrix

| Date/era | Preserved evidence | Repairability | Required treatment |
|---|---|---|---|
| 2026-05-13 | JSON/XLSX/SQLite/dashboard/done/integrity and dated payload | Derivable partial | Import as legacy partial. XLSX has no taxonomy sheet; derive taxonomy only under a new version. |
| 2026-05-14 | No run; legacy code declares it a known gap | Unavailable | Permanent explicit gap. No synthetic observation or neighbouring-day copy. |
| 2026-05-15–05-18 | Rich cleaned product details and cross-format count agreement | Derivable partial | Canonical projection with unit, taxonomy, rate-tier, and provenance quarantines. |
| 2026-05-19 | Two inconsistent projections under one date | Quarantine/split | Main JSON/XLSX/done: 1,632 products, 10,554 rates. SQLite/dashboard/payload/integrity: 1,618 products, 10,514 rates. Preserve both variants; no silent winner. |
| 2026-05-20 | Original backups plus later CBA correction | Original plus unverified legacy revision | Backup bytes are the original observation. Current bytes become a child revision labelled externally asserted, not settled same-day evidence. |
| 2026-05-21–05-25 | Rich exports; no provider/register denominator | Derivable partial | Reproject with versioned classifier and units. |
| 2026-05-26 | Original backups plus later CBA correction | Original plus unverified legacy revision | Same treatment as 2026-05-20. |
| 2026-05-27–06-07 | Rich exports; no complete attempt provenance | Derivable partial | Individual product facts usable; market claims withheld. |
| 2026-06-08–06-10 | Rolling payload directory begins | Derivable partial | Rolling assets are later additions, not evidence that the original observation was complete. |
| 2026-06-11–06-13 | Search and legacy history sidecars begin | Derivable partial | Ignore sidecars as canonical history; regenerate from retained product observations. |
| 2026-06-14–06-19 | Product population jumps from 1,591 to 3,026 on 6/14 | Derivable but cohort break | No cross-boundary trend claim. Cause cannot be proved without register/attempt evidence. 6/16 lacks local payload assets, although its mirrored dated GitHub release has them. |
| 2026-06-18–08-14 | Legacy ledger reports `CHANGED` | Source bytes sound; additive-ledger repair needed | Original recorded artifacts re-hash correctly. Explain additions append-only; never rebuild old manifests. |
| 2026-06-20–06-25 | `ingest-status.json` begins, but contains only aggregate failure counts | Derivable partial | Status is explicitly incomplete and lacks provider/register equations. 6/21 drops to 2,490 products and 36 failures. |
| 2026-06-26 | No run, state marker, or dated release | Irreparable | Permanent unclassified gap. 6/27 is genuinely dated 6/27 in Hobart time; it cannot be relabelled. |
| 2026-06-27–08-10 | Generally 2,905–3,116 products; intermittent dips | Derivable partial | Product-level observations usable. Suppress market trends across unexplained membership changes, including 7/11 and 8/9. |
| 2026-08-11 | 1,975 products, 1,075 failures | Severe partial | Never market-wide. Failure breakdown includes 537 circuit-open and 532 HTTP 406 records. |
| 2026-08-12–08-14 | About 1,861–1,864 products, 1,197 failures/day | Severe partial | Never `latest_complete`. Product detail facts remain usable with explicit partial status. |

Every retained date contains at least 16 failure records, and no date has the register/attempt/provider-state evidence demanded by the new complete-observation contract. Therefore, even the apparently healthy dates cannot be retrospectively upgraded to complete.

## 2026-05-19 mixed-generation finding

**[P] Concrete discrepancy.**

- `pi/data/runs/2026-05-19/_exports/banks-2026-05-19.json`
  - 1,632 products
  - 10,554 rates
  - mtime 2026-05-19T02:27:21Z
- matching XLSX and `pi/data/state/2026-05-19.done.json` also describe 1,632 products
- `local-cdr.sqlite`, dashboard cache, dated payload, and integrity `row_count`
  - 1,618 products
  - 10,514 rates
- dashboard generation occurred on 2026-05-20/21
- 14 products exist only in the larger projection
- 74 shared products have different retained detail content, including differences in `lastUpdated`, rates, fees, features, eligibility, and constraints

The 14 missing products are Defence Bank and Westpac mortgage products.

The public mirrored release at:

`github/AR-local/releases/app-payload-2026-05-19/`

selects the smaller 1,618/10,514 projection.

**Required treatment:** create one immutable historical source record binding all bytes, then expose two named variants:

- `legacy-export-original-20260519` — JSON/XLSX/done lineage
- `legacy-derived-dashboard-20260519` — SQLite/dashboard/public-payload lineage

Do not claim that the later variant is a correction unless a future row-level lineage audit proves its source and transform.

## May 20 and May 26 CBA corrections

**[P] Original bytes survive.**

Examples:

- `pi/data/runs/2026-05-20/_exports/banks-2026-05-20.json.bak-20260527T011635Z`
  - SHA-256 `96a7fdd2e591cf4eec599f0185e11529a0e83b92ac0e2af99688c3e06bc645d2`
- `pi/data/runs/2026-05-26/_exports/banks-2026-05-26.json.bak-20260527T011635Z`
  - SHA-256 `5a2dddf2ea16976bf54481f115383ae2335fb0da13bbebc53ac1baff28713d2e`

SQLite, dashboard, and XLSX backups also survive. The integrity manifests bind both the current and backup files.

**[P] The correction procedure was not same-day-source-only.**
`scripts/repair_cba_fx_anomaly_2026_05.py:2-14`, `23-40`, and `145-177` state that it:

- replaced May 20/26 CBA Foreign Currency Account ladders
- used flanking-day ladders
- cited then-current live CDR corroboration
- modified SQLite, banks JSON, dashboard JSON, and regenerated XLSX

That evidence does not satisfy the new prohibition on invented/refetched history.

Required representation:

1. Backup generation = original retained observation.
2. Current generation = `legacy_external_correction`.
3. Child revision records the exact changed rows, flanking source dates, script commit/hash, and original/current artifact hashes.
4. App wording must not present the corrected values as definitively observed on May 20/26 unless independent preserved evidence later proves that.

## Legacy-ledger `CHANGED` findings

**[P] Root cause is additive publication, not mutation of the originally recorded artifacts.**

The old tool recursively hashes every file below `_exports` (`cdr_ledger_integrity.py:137-143`) and compares the entire current list with the original list (`295-357`). Payloads and logo caches were later added to already-finalized directories, so the list changed.

I re-hashed every artifact recorded by every affected manifest:

- 57 affected dates, 2026-06-18 through 2026-08-14
- 568 originally recorded artifacts
- 18,177,646,221 bytes re-hashed
- zero missing, size-mismatched, or hash-mismatched recorded artifacts

The current directories contain 688 additional files totalling 147,127,281 bytes:

- 172 `app-payload` files — 53,998,080 bytes
- 459 `app-payload-latest` files — 92,522,743 bytes
- 57 `cdr-brand-logos-v2.json` files — 606,458 bytes

The old manifest writer can overwrite historical manifests in place (`cdr_ledger_integrity.py:194-221`). It must never be run against preserved history.

Correct repair: emit an immutable `legacy-ledger-additions-audit-v1` containing, per date:

- old integrity-manifest SHA-256
- old recorded file list and chain SHA
- re-hash result for every old artifact
- every added path, bytes, SHA-256, inferred producer/capability
- explicit result `original_artifacts_unchanged_additions_detected`

Leave all 57 old `CHANGED` findings intact as historical evidence.

## Field-level reconstruction matrix

| Target field/capability | Status | Safe reconstruction rule |
|---|---|---|
| Observation date | Exact | Use directory/manifest date. Never infer a gap date. |
| Original artifact bytes, size, SHA | Exact | Bind snapshot inventory, legacy integrity record, local payload, and GitHub mirror independently. |
| Source observation timestamp | Unavailable | Export `generated_at` is available, but holder fetch time is not. Record it as legacy export time only. |
| Official register response/hash | Unavailable | No retained register response or hash. |
| Provider display/brand text | Exact cleaned projection | Preserve as observed alias text. |
| `provider_uid` | Derivable legacy only | Create `legacy-prd:<hash>` with `identity_status=derived_legacy`; official holder/brand ID is unavailable. |
| Product ID | Exact cleaned projection | All retained product IDs were nonempty and matched embedded product details. |
| `product_uid` | Derivable with version | `derived_legacy_provider_alias + productId`. Do not merge across provider-name changes without explicit alias evidence. |
| Product rename continuity | Partly derivable | Only two provider+productId pairs changed names, but official provider identity is absent. Keep aliases and confidence/status. |
| Product description/category/brand | Exact cleaned projection | Null/empty/URL semantics are not exact because cleaning removed them. |
| Raw retained rate string | Exact cleaned projection | Preserve separately from any typed normalized value. |
| Flattened normalized rate | Exact legacy output | Preserve for audit only; it may embody unsafe heuristics. |
| Product rate unit | Derivable or quarantine | Typed fraction only where source convention is provable. Mixed-scale products are quarantined. |
| RBA unit | Unavailable from product rows | Never infer or interchange with product rates. |
| Rate metric/type | Exact when present | Advertised/comparison/deposit/lending/application fields are retained where published. |
| Ongoing/reversion rate | Unavailable unless explicit | Never derive “ongoing” from a TD or infer a reversion rate. |
| `rate_uid` | Derivable for unambiguous semantics | Hash canonical retained tier/applicability semantics, excluding rate value and array index. |
| Ambiguous rate tiers | Quarantine | At least 763 same-day semantic-collision groups, containing 2,066 rows, have indistinguishable semantics but different values. They cannot support exact alerts/history. |
| Duplicate product observation | Quarantine/deduplicate projection | 2026-05-31 AMP `AMP_LAND_HL` occurs twice with identical Land Loan content; do not invent the apparent missing product suggested by the path text. |
| TD term | Exact/derived/null | Of 8,372 legacy 12-month fallbacks: 552 have exact ISO evidence, 1,564 structured range evidence, 5,796 text-derived evidence, 460 have none. The last group must become null. |
| Product classification | Derivable with version | Run one classifier over retained category, dataset, name, rate semantics, eligibility, and features. Emit status/basis/version. |
| Confirmed Savings | Derivable subset | Exclude confirmed transaction, mortgage-offset, TD, business/restricted, and unknown rows. |
| Ambiguous classification | Quarantine | Do not promote regex-only candidates. |
| Effective date | Exact when present | Preserve `effectiveFrom`/`effectiveTo`; missing stays null. |
| “Changed on” | Only when effective date exists | Otherwise use “First observed on”. |
| Fees | Exact cleaned items when present | Absence is unknown because the exporter removed null and empty lists. Never convert to `$0`. |
| Eligibility/constraints/features | Exact cleaned items when present | Absence cannot prove unrestricted availability. |
| Availability | Unavailable/derivable only from explicit evidence | No general historical availability state exists. |
| Product/source URL | Unavailable | URL values were stripped. Eleven 8/14 products retain `additionalInformation` descriptions, but not their URIs; there were no HTTP(S) strings in the 8/14 banks export. |
| Failure records | Exact serialized projection | 8,077 valid objects; statuses and phases retained. |
| Failure provenance completeness | Unavailable/false | Original line corpus, register denominator, holder attempts, and not-attempted providers are absent. |
| Registered/attempted/responded provider counts | Unavailable | Visible providers and failure-bank names are derivable; complete equations are not. |
| Product/rate/fee row populations | Exact per projection | Keep explicitly named counts and reconcile every derivative. |
| Consumer-eligible/priced product populations | Derivable with classifier | Must publish exclusion equations, not reuse generic “products”. |
| Exact product history | Derivable subset | Only stable product/rate identities with unambiguous units and semantics. Gaps remain null. |
| Product-level history | Derivable broadly | Safe fallback when tier identity is ambiguous. |
| Bank response | Derivable only for stable matched cohorts | Partial endpoints remain unknown; churn is not a move. |
| Spread history | Derivable with membership evidence | Label catalogue rate gap; suppress trend across membership/classifier changes. |
| RBA decisions | Legacy unverified only | Preserved RBA calendar begins 6/22 but lacks decision ID, official source, fetch time, and verification status. |
| Economic observations | Derivable with version and stale state | `pi/repo-state/state/local-macro.sqlite` holds 29 series and 9,855 observations with source URLs/freshness; raw source hashes and unit metadata are absent from the DB. One `consumer_sentiment` point is dated after its recorded fetch and must be quarantined. |
| Historical v1 asset descriptors | Exact | Public/local bytes and hashes are preserved. |
| New v3 asset descriptors | Exact after deterministic rebuild | Compute schema, compressed/inflated bytes, hash, capability, and cohort from the new immutable revision. |

## Unit and normalization hazards

`cdr_rate_normalize.py:17-26` chooses a single divisor from product-level magnitude. Lines 29-39 then apply a second lending heuristic.

Across all retained observations:

- 1,110 embedded raw rates are greater than 1
- 2,690 are between 0.2 and 1
- 11,538 flattened rows were changed by the magnitude heuristics
- 691 product-day groups contain mixed-scale values

Examples include Bank of Sydney lending products mixing `0.0709`, `0.0719`, and `0.719`, and Traditional Credit Union deposit products mixing `0.01` and `2.0`. A product-wide divisor corrupts at least one side of these groups.

Migration must carry:

- `legacy_raw_value`
- `legacy_normalized_value`
- `typed_value`
- `typed_unit`
- `unit_basis`
- `unit_status`
- `normalization_version`

`typed_value` remains null for unresolved mixed-scale evidence.

## Taxonomy hazards

The old taxonomy maps all `TRANS_AND_SAVINGS_ACCOUNTS` to Savings (`cdr_taxonomy.py:54-89`) and the ribbon normalizer infers Savings account type from name/category (`cdr_ribbon_normalize.py:816-848`).

All-date observations include:

- 68,362 `TRANS_AND_SAVINGS_ACCOUNTS` rows in Savings
- 48,223 term-deposit product observations
- 566 `BUSINESS_LOANS` products in Mortgage
- 508 overdrafts in Mortgage
- 110 personal loans in Mortgage
- 92 personal loans in Savings
- 92 credit/charge-card products in Savings
- 92 business loans in TD
- 61 overdrafts in Savings
- 23 clear miscategorized product identities
- 149 explicit transaction/everyday/offset/cash-management name candidates in Savings

The 149 candidates are not all automatically wrong—names such as “Everyday Saver” need structured evidence. The classifier must emit `confirmed`, `ambiguous`, or `quarantined`, not a Boolean regex result.

On 2026-08-14 the preserved populations reconcile as:

- 1,864 discovered product rows
- 1,756 unique product keys with at least one rate
- 1,754 product keys in the v1 core
- two priced gmcu business-loan products excluded by the old Mortgage `DISCOUNT` filter
- 11,389 flattened rates
- 11,267 v1-core rate rows

The v1 manifest reports only the first and total-rate populations. It does not explain the 1,756/1,754 or 122-rate exclusions. V3 must.

## Cross-format and publication findings

**[P] Count-level parity.**

- 91 of 92 retained dates agree across banks JSON, XLSX sheet counts, done marker, SQLite table counts, dashboard manifest, and dated payload counts.
- 2026-05-19 is the sole count-level mismatch.
- Every workbook’s data-sheet counts matched its corresponding banks JSON.
- 2026-05-13 lacks the later taxonomy sheet.

**[U] Row-value parity is not yet proven.**
The audit proved row counts and bank-JSON-to-embedded-rate mapping, not complete value-by-value equality among JSON, SQLite, and every XLSX cell. Full parity is a hard migration gate.

**[P] Public release history was not create-once.**

Mirrored dated releases retain multiple generations on:

- 2026-06-12 — two core assets
- 2026-06-29 — two core and two details assets
- 2026-07-31 — real assets plus 90-byte/78-byte fixture assets

The manifest selects one generation, so the selected public bytes are identifiable, but the tag accumulated extra assets.

**[P] Local/public discrepancy.**

- 2026-06-16 has no local `app-payload` directory in the run partition.
- Its mirrored dated GitHub release contains core, details, manifest, and metadata.

**[P] Rolling 8/14 payload.**

The selected rolling details asset:

`pi/data/runs/2026-08-14/_exports/app-payload-latest/details-2026-08-14-41f0397f4afc.json.gz`

is:

- 3,223,250 compressed bytes
- 31,567,830 inflated UTF-8 bytes
- 1,864 product entries

The run retains multiple 8/14 rolling generations. All should remain preserved; only the manifest-selected set is the historical rolling head.

## Historical history-sidecar assessment

The old history generators are unsuitable as canonical history:

- `app_payload_v2.py:63-105` defines identity using provider display, product ID, category, and dataset.
- It selects a single best rate per product and section.
- `app_payload_mobile.py:118-192` normalizes by magnitude and builds movements from mutable product keys.
- `app_payload_bank_spread.py:19-64` uses legacy `account_class`, name tokens, and magnitude heuristics.
- History scanning uses dashboard-cache banks files (`app_payload_mobile.py:76-103`), so 2026-05-19 follows the later smaller projection.

Preserved sidecar availability:

- search, bank history, and history-banks begin 2026-06-11
- RBA calendar begins 2026-06-22
- bank-spread-history appears only on 2026-08-14

These assets are audit evidence, not source truth. Rebuild histories from the canonical historical revisions.

## Ledger-safe historical import and revision procedure

1. **Freeze inputs.** Work only from the verified snapshot or an independently reverified restore. Re-hash the 1,932 critical files before each migration release.

2. **Create an immutable legacy source manifest per date.** Include:

   - snapshot ID and preservation inventory digest
   - legacy integrity-manifest path and SHA-256
   - every source artifact path, bytes, SHA-256
   - local/public payload-selection manifests and hashes
   - known variants/backups
   - source evidence limitations
   - explicit gap registry

3. **Import each retained date as partial.** Append a create-once `observation_finalized` event referencing the immutable legacy source manifest. Do not reuse or overwrite `state/<date>.done.json` or `<date>.integrity.json`; use a new historical-import marker namespace.

4. **Record gaps separately.** Do not create an empty observation for 5/14 or 6/26. Add an immutable gap registry with status `known_gap` and `unclassified_gap`.

5. **Handle variants.**

   - 5/19: preserve both projections in a variant manifest.
   - 5/20 and 5/26: backup bytes are original; current corrected bytes are child revisions.
   - multi-asset GitHub tags: record every asset, then separately record the manifest-selected generation.

6. **Build a derivation manifest for every revision.** It must contain:

   - parent generation ID, event digest, contract digest
   - every parent source artifact SHA-256
   - classifier, unit, identity, and normalization versions
   - exact tool source commit/digest
   - deterministic configuration
   - field lineage
   - all quarantines and unavailable fields
   - before/after population equations
   - row-level source references

7. **Build canonical artifacts in a new namespace.** Never write below preserved run directories. Use content-addressed product/rate/detail/history shards and reference original hashes rather than copying the 25.5 GB corpus again.

8. **Complete revision validation before import.** The remediation accompanying
   this report now enforces parent event existence, same-date binding, parent
   event digest binding, verified parent artifacts, and revision ancestry/cycle
   checks in ledger-v2. Immutable primary and pre-hardening revision events
   emitted before the new digest field remain readable; unbound legacy revisions
   are warned, never silently upgraded. Historical import remains blocked until
   it also supplies a create-once revision ordinal/tag and exercises these checks
   against the preserved corpus; import tooling must not duplicate or bypass them.

9. **Double-build offline.** Windows and Linux builds from identical source manifests must produce byte-identical hashes. Packaging must have networking disabled.

10. **Append, never heal.** Append imported source event, then its derived revision event. Do not rewrite the legacy v1 chain or convert its 58 red findings to green.

11. **Use separate historical pointers.** No historical import or revision may advance operational `latest_complete`. V3 history indexes may reference partial historical generations with explicit state.

12. **Publish revisions under new immutable tags.** Original dated tags and assets remain addressable. No force-update or pruning.

## Suggested audit/migration tools

- `historical_source_inventory`
  - verifies snapshot and restore hashes
  - emits per-date source/variant/gap manifest
- `legacy_ledger_explain`
  - reproduces the 57 additive `CHANGED` findings
  - proves all originally listed bytes remain unchanged
- `historical_format_parity`
  - canonicalizes and compares every JSON, SQLite, XLSX, dashboard, and payload row
  - detects equal-count/different-membership cases
- `historical_identity_audit`
  - provider aliases, product renames, collisions, duplicate products
- `historical_rate_semantics`
  - raw/legacy/typed values, unit basis, mixed-scale quarantine
  - semantic rate-tier collision report
- `historical_classifier`
  - one shared product classifier with versioned evidence and exclusion equations
- `historical_term_repair`
  - ISO/range/text/null TD term derivation with no 12-month fallback
- `historical_revision_builder`
  - source-hash-bound canonical artifacts and derivation manifest
- `historical_history_builder`
  - stable matched cohorts, no interpolation, no churn-as-move
- `historical_publication_audit`
  - local/GitHub asset parity, selected versus unreferenced assets, inflated caps
- `historical_acceptance`
  - one machine-readable gate report across all 92 observations and both gaps

## Required tests and acceptance gates

Before any historical v3 publication:

- all 1,932 preservation hashes still match
- all 92 retained dates and both gaps appear exactly once in the history index
- zero writes occur under original run, state, restore, or GitHub-mirror paths
- full row-value parity report exists for JSON/SQLite/XLSX/dashboard/payload
- 5/19 variants are explicit and not merged
- May 20/26 originals and legacy revisions remain separately addressable
- every flattened rate still maps to one retained cleaned rate object
- all mixed-unit groups are resolved by evidence or quarantined
- all 763 ambiguous semantic groups are quarantined from exact history/alerts
- all 460 no-evidence TD-term rows serialize `term=null`
- no transaction, offset, TD, business/restricted, or unknown row enters confirmed ordinary Savings
- every population equation reconciles or the revision fails
- no historical observation serializes complete provider/failure provenance
- no missing data becomes zero, unchanged, removed, `$0`, or complete
- deterministic Windows/Linux offline builds match
- revision parent existence/date/digests are verified
- v1 compatibility remains byte-addressable
- public bytes are downloaded and reverified after candidate publication
- no historical revision advances `latest_complete`

## Capacity and performance

Snapshot/run sizes:

- retained run corpus: 25,508,417,873 bytes
- banks JSON: 10,472,836,835 bytes
- XLSX: 947,626,882 bytes
- SQLite: 4,822,470,656 bytes
- run-local gzipped JSON: 179,599,685 bytes
- GitHub mirror: 93,701,756 bytes

The user-authorized 50 GiB free-space floor is bound by the committed evidence
locator to `manifests/capacity-policy-override-20260814.json` (575 bytes,
SHA-256 `06107530fd16f09f900682c4eb36a1005bf52aaf01239eab489eca40dcefeb97`).
The preservation gate recorded 145.065 GiB free after the snapshot, but current
free space must be rechecked before future writes.

Migration should:

- stream one date at a time
- avoid loading all 10.47 GB of banks JSON concurrently
- use bounded worker counts
- checkpoint by source hash
- avoid copying originals into every revision
- store compact canonical rows/shards plus references to source hashes
- cache semantic hashes and cross-format canonical row digests
- keep full-history rehashes outside normal app CI

## Permitted release wording

Historical UI may say:

- “Observed on 14 August 2026”
- “Legacy observation — partial coverage”
- “First observed on …”
- “Derived from the preserved 2026-05-20 observation using classifier vX”
- “Term unavailable from the preserved evidence”
- “Fee disclosure unavailable”
- “Provider identity derived from a legacy alias”
- “Historical catalogue rate gap; membership changed”

It must not say:

- “Complete market”
- “All banks”
- “Changed on” without lender-published effective date
- “No fee” or `$0` when fee evidence is absent
- “Unchanged” across missing/partial endpoints
- “Bank removed the product” when a provider endpoint was partial
- “Exact rate history” for ambiguous semantic tiers
- “RBA verified” for the preserved legacy calendar without official evidence
- “Bank margin”
- “Corrected observed rate” for the May 20/26 externally asserted revisions

## Hard stops

Deployment/promotion must stop if:

- any preservation or restore hash differs
- any source file is missing or unreadable
- row-level cross-format discrepancies remain unexplained
- the historical importer would write into original namespaces
- a historical importer bypasses the completed parent checks or lacks a
  create-once revision ordinal/tag
- a missing register/provider denominator is represented as zero
- a historical observation is marked complete
- ambiguous units, tiers, taxonomy, or terms are coerced into settled values
- 5/19 is collapsed into one silent generation
- 5/20 or 5/26 backups are treated as disposable
- old ledger manifests are regenerated
- packaging accesses the network
- a dated tag is overwritten
- 5/14 or 6/26 is synthesized
- public candidate bytes do not reverify exactly

The central conclusion is firm: the retained history is highly valuable and largely reprojectable, but only as a versioned, partial, evidence-scoped historical ledger. The missing provenance and ambiguous semantics are permanent facts to model explicitly, not defects that code should conceal.
