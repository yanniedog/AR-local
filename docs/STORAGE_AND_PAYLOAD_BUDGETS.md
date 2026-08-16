# Storage and payload budgets

## Non-negotiable ingest priority

- `ar-local-daily.timer` remains independent from storage monitoring and payload publication.
- `ar-local-daily-watchdog.timer` catches missed boots/runs every 15 minutes.
- App payload build, budget, and publish failures remain non-fatal after ingest finalization.
- The capacity monitor is read-only apart from its small state record. It never prunes or moves retained evidence.

## Pi storage policy

`pi_capacity_monitor.py` samples filesystem counters without walking the 33+ GiB evidence tree. It retains 45 daily samples, estimates conservative p90 daily growth, and alerts at:

- warning: below 250 GiB free or 180 days estimated runway;
- critical: below 100 GiB free or 60 days estimated runway.

No retained CDR evidence may be retired until a byte-verified, independently restorable, off-Pi object-locked copy exists. Storage pressure is handled by adding capacity or verified tiering, not silent deletion. Temporary build/cache cleanup must remain separately allowlisted and must never traverse retained run evidence.

## App transfer budget

Budgets are enforced against the compressed/encrypted bytes declared in `manifest.json` and rechecked against local release assets before publication:

| Asset/journey | Budget |
| --- | ---: |
| Manifest | 64 KiB |
| Critical core | 512 KiB |
| Details (on demand) | 4 MiB |
| Search index (on demand) | 2 MiB |
| Other individual asset | 1 MiB |
| All rolling assets | 8 MiB |

Measured 2026-08-16 against the live 2026-08-14 complete manifest:

| Journey | Bytes | 0.5 Mbps | 1 Mbps | 5 Mbps | 20 Mbps |
| --- | ---: | ---: | ---: | ---: | ---: |
| Core only | 241,499 | 3.9s | 1.9s | 0.4s | 0.1s |
| Current standard Home (core + details) | 3,464,749 | 55.4s | 27.7s | 5.5s | 1.4s |
| Deep search (core + details + search) | 4,259,787 | 68.2s | 34.1s | 6.8s | 1.7s |

Times exclude DNS/TLS/GitHub redirect latency, retries, decryption, inflation, JSON parsing, and device scheduling. CI therefore treats them as optimistic lower bounds.

## Delivery sequence

1. Keep core-first startup and cached stale-while-refresh behavior.
2. Publish a small, hash-bound suitability capability so standard Home no longer needs the 3.2 MiB details asset on a cold start.
3. Keep details and search user-triggered, cached by content hash, resumable, and independently replaceable.
4. Keep history date-indexed and fetch only requested windows; never sync the full historical corpus to a phone.
5. Add the same compressed-byte/time report to every future capability before activation.

The suitability capability is a cross-repository contract change and must not be activated until producer and app validators, fixtures, cache behavior, and cold-start tests converge on the same bytes.
