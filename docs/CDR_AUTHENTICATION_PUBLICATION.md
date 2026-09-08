# Bank authentication failures and GitHub payload publication

Operator decision, 8 September 2026: authentication errors from Geelong Bank,
Hume Bank, Police Credit Union, QBANK, Unity Bank, or any other public CDR
provider must not prevent valid rates from reaching GitHub Releases.

The collector recognises HTTP 401/403/407 and explicit credential-rejection
messages, including API keys, subscription keys and authentication tokens. It
derives per-provider failure categories from the recorded status and response;
provider names and a manually assigned failure label do not grant an exemption.
Long errors retain a compact matching credential clause separately from the
short display snippet; full bodies remain in raw attempt evidence. This keeps
error records inside the recovery queue and retained-journal limits.
Generic authentication failures in 5xx responses remain
retryable server outages unless they explicitly identify API/access credentials.

Finalization retains those categories inside the immutable export contract's
provider states. The shared publication gate checks that provider identities,
failure totals, category counts and provider states reconcile. It then excludes
authentication failure records from the numeric failure budget. A provider is
excluded from the partial/failed-provider budget only when all its recorded
failures are authentication failures. Other failures at that same provider
continue to count. Historical contracts without classification retain their
existing publication policy.
Same-day reuse reconciliation refreshes categories whenever it changes failure
counts, so unrelated recovery errors do not invalidate verified authentication
accounting for other providers.

The daily publisher and backfill publisher share this gate. Dated v1, rolling
v1 and the dates index can advance; the existing v2 sidecar path follows a
verified v1 publication. This change does not activate the separate v3 rollout.

Coverage remains incomplete where data could not be collected. Total failure
and provider counts are preserved. Public coverage includes
`nonblocking_authentication`, identifying the affected providers and the
authentication records excluded from publication budgets. No stale products,
invented rates or falsified complete observations are introduced. Existing
same-day recovery continues to probe unresolved providers.

Register failures, missing or corrupt provenance, unverifiable completion
markers, empty catalogues, unrelated failure limits and actual GitHub
authentication/upload failures remain genuine publication failures.

Verification includes the five retained September 7 authentication responses,
additional credential-error dialects, a 1,200-authentication-error fault
injection, mixed-provider errors, malformed accounting, preserved public
coverage, and a finalized-contract test through daily and backfill publication.
The tests replace GitHub uploads and do not publish test data.
