# Bounded provider recovery

The November 14 expanded capture exposed two local retry gaps alongside real
upstream failures. A slow Cairns index exhausted the remaining recovery window
before DDH Graham and Thriday received a turn. DDH's exact server-side tenant
token error was classified retryable, but the numeric HTTP retry predicate
rejected its 401 status before a retry could occur.

## Scheduling and evidence

Recovery still runs once, sequentially, before finalization, with a normal
180-second total deadline and at most 12 providers. Before each provider, its
share is the remaining time divided by the remaining admitted providers. The
existing ingest and HTTP paths receive that earlier deadline. Unused time is
available to later providers; no full daily response cache is introduced.

The report retains `attempted`, initial failure bytes/hash, remaining failure
count, and existing result meanings. It additionally records:

- `eligible_providers`: every provider with a retryable retained failure;
- `allocations`: actual per-provider time grants, in seconds;
- `unattempted`: provider and reason (`provider_limit`,
  `provider_not_scheduled`, `recovery_disabled`, or the stopping result).

`completed` means the recovery pass ran, not that its requests succeeded.
An exhausted provider share remains an explicit capture gap. Corrupt or
ambiguous failure journals still abort reconciliation; successful same-run
details or a positively validated complete index are required to clear failures.
No prior-day values are carried forward and finalized history is never rewritten.

## Dependency retries and compatibility

Only CDR fetches admit HTTP401 to the existing full-body retry classifier.
`cdr_upstream_dependency.py` requires the exact unambiguous EBAU001 tenant-token
dependency envelope; ordinary, altered or mixed authentication errors and403
remain terminal. No credentials are introduced. Caller-supplied retry predicates
outside CDR fetch remain authoritative.

The recognized dependency error retries the same negotiated version under the
existing total-attempt, per-version, request-timeout and Retry-After limits.
It does not sweep API versions. A later success must pass the existing response
envelope and product identity checks.

The original schema failures are independent: BOQ/ME rejected deposit condition
amounts and Bank of Sydney rejected a missing rate applicationType. Existing
diagnostic v6/v5 reads did not recover those products. This change does not
coerce source fields or enable speculative downgrades. Raw bodies, exact errors,
requested/returned versions and the first substantive failure remain preserved.
Provider outages, contradictory inactive details and conflicting identities
remain uncertain; fixing retries does not prove full provider coverage.

## Verification and rollout

Focused tests exercise actual `ingest_brand` and HTTP deadline propagation,
slow-provider fairness, redistribution, global cutoff, skipped-provider reasons,
corrupt-journal abort, exact dependency retries, generic authentication negatives,
version/attempt limits and Retry-After. Captured source fixtures are used for
dependency errors and valid-response shape; timing controls are not live acceptance.

Run `python -m pytest tests/test_cdr_recovery_fairness.py
tests/test_cdr_upstream_dependency.py tests/test_cdr_ingest_recovery.py
tests/test_cdr_ingest_retry.py` (one command). Source tests/CI and merge do not
prove deployment or upstream recovery. A separately authorized fresh capture
must show actual outcomes; preserve its remaining coverage warnings.
