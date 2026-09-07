# September 7 data quality and automated recovery

The repair is deployed and verified. Remaining upstream failures are still explicit.
The verified source changes are merged in PRs #633, #634, #638 and #639.

## Coverage and integrity

| Check | September 7 result |
| --- | --- |
| Registered providers attempted | 119 |
| Captured products | 2,577 |
| Captured rate rows | 16,013 |
| Brands with captured products | 101 |
| Provider states | 105 complete; 14 partial |
| Terminal source failures | 24 requests across 14 providers |
| SQLite integrity, foreign keys and product identities | PASS |
| JSON and numeric rate validation | PASS |
| Public dated v1, rolling v1, v2 and dates index | September 7; 116 indexed dates |
| Independent public asset verification | 11 downloaded assets matched exact sizes and SHA-256 hashes |
| Economic series | 29 with current source checks; none stale, missing or errored at verification |

The selected observation is `obs-2026-09-07-359b23e789d193d5`. The real recovery
at 09:14–09:30 Hobart retained every original product and rate row, with their
original source timestamps. BankSA then returned an empty catalogue, leaving
20 retained products unconfirmed. The recovery therefore had 25 failures and
was refused by the selection guard. Its immutable evidence remains available as
`obs-2026-09-07-3222a5e50bccfb68`; the better original remains selected.

Consumer cohort filters are intentional: the standard cohort contains 1,995 rate
products across 97 brands. The all-core export has 2,434 products and 15,854 rate
rows; 159 discount components are excluded from that rate cohort. These filters
are distinct from inaccessible upstream products.

## Automated behaviour

- CDR version negotiation, verified register updates and compatible optional
  fields handle ordinary upstream changes. Invalid or conflicting evidence is
  retained as a failure.
- A durable queue retries failed indices and product details with bounded
  backoff, request and response limits. Each tick probes up to four failed
  requests, plus register discovery. A fresh valid response can trigger capture
  subject to cooldown, daily and operating-window limits; repeated identical
  evidence has a two-hour cooldown.
- Same-day recovery reuses verified raw captures and preserves observation
  dates. An empty catalogue cannot silently withdraw previously captured
  products. Selection refuses unexplained loss or additional uncertainty without
  a coverage gain.
- Finalized revisions are reconsidered in verified ledger order before another
  network capture. Upload retries retain the exact approved observation pointer
  across interruption and later days. Pending publication settles first.
- Ingest, backup and service healing share the production lease. A planned
  dashboard pause does not trigger a competing restart. Local recovery failures
  return failure to systemd.
- Economic sources refresh independently with bounded retries and timeouts.
- Backup inventory authenticates successful historical runtime ancestry,
  avoiding unnecessary historical recopying. Cleanup failures are recorded as
  failures while valid component receipts remain preserved.

## Remaining source gaps and credentials

Nine index requests still failed: Aussie, DDH Graham, Darling Downs, Family
First, Geelong, Hume, Police Credit Union, QBANK and Unity. Fifteen detail
requests failed across the source labels BOQ, Sydney, CommFCU, ME Go and SWSbank.
The source failure report retains their
actual HTTP, DNS and schema diagnostics for automatic retry.

The five endpoints returning an API-key error are public product endpoints.
No supported client-key enrollment was found in official documentation, so no
keys were obtained. The matching errors suggest provider/shared-backend
configuration, whose internal cause remains unconfirmed. Verified official
alternatives also failed. See [the access investigation](CDR_ACCESS_20260907.md).

The system can preserve verified observations and retry unavailable sources; it
cannot claim products that the providers have not supplied. The 24 source
failures remain visible and are not represented as successful captures.

## Verification and operational evidence

The exact final Pi bundle passed **394 tests**. Its replay examined **2,786 CDR
HTTP-200 response records**: **2,785 successful JSON responses** passed
compatibility validation, and one non-JSON upstream response was classified
separately and excluded from the successful count. Non-200 responses are outside
this replay count. Tests used private paths with production mounted read-only. The
previous private v6 bundle failed its tests because it lacked saved-pointer
publication support; it was never activated. The corrected v7 bundle preserves
the deployed publication policy and builder argument contract.

The receiver change passed **249 regression tests**. Its first real run on the
preceding runtime finished **PASS / UP_TO_DATE at 10:46:31 Hobart**: observation,
control and macro restores passed, no retained dates were missing, and no
historical backfill was requested. Execution receipt SHA-256:
`b4acfeb5434177f0b3ca1f88853af87f707a4c4369030f9c80f16e36ebb3116b`.

The final runtime `2607ed681d5d3c1da66f9c3c0109cff524e02338` activated at **10:52:51 Hobart** without a dashboard
restart. Exact data hashes were unchanged, live HTTP acceptance passed and the
ingest, recovery and health timers remained active.

The matching backup finished **PASS / UP_TO_DATE at 10:59:32 Hobart**, restoring
10,574 files and 4,908,914,658 bytes, including both September 7 databases. All
108 retained dates were covered, with no historical backfill requested. Its
execution receipt SHA-256 is `701266621fb077221b7acc0f9582710296d939ee98f911b87c7b6b2169c53f46`.

The ordinary-user backup task is Ready. Its principal, triggers and settings are
unchanged: the next natural ingest is September 8 at 01:00 Hobart and backup at
06:00. Those future natural runs have not yet been observed under this runtime;
the completed matching restore proofs were operator-triggered.

The local evidence packet is `C:/code/AR-local-resilience-terminal-0907-1045/runs/2026-09-07-resilience/20260907T010241Z`. Its artifact manifest SHA-256 is
`599fb0479c10cb4ae750c42282968ed9a5a6f66bce3b16b1266954586508a7f9`. Detailed prior evidence and rollback boundaries are in
[the runtime record](CDR_RESILIENCE_RUNTIME_20260907.md) and the append-only
[operations handoff](PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md).
