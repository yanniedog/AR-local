# AR-local Pi Ingest and Payload Recovery Runbook

## Document control

| Field | Value |
|---|---|
| Document ID | `ARL-OPS-001` |
| Version | `1.4` |
| Status | Controlled execution plan |
| Effective date | `2026-08-27` |
| Owner | AR-local operator |
| Time zone | Australia/Hobart |
| Implementation model | `gpt-5.6-sol`, Max reasoning |
| Source baseline commit | `97c8311e4e14c5cd6ca2aeec7bd406909f502c05` |
| Document-containing commit | Resolve with `git log -1 --format=%H -- docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md`; record the returned immutable commit in every execution record |
| Controlled plan SHA-256 | `b234469085141f8799a7744f20980728bf829970758e904126b811dca7f98218` |

The controlled plan SHA-256 is calculated over UTF-8 text without a byte-order
mark after normalising CRLF/CR to LF and replacing exactly two occurrences of
the published digest with `PLAN_SHA256_PENDING`. This avoids an impossible
self-reference and cross-platform drift while detecting every other byte. The
raw file SHA-256 is also recorded in each execution/deployment record.

This is the complete authoritative plan; chat, summaries, and recollection do
not override it. Read it fully before any covered operation.

## Change control

- Completed evidence is append-only and must never be rewritten.
- A deviation requires an append-only decision entry stating the reason, risk,
  compensating controls, revised acceptance criteria, authorisation, and time.
- Every execution record and deployment acceptance manifest must contain the
  document ID, version, document-containing commit, controlled plan SHA-256,
  raw file SHA-256, candidate code SHA, operator, timestamps, exact commands,
  evidence paths and hashes, result, and deviations.
- Allowed results are `NOT_STARTED`, `RUNNING`, `PASS`, `FAIL`, `BLOCKED`, and
  `ROLLED_BACK`.

### Decision ledger

| ID | Time | Decision | Reason and risk | Compensating control | Authorisation |
|---|---|---|---|---|---|
| D-001 | 2026-08-23 | Use a canonical embedded plan checksum and dynamically resolve the immutable document-containing Git commit. | A file cannot contain its own literal raw SHA-256, and a commit cannot contain its own future commit ID, without changing the value being identified. A placeholder would falsely imply verification. | Canonicalise only the checksum field; record both canonical and raw hashes plus the resolved commit in every external execution/deployment record. | Required to make the requested document control truthful and reproducible. |
| D-002 | 2026-08-23 | Keep this controlled runbook immutable; record execution and deviations in external append-only evidence. The approved source plan remains reproduced below, but its instructions to recreate or append to this file are provenance text after merge. | Recreating or appending evidence to the controlled file would invalidate its version and checksum. Specialist review also found that the pinned producer cannot provide #506/#507 guarantees and that inherited Pi environment could defeat canary isolation. | Mandatory execution clarifications below supersede only those ambiguous mechanics. Any substantive plan change requires a new document version, checksum, and documentation PR. | Approved implementation of the user requirement for a literal drift-resistant plan. |
| D-003 | 2026-08-25 | Make the product-day the atomic publication unit. Publish every independently valid current product, quarantine or omit only the affected product, and disclose attributable provider and product gaps. Remove numeric failure-count and failure-ratio eligibility thresholds. | The v1.0 bounded-partial gate withheld otherwise valid observations and could strand the app on an older date. Conversely, relaxing the gate without positive membership proof could publish corrupt or stale products. | Require a ledger-bound `ProductAccountingV1` membership sidecar, exact database/sidecar/payload reconciliation, product-level validation, no stale carry-forward, transactional public verification, an upgraded AR-app before activation, staged feature modes, and whole-observation holds for control-plane failures that cannot be scoped safely. | Direct operator decision after the 2026-08-24 publication gap and the 2026-08-25 accounting-disclosure mismatch. |
| D-004 | 2026-08-25 | Use the physically separate Windows laptop as the primary off-device pull-backup target, while preserving the existing 32 GB historical recovery-image candidate for later boot proof. Maintain a strict 50 GiB laptop free-space floor and store immutable, compressed, hash-manifested observation packs plus current control/configuration packs instead of thirty full physical-disk images. | The Pi has no adequate separate mounted disk: its 59.7 GB USB and 29.7 GB MMC devices are smaller than the 72.7 GiB authoritative data set. The laptop has enough measured capacity, already holds recovery material, and avoids writing credentials or network shares onto the Pi. Risks are laptop unavailability, single-site loss, ransomware, interrupted network transfer, and divergence between the historical boot image and current data layer. | Laptop initiates every pull over SSH; the Pi never receives laptop credentials. Use immutable per-observation packs, canonical source and archive hashes, atomic `.partial` promotion, continuous free-space enforcement, SQLite-consistent copies, secret exclusion, restore drills, freshness receipts, and a fail-closed scheduler. Preserve but quarantine the known-short failed image; do not call the exact-size historical image current or bootable until A4 proves it. A later independent site remains required for full disaster resilience. | Explicit operator direction to use the existing laptop backup and retain approximately 50 GB free. |
| D-005 | 2026-08-25 | Correct the laptop backup bootstrap before its first data transfer: preserve every retained completed and terminal-failed run plus `runs-archive`; reserve archive and scratch space simultaneously; verify every canonical manifest metadata field; durably flush every commit boundary; and make observation, control, and macro freshness independent scheduler gates. | Late review of v1.2 found that a latest-completed-only interpretation could lose older or failed raw evidence, that the stated capacity check omitted simultaneous archive bytes, that restore comparison omitted mode/time/ownership metadata, and that an observation-only no-op could leave control or macro recovery data stale. The same review found ambiguous DOC-02/DOC-03 and mounted-storage wording. | No backup transfer or schedule is accepted under v1.2 alone. Use DOC-03 for this document lineage; D-004/D-005 explicitly supersede the retained mounted-storage instruction. The receiver inventories all retained run namespaces, treats terminal failures as diagnostic evidence rather than publishable observations, uses worst-case dual-copy capacity, compares tar metadata and extracted bytes, flushes file and directory metadata in dependency order, and records independent freshness identities. | Mandatory safety correction from the repository's post-merge substantive review before first execution. |
| D-006 | 2026-08-27 | Treat recovery as a multi-day controlled program while preserving the natural 01:00 ingest as an independent, non-negotiable daily production obligation. Daily capture takes precedence over every development, remediation, canary, deployment, backup, and recovery-proof activity. | The upstream CDR exposes only the current Australia/Hobart calendar day's data. At midnight that source data disappears and the next day's data replaces it. A missed capture therefore creates an irreversible source gap; later development success, a forced rerun on another day, or a reconstructed payload cannot recover the lost source observation. Multi-day work also creates repeated collision risk around the daily timer. | Use the v1.4 daily operating cycle, immutable per-day evidence, an enforced pre-ingest freeze, independent capture/finalization/publication outcomes, and same-day-only controlled recovery. Pause phase work whenever required to protect the natural ingest. Never disable or repurpose the production timer for development. Record a missed day as an immutable source gap rather than substituting stale or next-day data. | Direct operator instruction on 2026-08-27. |

## Version 1.4 multi-day continuity and daily capture amendment

This section is normative for all work performed on or after 2026-08-27. The
recovery program is expected to span multiple days or weeks. No phase, slice, or
pull request is expected to finish in one day. The safe unit of progress is one
small, bounded, evidenced change that leaves production ready for the next
natural ingest. Unfinished work remains `RUNNING` or `BLOCKED`; schedule pressure
is never permission to widen a slice, waive a gate, or deploy near an ingest.

The document-control execution ID for this version is `DOC-04`. Existing
completed evidence retains the plan identity under which it was created and is
never rewritten. New executions started after the v1.4 documentation merge use
the v1.4 plan commit and controlled digest, subject to the explicit transition
rule below.

### Irreversible upstream availability boundary

- The upstream CDR exposes only data for the current calendar date in
  `Australia/Hobart`.
- The upstream day changes at 00:00. Once midnight passes, the previous day's
  source data is no longer available from that upstream interface.
- A successful 01:00 ingest therefore captures the only live source observation
  available for that day. It is not merely a scheduled convenience.
- A missed day cannot be repaired by assigning the next day's data to the prior
  date, copying a prior payload, carrying a stale product forward, or changing a
  manifest date. Those actions would create invalid provenance.
- Historical public payloads, local exports, backups, or caches may preserve
  evidence already captured, but they do not recreate source evidence that was
  never captured.
- If a day's source window is lost, record an immutable source-gap entry with the
  affected date, known cause, available evidence, impact, and recovery limits.
  Never conceal the gap or label reconstructed data as a live CDR observation.

### Non-negotiable daily production obligation

The natural `ar-local-daily.timer` 01:00 ingest continues every day throughout
all remediation phases. It is independent of whether the current development
slice is `NOT_STARTED`, `RUNNING`, `PASS`, `FAIL`, `BLOCKED`, or `ROLLED_BACK`.
No phase owner may disable, postpone, mask, stop, replace, or repurpose that
timer to make development easier. Production stays on the last-known-good
commit until a later candidate satisfies every deployment gate in this runbook.

Daily capture outranks:

1. canary or shadow work;
2. pull-request completion and CI;
3. deployments and rollback exercises;
4. manual ingest experiments;
5. backup, restore, or clone tests;
6. package, operating-system, service, network, or storage maintenance; and
7. convenience or pressure to finish a phase on a particular day.

When any work might threaten the next natural ingest, stop or defer that work.
Protecting the day's only source window is the controlling acceptance criterion.

### Repeating daily operating cycle

Every Australia/Hobart calendar day uses the following cycle until the complete
recovery train is closed:

1. **After the prior natural ingest is validated:** select at most one bounded
   slice whose stop point leaves production unchanged or demonstrably safe.
   Record its planned files, commands, resource limits, rollback boundary, and
   latest safe stop time before starting.
2. **Daylight work:** perform documentation, isolated development, review, CI,
   and approved non-production proof. Runtime deployment remains subject to the
   stricter daylight, backup, rollback, soak, and natural-ingest gates elsewhere
   in this runbook.
3. **Pre-freeze closure:** stop mutating operations early enough to restore a
   clean, healthy, known state and complete evidence. A task that cannot finish
   safely before the freeze is left `RUNNING` or `BLOCKED` and resumes on a later
   day; it is not rushed through.
4. **00:30 freeze:** from 00:30 until the natural ingest is terminally complete
   and production validation has finished, perform read-only observation only.
   No deployment, canary, manual ingest, service restart, package change,
   publication manipulation, backup transfer, restore drill, clone test, or
   storage maintenance is permitted.
5. **01:00 natural ingest:** allow the production timer to start exactly once.
   Observe locks, service state, resource pressure, dashboard pause/return, raw
   capture, finalization, and publication without competing with the job.
6. **Post-ingest validation:** independently record raw capture, observation
   finalization, database/contracts/ledger/pointers, dashboard return, and every
   public publication component. A zero process exit is not by itself a pass.
7. **05:00 laptop protection:** when the laptop is available and the A3 task is
   proven, the scheduled pull normally creates and verifies a new generation for
   the newly captured observation and any changed control or macro identity.
   `NO_BACKUP_DATA_WRITE` is correct only when all three independently verified
   source identities are genuinely unchanged. It must not be expected merely
   because the preceding manual proof was a no-op.
8. **Resume gate:** resume the next bounded development slice only after the
   natural ingest has a terminal evidence result, the dashboard is healthy, no
   ingest lock remains, production is clean at the expected SHA, and the day's
   backup outcome is understood. A publication-only issue follows the recorded
   observation's existing-payload retry path and does not justify rerunning
   ingest.

The 00:30 boundary is a minimum protection window, not a target for finishing
work. Runtime deployments must still finish several hours before 00:30 and meet
the required soak. A longer freeze is mandatory whenever system health or the
remaining work duration is uncertain.

### Independent daily result model

Use execution ID `NATURAL-YYYYMMDD` for the natural ingest of each source date.
Its append-only evidence must separately record:

| Component | Required result and meaning |
|---|---|
| `source_capture` | Whether same-day upstream responses and raw attempts were durably retained |
| `observation_finalization` | Whether SQLite, completion, contract, ledger, pointers, schema, integrity, and accounting passed |
| `dated_v1` | Whether the immutable dated v1 component was publicly downloaded and verified |
| `rolling_v1` | Whether the monotonic rolling v1 component was publicly downloaded and verified |
| `dates_index` | Whether the public dates index was independently downloaded and verified |
| `v2` | Its independent state; it cannot clear or redefine a v1 result |
| `dashboard_return` | Whether the controlled ingest pause ended and dashboard health returned automatically |
| `laptop_backup` | The later scheduled backup result and exact observation/control/macro identities when available |

Capture, finalization, publication, and backup are not interchangeable. For
example, a publication failure can coexist with a preserved valid observation;
it must not trigger a second upstream ingest. Likewise, a withheld payload must
not cause raw evidence or a valid daily database to be deleted.

### Same-day failure and catch-up boundary

On any natural-ingest failure:

- preserve the first attempt, raw responses, logs, partial files, service state,
  lock evidence, and all already-durable database or contract material;
- keep the previous verified rolling payload public;
- do not reflexively use `--force`, overwrite the primary observation, or rerun
  the publication path as though it were a fresh ingest;
- distinguish upstream capture failure, observation-finalization failure, and
  publication-only failure before choosing any response;
- use the existing-payload retry path for publication-only failures; and
- never wait until after midnight expecting the failed source day to remain
  available.

A manual same-day catch-up may occur only if an already-proven
immutable-generation procedure exists, the exact approved code SHA and plan identity are
recorded, the production lock is absent, the first attempt remains preserved,
resources and dashboard are healthy, no competing job exists, and enough time
remains to finish and validate before the next 00:30 freeze. It creates a
separate generation and never overwrites the primary attempt. Until that path is
proven under the applicable remediation phase, preserve evidence and escalate;
do not improvise on production.

If safe same-day recovery is unavailable or midnight has passed, mark that
source date `FAIL` with an immutable `SOURCE_WINDOW_LOST` condition. Development
may continue later, but no later observation can be represented as the lost day.

### Phase progress across calendar days

- Only a small amount of the plan may advance on any day. That is expected and
  does not constitute delay or failure.
- Each slice has an explicit daily start state, safe stop state, resume point,
  and evidence pointer. The next session reads the complete runbook and the
  append-only evidence before resuming.
- A phase can remain `RUNNING` across many natural ingests. Each intervening
  ingest is still performed, validated, and backed up independently.
- No behavioral slice advances merely because development tests pass. It still
  requires its exact-head gates and the prescribed natural-ingest proof.
- If there is no safe deployment and soak window on a given day, wait for a later
  day. Never borrow time from the freeze or natural ingest.
- Daily operational evidence is not edited when a later phase discovers a new
  defect. Append a linked finding or decision instead.

### In-flight A3 transition

The already-installed laptop scheduled task and its first natural 05:00 proof
remain bound to the immutable v1.3 execution identity, plan commit
`8efefe10890a295ef87f97b46d3cb981193cfddc`, controlled plan digest
`8834990f8c3cfbe86d4006b0d4fca3c564c760362a0928bf2a688f6dacd83a3d`, and
receiver candidate `c87cdd0077e209d1824bbe485c0f5ad30723d0c4`. Do not rewrite,
reinstall, or relabel that in-flight proof as v1.4. Its natural 05:00 execution
after the 2026-08-28 ingest is expected to perform `BACKUP-LATEST` when the new
observation changes the verified source identity; a no-write is acceptable only
when the source identities truly have not changed and the reason is understood.

After that A3 execution reaches a terminal evidence state, new executions use
the v1.4 plan identity. The documentation-only v1.4 merge does not authorize
running newer-main backup tooling whose embedded plan constants have not yet
been updated and reviewed in a separate focused implementation PR. Continue
using the installed exact-candidate task for its approved proof, then advance
only through the normal slice gates.

## Version 1.3 backup completeness and durability amendment

This section is normative for laptop backup Phases A0 through A4 and corrects
v1.2 before the first production-data transfer. It does not authorize a runtime
deployment. Decision D-004 and this decision D-005 explicitly supersede the
retained Phase A instruction to wire replication to Pi-mounted storage. Use only
the laptop-side receiver at `C:\code\backups\AR-local-pi5`; the laptop initiates
SSH and the Pi never mounts a Windows share or receives laptop credentials.

The document-control execution ID for this version is `DOC-03`. `DOC-02`
remains the immutable v1.1 record and is never reused for v1.2 or v1.3 work.

Before opening a transfer, reserve at least the 50 GiB floor plus the complete
uncompressed source, a worst-case archive of the same size, and a 1 GiB
operational reserve. Recheck free bytes during the stream and before scratch
extraction, promotion, receipt creation, catalog append, and pointer replace.
Measured compression never reduces this admission requirement.

The bootstrap inventory includes every direct retained date directory under
`runs/`, whether completed or terminal-failed, and every retained namespace
under `runs-archive/`. Completed observations use the marker/contract/ledger
acceptance path. A run without a valid completion marker is preserved only as a
non-publishable diagnostic generation, together with attributable terminal
failure and raw-attempt evidence; it never advances latest-observation. Unknown
or actively mutating run state blocks that generation but does not erase it.
The current control generation includes `runs-archive`, predeployment evidence,
state, Git bundles, service definitions, package/configuration metadata, and an
online-backed-up macro database.

For each tar member, compare path, regular-file type, size, normalized
modification time, POSIX mode, UID, and GID against the canonical source
manifest. Independently compare every extracted path, size, and SHA-256. The
manifest remains the authoritative restoration metadata on filesystems that
cannot represent POSIX ownership, but the archived tar header must still match
it before promotion.

Durability order is archive flush, containing-directory flush, manifest flush,
receipt flush, catalog append flush, catalog-directory flush, and only then
atomic latest-pointer replace plus its directory flush. A platform that cannot
prove a required durability barrier blocks acceptance; it does not silently
substitute process exit for durable storage.

Scheduling remains prohibited until manual full backfill and restore PASS. A
future scheduled no-op requires three independently verified identities:
latest retained run/observation, current control source, and current macro
SQLite source. A change to any one creates and restores a new generation even
when the observation date is unchanged. A terminal failed run is backed up as
diagnostic evidence rather than deferred indefinitely.

## Version 1.2 laptop pull-backup amendment

This section remains normative subject to the v1.3 corrections above. D-004 and
D-005 explicitly supersede every retained instruction to use Pi-mounted storage
or a Windows share. It does not relax backup scope,
integrity, restoration, freshness, production-pinning, quiet-window, or rollback
gates. Version 1.1 remains authoritative for product and payload behavior.

### Fixed laptop target and capacity contract

- Target root: `C:\code\backups\AR-local-pi5` on the operator laptop.
- Minimum free space after every write, promotion, verification, or cleanup:
  `53,687,091,200` bytes (50 GiB). This stricter binary floor controls whenever
  “50 GB” is stated conversationally.
- Every receiver preflight records volume identity, total/free bytes, target
  canonical path, owner, ACL summary, source Pi identity, and projected
  worst-case write. It refuses to start unless the uncompressed source could fit
  without crossing the floor; measured compression is planning evidence, never
  permission to overrun the floor.
- The receiver checks free bytes during transfer and aborts before the floor.
  Only the exact `.partial` file created by that execution may be removed after
  its failure is recorded and its canonical path is revalidated under the target
  root. Existing completed backups are never deleted automatically.
- The laptop pulls from `ar-local-pi5-lan`; the Pi does not mount a Windows share,
  store laptop credentials, or expose a new listener.

### Recovery base classification

Treat `C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21`
as a historical candidate, not an accepted bootable or current base. It is
`31,902,400,512` bytes, has SHA-256
`d0caeeb3a83a50b79703dd650c8198b9a0afcbbb09c667b24b716fada716be4f`,
and has a valid MBR whose first-sector hash matches the recovery card. Its full
hash differs from the current card
(`ce0bcd6f1cb4364df2b97fb6324d0871a053fed6ed7738dcb0a65ef174d371d2`),
and no creation-time source hash was found. Preserve it unchanged; accept it only
after A4 boots it and validates root device, network, dashboard, storage, and
inhibited timers. The shorter
`C:\code\backups\pi5-microsd-20260521-175524\pi5-microsd.img` is quarantined:
its own status records a sector-read failure and it must never be a restore
source. No file is deleted merely because it is redundant or failed.

The recovery base is not current-data proof. A boot restore always applies the
latest separately verified current-state generation afterward and keeps ingest,
publication, and credential-bearing timers inhibited until restoration checks
pass.

### Incremental backup layout

Use immutable, content-addressed generations:

```text
AR-local-pi5/
  recovery-base/                 # receipt; image remains at its existing path
  observations/YYYY-MM-DD/
    <source-manifest-sha256>/
      observation.tar.zst
      source-manifest.json
      receipt.json
  control/<generation-id>/
    control.tar.zst
    source-manifest.json
    receipt.json
  macro/<generation-id>/
    macro.sqlite
    receipt.json
  catalog/
    generations.jsonl
    latest-verified.json
  restore-drills/<execution-id>/
```

One observation archive namespace contains exactly one completed immutable run
directory plus its ledger-bound completion marker, contract, pointer, and
diagnostic material selected from production state without modifying or copying
anything into the production run. The run includes raw attempts, daily SQLite,
and exports. The canonical source manifest lists every relative path, source
namespace, type, size, mode, modification time, and SHA-256, sorted by UTF-8
path bytes. Symlinks, devices, sockets, traversal, case collisions, alternate
data streams, and paths invalid on Windows fail closed.

The control pack records current state, completion/observation pointers, ledger,
publication pending/component state, deployment records, redacted service/timer
definitions, package inventory, Git bundles, and configuration metadata. It
records secret-file locations, owner/mode, and digests but excludes secret bytes,
SSH material, tokens, raw environment files, Netdata credential stores, caches,
and logs. An optional secret escrow requires a separate encrypted design and is
not implied by this backup.

The macro SQLite file is produced with SQLite's online backup API into a unique
temporary Pi path, checked with `PRAGMA quick_check`, streamed, rehashed, restored
to laptop scratch, checked again, and then the exact temporary file is removed.
Never copy a live WAL database by copying only its main file.

### Transfer, commit, and retry protocol

1. Refuse during 00:30–03:30 Australia/Hobart, while ingest is active, when the
   production checkout is dirty or not pinned, or when dashboard/timer/lock/free
   space preflight fails.
2. Resolve and freeze the authoritative latest completed observation identity.
   Generate its canonical source manifest without modifying production data.
3. If the catalog already has an independently verified pack with that exact
   source-manifest hash, skip its bytes and verify it again before advancing.
4. Stream deterministic tar through `zstd` at low I/O priority and at most two
   compression workers into a unique laptop `.partial` file. Capture SSH, tar,
   compressor, byte-count, duration, and dashboard/resource results separately.
5. Flush the file, verify compressed-frame and tar readability, compare every
   extracted path/size/SHA-256 in scratch, validate SQLite and observation
   contracts, and ensure laptop free space remains above the floor.
6. Atomically rename `.partial` to its content-addressed final name. Create the
   immutable receipt last, then append the hash-linked catalog entry and replace
   `latest-verified.json` atomically.
7. On interruption, never advance catalog/latest. Record the failed partial,
   revalidate its exact path, remove only that partial if required to restore the
   floor, and retry the same frozen observation. Never rerun ingest.

Compression is not the integrity boundary. Acceptance requires source manifest,
archive, extracted bytes, SQLite, contracts, ledger/pointers, and receipt hashes.
At least one complete observation restore is performed from laptop bytes without
reading the Pi source during verification.

### Scheduling and residual risk

After one manual backup and restore pass, schedule a laptop-side pull for 05:00
Australia/Hobart and at laptop startup when stale. It exits successfully without
writing when the latest observation is already verified; otherwise it defers on
an active/failed ingest or unavailable Pi and alerts. It never runs in the quiet
window. A freshness monitor reports the latest source observation, latest
verified laptop generation, age, free bytes, and last restore result.

The laptop is physically separate but not geographically separate and may be
offline. This design therefore satisfies the immediate off-device Phase A0/A1
foundation but does not complete A4 or eliminate the requirement for a later
independent-site copy and boot test.

## Version 1.1 controlling amendment

This section is normative and supersedes only the conflicting v1.0 statements
identified below. All other v1.0 safety controls remain in force. In particular,
production stays on its last-known-good immutable commit until the backup,
rollback, exact-candidate, canary, daylight-deployment, and natural-ingest gates
for the relevant slice pass.

### Superseded v1.0 rules

The following v1.0 publication rules are replaced by D-003:

- `providers_failed == 0` as a publication requirement;
- failure totals between 1 and 50;
- failures no greater than 1% of discovered products;
- partial providers no greater than 15% of registered providers; and
- treating an attributable provider or product gap as a reason to suppress every
  independently valid product in the observation.

Those quantities remain mandatory metrics for disclosure, alerting, trend
analysis, and operator triage. They never independently decide publication.
Until the product-accounting activation slice passes, the deployed legacy gate
continues to fail closed; D-003 is not permission to bypass it manually.

### Non-negotiable safety invariants

1. A consumer product appears for an observation only when its current-day
   identity, classification, and consumer-critical rate evidence validate.
2. A defect in optional details removes only those details and produces
   `published_core_only`; it does not suppress valid core rates.
3. A trust-critical defect suppresses that product everywhere and produces
   `quarantined_invalid`.
4. A valid but intentionally non-displayable product, including a product with
   no valid current rate, produces `omitted_valid`.
5. No prior-day row is copied forward or represented as observed today.
6. Every registered provider receives an attributable attempt. A provider may
   produce no current products and the remaining providers may still publish.
7. Every discovered product belongs to exactly one disposition, and every
   consumer row belongs to a publishable disposition.
8. Daily SQLite observations become immutable after finalization. Corrections
   use a new generation and immutable revision tag.
9. Dated v1, rolling v1, and the dates index are separate transactions whose
   public bytes must be verified independently.
10. The upgraded AR-app must be released and verified before production can
    activate product-scoped publication.
11. Unknown, corrupt, or contradictory membership is never converted into an
    apparently complete observation.
12. `dev`, PR #508, and quarantined restoration branches are never production
    sources. Candidates are exact immutable commits descended from `main`.

### Product and provider dispositions

Every currently indexed product receives exactly one of these values:

| Disposition | Consumer eligibility | Required evidence | Public meaning |
|---|---|---|---|
| `published_full` | Core and valid details | Valid identity, classification, core rates, and optional details | Fully observed product |
| `published_core_only` | Core plus independently validated optional fields | Valid identity, classification, and core rates; one or more optional fields rejected | Rates are usable; detail completeness is not promised |
| `omitted_valid` | None | Valid identity and attributable current observation with genuinely absent current rate evidence, or an explicit supported exclusion | Expected gap, not invalid data |
| `quarantined_invalid` | None | Evidence is missing, malformed, contradictory, misclassified, duplicated with conflicting values, or otherwise trust-critical | Invalid product withheld |

For each observation:

```text
products_discovered
  = published_full
  + published_core_only
  + omitted_valid
  + quarantined_invalid
```

This is set-membership equality, not merely count equality. Product UIDs are
unique. Current-day core, details, search, change, ribbon, and aggregate outputs
reference only `published_full` or `published_core_only`. For
`published_core_only`, the details asset may retain independently validated
fields, must omit every rejected field, and sets `details_complete=false`.
Prior verified history remains intact; an affected current date is `null`.
Omitted and quarantined products appear only in quality disclosure.

Provider state is independent of product disposition:

| State | Definition |
|---|---|
| `complete` | Current provider population is known and every product reconciles |
| `partial` | Some current provider products reconcile, with attributable gaps |
| `empty` | An attributable successful attempt proves a current empty population |
| `failed` | The provider was attempted but no trustworthy current population was obtained |
| `not_attempted` | No attributable attempt exists; this is a global control-plane blocker |

A `failed` provider contributes no current products and is disclosed. It does
not block products from other providers. `population_known=false` must be used
when a provider-index or pagination failure leaves the missing tail unknown.

### Whole-observation hold conditions

The producer withholds production publication only when safe separation or
publication integrity cannot be proven. Initial activation blockers are:

- completion marker, export contract, ledger event, observation pointer,
  accounting digest, or required artifact missing or unverifiable;
- any hash, generation ID, observation date, or pointer binding disagreement;
- register provenance incomplete, a registered provider not attributable to an
  attempt, or register/provider membership unreconciled;
- corrupt or unattributed failure evidence greater than zero;
- a raw failure record that cannot be mapped to a normalized issue or preserved
  by raw-byte digest;
- product disposition sets that overlap, omit a discovered product, contain a
  duplicate conflicting identity, or disagree with SQLite or payload output;
- an omitted or quarantined product present in any consumer asset;
- zero individually publishable products;
- invalid top-level payload schema, unsafe decompression bounds, or product and
  provider summary disagreement;
- required public asset, manifest, or dates-index upload or post-download
  verification failure; or
- candidate, plan, deployment, backup, rollback, or app-compatibility evidence
  not matching the exact commit being promoted.

Issue volume and impact severity do not independently hold publication once
these trust-boundary gates pass. A severe but fully reconciled observation is
published as severe rather than silently replaced with stale data.

### Validation boundary

Consumer-critical product validation must cover at least:

- stable provider and product identity and a non-empty CDR product ID;
- a known dataset and section classification;
- conflict-free duplicate resolution;
- finite numeric rate values with correct units and supported relationships;
- Mortgage, Savings, and TD rate values between 0 and 1 inclusive in stored CDR
  decimal form before percentage presentation;
- tier boundaries that are finite, ordered, non-overlapping where the CDR
  contract requires it, and bound to the correct product;
- timestamps and effective dates that are parseable and not more than 24 hours
  beyond the observation date;
- no foreign product/provider cross-reference; and
- every included row having positive evidence bound to the current generation.

Invalid optional fields are removed, recorded as `field_omitted_invalid`, and
yield `published_core_only`; remaining independently valid optional fields may
be retained. Invalid identity, classification, observed rate value/unit,
duplicate, or evidence binding yields `quarantined_invalid` for the whole
product. `omitted_valid` is allowed only when current rate evidence is genuinely
absent; malformed, conflicting, incorrectly unitised, or unbound observed rate
evidence is always `quarantined_invalid`.

### `ProductAccountingV1` internal sidecar

Before finalization, generate canonical JSON named
`product-accounting-v1.json`. It is an immutable export artifact and is hashed
by the export contract and ledger event. Its minimum structure is:

```json
{"schema_version":1,"observation_date":"YYYY-MM-DD",
 "accounting_id":"ingest-session-id","raw_attempt_journal_digest":"sha256",
 "providers":[],"products":[],"issues":[],"summary":{}}
```

Provider records contain provider UID, safe display name, state, attempted,
population-known, discovered and disposition counts, and issue IDs. Product
records contain product UID, provider UID, CDR product ID, dataset, optional
safe display name, disposition, allowlisted reason codes, and positive evidence
IDs/digests. Issue records contain deterministic issue ID, scope, provider and
product references when known, phase, allowlisted code, optional HTTP status,
occurrence count, first/last timestamps, evidence digest, and resulting
disposition. Arbitrary exception text, request headers, credentials, response
bodies, and unredacted URLs are prohibited from public projections.

`accounting_id` is the immutable raw-attempt session/source observation ID; it
is assigned before finalization and is not derived from these JSON bytes. The
sidecar contains neither its own hash nor the final generation ID. Canonical
JSON uses UTF-8, sorted keys, compact separators, LF where text lines exist, and
no non-semantic timestamps. The export contract hashes the completed sidecar;
its digest then contributes to the final generation, contract, and ledger.

Initial stable issue codes are product codes `detail_fetch_failed`,
`detail_invalid_json`, `cdr_error`, `identity_mismatch`, `duplicate_conflict`,
`rate_invalid`, `classification_unresolved`, `no_current_rate`,
`product_closed`, and `unsupported_category`; optional-field code
`field_omitted_invalid`; provider codes `products_index_failed`,
`pagination_incomplete`, `holder_worker_crash`, and
`provider_population_unknown`; and run codes `register_failed`,
`failure_record_corrupt`, `failure_unattributed`, and
`accounting_unreconciled`.

Unknown codes fail schema validation in the producer. AR-app renders a generic
safe label for a future unknown code so an additive producer release cannot
crash an older supported app.

### SQLite schema for new observations

Historical SQLite files are never migrated in place. Newly finalized databases
increment their schema version and add:

```text
bank_product_dispositions(
  accounting_id TEXT, product_uid TEXT, provider_uid TEXT,
  cdr_product_id TEXT, dataset TEXT, display_name TEXT,
  disposition TEXT CHECK (...four allowed values...),
  reason_codes_json TEXT, evidence_ids_json TEXT,
  core_valid INTEGER CHECK (core_valid IN (0,1)),
  details_valid INTEGER CHECK (details_valid IN (0,1)),
  PRIMARY KEY (accounting_id, product_uid)
)
bank_provider_observations(
  accounting_id TEXT, provider_uid TEXT, brand_name TEXT,
  state TEXT CHECK (...five allowed values...),
  attempted INTEGER CHECK (attempted IN (0,1)),
  population_known INTEGER CHECK (population_known IN (0,1)),
  discovered_count INTEGER, published_full_count INTEGER,
  published_core_only_count INTEGER, omitted_valid_count INTEGER,
  quarantined_invalid_count INTEGER, issue_count INTEGER,
  PRIMARY KEY (accounting_id, provider_uid)
)
bank_observation_issues(
  accounting_id TEXT, issue_id TEXT,
  scope TEXT CHECK (scope IN ('product','provider','register','run')),
  provider_uid TEXT, product_uid TEXT, phase TEXT, code TEXT,
  http_status INTEGER, occurrence_count INTEGER CHECK (occurrence_count > 0),
  first_seen_at TEXT, last_seen_at TEXT, evidence_digest TEXT,
  disposition TEXT, public_safe INTEGER CHECK (public_safe IN (0,1)),
  PRIMARY KEY (accounting_id, issue_id)
)
```

Every column shown without an explicit nullable role is `NOT NULL`; every count
has `CHECK (value >= 0)`.

`display_name` is nullable. In issues, `provider_uid`, `product_uid`,
`http_status`, and `disposition` are nullable only where the scope requires;
every other shown column is `NOT NULL`. Enable `PRAGMA foreign_keys=ON` and use
composite foreign keys on `(accounting_id, provider_uid)` and
`(accounting_id, product_uid)`; application validation is additional defence,
not a substitute. Add indexes on identity, disposition, state, code, and scope.
Before finalization, independently regenerate canonical sidecar bytes from the
tables, require byte-for-byte equality with the stored sidecar, verify its
external SHA-256, and run `PRAGMA quick_check`.

### Checked-in schemas and reconciliation

Implementation must add and test `product-accounting-v1.schema.json`,
`app-quality-v1.schema.json`, `app-observation-v1.schema.json`, and
`dates-index-v1.schema.json`, `dates-index-entry-v1.schema.json`, and
`dates-index-status-event-v1.schema.json`,
`dates-index-compatibility-event-v1.schema.json`, and
`rolling-unavailable-v1.schema.json`. Internal schemas reject additional
properties. Public schemas allow only documented additive extension points.
They define all required keys, types, enums, string patterns, nullable fields,
integer minima, array uniqueness, gzip/media types, and byte limits.

Provider summary requires `registered`, `attempted`, `complete`, `partial`,
`empty`, `failed`, `not_attempted`, and `population_unknown`. Product summary
requires `discovered`, `published_full`, `published_core_only`, `omitted_valid`,
`quarantined_invalid`, and `consumer_visible`. Issue summary requires `total`,
`corrupt`, `unattributed`, `affected_providers`, `affected_products`, and
allowlisted `by_code`. Reconciliation requires provider states to total
registered providers; attempted to equal complete + partial + empty + failed;
product dispositions to total discovered; consumer-visible to equal both
publishable dispositions; and every summary to match SQLite, sidecar, quality,
core membership, manifest, and dates-index entry.

Observation `state=complete` only when all registered providers are complete or
proven empty, `population_unknown=0`, every discovered product is
`published_full`, and issue total is zero. Every other accepted observation is
`degraded`. Impact is separate and never changes this deterministic state rule.

The following field sets are exhaustive and normative; schema files implement
them rather than redesign them:

| Object | Required fields |
|---|---|
| Accounting root | `schema_version` integer 1; `observation_date` date; `accounting_id` non-empty string; `raw_attempt_journal_digest` SHA-256; unique `providers`, `products`, and `issues` arrays; exact `summary` |
| Provider | `provider_uid`, `brand_name`, unique `datasets`/`affected_sections`; provider `state`; booleans `attempted`/`population_known`; all discovered/disposition/issue counts; unique `issue_ids` |
| Product | `product_uid`, `provider_uid`, `cdr_product_id`, dataset enum, nullable `display_name`/`legacy_product_key`; disposition; unique reason/evidence IDs; booleans `core_valid`/`details_complete` |
| Issue | `issue_id`, scope, nullable provider/product UID as scope permits, affected sections, phase, allowlisted code, nullable HTTP status/disposition, positive count, first/last timestamps, evidence SHA-256, `public_safe` boolean |
| Gap | date, provider UID, nullable product UID, non-empty affected sections, `population_known`, reason codes, and disposition |
| Quality root | schema version 1, run date, accounting/generation IDs, publication mode, accounting SHA-256, exact summaries, unique gaps, and optional grouped issues only in expanded quality |

All counts are integers at least zero; IDs and enums follow the values fixed in
this document; arrays are deterministically sorted and unique. Public objects
may contain one optional namespaced `extensions` object; other unknown keys are
rejected by the producer and safely ignored by compatible consumers only inside
that extension object.

Official `provider_uid` is `provider:v1:<hex>` where `<hex>` is SHA-256 of
compact sorted-key UTF-8 JSON `["identity-v1","provider",{"brand":B,"holder":H}]`,
with `B` and `H` substituted as JSON strings. `H` and `B` are the exact trimmed
CDR Register `dataHolderId` and
`dataHolderBrandId` strings. Do not case-fold them. If either is missing, use
`provider-fallback:v1:<hex>`, where `<hex>` hashes canonical JSON
`["provider-fallback-v1",A,N]`. Build `A` by collecting every HTTPS endpoint in
the register provider record, IDNA-encoding and lowercasing each host, removing a
trailing dot and port 443, retaining any other explicit port, discarding path,
query, and fragment, then choosing the lexicographically smallest non-empty
`host[:port]`. Build `N` by Unicode NFC-normalising the display name, trimming it,
and collapsing each ASCII whitespace run to one space; do not case-fold it.
Missing `A` provider-scope holds that register record and exposes only its
evidence digest as an unattributed-to-product provider issue. Mark
fallback identity publicly and bind an append-only fallback identity/alias
registry into the accounting contract and ledger. On later days, reuse the
registered UID. If fallback inputs change without an operator-authorised alias,
or any official/fallback UID collides, mark every affected provider population
unknown and provider-scope hold its products rather than minting a new identity;
unrelated providers remain eligible. Dataset is exactly one case-sensitive enum:
`Mortgage`, `Savings`, or `TD`.

`product_uid` is lowercase hex SHA-256 of UTF-8 bytes
`product-v1\0<provider_uid>\0<dataset>\0<cdr_product_id>`. The producer adds it
to every product-bearing core, details, search, history, change, saved-rate, and
aggregate record. Accounting records also carry nullable `legacy_product_key`;
the build verifies its one-to-one mapping and globally holds on collision or
cross-asset disagreement.

Canonical sidecar and public JSON are compact UTF-8 with sorted keys. Canonical
arrays use their documented identity sort. Reproducible gzip uses empty filename,
mtime zero, compression level 9, and a fixed OS header byte. Hashes cover exact
compressed public bytes; inflated sizes cover canonical JSON bytes.

### Additive public v1 contract

Keep manifest `schema_version: 1` and every existing stable-app field unchanged.
Add:

```json
{"publication_state":"accepted",
 "observation":{"schema_version":1,"state":"complete","impact":"none",
   "accounting_id":"ingest-session-id","generation_id":"obs-...",
   "publication_mode":"product_scoped","export_contract_digest":"sha256",
   "ledger_digest":"sha256","product_accounting_digest":"sha256",
   "providers":{"registered":0,"attempted":0,"complete":0,"partial":0,
     "empty":0,"failed":0,"not_attempted":0,"population_unknown":0},
   "products":{"discovered":0,"published_full":0,
     "published_core_only":0,"omitted_valid":0,
     "quarantined_invalid":0,"consumer_visible":0},
   "issues":{"total":0,"corrupt":0,"unattributed":0,
     "affected_providers":0,"affected_products":0,"by_code":{}}},
 "commit":{"dated_manifest_sha256":"sha256",
   "index_entry_sha256":"sha256","dates_index_sha256":"sha256",
   "quality_index_sha256":"sha256","quality_sha256":"sha256"},
 "files":{"quality_index":{"name":"quality-index-YYYY-MM-DD-<digest>.json.gz",
   "url":"https://github.com/.../quality-index-....json.gz",
   "media_type":"application/json","content_encoding":"gzip",
   "bytes":0,"inflated_bytes":0,"sha256":"sha256"},
  "quality":{"name":"quality-YYYY-MM-DD-<digest>.json.gz",
   "url":"https://github.com/.../quality-....json.gz",
   "media_type":"application/json","content_encoding":"gzip",
   "bytes":0,"inflated_bytes":0,"sha256":"sha256"}}}
```

`commit` is required only on rolling and prohibited on dated manifests, avoiding
a circular dependency. `index_entry_sha256` hashes canonical entry JSON without
any self-hash field; `dates_index_sha256` hashes the complete published index.

`publication_state` is `accepted` or `diagnostic`. Production dated, rolling,
and dates-index entries accept only `accepted`. Diagnostic smoke tags use
`diagnostic` and can never finalize an app date. The separately schema-validated
rolling-unavailable control manifest defined in the correction procedure is the
only exception; it is not a dated manifest, observation, or dates-index entry.

The mandatory `quality_index` binds run date, accounting ID, generation, mode,
accounting digest, all summaries, stable affected identities/reason aggregates,
and the gap matrix keyed by date, provider UID, optional product UID, and
affected sections. It is eagerly downloaded before adoption and capped at 1 MiB
compressed and 8 MiB inflated. Expanded `quality` adds normalized issue groups,
is lazy, and is capped at 8 MiB compressed and 64 MiB inflated. Both are safe
public projections, uploaded before the manifest, content-addressed,
gzip-compressed, and SHA-256 verified before parsing.
Exceeding either bound is a control-plane failure; issues are not silently
truncated. Neither projection contains raw URLs, bodies, headers, credentials,
or arbitrary exceptions. The accepted dated-manifest hash authenticates both
descriptors and their URL, encoding, sizes, and SHA-256 values.

Impact uses ordered algorithm `impact-v1` and never overrides inclusion proof.
Evaluate `severe` first: more than 10% of discovered products are non-publishable;
more than 10% of registered providers failed; a section discovered products but
has zero visible products; or visible products are below 50% of the median of at
least three available same-dataset accepted observations from the prior seven.
Otherwise `degraded` applies when any provider failed, population is unknown,
any product is quarantined, non-full products exceed 1% of discovered, or
affected providers exceed 15% of registered. Otherwise `limited` applies when
any issue, core-only product, or omitted product remains. Otherwise impact is
`none`. Ratios use exact integer counts and strict `>`; zero required denominators
are global blockers, and the trailing baseline test is skipped with fewer than
three comparable observations.

Extend `dates-index.json` additively while preserving the sorted legacy `dates`
array:

```json
{"schema_version":1,"dates":["YYYY-MM-DD"],
 "entries":[{"date":"YYYY-MM-DD","publication_status":"accepted",
   "revision":0,"state":"complete","impact":"none","population_unknown":0,
   "generation_id":"obs-...","tag":"app-payload-YYYY-MM-DD",
   "dated_manifest_sha256":"sha256","quality_index_sha256":"sha256",
   "quality_sha256":"sha256"}],
  "status_events":[{"sequence":2,"event_id":"sha256",
    "generation_id":"obs-...","status":"withdrawn",
    "replacement_generation_id":null,"reason_code":"semantic_failure",
    "recorded_at":"RFC3339Z","operator":"identity"}],
  "compatibility_events":[{"sequence":1,"activation_id":"sha256",
    "type":"legacy_cutoff_activated","app_min_version":"1.0.174",
    "legacy_cutoff":{"date":"YYYY-MM-DD","tag":"app-payload-YYYY-MM-DD",
      "generation_id":"obs-...","manifest_sha256":"sha256"},
    "recorded_at":"RFC3339Z","operator":"identity"}]}
```

Entries are immutable and unique by `(date, generation_id, revision)`.
Corrections append status events; they never edit an entry. Check in schemas for
the complete dates index, each immutable entry, and each status event. A status
event contains only `sequence`, `event_id`, `generation_id`, `status`, nullable
`replacement_generation_id`, `reason_code`, `recorded_at`, and `operator`.
`event_id` is lowercase SHA-256 of canonical event bytes with `event_id` omitted;
canonicalisation follows the JSON rule above. Sequence is a positive integer,
unique across both event arrays, contiguous from one when arrays are merged, and
evaluated in ascending order.
Every event generation and non-null replacement must resolve to a unique existing
entry; replacement must differ from source, be effectively accepted, and have a
later `(date, revision)`. The only legal first transition is `accepted ->
withdrawn` or `accepted -> superseded`. Both are terminal for that generation;
replacement linkage is carried on the same terminal event and never by a later
second transition. Reject unknown fields, duplicate IDs/sequences, broken links,
illegal transitions, and non-canonical order. The newest effectively accepted
generation is the greatest `(date, revision, generation_id)` after applying all
valid events; it must match the rolling commit. Legacy `dates[]` remains a
monotonic record of dates ever published and is not pruned on withdrawal.

`compatibility_events` is empty before APP-GATE-B and contains exactly one event
after it. `activation_id` is lowercase SHA-256 of canonical event bytes with that
field omitted. The cutoff tuple binds the final independently downloaded and
hash-verified legacy manifest directly; its date must already exist in legacy
`dates[]`, but it does not require or manufacture a new-format entry. The
APP-GATE-B receipt records every legacy asset hash and the manifest hash;
`app_min_version` is exact APP-01. A second activation, altered tuple, or
sequence/order error invalidates the index. Every accepted rolling commit
after activation binds `cutoff_activation_event_id=activation_id`. All apps,
including fresh installs, select the first and only valid activation event from
the verified full index and require rolling to match it; rolling alone can never
create, remove, or widen the cutoff.

For a new-format observation, use this literal consumer commit protocol:

1. Upload and publicly verify immutable dated assets, quality, and dated manifest.
2. Upload and verify rolling content-addressed assets without changing the
   rolling manifest.
3. Publish and verify the monotonic dates index entry referencing exact dated
   manifest and quality hashes.
4. Publish and verify the rolling accepted manifest last. Its rolling-only
   `commit` binds the dated manifest, canonical index entry, full dates index,
   quality index, and expanded quality SHA-256 values; its date and generation
   match all documents.
5. Clear internal pending only after all four public components are verified.

The APP-GATE-B minimum-version manifest prevents unsupported clients
from consuming step 3 early. The supporting app requires both the exact accepted
index entry and matching rolling commit for the newest effectively accepted
generation. If step 3 succeeds
and step 4 fails, rolling stays old, the index remains a monotonic superset, and
retry resumes step 4 from the original observation without rerunning ingest.

### AR-app compatibility and disclosure

Ship app support before producer quarantine or product-scoped publication.
APP-01 targets versionName `1.0.174` and Android versionCode `193`. Its immutable
release receipt records both values, APK SHA-256, and signing-certificate digest.
The compatibility gate copies the verified versionName exactly into
`app_min_version`; versionCode is evidence, not the compared value. AR-app fails
closed when its native version cannot be read or does not satisfy the minimum.

Required app behavior:

- validate top-level manifest, run date, hashes, sizes, decompression bounds,
  publication state, and observation summary before adoption;
- before cutoff activation, accept legacy manifests under existing rules; after
  observing the authenticated APP-GATE-B cutoff, accept them only through that
  immutable tuple and never forget or move the cutoff forward;
- never adopt a `diagnostic` manifest or diagnostic dated tag;
- for every new-format manifest, require an exact accepted dates-index entry
  matching date, tag, generation, dated-manifest, quality-index, and expanded
  quality hashes; for the newest effectively accepted generation also require a
  rolling `commit` whose
  entry/index/artifact hashes match downloaded bytes; availability alone
  finalizes only legacy data;
- validate rows independently at download and cache-read boundaries, but assign
  disposition by `product_uid`; any trust-critical row failure removes every
  current row and dependent reference for that product;
- use one local quarantined-product set to filter core, details, search, bank and
  product history, changes, ribbons, aggregates, saved-rate lookups, and
  notifications; an unscoped membership mismatch holds the prior cache;
- retain the previous trusted cache only for top-level corruption, hash/run-date
  mismatch, or an unusable observation contract;
- preserve known history gaps as `null`; do not forward-fill a reported gap or
  generate a removal/rate-change notification from it;
- label the next observed change after a gap as first observed after a data gap;
- exclude incomplete providers from aggregates/rankings that require complete
  provider populations, or label the aggregate as incomplete;
- show a calm tappable summary such as “3,018 valid products · 7 omitted ·
  2 lenders affected” only when needed;
- when population is unknown, separate known and unknowable scope, for example
  “7 known products omitted · product count unavailable for 2 lenders”;
- provide a Data quality screen with date, observation identity, reconciled
  totals, collapsed provider groups, product/reason groups, and copyable stable
  issue codes;
- show an affected-lender notice and an exact-product optional-detail notice
  without placing warnings on unaffected cards; and
- never expose raw response bodies, credentials, or unsafe URLs.

Legacy acceptance is bounded by an immutable pre-activation tuple of final
legacy date, tag, generation (when present), and manifest hash recorded in the
APP-GATE-B deployment receipt. Only releases at or before that boundary use
legacy semantics. After APP-GATE-B, every mode, including rollback, emits the
additive contract; missing required fields holds the previous trusted cache.

APP-01 implements the cutoff protocol before release; it does not hardcode a
future tuple. APP-GATE-B adds `compatibility.schema_version=1`, exact
`app_min_version`, and the complete legacy cutoff tuple to the hash-verified
rolling manifest and appends the one permitted compatibility activation event to
the full dates index. APP-01 requires the two to match, then atomically persists
that activation tuple, activation ID, rolling-manifest hash, and full-index hash
before adopting the first gated generation. The activation is one-way: replay,
absence, or an altered/future cutoff cannot erase or widen the stored boundary.
A fresh install derives it only from the first valid activation event in the
verified full index and matching rolling commit; an offline existing install may
use only its already verified cache until it can verify the gate.

Producer disclosure remains immutable. Device findings are stored separately
as `device_quarantine` and displayed alongside, never merged into or substituted
for signed producer counts. Persist device quarantine only in an atomic sidecar
keyed by core SHA-256, every dependent-asset hash, and validator-schema version;
otherwise recompute it. Never alter producer bytes or delete saved references;
affected saves become unavailable. Cache quality atomically by `(run_date,
generation_id, quality_index_sha256)` in the same cache transaction as core and
never evict it independently. Cache expanded quality separately by `(run_date,
generation_id, quality_sha256)` and use it offline only when identities match.
Mandatory quality-index failure prevents adoption. Missing/unavailable expanded
quality shows “Details unavailable” without invalidating verified core.

Atomically retain at least the current and previous accepted, non-withdrawn
generations. Cleanup never removes the predecessor until its successor has
survived seven natural ingests with no open semantic alert; the last two verified
generations are retained regardless.

The gap matrix drives history and aggregates. Rankings may use valid current
products with visible coverage. Lender/section aggregates are labelled partial.
Before/after population calculations exclude affected provider-dates. Explicit
gaps break chart lines; unknown local history warming is a different state.
Exact-product alerts require publishability at both endpoints; the first valid
post-gap observation re-baselines without alert. Category/search-best alerts
are suppressed when an affected section population could change the winner.
RBA-only alerts are unaffected; device quarantine follows the same suppression.

Provide a date-addressable Data quality route. It verifies the selected dated
manifest hash, tag, effective status, date, generation, quality-index hash, and
expanded quality hash against the index before fetching/caching. Test loading,
unavailable, hash-mismatch, empty-report, and withdrawn/superseded states.

Production AR-app must reject diagnostic tags. Candidate rendering uses an
internal signed test build from the exact APP-01 commit and lockfile with one
compile-time pinned candidate URL and no runtime URL override. Its receipt binds
source SHA, lockfile, candidate tag, APK hash, and signing certificate. Binary
comparison must show the released build differs only in build profile and pinned
endpoint; the released APK separately proves diagnostic rejection.

Accessibility requires text and icon in addition to colour, button role and
expanded state for disclosures, at least 48dp targets, one polite refresh
announcement rather than per-row announcements, selectable diagnostic codes,
and reduced-motion compliance. Large reports use virtualized provider/product
groups, semantic headings, stable focus across expansion, complete disposition
and count labels, one announced copy confirmation, large-text layouts without
clipping, and no nested conflicting press targets.

### Staged feature modes

`AR_LOCAL_PRODUCT_PUBLICATION_MODE` has exactly four values:

| Mode | Behavior |
|---|---|
| `legacy` | Current production behavior; no product-accounting authorization |
| `report` | Preserve catalogue/core/details membership and legacy authorization decisions while allowing additive observation, quality, index, and manifest bytes |
| `quarantine` | Remove individually invalid products while retaining the legacy observation-wide publication gate |
| `product_scoped` | Authorize publication using the D-003 inclusion-proof gate |

Absent configuration defaults to `legacy`; unknown values fail closed. The
selected mode is recorded in completion, contract, ledger, internal publication
state, manifest, deployment record, and evidence ledger. A code deploy and a
mode activation are separate approvals and rollback targets.

### Incremental implementation train

Each numbered slice uses a fresh branch from current `origin/main`, one focused
PR, exact-head CI, substantive review disposition, public PR gates, and immutable
evidence. Runtime slices deploy only in daylight, soak at least two hours, end
several hours before 00:30, and survive one natural ingest before the next
behavioral slice advances. This train explicitly spans multiple calendar days.
Every intervening 01:00 natural ingest proceeds under D-006 regardless of phase
status. Daily capture is production continuity work, not a reason to skip gates
or declare the active remediation slice complete.

1. **DOC-03 — controlled v1.3 laptop-backup plan.** Merge this document; recalculate plan
   commit, raw SHA-256, controlled SHA-256, and post-merge candidate SHAs.
2. **A0 — physically separate bootstrap.** Verify the laptop volume, canonical
   target, owner/ACL, 50 GiB floor, pull-only SSH route, recovery-base image, and
   secret-exclusion policy under D-004. Install and run exact-candidate receiver
   tooling only from a non-production checkout without changing the pinned Pi
   checkout, services, or timers. A0 alone is exempt from the not-yet-possible
   backup/rollback gate.
3. **A1 — backup completeness.** Reject empty observation skeletons; require at
   least the authoritative latest observation chain and inventory counts.
4. **A2 — restore fidelity.** Rehash every restored byte against the snapshot
   manifest, compare macro table counts, verify marker-to-contract-to-ledger and
   pointer-to-marker bindings, and restore-test Git bundle and system config.
   Use an isolated scratch volume or reserved free-space floor, I/O/memory/time
   limits, dashboard/resource monitoring, and never run from 00:30–03:30.
5. **A3 — backup crash recovery.** Detect and quarantine or resume `.partial-*`
   and orphan generations; do not count them as retention; recompute the full
   thirty-generation reserve at deployment time. Hold the production ingest
   lock for backup/catch-up coordination and do not auto-enable a backup timer
   until one manual backup and full restore pass. Apply the A2 scratch/free-space,
   I/O, memory, runtime, dashboard/resource, and 00:30–03:30 exclusion controls
   to every backup and catch-up execution.
6. **A4 — physical recovery proof.** Bind backup freshness to the latest
   observation identity, require stable storage UUID/serial identity, exclude or
   redact secrets from config capture, and prove an actual clone boot/root
   device. Inhibit cloned ingest/publication timers and credentials, identify
   clone/root/source disks before writable mounts, verify timer definitions
   without running them, then restore primary boot and reverify the pinned Pi,
   dashboard, network, storage, and next 01:00 trigger.
7. **B1 — immutable deployment records.** Before any candidate checkout, create
   and verify a genesis record for pinned `9302890` containing cleanliness,
   service/timer/dashboard state, backup/observation/public-payload identities,
   plan identity, and legacy mode. Thereafter record candidate and prior SHA.
8. **B2 — rollback correctness.** Roll back every failure after checkout,
   including service apply, sync verification, and dashboard smoke. Permit only
   the previous SHA from a verified deployment record and run full post-rollback
   checks.
9. **B3 — non-production deploy/rollback proof.** Exercise both paths against an
   isolated checkout before any production runtime change.
10. **C — current-main safeguards.** With PR #508 still held, canary and promote
   #506 provider-accounting protection and #507 early raw-attempt preservation
   only after A/B pass. Survive one natural ingest.
11. **D — transactional v1.** Introduce independent versioned state for dated
    v1, rolling v1, dates index, and v2; upload assets first and manifest/pointer
    last; retry only incomplete components from the original observation.
12. **E1 — report-only accounting.** Correct provider `failed`/`empty`
    classification; capture true discovered/detailed/priced/disposition
    populations; add new-observation SQLite tables and ledger-bound sidecar.
13. **E2 — diagnostic disclosure.** Produce observation summary and quality
    asset only on a diagnostic tag. Prove stable-app compatibility and public
    bytes without advancing production dates.
14. **APP — supporting AR-app release.** Implement runtime product quarantine,
    gap-aware history and notifications, concise disclosure, accessibility, and
    lazy verified quality details. Pass `cd mobile && npm run ci`, emulator
    rendering, and physical-device evidence; release before producer activation.
15. **APP-GATE-A — dormant compatibility deployment.** Deploy the additive
    contract in `report` mode without changing catalogue membership or raising
    the client minimum. Record it as the verified rollback predecessor, prove the
    released app and stable legacy app both behave safely, and survive a natural
    ingest.
16. **APP-GATE-B — cutoff activation.** From the same additive-capable runtime,
    republish current verified data with exact APP-01 `app_min_version`, record
    the immutable legacy cutoff tuple, and publicly verify it. Its verified
    rollback predecessor is APP-GATE-A and therefore continues emitting the
    additive contract. No catalogue changes occur in either gate slice.
17. **E3 — quarantine mode.** Activate `quarantine` while retaining the legacy
    observation gate. Prove invalid products disappear everywhere, valid output
    parity remains, and unsupported apps cannot consume the changed catalogue.
18. **E4 — product-scoped mode.** Publish a public diagnostic candidate and
    validate it with the receipted internal APP-01 test build; separately prove
    the released APP-01 APK rejects diagnostic tags and accepts the same contract
    only after APP-GATE-B production activation. Then activate `product_scoped`
    in daylight under that minimum and survive a natural ingest before stable.
19. **F/G — provider, v2, macro, and operations hardening.** Diagnose endpoint
    failures with retained evidence; keep v2 independent/default-off until
    verified; move and consistently back up macro storage; then repair journald,
    alerts, WayVNC, and planned power-cycle recovery.

No slice may combine documentation approval, backup foundation, transactional
publication, app release, and gate activation into a single irreversible change.

A0 through B3 are non-production prerequisite/evidence slices. They may operate
only on the separate backup target and isolated checkouts; they do not activate
production services, timers, candidates, or publication. Their purpose is to
create the backup, restore, genesis-record, and rollback evidence that the full
runtime gate requires. The full gate below first applies to Phase C and every
later production activation slice.

### Exact slice acceptance gates

Every runtime slice requires the exact candidate SHA in a clean `origin/main`
worktree; verified plan identity; exact-head CI/review/bot gates; an
observation-bound backup and scratch restore; verified previous SHA and rollback
proof; an isolated retained-real-data canary; database/schema/membership,
contract/ledger/pointer/raw-attempt/digest verification; stable and upgraded app
evidence for clean, gap, outage, offline, and large-report states; a diagnostic
release whose public bytes verify; daylight deployment, service/dashboard
checks, two-hour soak, and rollback readiness; then one observed natural ingest
with dated, rolling, and index verification before advancement.

### Required retained-real-data cases

- **2026-08-23 parity:** unaffected product/rate rows match the existing
  consumer-safe view. Every difference is explained by a disposition.
- **2026-08-24 gaps:** Aussie Home Loans 404 and DDH Graham 406 are attributable
  provider gaps; stale products are absent; all other valid products publish;
  the app opens the date and concisely reports affected providers/products.
- **2026-08-25 accounting mismatch:** reproduce the observed disagreement where
  ingest status reported seven partial providers while the public core reported
  three failed and four partial. New code must fail report reconciliation and
  cannot authorize publication until one canonical membership view is used.
- **2026-08-15 catastrophic case:** remain blocked when provenance or membership
  cannot reconcile. It is not blocked merely for exceeding an arbitrary count.
- **High-volume reconciled failure:** publish valid products with `severe`
  disclosure when every inclusion and exclusion is proven.
- **All products invalid:** retain the previous verified rolling payload because
  zero individually publishable products is a global blocker.

### Failure, rollback, and correction rules

- On ingest failure, preserve raw and terminal evidence, keep the last verified rolling payload, and do not force or overwrite the primary observation.
- On publication-only failure, never rerun ingest; retry only failed components using the immutable original observation pointer.
- An older retry may repair its dated/revision release but cannot replace a newer rolling observation or remove newer index entries.
- Disable a newly activated mode before code rollback when that restores the previous safe gate, and record both transitions.
- Roll back only to the previous SHA in the verified deployment record, never arbitrary local HEAD.
- After any post-checkout failure, restore the verified previous SHA and mode, reapply services, and repeat cleanliness, timer, dashboard, database/payload, and public freshness checks.
- Same-day correction creates a new generation and revision tag; never mutate the original dated observation or historical SQLite file.
- If semantic failure is discovered after acceptance, stop advancement and run
  this correction transaction; never delete or overwrite the original dated
  release:
  1. Select the newest effectively accepted predecessor, or first publish and
     verify an immutable replacement revision. APP-GATE-B activation and every
     later acceptance require a separately verified retained fallback, so the
     normal correction path cannot reach zero candidates.
  2. Build a new canonical index by appending exactly one terminal event for the
     bad generation: `withdrawn` with nullable replacement linkage, or
     `superseded` naming the already verified replacement. Publish and publicly
     verify that full index before altering rolling.
  3. Until rolling is recommitted, the app observes the index/rolling mismatch
     and immediately uses its retained predecessor with an explicit verification
     or withdrawal notice; it must never continue showing the withdrawn current
     generation and this is never a silent date downgrade.
  4. Publish a new rolling manifest for the selected fallback. Its commit binds
     the fallback dated manifest and exact immutable entry plus the newly
     verified full-index and quality hashes. This is the sole monotonicity
     exception: rolling may move backward only because the previously current
     generation is terminally withdrawn or superseded in that exact index.
  5. Download and verify rolling and index together. If rolling publication
     fails, keep the append-only index and retry only step 4 idempotently. Clear
     correction pending only after both components match publicly.

If exceptional evidence invalidates every retained generation, append and verify
the terminal event first, then publish a rolling `publication_state=unavailable`
control manifest last under checked-in `rolling-unavailable-v1.schema.json`. Its
exact top-level keys are `schema_version=1`,
`publication_state="unavailable"`, `reason_code`, `generated_at`, `compatibility`,
and `commit`; it contains no `observation`, `files`, `run_date`, or `generation_id`.
`compatibility` contains schema version 1, exact APP-01 minimum, and the immutable
legacy cutoff. `commit` contains only schema version 1, `dates_index_sha256`,
`terminal_event_id`, `previous_rolling_manifest_sha256`, and
`cutoff_activation_event_id`. The downloaded index must match the full-index
hash; the terminal event must be its effective event for the previously rolling
generation; the activation event and cutoff must match; and the previous rolling
hash must equal the producer's last publicly verified receipt.

APP-01 must implement an explicit unavailable-manifest parsing branch before
APP-GATE-B. That branch is exempt only from accepted-entry, observation, and
product-asset requirements; all schema, HTTPS, canonical-hash, index, event,
cutoff, and anti-replay checks remain mandatory. On success it clears current
catalogue views, preserves saved references without resolving them, and shows
“Current rates unavailable while data is verified.” Retry a later replacement as
a new immutable acceptance transaction. Never leave or restore a known-invalid
generation merely to avoid an empty UI.

### 2026-08-25 natural-run evidence and disposition

The scheduled stable run started once at 01:00 and exited zero at 01:16:47. The
dashboard returned, the lock cleared, raw evidence was retained, SQLite
`quick_check` returned `ok`, and dated/rolling/index public assets were
hash-verified. It contained 3,039 products, 17,120 rates, and 17 attributable
failures across seven providers, with zero corrupt or unattributed records.

Controlled acceptance is `FAIL`, not `PASS`: `ingest-status.json` classified 112
providers complete and seven partial; public core classified 116 succeeded,
three failed, and four partial; and the manifest had no observation disclosure.
The operational Pi and public Aug 25 payload remain in place. This does not
authorize an emergency rerun, force, rollback, or publication edit.

### Version 1.2 evidence records

New execution IDs use `DOC-03`, `LAPTOP-BACKUP-01`, `LAPTOP-RESTORE-01`,
`NATURAL-02`, `PHASE-A0`–`A4`, `PHASE-B1`–`B3`,
`PHASE-C`, `PHASE-D`, `PHASE-E1`–`E4`, `APP-01`, `APP-GATE-A`, `APP-GATE-B`,
`PHASE-F`, and `PHASE-G`.
Each hash-linked JSONL entry records schema/step/execution IDs; plan identity and
hashes; candidate/previous SHAs; mode; operator/timestamps; exact commands and
exit codes; evidence paths/sizes/hashes; observation and artifact identities;
service/dashboard/GitHub/app/backup/restore/rollback results; controlled result;
and authorized deviations with risk, controls, and revised criteria.

Completed entries and evidence files are create-once. A correction is a new
hash-linked entry; it never edits the prior record.

## Retained v1.0 execution clarifications

This section is retained for audit provenance. Its non-conflicting safety
controls continue, but its dated canary command, v1.0 thresholds, old step IDs,
and statements superseded by D-003 are historical and must not be executed as a
current instruction. The v1.1 amendment above is authoritative.

### Immutable identities and document gate

- Stable Pi commit: `9302890fcc752cbf90da97d597e972c157d913e3`.
- #506 provider-accounting commit: `417a4bd52817f8e952fc719b4e108fadda4adc52`.
- Source `main` before this documentation PR: `71003a5c1b69fe1da90c3781629fbfb5eda948a0`.
- WIP-only `dev`: `cd32e51ef5f5fc95491b0548724ce5d6b5b5c359`.
- Quarantined restoration branch: `d92382f3d9df9a98c21791033ae2a1478d5b9414`.
- Held PR #508 reviewed head: `6ad1e48b72b59120c897db45d78f1fcab706eddc`, parent `b4ce14c22b1e3b5d8848d4d80de72ece63276cdc`.
- `BASE-01` may be read-only before merge. `CANARY-01`, `GH-01`, and every
  remediation or public-repository mutation remain prohibited until the
  documentation PR is merged, its document-containing commit plus raw and
  controlled hashes are recorded externally, and the post-merge `main` SHA is
  fetched and recalculated.
- After merge, verify this file at this path; do not recreate it. A content
  change requires version 1.1 or later through a new controlled PR.

### Known limitations of the pinned 01:00 producer

- The decision to keep production pinned is authoritative. It also means the
  `2026-08-24` natural run is an observation of the last-known-good operational
  path, not proof of safeguards that exist only in #506/#507.
- The pinned producer may publish rolling v1 before the operator detects that
  row-derived disclosure disagrees with the authorising export contract. It
  cannot truthfully satisfy the later additive observation-disclosure contract.
- The pinned producer may lose RAM-only raw attempt evidence on a non-zero exit,
  timeout, power loss, or pre-promotion build failure because #507 is absent.
- These are unmitigated tonight because disabling publication or deploying code
  would violate the production freeze. Record either condition as `FAIL`, never
  relabel it `PASS`, preserve whatever evidence exists, and do not claim the
  natural run met the future-state acceptance contract.
- Do not delete a bad public release or overwrite historical data during the
  quiet window. Preserve evidence and correct the producer through the
  controlled remediation phases.

### Exact canary isolation and command

The canary is cancelled for 2026-08-23 if all document, path, baseline, and
resource gates are not proven by 21:30 Australia/Hobart. It must not be deferred
into the quiet window or started late to satisfy a checkbox.

Before start, resolve and compare every path, inspect the effective environment,
and require all of the following:

- `AR_LOCAL_DATA_ROOT=/srv/ar-local/canary/20260823/data`;
- `AR_LOCAL_RAM_ROOT=/dev/shm/ar-local-canary-20260823`;
- no production `EnvironmentFile` is loaded;
- production checkout and `/srv/ar-local/data` are read-only to the unit;
- only the canary data and RAM roots are writable;
- at least 4.5 GiB `MemAvailable`, at least 500 GiB free on the data volume,
  no OOM event since baseline, and memory PSI `avg10` below 10%;
- dashboard HTTP status 200 within five seconds immediately before start.

Start the transient unit from the candidate checkout using the following
literal command, after substituting only the post-merge full candidate SHA in
the evidence record (not in these paths):

```sh
sudo systemd-run \
  --unit=ar-local-canary-20260823 \
  --property=Type=exec \
  --property=WorkingDirectory=/srv/ar-local/canary/20260823/source \
  --property=Environment=AR_LOCAL_DATA_ROOT=/srv/ar-local/canary/20260823/data \
  --property=Environment=AR_LOCAL_RAM_ROOT=/dev/shm/ar-local-canary-20260823 \
  --property=Environment=PYTHONDONTWRITEBYTECODE=1 \
  --property=ProtectSystem=strict \
  --property=ReadOnlyPaths=/srv/ar-local/AR-local \
  --property=ReadOnlyPaths=/srv/ar-local/data \
  --property=ReadWritePaths=/srv/ar-local/canary/20260823 \
  --property=ReadWritePaths=/dev/shm/ar-local-canary-20260823 \
  --property=MemoryHigh=2500M \
  --property=MemoryMax=3G \
  --property=MemorySwapMax=0 \
  --property=CPUQuota=200% \
  --property=IOWeight=10 \
  --property=TasksMax=256 \
  --property=OOMPolicy=stop \
  --property=KillMode=control-group \
  --property=TimeoutStopSec=30s \
  --property=RuntimeMaxSec=90m \
  /usr/bin/python3 /srv/ar-local/canary/20260823/source/cdr_daily.py \
    --runs /srv/ar-local/canary/20260823/data/runs \
    --state /srv/ar-local/canary/20260823/data/state \
    --date 2026-08-23 \
    --banks-only \
    --ram-stage \
    --ram-root /dev/shm/ar-local-canary-20260823 \
    --archive-failed-ram-stage \
    --workers 2 \
    --detail-workers 2
```

Any dashboard probe failure, response over five seconds, new OOM event, memory
PSI `avg10` at or above 10%, `MemAvailable` below 2 GiB, or production mutation
stops the canary unit immediately. `KillMode=control-group` must remove every
descendant. The unit, child PIDs, canary lock, and RAM stage must be quiescent by
23:30.

At 00:30, prove the canary unit has no active children, no production lock
exists, production unit/timer definitions and data hashes/mtimes are unchanged,
the next timer trigger is exactly 01:00, resources recovered, and the dashboard
is healthy. If any fact is unknown, record `BLOCKED`; do not attempt repairs or
restarts inside the quiet window.

### Exact data and publication gates

- Bounded partial additionally requires `products_discovered > 0`,
  `providers_registered > 0`, and `register_sources_attempted > 0`; zero
  denominators never pass vacuously.
- The existing `cdr_ledger_replicate.py` covers legacy `_exports` partitions
  only. Phase A must add an inventory for ledger v2, export contracts, pointers,
  completion markers, raw attempts, publication state, and macro storage. Never
  run the legacy integrity `build` mode over preserved history. Back up SQLite
  through its backup API or verified quiescence that includes WAL/SHM files.
- A dated v1 generation is create-once. A same-day revision uses a distinct
  immutable generation/revision tag; it never clobbers the original dated
  manifest. Dates index success requires a monotonic superset, inclusion of the
  current verified dated generation, no removal except an explicit gap record,
  and public post-download verification.
- Before changing the already-public v2 channel, prove consumer behavior.
  Preserve old assets, publish a non-destructive deprecation/quarantine state,
  and split future state into `v2_product_history` and
  `v2_economic_outlook`. Define source- and frequency-specific macro freshness,
  including how monthly reference periods are dated.

### External append-only evidence

The controlled runbook is immutable. Execution records are hash-chained JSONL
under `/srv/ar-local/canary/evidence/ARL-OPS-001/<execution-id>/execution.jsonl`
and are copied to the corresponding immutable GitHub canary/diagnostic evidence
release. Each record contains the required plan identity, both hashes, exact
commands, stdout/stderr artifact hashes, candidate SHA, state transition,
operator, timestamps, result, and authorised deviation. Each entry includes the
previous entry SHA-256; a runbook change creates a new version rather than
editing completed evidence.

## Retained v1.0 source plan (historical)

The remainder of the v1.0 source plan is preserved for provenance. It is not a
current command sheet where a date, threshold, phase order, interface, or step
ID conflicts with the v1.1 controlling amendment above.

Before any canary, deployment, or remediation, write the entire contents of this plan verbatim to:

`docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md`

Create it from a fresh `origin/main` worktree. Do not touch the existing dirty checkout or its unrelated `.cursor/` and `.codex/` changes.

The document must contain:

- Document ID: `ARL-OPS-001`
- Version: `1.0`
- Status: `Controlled execution plan`
- Effective date: `2026-08-23`
- Owner: AR-local operator
- Time zone: Australia/Hobart
- Git commit containing the document
- SHA-256 of the final document
- Fixed decisions, known risks, phases, commands, acceptance gates, stop conditions, rollback procedure, and evidence ledger
- A version history in which prior entries are never rewritten

Add prominent links to the runbook from `AGENTS.md`, `README.md`, and `docs/UNIVERSAL_ROADMAP.md`. Those files must direct every future Pi ingest, payload, database, backup, or deployment task to read the runbook completely before acting.

Use a documentation-only branch and PR. After normal CI and review gates, merge it before remediation begins. The merge changes `main`, so all candidate SHAs must be recalculated afterward.

Every execution record and deployment acceptance manifest must include:

- `plan_document_id`
- `plan_version`
- `plan_git_commit`
- `plan_sha256`
- candidate code SHA
- operator and timestamps
- exact commands
- evidence paths and hashes
- result: `NOT_STARTED`, `RUNNING`, `PASS`, `FAIL`, `BLOCKED`, or `ROLLED_BACK`
- deviations and their authorization

A deviation cannot be made conversationally. It requires an append-only decision entry explaining the reason, risk, compensating controls, and revised acceptance criteria. Completed evidence must never be edited.

## Fixed safety decisions and known risks

- Production remains pinned at the known-working `9302890` through the coming 01:00 ingest.
- `dev` remains WIP-only and is never a production source.
- The divergent Claude restoration branch remains quarantined.
- PR #508 remains excluded until the existing 406/404 failures are understood.
- The power cycle approximately one hour before diagnosis was intentional and is not treated as an unexplained reboot.
- The current production job intentionally pauses the dashboard during ingest. “Pi remains functional” means the pause is controlled, the ingest does not damage other services, and the dashboard automatically returns.
- Current `main` initially contained #506 provider-accounting protection and #507 early raw-attempt preservation, but it was not yet proven as a production deployment.
- The current publication path can report success without independently proving the dated release, rolling release, and dates index all succeeded.
- v2 and macro data can become stale independently of v1.
- There is no currently proven automated rollback from a newer `main` to the pinned stable commit.
- The Pi has substantial local disk capacity, but no currently proven active off-device backup and restoration path.
- Journald persistence and alert delivery are unreliable, so the coming ingest must be observed directly.
- The current stable code is preserved for 01:00 even though it lacks the later safeguards. Introducing unproven code before the scheduled run is a greater immediate risk.

## Today’s isolated ingest and the 01:00 run

### 1. Freeze and baseline production

Record, without changing anything:

- exact Pi commit and repository cleanliness;
- current `origin/main`, `dev`, PR #508, and quarantined branch SHAs;
- system boot time and reason;
- timer and service definitions;
- active processes and ingest lock state;
- free disk, memory, swap, and OOM history;
- dashboard HTTP health at `http://100.78.28.10/`;
- production data and state paths;
- latest completion, observation, contract, ledger, and publication pointers;
- current daily SQLite file, size, hash, and `PRAGMA quick_check`;
- current public v1, v2, and dates-index manifests and asset hashes;
- modification times and hashes of production files that the canary must not change.

Abort if the Pi is dirty, the stable commit differs unexpectedly, the timer is unhealthy, an ingest is already active, or any production path cannot be identified unambiguously.

### 2. Run a real 2026-08-23 shadow ingest

Use a clean detached checkout of the exact post-documentation `origin/main`. Never use the production checkout, `dev`, or PR #508.

Use isolated locations:

- `/srv/ar-local/canary/20260823/source`
- `/srv/ar-local/canary/20260823/data/runs`
- `/srv/ar-local/canary/20260823/data/state`
- `/dev/shm/ar-local-canary-20260823`

Resolve every path before starting. Abort if a path falls inside production data, production state, or the production checkout.

Copy—not symlink or hardlink—the minimum verified 2026-08-22 history required for change calculation. Record source and destination hashes.

Run `cdr_daily.py` for `2026-08-23` with:

- canary `--runs`, `--state`, and `--ram-root`;
- `--banks-only`;
- two workers;
- failed RAM-stage preservation;
- no production `pi_daily_sync.py`;
- no production lock;
- no production dashboard pause;
- no production payload publication.

Run it as a transient systemd unit with:

- `MemoryHigh=2.5G`;
- `MemoryMax=3G`;
- a two-core CPU limit;
- low I/O weight;
- a 90-minute runtime limit.

Start by 21:30. Terminate only the canary unit if incomplete at 23:00. Finish evidence gathering by 23:30 and enter the quiet window by 00:30.

During the run, monitor dashboard HTTP, memory pressure, OOM events, disk space, and production modification times. Abort the canary if it mutates production, causes persistent dashboard failure, approaches its memory limit, or risks overlapping the scheduled ingest.

### 3. Validate today’s canary database and exports

Require:

- successful process completion;
- preserved raw attempts;
- a valid completion marker;
- a valid export contract;
- a ledger-bound observation;
- valid observation pointers confined to the canary root;
- SQLite `PRAGMA quick_check`;
- expected schema and required tables;
- contract and ledger hash verification;
- provider and product population reconciliation;
- explicit enumeration of unpriced or omitted products;
- no unexplained difference between discovered, detailed, and priced populations.

> **Historical v1.0 threshold — superseded by D-003. Do not use for new
> publication decisions.**

A partial observation was eligible in v1.0 only when:

- failure and register provenance are complete;
- corrupt and unattributed failures are zero;
- all registered providers were attempted;
- all register sources completed;
- no provider failed completely;
- failures are between 1 and 50;
- failures are no more than 1% of discovered products;
- partial providers are no more than 15% of registered providers.

Anything outside those limits is retained as diagnostic evidence but is not publishable.

### 4. Exercise GitHub delivery safely

Build v1 from the canary exports and publish only to:

`payload-smoke-20260823-<candidate-sha>`

Before publication, prove that no production consumer references this tag.

The diagnostic release must contain:

- v1 core and details assets;
- manifest uploaded last;
- canary report containing the plan identity and evidence;
- exact hashes and sizes;
- observation state and coverage disclosure.

Do not modify:

- `app-payload-latest`;
- any production dated tag;
- production `dates-index.json`;
- v2;
- production pending state.

Download every asset from public GitHub and verify bytes, SHA-256, schema, run date, generation, coverage, and manifest references. Retain the diagnostic release as evidence; it does not authorize deployment.

### 5. Protect the natural 01:00 ingest

From 00:30 until completion:

- no deployments;
- no canary work;
- no manual ingest;
- no service restart;
- no package update;
- no production publication manipulation.

Immediately before 01:00, perform read-only checks of timer status, locks, disk, memory, GitHub connectivity, previous completion state, and dashboard health.

Observe the natural `2026-08-24` run directly.

Accept it only when:

- the scheduled unit starts once;
- no competing ingest exists;
- raw evidence is retained;
- finalization succeeds;
- the database and contracts validate;
- provider accounting satisfies policy;
- the dashboard resumes automatically;
- the dated v1 release, rolling v1 release, and dates index are separately verified from public GitHub;
- the public manifest accurately discloses a bounded partial result, if applicable.

Failure handling:

- On ingest failure, preserve all evidence, retain the previous public payload, and do not delete or overwrite the day.
- Do not reflexively run `--force`.
- On publication-only failure, do not rerun ingest. Verify the recorded observation and use the existing-payload retry path.
- If a result exceeds partial thresholds, withhold it and retain the last verified rolling payload.
- Upstream CDR failures do not become “success” merely because the process exits zero.

## Incremental remediation train

Each slice uses a separate PR. It must pass exact-head CI, isolated canary validation, backup and rollback gates, daylight deployment, Pi verification, and one natural ingest before the next behavioral slice advances.

### Phase A — Backup and recovery foundation

- Inventory daily SQLite databases, raw attempts, export contracts, completion markers, pointers, ledger, payload state, macro store, systemd configuration, deployment metadata, and secrets-file locations without copying secrets into Git.
- Wire the existing replication tooling to physically separate mounted storage.
- Back up the production code SHA, Pi configuration, systemd definitions, state, current data, publication state, and macro database.
- Restore a copied observation into scratch storage and verify SQLite integrity, contracts, ledger, pointers, and exports.
- Prove the bootable clone by actually booting it and verifying network, dashboard, ingest timers, and storage identification.
- Block deployment if the backup target is absent, stale, writable by the wrong user, or fails restoration.

### Phase B — Deployment and rollback infrastructure

- Production candidates originate only from exact immutable `main` commits.
- Record the last-known-good commit in an immutable deployment record.
- Configure the `pi-production` GitHub environment, required approval, Tailscale/SSH secrets, and exact candidate variables.
- Add a canary-evidence producer covering preservation, historical integrity, shadow ingest, producer contracts, stable-app compatibility, emulator/device checks, and public candidate bytes.
- Add a rollback workflow before deploying new runtime code.
- Rollback may use only the previous SHA named in a verified deployment record, requires production approval, and runs the same cleanliness, backup, service, dashboard, and payload checks.
- Prove deploy and rollback using a non-production checkout.

### Phase C — Promote the current-main safeguards

- Continue holding PR #508.
- After infrastructure merges, recalculate the exact candidate SHA.
- Rerun full CI and the isolated real-data ingest against that exact SHA.
- Deploy only during daylight with at least two hours of soak and several hours before the next 00:30 freeze.
- This introduces the #506 provider-accounting gate and #507 early raw-attempt preservation without importing `dev`.
- Verify services, dashboard, database, contracts, pointers, payload bytes, and rollback readiness.
- Do not label the candidate stable until it survives a natural 01:00 ingest.

### Phase D — Transactional v1 publication

Treat these as separate required components:

- immutable dated v1;
- monotonic rolling v1;
- dates index.

For every component:

- stage locally;
- upload assets first;
- publish the manifest or pointer last;
- download public bytes;
- verify SHA-256, size, schema, and observation identity;
- persist success or failure independently.

Clear publication pending only when all required v1 components are publicly verified. Retry only incomplete components and always use the original observation pointer. An older retry may repair its dated release but cannot replace a newer rolling payload.

Add an independent freshness monitor that reads public GitHub state rather than trusting producer logs.

### Phase E — Data completeness and provider recovery

- Analyse retained 406/404 attempts using their real provider, URL, response, and timestamp.
- Determine whether each failure is endpoint drift, request formatting, throttling, breaker behaviour, or genuine upstream rejection.
- Implement provider-specific repair or same-day top-up only when provenance remains auditable.
- Test PR #508 separately. Its recovery probe is not accepted as a fix for an incorrect endpoint or missing population.
- Preserve the original daily database. Same-day reruns create a separate generation and never overwrite the primary observation.
- Reject any payload whose missing priced population cannot be explained and disclosed.

### Phase F — v2 and macro repair

- Keep v2 default-off until it has independent state, retry, freshness, and public verification.
- Move the macro SQLite store outside the checkout.
- Back it up using SQLite’s consistent backup mechanism.
- Schedule and monitor refreshes.
- Reject future-dated, stale, or internally inconsistent macro observations.
- v2 failure must never clear v1 pending state or be reported as complete v1 publication.

### Phase G — Operational hardening

After ingest and payload correctness are proven:

- make journald persistent and bound its storage;
- repair alert credentials and test delivery;
- add independent missed-ingest and stale-payload alerts;
- resolve the WayVNC restart loop without affecting dashboard services;
- record reboot reason and post-boot validation;
- run a planned power-cycle recovery test with dashboard, network, timer, storage, and payload checks.

## Interfaces and compatibility

Add an additive v1 observation block containing:

- observation state;
- generation ID;
- export-contract digest;
- ledger digest;
- registered, attempted, complete, partial, and failed provider counts;
- discovered, detailed, priced, and unpriced product counts;
- failure, corrupt, and unattributed counts;
- missing or partial provider disclosure.

Existing stable-app fields remain unchanged.

Replace the ambiguous pending marker with a versioned internal publication record containing independent:

- `dated_v1`;
- `rolling_v1`;
- `dates_index`;
- `v2`.

Each component records intended observation, tag, manifest hash, asset hashes, attempts, public verification time, status, and last error. Read the legacy marker for one compatibility release.

Historical daily SQLite files remain immutable. New metadata uses versioned sidecars or new generations, never in-place historical migrations.

## Verification matrix and completion criteria

Required automated and real-data scenarios:

- interruption or reboot after raw download, database creation, finalization, each asset upload, and each manifest update;
- missing GitHub token, timeout, partial upload, propagation delay, stale rolling payload, and idempotent retry;
- 406/404 responses, completely failed provider, threshold boundaries, corrupt/unattributed evidence, and unexplained unpriced products;
- same-day revision isolation and primary-observation preservation;
- stale/future macro values and independent v2 failure;
- dirty Pi checkout, mismatched candidate SHA, missing plan checksum, failed canary evidence, deployment health failure, and rollback;
- public download and SHA-256 verification;
- stable-app compatibility and required emulator/device evidence;
- planned power cycle and catch-up behaviour.

A phase is complete only when its evidence ledger entry contains:

- exact code and plan SHAs;
- exact commands;
- timestamps;
- source and public artifact hashes;
- database and contract results;
- dashboard/service results;
- GitHub results;
- rollback result where applicable;
- explicit `PASS`;
- links to durable logs and evidence.

The safe default for every failed or uncertain gate is:

- keep the Pi on the last-known-good commit;
- keep the previous verified rolling payload public;
- preserve raw data and diagnostic state;
- make no unrecorded deviation;
- continue only after the controlled document records the revised decision.

## Execution evidence ledger schema

> **Historical v1.0 step IDs — new records use the v1.1 IDs above.**

The append-only ledger is external as specified above. Its v1.0 step IDs
are `DOC-01`, `BASE-01`, `CANARY-01`, `GH-01`, `NATURAL-01`, and `PHASE-A`
through `PHASE-G`. A state transition is invalid unless its JSONL entry contains
all document-control fields and a valid previous-entry hash.

## Version history

This table is append-only.

| Version | Effective date | Git commit | Controlled plan SHA-256 | Change |
|---|---|---|---|---|
| 1.0 | 2026-08-23 | Resolve from Git history after merge | `510937fc4d09d0e9066c5830fedd80053c9d3c40a062c34c8acce764f1fa8adc` | Initial controlled recovery runbook transcribed from the approved plan with mandatory execution clarifications D-001 and D-002. |
| 1.1 | 2026-08-25 | Resolve from Git history after merge | `4aa3a4d6e16d770e275801c10cdc1eecc56309f7998f4399000367db56e2fa46` | Added controlling decision D-003, product-day atomic publication, canonical product/provider accounting, new-observation SQLite and public quality contracts, AR-app disclosure and compatibility gates, staged feature modes, repaired backup/rollback prerequisites, retained-real-data acceptance cases, and the incremental activation train. |
| 1.2 | 2026-08-25 | Resolve from Git history after merge | `94b089741670e4d8949b28f698f59b5851797bcf22b58d47ba57d15bdc687194` | Added D-004 and the controlled laptop pull-backup architecture: classified the historical recovery-image candidate, immutable compressed per-observation generations, 50 GiB free-space floor, SQLite-consistent macro capture, atomic transfer/catalog protocol, restore drills, scheduling, and residual-risk boundaries. |
| 1.3 | 2026-08-25 | Resolve from Git history after merge | `8834990f8c3cfbe86d4006b0d4fca3c564c760362a0928bf2a688f6dacd83a3d` | Added D-005 before first transfer: full retained/failed-run scope, simultaneous archive-and-scratch capacity, complete tar metadata verification, durable file/directory commit barriers, independent observation/control/macro freshness, explicit mounted-storage supersession, and unambiguous DOC-03 execution identity. |
| 1.4 | 2026-08-27 | Resolve from Git history after merge | `b234469085141f8799a7744f20980728bf829970758e904126b811dca7f98218` | Added D-006 and the normative multi-day continuity model: daily 01:00 current-day-only capture takes precedence over remediation, repeating freeze/validation/backup cadence, independent daily outcomes, immutable source-gap handling, same-day recovery limits, cross-day phase resumption, and an explicit transition for the in-flight v1.3 A3 proof. |
