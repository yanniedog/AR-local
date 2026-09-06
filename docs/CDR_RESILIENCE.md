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
  values, duplicate index IDs and inconsistent pagination are recorded failures.
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

Client resilience cannot repair a provider's DNS, API-key configuration or
invalid source database. These remain attributable coverage gaps, checked again
on the next scheduled capture. Changing code or loosening validation is not
the routine response to such incidents.

The version negotiation rules follow the [Consumer Data Standards HTTP header
contract](https://consumerdatastandardsaustralia.github.io/standards/#request-headers).
