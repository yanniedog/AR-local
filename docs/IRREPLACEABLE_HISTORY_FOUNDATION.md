# Irreplaceable-history foundation

Status: additive implementation; Pi activation and app promotion remain gated.

This foundation does not rebuild, delete, rename, or overwrite any historical
observation or legacy integrity manifest. It adds a new finalization namespace
for observations collected after deployment. Historical corrections must be
separate revision generations derived from preserved source hashes.

## Transaction boundary

The daily path now installs state in this order:

1. Raw holder responses and derived exports finish in a new primary or revision
   export root.
2. Failure provenance, provider observations, populations, and every export
   artifact are validated and hashed into `ExportContractV2`.
3. The contract is written create-once under
   `state/export-contracts-v2/<date>/<generation>.json`.
4. A finalized ledger event is appended create-once under
   `state/ledger-v2/events/<date>/<generation>.json` and its head is advanced.
5. The completion marker is written create-once.
6. `latest-observation` advances; `latest-complete` advances only for a complete,
   reconciled observation.
7. Legacy ledger-v1 emission may run for compatibility. Its failure cannot erase
   or invalidate the mandatory v2 event.

A crash before step 5 leaves recoverable candidate evidence, never a completed
day. The watchdog accepts only a verified completion marker. A retry against any
existing export root creates a revision, including on the same calendar day.

## Truth states

`ledger_state` and `observation_state` are independent:

| Field | Values | Meaning |
| --- | --- | --- |
| `ledger_state` | `finalized` | Ledger-v2 emits only finalized events. `provisional` is reserved for a later candidate layer and is not currently emitted. |
| `observation_state` | `complete`, `partial`, `failed` | Whether the observed market population and failure provenance reconcile |

A partial observation is finalized and retained. It advances
`latest-observation`, never `latest-complete`, and is withheld from compatibility
v1 publication. Missing or malformed failure evidence cannot serialize a
complete observation.

## Field lineage for the foundation

| Published field | Source | Transform / unit | Null or unavailable meaning | Consumer / permitted claim |
| --- | --- | --- | --- | --- |
| `generation_id` | Source-generation digest + prior ledger head | `obs-<date>-<digest-prefix>` | Never null | Ledger, pointers, later v3 manifest; chain-position identity only |
| `contract_digest` | Contract excluding self-identifying fields | SHA-256 | Never null | Ledger binding; no consumer wording |
| `observation_date` | Daily ingest run date | Hobart calendar date | Never inferred | “Observed on” only |
| `observed_at` | Finalization clock | UTC RFC 3339 | Never an effective date | Provenance only |
| `normalization_version` | Producer constant | Version label | Unknown versions block readers | Diagnostics / migration |
| `source_path` | Export root relative to portable data root | POSIX relative path | External machine paths are rejected | Restore and ledger verification only |
| `observation_state` | Failure log integrity + provider-state reconciliation | Complete only when every equation passes | Missing evidence becomes `partial` | Partial may be disclosed, never used as settled market fact |
| `provider_states` | Register-derived attempted holder work + failure records | Complete / partial per attempted provider | Missing population prevents complete state | Coverage disclosure and promotion gate |
| `coverage.products_discovered` | `dashboard-cache/latest.json` `banks_counts.products` | Integer count of export population | Not interchangeable with priced/eligible products | Label exactly as discovered products |
| `coverage.eligible_rate_rows` | `banks_counts.rates` | Legacy rate-row population pending canonical classifier | Not a product count | Audit only until v3 population model lands |
| `coverage.failure_records` | Parsed non-corrupt `failures.jsonl` objects | Integer | Corrupt records counted separately | Coverage disclosure |
| `coverage.failure_provenance_complete` | Full failure-log parse + provider reconciliation | Boolean | False blocks complete state | Promotion gate only |
| `artifacts[*]` | Every file below the finalized export root | Relative path, bytes, SHA-256 | Missing file is corruption | Restore / ledger verification |
| `prior_ledger_head` | Ledger-v2 head before finalization | SHA-256 or null at epoch | Null only for first event | Chain verification |

The existing ambiguous legacy populations are intentionally not renamed here.
They are listed under `unavailable_populations` until the canonical taxonomy and
v3 coverage contract land. This prevents a migration shim from presenting an
unmeasured population as zero.

## Provider identity compatibility

The current CDR register normalizer discards official holder identifiers. Until
the canonical register-identity migration lands, new provider observations carry
a deterministic `legacy-prd:<sha256>` alias derived from normalized endpoint,
legal name, and brand name, plus `identity_status=derived_legacy`. This alias is
not the final `provider_uid` and must be migrated through an explicit alias map;
it must not be silently reinterpreted as an official register identifier.

## Verification and quarantine

`python cdr_ledger_v2.py verify --state <portable-data-root>/state` verifies:

- every event and contract digest;
- prior-head continuity and orphan/loop detection;
- every bound artifact size and SHA-256; and
- containment of all source paths within the portable data root.

The preserved legacy ledger currently reports historical `CHANGED` findings and
one unclassified missing date. This implementation does not “heal” that evidence.
Deployment and rolling promotion remain blocked until a derived, append-only
legacy-audit report explains each changed path and references the preserved
original hashes. No legacy manifest may be regenerated in place.

## Next contract layers

This foundation deliberately precedes:

1. bounded HTTPS ingest and immutable raw-attempt journals;
2. official register IDs and canonical product/rate-tier identities;
3. the shared classifier and typed financial units;
4. reconciled `CoverageV2` populations;
5. immutable candidate generations and `manifest-v3`; and
6. the AR-app dual-read/cache bridge.

Those layers may consume these records, but they may not weaken create-once
semantics or make a partial observation appear complete.
