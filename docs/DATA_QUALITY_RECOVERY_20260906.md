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
