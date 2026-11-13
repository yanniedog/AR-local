# Daily publication resilience — progressive handoff

Date: 2026-11-13 Australia/Hobart. Owner: publication subagent of the active
ingest-resilience task. Worktree: `C:/code/AR-local-publication-resilience-20261113`.
Branch: `agent/publication-resilience-20261113`; base `4e3e394`.

## Verified findings and scope

1. `pi_daily_sync.maybe_publish_app_payload` still applies the older bounded /
   reconciled partial policy. `app_payload_observation_gate.publication_allowed`
   rejects every `provider_population_unverified` capture before reconciliation.
2. The checked-in `pi-payload-backfill.yml` and
   `scripts/pi_population_waiver_publish.py` record the owner's 2026-11-07
   decision to publish the best retained capture for every observed date from
   2026-10-29, disclosing partial coverage, without waiving integrity. The
   scheduled runner temporarily wraps the old policy and raw-status classifier
   for exact contract digests. This split leaves natural ingest withholding
   until a later GitHub runner republishes identical captured facts.
3. The waiver's source validation retains completion marker / ledger / contract
   binding and artifact verification. These checks, source immutability,
   same-day selection, encryption, revision transactions and both dated/rolling
   publication checks must remain. No copied-forward product becomes fresh.
4. Existing coverage export transport copies only selected contract fields;
   verify that the unverified provider list and degraded admission reason reach
   the public manifest, rather than relying on failure counts alone.

## Implemented source repair (local verification; runtime pending)

`app_payload_retained_policy.py` integrates the documented standing policy into
the shared gate for sealed partial contracts dated 2026-10-29 onwards. The old
policy remains for older contracts, unknown/missing contracts and failed
finalizations. The standing policy requires positive integer product and eligible
rate counts: a sealed all-empty partial cannot replace usable rolling data.
The existing natural completion-marker check also rejects zero-rate captures;
the shared predicate now enforces this before admission. Archive/failure evidence
remains retained. Marker/ledger/artifact checks remain unchanged; unknown failure
classification no longer withholds the entire retained partial capture after
those integrity checks succeed. No contract, failure record or ledger state is
rewritten or upgraded to complete.

`contract_coverage` and the payload builder now disclose observation state,
per-provider state/identity/failure categories, population uncertainty and the
standing policy with its previous verdict. Endpoint URLs and raw transport
snippets are excluded from the provider summaries. These are additive coverage
fields; consumers still need explicit UI and alert behavior for the metadata.

`pi_daily_sync` also had a separate historical-publication defect: rolling
confirmation (including a newer rolling date) could clear the retry even when
the dated upload failed. It now requires confirmation of the exact dated
manifest revision when the publisher has not already confirmed it. Missing,
wrong-date, wrong-revision and unavailable dated manifests keep retries pending.

Validation checkpoint: 257 tests passed in 23.11s, isolated Windows runner exit
0 with complete JUnit. Suites: retained policy, shared gate, partial accounting,
source verification, recovered resilience, authentication and population
coverage/membership/sanity. New tests exercise tampered artifacts, status bytes,
markers, events, contract identity and paths; source failure evidence remains
unchanged on admission. Fixtures are retained accounting plus existing protocol
controls, not Pi/business-data acceptance. Host Python 3.11.7 lacked jsonschema
and had an unrelated pytest plugin mismatch; tests used existing Python 3.10.9
with plugin autoload disabled, through the required 3.11.7 isolated launcher.

Additional integration suites: 176 passed, 7 skipped in 14.26s (payload builder,
revision publisher, waiver runner, insight contracts, partial-index accounting,
publication lifecycle). Skips were five unavailable 2026-05-19 sample-export
checks and the opt-in real finalized export/macro-store checks. These remain
runtime acceptance gaps. `git diff --check` passed. Hosted full Linux producer,
Windows process/dispatcher, security and exact-head feedback CI remain required.
Local receipts are under the isolated-run directories ending
`20261113-213924-a5400a91` and `20261113-214113-1e1efb16`; complete JUnit files
`publication-focused-results.xml` and `publication-integration-results.xml` are
untracked worktree evidence, not committed source.

Review follow-up: population recovery and pending-source replacement must follow
verified uncertainty, not the obsolete publication rejection string. The two
callers now use an independent uncertainty predicate; exact pending-pointer and
selected parent/reuse/ledger binding and existing budgets stay enforced. Public
population findings are projected to identity/status and last-nonempty counts;
nested historical endpoint URLs remain local. Current-policy invalid contracts
cannot fall back to legacy bounded admission. Expanded follow-up validation:
282 passed in 26.60s with complete JUnit (`publication-feedback-results.xml`,
isolated run `20261113-214950-9e970d57`). PR #1131 remains draft pending exact-head
CI/review and root integration; no deployment is implied.

## Integration dependency and product-detail follow-up

Do not deploy broadened partial admission without the provider agent's
coverage-aware change diff fix. `cdr_outputs.py` previously diffed before
population uncertainty was considered: an empty index could produce false
product/fact removals despite an unverified population. Coordinate through root
and `docs/COVERAGE_PROVIDER_HANDOFF_20261113.md`; preserve actual absences and
uncertainty instead of copying stale rows into today's observation.

Historical false-removal transport audit: `app_payload_build._compute_payload`
reads `banks.products` / `banks.rates` and constructs the core and details
explicitly; no `app_payload*.py` consumer reads `banks.product_changes` or
`bank_product_changes`. Therefore the existing sealed historical removal-event
rows are not sent as events through the current v1/v2 publication path. V2
`_moves` breaks continuity at `None` gaps. Revision summaries separately compare
product/rate fingerprints and explicitly do not imply withdrawal
(`app_payload_revisions_state.revision_delta`). Optional executable/activity
packages have separate feature gates and have not been accepted by this audit;
do not infer their safety from the legacy v1/v2 trace. Existing stored historical
change events remain untouched and need coverage-aware interpretation by any
future consumer that exposes them.

`app_payload_details.build_details` is a curated mobile projection of fees,
features, eligibility, constraints, rate conditions and official document links.
It does not transport every unknown upstream field or the full bundles object.
This is a consumer-projection gap, not proof those source fields were never
captured: provider agent confirms raw HTTP journals are the lossless authority;
`details_json` is cleaned, and generic normalized fact extraction already retains
scalar source facts. `cdr_terms/discovery.py` already handles nested URI arrays.
Next work: inventory retained raw ProductDetail fields against cleaned facts,
detail payload and actual AR-app display/diff surfaces; implement any missing
typed/raw evidence transport within existing payload size/encryption budgets.
Do not append full raw JSON to startup core without reviewing memory/network
budgets and the current consumer. User watchlist delivery is still unverified.

## Remaining acceptance

- Review/implement tests and inspect consumer handling of uncertainty.
- Complete repository CI, review feedback and guarded merge through root owner.
- No Pi operation, deployment, SSH, backup write or publication has occurred in
  this subtask. Runtime acceptance belongs to the root/runtime owner.
- After exact approved deployment, observe a natural run and verify every dated
  asset, rolling date/index, coverage disclosure, immutable history and backup
  receipt. Run Pi dashboard inspection plus `npm run verify:pi`.
- Consumer watchlist notification implementation is a separate acceptance gap;
  never infer bank misconduct from absent data or an unverified source response.
