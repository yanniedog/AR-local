# AR-local Pi Ingest and Payload Recovery Runbook

## Document control

| Field | Value |
|---|---|
| Document ID | `ARL-OPS-001` |
| Version | `1.0` |
| Status | Controlled execution plan |
| Effective date | `2026-08-23` |
| Owner | AR-local operator |
| Time zone | Australia/Hobart |
| Implementation model | `gpt-5.6-sol`, Max reasoning |
| Source baseline commit | `71003a5c1b69fe1da90c3781629fbfb5eda948a0` |
| Document-containing commit | Resolve with `git log -1 --format=%H -- docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md`; record the returned immutable commit in every execution record |
| Controlled plan SHA-256 | `df07c9015d9d09d07542404856c0ddf6c2b08b7a5523b12250b925a59bd5a94e` |

The controlled plan SHA-256 is calculated over this final file after replacing
every occurrence of the published 64-character controlled digest with the
literal token `PLAN_SHA256_PENDING`. This canonicalisation avoids an impossible
self-referential raw-file checksum while still detecting every other byte of
drift. The raw file SHA-256 must also be recorded externally in each execution
record and deployment acceptance manifest.

This document is the complete, authoritative execution plan. Chat context,
summaries, and operator recollection do not override it. Read it in full before
any Pi ingest, payload, database, backup, canary, deployment, or rollback work.

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

## Controlled document

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

A partial observation is eligible only when:

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

## Execution evidence ledger

This ledger is append-only. Add one row when a controlled step changes state;
store detailed command output in durable evidence artifacts and link it here.

| Step | Status | Started | Finished | Operator | Candidate SHA | Commands and evidence | Result notes | Deviation |
|---|---|---|---|---|---|---|---|---|
| DOC-01 Controlled document PR | RUNNING | 2026-08-23 |  | Codex | `71003a5c1b69fe1da90c3781629fbfb5eda948a0` | Documentation-only worktree and PR | Awaiting verification and merge | D-001 |
| BASE-01 Production baseline | NOT_STARTED |  |  |  |  |  |  |  |
| CANARY-01 2026-08-23 shadow ingest | NOT_STARTED |  |  |  |  |  |  |  |
| GH-01 Diagnostic payload publication | NOT_STARTED |  |  |  |  |  |  |  |
| NATURAL-01 2026-08-24 scheduled ingest | NOT_STARTED |  |  |  |  |  |  |  |
| PHASE-A Backup and recovery | NOT_STARTED |  |  |  |  |  |  |  |
| PHASE-B Deployment and rollback | NOT_STARTED |  |  |  |  |  |  |  |
| PHASE-C Current-main safeguards | NOT_STARTED |  |  |  |  |  |  |  |
| PHASE-D Transactional v1 | NOT_STARTED |  |  |  |  |  |  |  |
| PHASE-E Provider recovery | NOT_STARTED |  |  |  |  |  |  |  |
| PHASE-F v2 and macro | NOT_STARTED |  |  |  |  |  |  |  |
| PHASE-G Operational hardening | NOT_STARTED |  |  |  |  |  |  |  |

## Version history

This table is append-only.

| Version | Effective date | Git commit | Controlled plan SHA-256 | Change |
|---|---|---|---|---|
| 1.0 | 2026-08-23 | Resolve from Git history after merge | `df07c9015d9d09d07542404856c0ddf6c2b08b7a5523b12250b925a59bd5a94e` | Initial controlled recovery runbook transcribed from the approved plan. |
