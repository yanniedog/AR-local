# Irreplaceable-history foundation

Status: additive implementation; Pi activation and app promotion remain gated.

This foundation does not rebuild, delete, rename, or overwrite any historical
observation or legacy integrity manifest. It adds a new finalization namespace
for observations collected after deployment. Historical corrections must be
separate revision generations derived from preserved source hashes.

## Transaction boundary

The default RAM-staged daily path now installs state in this order:

1. Raw holder responses and derived exports finish in an isolated RAM stage.
2. The completed raw-attempt journal is re-verified and copied create-once below
   `attempt-evidence/raw-attempt-journals-v1/<session-id>` in the staged export.
   Its deterministic promotion manifest binds the source tree SHA-256, every
   source file, and the verified journal head. `ingest-status.json` is then
   rewritten atomically to an export-root-relative path; it never points back to
   the disposable RAM run root.
3. The complete staged export tree is re-hashed, copied into a deterministic
   same-parent temporary tree, re-verified against the unchanged source, and
   renamed create-once into the new primary or revision export root. An existing
   different destination is preserved and refused.
4. Failure provenance, provider observations, populations, and every export
   artifact are validated and hashed into `ExportContractV2`.
5. The contract is written create-once under
   `state/export-contracts-v2/<date>/<generation>.json`.
6. A finalized ledger event is appended create-once under
   `state/ledger-v2/events/<date>/<generation>.json` and its head is advanced.
7. The completion marker is written create-once.
8. `latest-observation` advances; `latest-complete` advances only for a complete,
   reconciled observation.
9. Only after the completion marker verifies may the default successful path
   remove its RAM-stage source and derived-export directories. `--keep-ram-stage`
   retains both for operator inspection.
10. Legacy ledger-v1 emission may run for compatibility. Its failure cannot erase
   or invalidate the mandatory v2 event.

A revision event must name an existing generation from the same observation
date and bind that parent event's SHA-256 digest. Runtime and JSON Schema checks
reject missing, cross-date, self, or structurally invalid parents; full-ledger
verification also walks revision ancestry and reports loops. Existing primary
events remain readable without revision metadata.

Immutable revisions emitted before parent-digest hardening also remain readable
and recoverable. They are reported as `LEGACY_UNBOUND_REVISION_PARENT`; their
missing binding is never invented or written back. The append path requires the
digest for every new revision, so this compatibility rule cannot emit new
unbound history.

A crash before step 7 leaves recoverable candidate evidence, never a completed
day. A retry deterministically resumes the same generation when its immutable
source digest and prior head still match. Recovery verifies and completes only
the missing suffix of the transaction: event to head, head to marker, or marker
to pointers. It never appends a second event for the same generation and refuses
ambiguous orphan events. The watchdog accepts only the exact verified marker
selected by `latest-observation`; a stale primary marker cannot hide a verified
revision. A genuinely different same-day source generation creates a revision.

## Truth states

`ledger_state` and `observation_state` are independent:

| Field | Values | Meaning |
| --- | --- | --- |
| `ledger_state` | `finalized` | Ledger-v2 emits only finalized events. `provisional` is reserved for a later candidate layer and is not currently emitted. |
| `observation_state` | `complete`, `partial`, `failed` | Whether the observed market population and failure provenance reconcile |

A partial observation is finalized and retained. It advances
`latest-observation`, never `latest-complete`, and is withheld from compatibility
v1 publication. Missing or malformed failure evidence cannot serialize a
complete observation. Each ingest creates an explicit empty failure journal
before holder work; a missing or unreadable journal is incomplete provenance,
not authoritative evidence of zero failures.

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
| `coverage.register_sources_attempted` | All configured CDR register discovery endpoints | Per-attempt URL, mode, outcome, response bytes, and SHA-256 | Missing attempts make provenance incomplete | Audit and promotion gate only |
| `coverage.register_sources_complete` | Successful, hash-bound register responses | Integer | Fewer than attempted means a partial register population | Coverage disclosure and promotion gate |
| `coverage.register_provenance_complete` | Every configured register source completed with retained digest evidence | Boolean | False forces `partial` even if one source returned usable holders | Promotion gate only |
| `ingest-status.json.raw_attempt_journal.path` | Verified RAM-stage attempt journal | POSIX path relative to the finalized export root | Missing for legacy ingest only; a current dangling RAM-root pointer is rejected | Audit lookup only |
| `ingest-status.json.raw_attempt_journal.source_tree_sha256` | Canonical inventory of the sanitized journal files | SHA-256 | Missing blocks current promotion | Evidence identity and replay verification |
| `attempt-evidence/.../promotion-manifest.json` | Source inventory + verified journal summary | Canonical JSON, create-once | Missing or conflicting bytes block promotion/finalization | Audit and restore verification |
| `artifacts[*]` | Every file below the finalized export root | Relative path, bytes, SHA-256 | Missing file is corruption | Restore / ledger verification |
| `prior_ledger_head` | Ledger-v2 head before finalization | SHA-256 or null at epoch | Null only for first event | Chain verification |
| `completion_marker_path` | Finalizer-selected marker for this exact generation | State-root-relative POSIX path | External, absolute, or mismatched paths are rejected | Recovery and watchdog truth boundary |

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

For newly ingested observations, the export contract's `artifacts[*]` inventory
also binds `ingest-status.json`, the promotion manifest, and every sanitized
attempt-journal event, body, index, and chain-head file. Promotion replays accept
only a byte-identical verified journal at the deterministic destination. A crash
may leave a deterministic temporary tree or an installed candidate, but retry
finishes from those same bytes; it never deletes or overwrites the source or an
existing finalized destination. Failed or zero-rate RAM stages are retained in
place for diagnosis. A same-day retry fails closed while that non-empty stage
remains, instead of deleting it; the operator must archive or clear it
explicitly. No new time-based quarantine or deletion policy is introduced by
this layer.

The preserved legacy ledger currently reports historical `CHANGED` findings and
one unclassified missing date. This implementation does not “heal” that evidence.
Deployment and rolling promotion remain blocked until a derived, append-only
legacy-audit report explains each changed path and references the preserved
original hashes. No legacy manifest may be regenerated in place.

The read-only feasibility census and date-by-date repair rules are recorded in
[`HISTORICAL_REPAIRABILITY_REPORT.md`](HISTORICAL_REPAIRABILITY_REPORT.md). Its
qualified verdict is authoritative for any later importer: retained dates may
be represented only as hash-bound legacy partial observations and derived
revisions; they must never advance `latest-complete`.

App publication has no export-directory fallback once this foundation is in
place. It requires `latest-complete` to select an exact marker whose contract,
ledger event, and source artifacts all re-verify. The Pi installer provisions
and imports the system-Python Draft 2020-12 validator before activating services.

## Next contract layers

This foundation now includes bounded HTTPS ingest, immutable sanitized raw
attempt journals, and their hash-bound promotion into finalized export
artifacts. The remaining contract layers are:

1. official register IDs and canonical product/rate-tier identities;
2. the shared classifier and typed financial units;
3. reconciled `CoverageV2` populations;
4. wiring finalized observations into the dormant immutable v3 candidate
   builder and transactional promoter; and
5. the AR-app dual-read/cache bridge and an explicitly approved activation.

The dormant promoter now supplies the repository-side publication boundary:
create-once candidate releases, verify-only shared content, public byte and
historical tag-target re-verification, complete acyclic ordered ledger-lineage
enumeration, recoverable append-only owner leases and control history, a
verified complete-dates index,
and rolling-pointer compare-and-swap last. Both pointer heads come from the full
verified release census, including a candidate left public by a prior crash,
rather than from the invocation candidate alone. Its workflow
is manual-only, defaults to validation, and requires both an explicit execute
input and the protected `app-payload-v3-promotion` environment. No Pi service,
daily producer, deployed v1 release, or AR-app reader invokes it in this slice.
The allowlisted `.github/workflows/app-payload-v3-candidate.yml` producer is
intentionally absent pending its own pipeline review, so workflow promotion is
not activatable yet; an arbitrary Actions artifact cannot substitute for it.
Activation is independently blocked by an intentionally unset AR-local/AR-app
contract-parity lock. The currently frozen consumer expects a different v3
pointer/manifest shape, so the producer and consumer schema sets must first
converge and their exact reviewed SHA-256 digests must be pinned. Until then,
`--execute` fails before any repository read or write even if run provenance and
environment approval are otherwise valid.

A third independent, structured publication-store contract is also unset. The
current repository cannot enable immutable releases without breaking the mutable
v1 compatibility channel, leaving an uncloseable publish-between-read-and-write
race in same-repository draft uploads. Merely assigning this contract remains
fail-closed until a separately reviewed adapter verifies either a dedicated
immutable v3 store/repository or a Git content-addressed commit/branch design;
the execute workflow stops before provenance lookup or candidate download.

The current release adapter is dormant scaffolding, not an activatable
publication store. Its orchestration validates the prospective published census
plus the local candidate before creating any tag, draft, asset, or control
commit. The invoked candidate is staged as an exact resumable draft, its complete
asset inventory is uploaded and hash-checked, and publication occurs last; a failed draft is preserved and
never auto-deleted. Published releases are verify-only and cannot receive later
assets. The current golden builder's shared `app-payload-gen` capability URLs
therefore must already resolve to exact immutable bytes. A future reviewed
candidate-artifact builder must emit candidate-owned capability URLs and bundle
those assets for draft staging before activation; this slice does not repurpose
the golden builder or append to the shared release.

The two-hour owner lease is renewed by exact-head compare-and-swap before every
release mutation, prepared control commit, and final ref install; all GitHub
commands are bounded to 60 seconds and ambiguous write outcomes are reconciled
against exact remote state. A displaced owner is fenced before its next asset
or control write and cannot release its successor's lease.

An independent artifact-byte binding is also intentionally absent. Activation
requires GitHub's archive digest to be reconciled to an exact expanded-tree
inventory from the canonical candidate workflow; a matching run head alone is
insufficient. The complete candidate census uses two paginated/batched API
listings—release metadata/assets and direct matching tag refs—rather than
re-querying every historical release and tag. Public manifest/capability bytes
are still re-downloaded, while API request growth remains bounded as retained
history passes one thousand revisions.

Those layers may consume these records, but they may not weaken create-once
semantics or make a partial observation appear complete.
