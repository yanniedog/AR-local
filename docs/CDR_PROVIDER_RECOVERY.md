# Bounded provider recovery

## Scheduling and evidence

| Parameter / Field | Rule |
|---|---|
| Execution mode | Single sequential pass before finalization |
| Global deadline | `180s` (`RECOVERY_SECONDS`) |
| Provider cap | `12` (`RECOVERY_PROVIDERS`) |
| Per-provider share | `(deadline - now) / remaining_admitted` (unused time rolls forward) |
| `eligible_providers` | Sorted providers with retryable retained failures |
| `allocations` | `[{provider, seconds}]` (always initialized as a list) |
| `unattempted` | `[{provider, reason}]` (`provider_limit`, `provider_not_scheduled`, `recovery_disabled`, or stopping result) |
| Journal clearance | Requires positive same-run detail or complete validated index; corrupt/ambiguous journals abort |

## Dependency retries and compatibility

- Only CDR fetches admit HTTP 401 to the full-body retry classifier.
- `cdr_upstream_dependency.py` matches only the exact `EBAU001` tenant-token dependency envelope; generic 401/403 remain terminal.
- Retries stay on the negotiated version (`x-v`) within existing attempt, timeout, and `Retry-After` limits; no version sweep or field coercion.

## Verification

```sh
python -m pytest tests/test_cdr_recovery_fairness.py tests/test_cdr_upstream_dependency.py tests/test_cdr_ingest_recovery.py tests/test_cdr_ingest_retry.py
```
