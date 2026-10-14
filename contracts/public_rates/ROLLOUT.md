# Public pricing rollout and evidence ledger

## Current boundary

Collection and public capability publication are disabled by default. The
reviewed programme allowlist is empty. No schedule, daemon, Pi service or accepted
public payload is changed by a local build or by merging the producer extension.
The app change is staged until the agreed shadow and release gates are evidenced.

The public 2026-10-14 baseline represents 116 banking providers across all three
categories (348 entries), including unavailable and partial sources. It reports
legacy observation availability separately from validated pricing. It does not
endorse legacy prices. The public sizing fixture preserves 2,934 product
identities; its legacy-row counts are transport controls, never pricing evidence.

Retained lender acceptance material covers NAB, CommBank, Westpac, ANZ and ING
reference sources, NAB's public high-LVR assessed range, ANZ savings base/bonus,
and public ANZ/NAB term deposits. Other providers remain discoverable and their
coverage gaps remain explicit until their rules have public evidence and review.

## Review and verification

Run the producer's documented `python -m pytest tests/ -q` and the consumer's
`cd mobile && npm run ci`. On Windows use the documented isolated runner for
process-control tests. Retain complete stdout, stderr, exit status and JUnit;
an exit code without a completion marker is insufficient. Keep the existing
10,000 ms audit failure threshold and resource guards.

The shared resolver golden file binds original public response hashes and
independent expected arithmetic. Metamorphic future dates, corrupted downloads,
transport-only archives and simulated approval packets are unit tests. None
establishes a natural daily ingest, operator approval or installed-app acceptance.

Review adapters using the checked-in source register, exact public fixture
hashes and reviewed semantic shapes. Price-only changes within those shapes can
be interpreted automatically. Changed headings, units, formula relationships,
applicability or material footnotes require code, public fixtures and passing
validation. There is no manual rate override. Unknown or contradictory source
conventions stay unresolved.

## Existing operational lanes

After exact-commit Pi admission and operator approval, use the existing finalized
terms capture and guarded acquisition worker. `AR_LOCAL_PUBLIC_RATES_COLLECT=1`
opts that existing lane into deterministic compilation and registered public
reference checks. Do not create or enable another schedule. Generic document
interpretation jobs are never used for registered rate processing.

Every public provider/category participates in discovery, even when there is no
rate. Unique registered URLs share captures. Weekly unconditional refreshes
verify retained validators. Failed checks immediately remove current claims;
48 hours without successful verification makes values stale. Deferred work
retains its durable identity and appears in coverage. Collection limits are
300 seconds and 64 MiB per ingest; each document has a 16 MiB, 30-second,
five-redirect ceiling. Stricter existing admission limits win.

The derived candidate root is immutable and generation/hash bound, with bounded
programme/evidence chunks inside the existing evidence root. Its mutable
convenience file is only a checked pointer. Public publication loads approved
subsets; it does not place the entire retained archive in the app. A deferred
rewrite leaves the last complete candidate intact.

After a complete candidate changes, the existing durable publication lane can
queue a payload-only revision for the same selected ingest. Its source key
includes the candidate hash. The production lock, completion/export contract,
canary, immutable revision, publication/readback and pointer guards still apply.
An obsolete generation, corrupt chunk or unapproved pricing structure cannot
silently replace the accepted payload.

## Natural shadow and release gates

For each proposed programme, collect three consecutive natural daily ingest
generations. Retain controller trigger evidence, source URLs/bytes/hashes and
locators, extraction versions and candidate hashes. At least one cycle must have
unchanged source bytes. Each cycle needs independent public-source reproduction
and matching scenario/resolver results with no unexplained discrepancies.

The report contract is checked by the read-only tool:

```text
python scripts/validate_public_rate_shadow.py --report <shadow-report.json> --programme-id <semantic-programme-id>
```

Report cases include programme, scenario, as-of timestamp, expected result,
public evidence and the separately retained independent reproduction hash. A
historical/local-input calculation cannot verify current public pricing. Manual
replays and simulated fixture days cannot satisfy this gate.

Only then release the compatible app and independently verify published APK
bytes/hash, manifest metadata and source commit. Exercise native-device discovery,
local-input migration/privacy, unresolved pricing, cost assumptions, notifications,
offline refresh and performance. Web export and CI do not prove native acceptance.

Add the reviewed programme structure, approved shadow report and shipped consumer
commit to the checked-in publication policy through repository review. The
separate controlled receipt binds that policy, exact current candidate/generation,
consumer APK/metadata/native acceptance and explicit operator/canary approval.
Captured `enabledProgrammeIds` must remain empty. Activate progressively through
the existing publisher only after these bindings pass.

An operator-approved template can permit subsequent validated price updates.
Those receipts still bind the exact new candidate and retain the original final
shadow candidate, policy, consumer and operator/canary evidence. Same-day refreshes
can publish failures/warnings and price changes without pretending another shadow
cycle occurred. Any changed programme structure requires fresh review.

## Rollback and status reporting

Disable the capability through the existing controlled publication configuration
and restore the accepted immutable revision. Preserve public evidence, reviews,
programme history and private on-device entered rates. Reverting publication does
not reset the database or repurpose a saved semantic selection.

Report source acquisition, extraction, rate resolution, cost completeness,
freshness and publication independently. Record priced and unresolved counts;
partial loading cannot support a lowest-rate/cost claim. Keep lender comparison
rates separate from payable nominal interest. Unknown fees remain unknown and
range/quote-required products remain outside complete-cost rankings.

The three natural shadows, consumer release/hash readback, native acceptance and
operator activation are pending until their real receipts exist. A local test
pass must not be recorded as any of those outcomes.
