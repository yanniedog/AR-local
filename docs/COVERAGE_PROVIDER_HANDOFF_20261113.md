# Provider coverage repair handoff — 2026-11-13

Status: two focused repairs implemented and locally verified; PR publication pending. No Pi,
publication, backup, or runtime changes made by this worker.

## Resume

- Worktree: `C:/code/AR-local-coverage-resilience-20261113`
- Branch: `agent/coverage-resilience-20261113`
- Base: `4e3e394ee192a009946aa9d31b85d9a854c451bb`
- Owner: root task's `coverage` worker. Root owns integration and deployment.
- Existing operator handoff `C:/code/AR-local/docs/INGEST_COVERAGE_HANDOFF_20261113.md`
  is historical and remains untouched. Its section 7 corrects earlier missing-date
  claims: hosted waived publication was landing later than the freshness monitor.

## Verified source findings

1. Recovery has an envelope compatibility mismatch. Normal ingestion accepts
   both `data.products` and `data` product arrays (`extract_products` and
   `response_shape_error`). `cdr_ingest_recovery._index_captured` assumes only
   `data.products`. A list response causes `TypeError`, which reaches the recovery
   controller's broad exception handler and ends remaining provider recovery.
   Fix: reuse normal extraction after existing shape validation; retain all
   pagination checks and the original failure journal. Regression will reuse
   retained Defence Bank products with only the envelope varied. This is a
   reproducible code defect; it is NOT established as today's incident cause.
2. Current source already retains complete raw HTTP attempts, validates original
   body hashes, promotes that evidence out of RAM before export, accepts additive
   fields and unknown enums, negotiates advertised future x-v versions, separates
   detail/index version caches, bounds retries and uses same-day recovery.
   Reimplementing these as if absent would waste effort and risk regression.
3. Existing source has explicit Bank of Melbourne and St.George index-route/page
   size compatibility. Deploying those merged fixes still needs root's runtime
   audit; their existence in main proves no Pi activation.
4. Change-event suppression handled `product_detail` failures but omitted
   `classification_detail`, even though the latter is emitted when ambiguous
   index categories need a detail fetch. A failed classification could become
   false product/fact removal. Both flat and streamed guards now suppress that
   missing product while preserving comparisons for successfully captured rows.
5. `app_payload_details.build_details` emits a curated representation.
   `cdr_clean_export.detail_json` is NOT byte-lossless: generic cleaning removes
   URLs, empty values and normalizes whitespace; allowlisted links and discovered
   document references are restored separately. The raw attempt journal is the
   authoritative full response backstop. Unknown future fields are not
   automatically searchable/displayed; raw retention and consumer feature
   completeness are separate acceptance bars.
6. Broader confirmed design gap, not changed in this patch: `build_outputs`
   computes change events before `cdr_daily` writes the provider-population
   report. A successful but empty index has no HTTP failure, so the current
   failure-only removal guards can emit removals before finalization records
   `UNVERIFIED_SOURCE_ABSENCE`. Follow-up should make the diff coverage-aware
   using the same trusted population identities, rather than infer removals or
   fabricate HTTP failures. This also matters when publishing a degraded day.

## Evidence still needed

- Fresh 14-day per-provider failures from finalized `_exports/ingest-status.json`,
  population report and current Pi commit. Historical fixture failures cannot be
  called current incidents. Root/runtime worker is obtaining these.
- Per-provider missing index/detail counts, categories, last good observation and
  response identity. Diagnose structural drift separately from authentic upstream
  outages/auth-required endpoints; do not retire banks merely to clear warnings.
- Exact deployed source identity and applicable installed launchers/drop-ins.

## Remaining design/acceptance

- Preserve original observations and unknowns; never infer product removal from
  incomplete capture. Same-day retries must append observations/revisions rather
  than rewrite finalized evidence or backdate current upstream responses.
- Test coverage improvement using genuine provider responses and real exports.
  Helper envelope variations are fault-injection tests, not production acceptance.
- Raw documents plus stable field-level facts need a consumer/producer contract
  for watchlist changes, including fees, eligibility, constraints, features and
  document content changes. Unknown schema fields must remain recoverable.
- A provider's documented APIs can change beyond automatic inference. Bounded
  negotiation plus diagnosable schema-drift incidents is supportable; a guarantee
  of complete capture across arbitrary future protocol changes is not.

## Validation checkpoint

- `python -m pytest tests/test_cdr_ingest_recovery.py tests/test_cdr_compatibility.py
  tests/test_cdr_ingest_retry.py tests/test_cdr_ingest_version_cache.py
  tests/test_cdr_ingest_breaker.py tests/test_cdr_ingest_status.py
  tests/test_cdr_product_change_coverage.py tests/test_cdr_product_changes.py -q`:
  **155 passed**, Python 3.10.9, complete terminal summary (3.49 seconds).
- Python 3.11.7: the first five suites **86 passed**, with unrelated installed
  plugin autoload disabled. Adding status/export tests cannot collect because
  that interpreter lacks `jsonschema`; initial unfiltered collection also hit an
  incompatible installed pytest-asyncio. No shared packages were modified.
- Full producer and platform CI remain mandatory on the exact PR head.

Windows process
helper inspected: `process_safety.py` uses native handles on Windows and confines
`os.kill(pid, 0)` to the POSIX branch. No process-control tests planned here.
