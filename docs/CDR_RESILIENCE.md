# CDR and economic-source resilience

The daily collector treats upstream change as an operational condition. A
provider-specific incident should not require a provider-specific code patch.
It never invents a rate or substitutes yesterday's product for today's failure.

## Request and capture policy

- Negotiate advertised version lists/ranges under the existing request, retry,
  response-size and elapsed-time limits. Cache a successful detail version for
  that endpoint during the run; an invalid hint does not disable negotiation.
- Keep index and detail capabilities separate. New fields and enum values are
  retained, while invalid envelopes, product identity mismatches, malformed rate
  values, conflicting duplicate index IDs and inconsistent pagination are
  recorded failures. Absent or null optional rate sections are accepted.
  Identical index entries are counted against the raw pagination totals and
  fetched once; their counts remain in the observation's diagnostics.
- Distinguish transient transport/service failures from access requirements,
  inactive products, missing endpoints, server validation errors and unsupported
  versions. Do not cycle API versions for an explicit deterministic rejection.
- After the initial pass, retry transient-affected providers once, sequentially,
  with a 180-second shared deadline and a maximum of 12 providers. Reuse only
  successful details from the same unfinished observation. Debug captures with
  page/product caps do not run recovery.
- Retain original HTTP attempts and the first-pass failure journal. Reconcile
  only positively recovered identities; missing details remain missing even if
  they disappear from the second product index. Unrelated provider failures and
  interrupted recovery remain visible. Finalization happens after this pass.
- Preserve HTTPS, public-address validation, same-origin pagination/redirect
  restrictions and the existing publication and append-only ledger controls.

`ingest-status.json` records terminal coverage, failure categories/retryability,
and the recovery outcome. Request evidence distinguishes negotiation attempts
from unresolved product/provider failures. A high number of HTTP requests is
not itself a count of missing products.

## Automatic same-day gap recovery

The existing 15-minute watchdog also checks incomplete current-day observations
between 03:30 and 22:00 Hobart. It persists request reservations and outcomes
before doing work, so a crash or restart cannot reset the day's retry budget.
Provider backoff grows from 15 minutes to two hours. Every failure category stays
eligible for a later probe, including an access or schema error that the provider
may have fixed since the original capture.

Each tick refreshes the public register and probes at most four affected
providers, within a shared 60-second budget. Each GET is limited to two attempts,
12 seconds and 2 MiB. A probe is availability evidence only. It never clears an
observation failure or publishes a rate. A validated response can trigger one
same-day revision, with a one-hour capture cooldown, at most four captures per
day, and a 30-minute process-tree budget that finishes before 22:00.

`pi_daily_sync.py --force --resume-same-day --banks-only` fills gaps using the
selected observation for today. Before any live request it verifies the ledger,
export artifacts and retained request journal. Each reused product must match
an original successful same-day response and its normalized SQLite record.
Only the untouched HTTP body is copied into the new isolated scratch tree.
The new observation records original capture times, source generations, event
digests and body hashes; it does not count reuse as a fresh HTTP request.

Fresh register and product indexes determine which missing or new details to
fetch. An endpoint move requires a unique match for the same brand and legal
entity in the bound register evidence; the old/new endpoints and derived
identities are retained with the reused captures. Temporary register omissions
retain source identity separately from the fresh registered-provider count.
Ambiguous identity changes remain explicit and do not erase the selected data.
A failed index preserves already verified same-day products. Removing an
old product requires an unambiguous, complete fresh listing and retained evidence
that the ID is absent. Repeated identical entries can confirm a retained ID but
cannot prove a withdrawal. Every revision remains in the immutable ledger; a
revision that loses prior product coverage without withdrawal proof does not
replace the selected observation. Transient evidence-read failures can be
rechecked without overwriting the earlier refusal receipt.

Recovery acquires the daily ingest lock and rechecks backup activity before
pausing the dashboard. Timeout cleanup terminates the entire child process tree.
Dashboard restoration also checks lock ownership, so a failed repair cannot
resume the dashboard during another ingest's pause. The watchdog service's
`ExecStopPost` uses the same guarded cleanup after supervisor termination.
The 01:00 daily timer and ordinary-user backup schedule are preserved.

## Economic sources

The daily job refreshes economic sources independently of bank-capture success.
The v2 publication path also attempts refresh, with a persistent one-hour
cooldown so publication retries do not create another source-request loop.
Refresh uses bounded source concurrency, bounded HTTP bodies, a 180-second
process deadline, individual source transactions and a single-refresh lock.

Catalog and payload readers derive freshness from the live macro store. The
date on a newly generated payload never refreshes old source timestamps.
Missing, failed, overdue and retired source definitions remain explicit. Source
checks age out after 48 hours; observation age is assessed against the declared
frequency. Readers see committed WAL data rather than treating the live store
as an immutable export.

RBA columns prefer stable series identifiers, while ABS queries specify source
dimensions and units. Missing or ambiguous columns and unexpected units fail
that source without erasing its last good observations. The retired ABS CPI_M
indicator is not spliced into the complete monthly CPI series. Before replacement,
its exact observations and source metadata are preserved in a hash-verified,
immutable archive within the same SQLite transaction. A failed transition rolls
back the replacement and archive together. Hours worked is
presented in millions; housing lending levels use dollars in millions and a
quarterly frequency.

## Verification and operations

Run `python -m pytest tests/ -q` for producer CI. Real September 7 CDR responses
under `tests/fixtures/cdr-september7` and the source-response fixtures exercise
the upstream incident patterns. Transport/control tests do not substitute for
live capture acceptance.

For an actual release, record the exact source/runtime commits, run an isolated
Linux capture and macro refresh, verify database/ledger integrity, compare
provider/product coverage and publish only a verified observation. Preserve the
previous generation and keep the 01:00 Hobart production timer unchanged.
Complete `npm run verify:pi` and verify the public v1/v2 manifests and asset
hashes after activation.

Client resilience cannot repair a provider's DNS, access configuration or invalid
source database. Such failures remain explicit, with their request evidence,
until a later source response proves recovery. An HTTP error is never evidence
that a provider has no products.

Public CDR product-reference endpoints are documented as unauthenticated. An
error string mentioning an API key does not establish a client enrollment
requirement. Verify the official endpoint and access documentation before
seeking credentials; do not substitute customer account credentials or invent
an authentication header. See the [September 7 access investigation](CDR_ACCESS_20260907.md).

The version negotiation rules follow the [Consumer Data Standards HTTP header
contract](https://consumerdatastandardsaustralia.github.io/standards/#request-headers).

## Unexpected empty catalogues

A valid HTTP 200 empty index is not sufficient to withdraw previously captured
products during same-day repair. The September 7 canary observed this after
Bank of Melbourne negotiated from version 6 to version 5. Recovery retains
those original bodies and timestamps, marks them unconfirmed and queues index
rechecks. The independent selection gate also rejects empty-catalogue withdrawal
evidence, including hash-valid evidence. Nonempty complete listings still
support ordinary product withdrawal under the existing evidence checks.
