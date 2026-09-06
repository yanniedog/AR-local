# September 6 data recovery

Operator request: diagnose AR-app's missing September 6 data, repair the root
cause, and improve quality. Work started on September 6 in Australia/Hobart.

The primary observation was captured and finalized at 01:11, but its 31 failed
requests / 2,555 products (1.213%) and 21 partial / 119 providers (17.647%)
exceeded the deployed legacy publication bounds. Rolling v1 and the dates index
remained September 5. V2 remained August 21. The daily watchdog subsequently
reported the finalized observation as complete with no action, without stating
that app publication was withheld.

Retained request evidence showed overload responses from seven Bendigo-backed
brands, an unavailable Family First endpoint, DNS failure for Darling Downs,
an Aussie endpoint returning 404, provider-side API-key errors, inactive products,
and invalid product/rate records. Version fallback hid the actionable 400/422/500
responses behind later 406 responses. Fresh read-only probes at 21:29 confirmed
that all seven previously overloaded brands now return valid product indexes.

## Bounded same-day recovery decision

This is source-capture recovery from recovered providers, using the installed
immutable revision mechanism. It is not an upload-only retry or a code deployment.
ARL-OPS-001 v1.5's same-day recovery boundary applies. The existing pinned
code's revision, raw-evidence preservation, finalization and resilience tests
passed: 92 tests in 7.97 seconds. The production checkout is clean at
`9302890fcc752cbf90da97d597e972c157d913e3`; no ingest/backup process or ingest
lock was present, 5.9 GB memory was available, the dashboard returned HTTP 200,
and the next natural ingest remains September 7 at 01:00.

Authorized operation: start the existing `ar-local-ingest-now.service`, which
invokes the pinned `pi_daily_sync.py --banks-only --force --skip-git-sync`.
The service owns overlap locking, the process group and dashboard restoration.
The finalized primary is preserved and the run writes a separate revision.
Existing quality gates control publication; no thresholds or credentials change.
Validation/stop deadline: 23:00 Hobart, before the 00:30 freeze. Do not deploy a
candidate, change media or backups, advance A3/A4, or promote PR #607.

Primary evidence before recovery (SHA-256):

| Artifact | Digest |
|---|---|
| September 6 completion marker | `cd6f5e2df91b784069382a68a3521fb27e0bc3e883fffba338f7b74a322fa154` |
| Primary SQLite | `4577784854dcba675c903f83a3f4748ef2d4984372b88ea73c6344ffe0755d8c` |
| Primary banks JSON | `2d72498a7dd2bb422b4735e9f707dd99bd253ca4d37090b30d15281c740495f6` |
| Primary ingest status | `d2e06cedcbd57d67979c8824bfe5ac73b4904dead5342f0741eb62b60f72738b` |

Recovery is not accepted until the new observation verifies, these primary hashes
remain unchanged, the dashboard returns, and dated v1, rolling v1 and the dates
index are independently downloaded and checked. Native AR-app rendering remains
a separate verification boundary.

## Recovery acceptance recorded at 22:05 Hobart

The existing service finished successfully at 21:51:25 after restoring the
dashboard. The primary marker, SQLite, banks JSON and ingest-status hashes above
were rechecked and are unchanged. Production remains clean at the protected SHA;
the next natural ingest remains September 7 at 01:00.

The new immutable revision is
`runs/2026-09-06/_revisions/20260906T213439_601735/_exports`, generation
`obs-2026-09-06-1d92edd47cbaa071`. Its completion marker verifies against export
contract `9a0e5b4ba706574f576c2e2497a0b011047f9f6b5b2f8b4a7a8700043ce4e590`
and ledger digest `7e219e47b24ab64b8e13d92e207eb223eb3dba0214b553f5554010fcbee4171b`.

| Component | Result | Evidence |
|---|---|---|
| Source capture | PASS, incomplete coverage disclosed | 2,577 products, 16,012 rate rows; 24 failed requests, 14 incomplete providers of 119 attempted; all seven overloaded Bendigo-backed brands recovered |
| Finalization | PASS | Verified revision marker; zero corrupt/unattributed evidence; sanity comparison has zero structural/high/low anomalies |
| Dated v1 | PASS | Public `app-payload-2026-09-06` manifest and matching core/details metadata |
| Rolling v1 | PASS | September 6 manifest; all seven public assets downloaded, SHA-256 and byte sizes verified, gzip/JSON decoded |
| Dates index | PASS | Public index contains September 6, latest September 6, 115 sorted unique dates with matching count |
| Dashboard return | PASS | `npm run verify:pi` passed after the service completed |
| Native AR-app | PASS | Official signed 1.0.187 APK, version code 258, running on Android emulator; Explore reports `Rates updated · Sep 6, 2026`; Today reports September 6 and explicitly discloses 5 partial / 9 failed providers |
| V2 | FAIL, separately retained | New sidecar built but its upload was skipped with `v1_base_mismatch`; the public v2 channel remains August 21 |
| Pi code deployment | BLOCKED | Existing backup/physical recovery/canary/deployment gates remain applicable; this recovery used installed code only |
| A3 / A4 / PR #607 | Unchanged | A3 remains RUNNING, A4 BLOCKED and #607 remains outside this task |

The revision adds 22 source products and 612 rate rows relative to the preserved
overnight capture. Source export counts include records outside the app's
consumer-rate display; the Today screen shows 2,286 products from 97 lenders.

Current v1 core SHA-256:
`4628e6bcc5e83df32b0b5a3b194146da1c20faff6bd7aab6ea575877d1f44f2c`.
Details SHA-256:
`b5ae153b4afbaa7dad4ffa3681657bb6e3f9dca10708084ea64dfe3de83bfa48`.
Released APK SHA-256:
`c11d4b28afdc81452f62f7c36b4d196c67ae2f9a4a8a792ce2f7583a34f95a4e`.

## Durable fixes and remaining activation boundary

PR #626 preserves the first actionable non-406 provider error, promotes advertised
supported versions within the existing attempt budget, and separates capture
completion from coherent public manifest/index freshness. Replaying the 31 real
retained failure traces preserves every failure while correcting 20 misleading
terminal version errors. Both product CI checks passed; the full local suite had
1,547 passes and 13 skips, and all four compiler-environment failures passed when
rerun using the installed Visual Studio developer shell.

During public acceptance, unmodified control-document URLs continued returning
cached prior data after upload, despite no-cache headers. AR-app already appends
a cache-bypass query to manifest and date-index requests. The follow-up applies
this to monitor and v1/v2 publisher control reads, preserves supplied queries,
and adds regressions modeling stale redirects. It also addresses late #626
feedback: common enablement semantics, configured release targets, required
index count, core/details metadata validation, and index-specific alert details.
The follow-up focused suite passed 142 tests with 7 optional-dependency skips;
its read-only live checker reports September 6 current with no publication issues.

The GitHub freshness check uses merged code independently of the Pi deployment.
Pi retry diagnostics, local watchdog behavior, and publisher cache fixes require
the controlled deployment train; merging is not runtime acceptance. Do not pull
moving main onto the pinned Pi or relax quality gates to activate these changes.
V2 remains a separately failed component until its original sidecar can be retried
under the existing consumer, preservation and publication requirements.
