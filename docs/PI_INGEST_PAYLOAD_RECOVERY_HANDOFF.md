# AR-local Pi ingest and payload recovery handoff ledger

## Purpose and authority

This is the append-only operational continuation ledger for controlled runbook
[`ARL-OPS-001`](PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md). It exists so a new
human operator, LLM, or session can resume the multi-day recovery program
without relying on chat history, automation text, memory, or reconstruction.

This file does not replace the controlled runbook or immutable execution
evidence. The runbook controls policy, gates, stop conditions, and deviations.
This ledger records the current phase, the last accepted evidence, and the exact
next action. Source evidence remains authoritative at the paths and hashes
listed in each entry.

Before any Pi ingest, payload, database, backup, canary, deployment, recovery,
or publication action:

1. read `docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md` completely;
2. verify its document-containing Git commit and controlled SHA-256;
3. read this ledger completely and select the last chronological entry;
4. verify every live prerequisite in that entry rather than trusting its
   point-in-time snapshot; and
5. stop if the runbook, ledger, source evidence, task configuration, Pi state,
   or current date differs unexpectedly.

## Append-only rules

- Never edit, reorder, delete, squash, or reinterpret a completed entry.
- Append one new entry after every terminal gate, material state change,
  authorised deviation, failed check, or handoff to another session.
- The last chronological entry is the resume pointer. An entry may supersede an
  earlier entry only by naming it and explaining why; the earlier entry remains.
- `RUNNING` means the next operator must continue the named gate. It does not
  mean permission to advance to the next phase.
- A correction is a new entry with a new ID, timestamp, reason, risk,
  compensating controls, and revised acceptance criteria.
- Never copy secrets, tokens, private keys, passwords, full environment files,
  or secret values into this file or Git.
- Chat, memory, automation prompts, and summaries are advisory. If their state
  is not represented here or in immutable evidence, revalidate and append it.
- Point-in-time health expires. Re-run the listed preflight before acting.
- Daily natural-ingest evidence and backup evidence remain independently
  append-only. Neither result implies the other.

## Required entry schema

Every future entry must include:

- entry ID and creation time in Australia/Hobart and UTC;
- author/operator;
- result: `NOT_STARTED`, `RUNNING`, `PASS`, `FAIL`, `BLOCKED`, or
  `ROLLED_BACK`;
- controlling plan document ID, version, commit, controlled SHA-256, and raw
  file SHA-256 when recorded by the execution;
- in-flight legacy plan identity when an immutable older execution continues;
- production SHA, candidate SHA, repository path, and cleanliness;
- current phase, completed gates, open gates, and prohibited advancement;
- exact source evidence paths, sizes, SHA-256 values, and catalog sequence;
- the latest validated observation identity and independent capture,
  finalization, publication, dashboard, and backup states;
- exact next action, earliest start, latest safe stop, commands, acceptance
  criteria, stop conditions, and rollback or preservation action;
- known risks, unresolved findings, deviations, and authorization; and
- the previous handoff entry ID, or `NONE` for the first entry.

---

## Entry `HANDOFF-20260827T220351+1000`

### Control record

| Field | Value |
|---|---|
| Previous handoff entry | `NONE` |
| Created, Australia/Hobart | `2026-08-27T22:03:51+10:00` |
| Created, UTC | `2026-08-27T12:03:51Z` |
| Operator | `Codex for jkoka` |
| Result | `RUNNING` |
| Current phase | `A3 — backup crash recovery and first natural scheduled proof` |
| Controlling plan document | `ARL-OPS-001` |
| Controlling plan version | `1.4` |
| Controlling plan Git commit | `14dd066099bba393cccf61a280243e43162eedc9` |
| Controlling plan SHA-256 | `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Controlling plan raw Git-blob SHA-256 | `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4` |
| In-flight A3 plan version | `1.3` |
| In-flight A3 plan Git commit | `8efefe10890a295ef87f97b46d3cb981193cfddc` |
| In-flight A3 plan SHA-256 | `8834990f8c3cfbe86d4006b0d4fca3c564c760362a0928bf2a688f6dacd83a3d` |
| Protected Pi code SHA | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Installed receiver candidate SHA | `c87cdd0077e209d1824bbe485c0f5ad30723d0c4` |
| Deviations | None |
| Deviation authorization | None |

The v1.3 identity above is deliberate, not stale metadata. The already-installed
A3 task and its first natural 05:00 execution are one immutable in-flight proof.
Do not relabel, reinstall, update, or rerun it under v1.4. ARL-OPS-001 v1.4
controls the surrounding multi-day cadence and the transition after A3 reaches
a terminal result.

### Current phase status

| Gate | State | Meaning |
|---|---|---|
| Controlled runbook v1.4 documentation | `PASS` | Merged and checksum verified |
| Laptop backup/restore prerequisite gate | `PASS` | Installer accepted current observation, control, macro, diagnostics, and historical coverage |
| A3 task installation/read-back | `PASS` | Exact candidate installed with required triggers, overlap prevention, retries, and six-hour limit |
| A3 manual Task Scheduler runtime proof | `PASS` | Task ran as configured and produced an immutable successful no-write record |
| Natural `2026-08-28` 01:00 ingest | `NOT_STARTED` | Must occur naturally; never start it manually |
| Natural `2026-08-28` 05:00 laptop backup | `NOT_STARTED` | Must occur naturally after the new observation; never trigger it early |
| A3 terminal acceptance | `RUNNING` | Cannot pass until both natural executions and their evidence pass |
| A4 physical recovery proof | `NOT_STARTED` | Prohibited until A3 is terminally accepted and a new handoff entry is appended |
| Phases B through G | `NOT_STARTED` | No deployment or behavioral remediation is authorized |

### Authoritative paths and repository state

| Purpose | Authoritative path or state |
|---|---|
| Pi production checkout | `/srv/ar-local/AR-local` |
| Pi durable data root | `/srv/ar-local/data` |
| Pi production state root | `/srv/ar-local/data/state` |
| Pi production runs root | `/srv/ar-local/data/runs` |
| Protected production SHA | `9302890fcc752cbf90da97d597e972c157d913e3`, clean at the snapshot time |
| Laptop backup target | `C:\code\backups\AR-local-pi5` |
| Installed clean receiver | `C:\code\backups\AR-local-pi5-receiver-c87cdd0` |
| Installed receiver state | Clean at exact SHA `c87cdd0077e209d1824bbe485c0f5ad30723d0c4` |
| Historical recovery image | `C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21` |
| Existing developer checkout | `C:\code\AR-local`; dirty and stale at snapshot time; do not clean, update, deploy, or use it for controlled work |
| Clean-worktree rule | Create every new slice from fresh `origin/main` outside the dirty checkout |

At the snapshot time, `C:\code\AR-local` was at
`a0bd0f54200c91ef7aaa2fb163e752005ddb71e8`, 79 commits behind
`origin/main`, with an unrelated modified `.cursor/skills/pi-deploy-agent/SKILL.md`
and untracked `.codex/`. These are user-owned changes and must remain untouched.

### Accepted A3 evidence

All paths below are local Windows paths. Verify their bytes and SHA-256 again
before relying on them.

| Evidence | Bytes | SHA-256 |
|---|---:|---|
| `C:\code\backups\AR-local-pi5\catalog\task-definitions\installed-c87cdd0-20260827T112050Z.xml` | 2,386 | `6f69ec39707ffbe2fc2e79d712748250eb00133fb5948ce0fd9b8a0d673b2f28` |
| `C:\code\backups\AR-local-pi5\catalog\scheduled-runs\20260827T112012Z-a6655c68752c40b5ae6b6cafea49a0dd.json` | 1,944 | `da7fc47332bf0716e95cccad336740031846ce7470f73e7a79da08322f4c276e` |
| `C:\code\backups\AR-local-pi5\catalog\scheduled-runs\20260827T112135Z-43dfe67f2d054e41a3035441804495b4.json` | 1,927 | `545d0abb8d340a6a330c0ed19db1de28b4a7bbad7de6244e86fec7a3bf669f54` |
| `C:\code\backups\AR-local-pi5\catalog\latest-scheduled.json` | 195 | `cc6c8e0c1c824f009a74424f4957dee29e9c0e61ef493637a3f7f8f5aa716cbb` |
| `C:\code\backups\AR-local-pi5\catalog\generations.jsonl` | 226,763 | `6bc4beb18c7ee65083c5c899429d781c2e1055e132ddea3520364013488a218b` |
| `C:\code\backups\AR-local-pi5\catalog\latest-verified.json` | 316 | `33cebe5a1a6b17e9e58f01be194ecfaf3122868a323fe06a247eb42bb5ddca42` |
| `C:\code\backups\AR-local-pi5\catalog\latest-control.json` | 265 | `1fcf27752eb704b94d95f717747a0eef440b1ec764563d123760139cf360a568` |
| `C:\code\backups\AR-local-pi5\catalog\latest-macro.json` | 292 | `f5ebd7ad099f4821b0e4b6952b40cfc21779bd9124576fe7b4c4097c6e2b2d63` |
| `C:\code\backups\AR-local-pi5\observations\2026-08-27\e84a0d62055ad444c9bcbf2e53dcbe78f4bc148519ea2b324c9b7dcc60356363\receipt.json` | 3,392 | `4ed208724522c90f7feff56389ba6d885511af9b44596bda97c1ce5a1435794a` |
| `C:\code\backups\AR-local-pi5\control\20260827T111627Z-926a01eff002e835\receipt.json` | 2,482 | `4b687b9e794859954b7b3ab0c6840c61d315fdb9505511bb6a113d6dfae4ada8` |
| `C:\code\backups\AR-local-pi5\macro\2def7e4acc17445f29922ac398f36b3c238e3d3bd93e6329905b53a42e591586\receipt.json` | 2,223 | `91a54aa1edc03438c9bfc7ac8f604f5d46a317455e8183324281eab4859f66b0` |

Catalog state is a valid 322-entry hash chain at the snapshot time. Sequence
320 is the latest verified `2026-08-27` observation, sequence 321 is control,
and sequence 322 is macro. The observation archive SHA-256 is
`a2ebe4bd2a52506a449014025023bbe5e49df4b74cf28be7ecec43ff3159e3d1`.
The latest scheduled pointer names the manual runtime record ending
`43dfe67f2d054e41a3035441804495b4.json` and records `PASS`.

### Installed Windows task snapshot

At `2026-08-27T22:03:51+10:00`, Task Scheduler reported:

- task name: `AR-local laptop backup`;
- state: `Ready`;
- principal: `jkoka`, `S4U`, `Limited`;
- daily trigger: `05:00` Australia/Hobart laptop local time;
- boot trigger: startup plus `PT5M`;
- overlap policy: `IgnoreNew`;
- retries: three at `PT30M`;
- execution limit: `PT6H`;
- last run: `2026-08-27T21:21:21+10:00`;
- last result: `0`;
- next run: `2026-08-28T05:00:00+10:00`; and
- action path: the exact clean receiver
  `C:\code\backups\AR-local-pi5-receiver-c87cdd0` with the v1.3 plan and
  protected Pi SHA shown above.

Laptop `C:` free space was `161,576,448,000` bytes (`150.48 GiB`), safely above
the mandatory `53,687,091,200`-byte floor. Revalidate it before and after the
natural scheduled execution.

### Pi and latest-observation snapshot

This is point-in-time evidence from `2026-08-27T22:03:51+10:00`; it is not a
substitute for the mandatory 00:25 preflight.

- Pi host: `pi5`, reached through `ar-local-pi5-lan`.
- The intentional boot began `2026-08-23 18:45:28`.
- Production checkout was clean at protected SHA `9302890...913e3`.
- `ar-local-daily.timer` was enabled and active.
- Next trigger was exactly `2026-08-28 01:00:00 AEST`.
- `ar-local-daily.service` was inactive with previous `Result=success` and
  `ExecMainStatus=0`.
- `/srv/ar-local/data/state/daily-ingest.lock` was absent.
- Root/data storage had approximately `1.6 TiB` available.
- Memory had approximately `6.0 GiB` available; swap had approximately
  `1.1 GiB` free.
- Dashboard `http://127.0.0.1:8808/api/latest` returned a healthy
  `2026-08-27` observation.
- `https://api.github.com/` returned HTTP 200 from the Pi.
- No deployments, service restarts, timer changes, payload manipulation, or Pi
  writes were performed during this preflight.

Latest accepted observation:

| Field | Value |
|---|---|
| Observation date | `2026-08-27` |
| Generation | `obs-2026-08-27-7e5c661dea71d85e` |
| State | `partial` |
| SQLite path | `/srv/ar-local/data/runs/2026-08-27/_exports/local-cdr.sqlite` |
| SQLite bytes | `1,068,384,256` |
| SQLite SHA-256 | `d995b066c558fa4b430dd1a3e5a3b9c17df873c751dea8117c562303237bb601` |
| SQLite `PRAGMA quick_check` | `ok` |
| Contract digest | `242381a1090a1a83705d06bf0f4516ad180a9c01ed1eb5a7fae299c607cd5b12` |
| Ledger event digest | `587228b9d2819aa729aebd91e823c5feedd9023ce818516942a0b5ba93204102` |
| Completion/contract/ledger/pointer binding | `PASS` |
| Reachable artifact verification | `PASS`, 11,160 contracted artifacts |
| Raw attempts | 3,912; verified and durably retained |
| Registered/attempted providers | 119 / 119 |
| Complete/partial/failed providers | 111 / 8 / 0 |
| Failure/corrupt/unattributed records | 18 / 0 / 0 |
| Products | 3,027 |
| Rates | 16,835 |
| Fees | 30,377 |
| Features | 18,462 |
| Eligibility rows | 8,536 |
| Constraint rows | 5,093 |
| Product facts | 657,952 |

The `partial` state is attributable and rich, not a failed observation: all
registered providers were attempted, no provider failed completely, and corrupt
and unattributed failures were zero. It is not a promise that the next upstream
day will be complete. The natural run must be judged from its own evidence.

Public dated v1, rolling v1, dates index, and v2 bytes were not reverified in
this 22:03 preflight. They remain independent post-ingest acceptance gates and
must not be inferred from local producer success.

### Exact next action: protect and observe `2026-08-28`

The next operator must continue A3; do not start A4 or any deployment.

#### Before 00:30

1. Read the complete controlled runbook and this complete ledger.
2. Verify the runbook identity:

   ```powershell
   git -C C:\code\AR-local fetch origin main --prune
   git -C C:\code\AR-local log -1 --format=%H `
     origin/main -- docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md
   ```

   Expected document-containing commit:
   `14dd066099bba393cccf61a280243e43162eedc9`. Recompute the canonical
   SHA-256 using the algorithm in the runbook and require
   `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713`.

3. At approximately 00:25, perform read-only Pi preflight:

   ```powershell
   ssh -o BatchMode=yes ar-local-pi5-lan `
     "date --iso-8601=seconds; git -C /srv/ar-local/AR-local rev-parse HEAD; git -C /srv/ar-local/AR-local status --porcelain=v1; systemctl is-enabled ar-local-daily.timer; systemctl is-active ar-local-daily.timer; systemctl show ar-local-daily.timer -p NextElapseUSecRealtime -p LastTriggerUSec -p Result; systemctl is-active ar-local-daily.service || true; test ! -e /srv/ar-local/data/state/daily-ingest.lock; df -h /srv/ar-local/data; free -h; curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest; curl -fsS --max-time 15 -o /dev/null -w 'github_http=%{http_code}\n' https://api.github.com/"
   ```

4. Require the exact protected SHA, a clean checkout, enabled/active timer with
   next trigger at 01:00, inactive service, absent lock, healthy resources,
   healthy dashboard, and GitHub connectivity. If any differs, record
   `BLOCKED` and follow the runbook; do not improvise.

#### 00:30 through terminal ingest validation

Enforce the D-006 freeze. Read-only observation is allowed; no deployment,
canary, manual ingest, service restart, task trigger, package change, backup,
restore, clone test, storage maintenance, or publication manipulation is
allowed.

Observe the natural timer start exactly once. Do not run `--force` and do not
manually start the service. Continue read-only observation until the service is
terminal, the lock is absent, and the dashboard returns.

Natural-ingest acceptance requires, independently:

- source date `2026-08-28` and exactly one scheduled start;
- raw-attempt evidence preserved and hash-bound;
- completion marker, export contract, ledger event, and latest pointer bound to
  one generation;
- SQLite `PRAGMA quick_check=ok`, expected schema, and credible rich
  populations;
- all registered providers attempted, with complete attributable provider and
  product accounting;
- individual failures preserved and disclosed without discarding unrelated
  valid products;
- dashboard automatic return;
- dated v1, rolling v1, and dates index independently downloaded from public
  GitHub and verified; and
- v2 recorded independently rather than treated as v1 completion.

If ingestion fails, preserve all evidence and the previous verified rolling
payload. If publication alone fails, do not rerun ingest; use only the recorded
observation and the existing-payload retry procedure. If the upstream source
window is at risk, follow the runbook's same-day recovery boundary and never
substitute next-day or stale data.

#### Natural 05:00 laptop task

Do not manually trigger the task. After the natural 01:00 ingest has terminally
validated, wait for Task Scheduler's natural 05:00 run and inspect it:

```powershell
$task = Get-ScheduledTask -TaskName 'AR-local laptop backup'
$info = Get-ScheduledTaskInfo -TaskName 'AR-local laptop backup'
$task | Select-Object TaskName, State
$info | Select-Object LastRunTime, LastTaskResult, NextRunTime
Get-Content -LiteralPath `
  'C:\code\backups\AR-local-pi5\catalog\latest-scheduled.json' -Raw
```

Expected normal outcome: `BACKUP-LATEST` with `PASS`, because the natural ingest
should create a new `2026-08-28` observation. `NO_BACKUP_DATA_WRITE` is
acceptable only if observation, control, macro, diagnostics, and historical
coverage identities are independently unchanged. If the Pi observation did not
advance, investigate and record that condition; never call the no-write a pass
merely because the task exited zero.

A3 terminal acceptance requires:

- task returns to `Ready` and `LastTaskResult=0`;
- a new immutable scheduled-run record exists after 05:00 and its pointer hash
  matches;
- candidate, protected SHA, v1.3 in-flight plan, operator, timestamps, exact
  command, and deviations are correct;
- action and result are truthful;
- the backed-up observation is exactly the Pi's current accepted observation;
- control, macro, diagnostics, and historical inventory are current;
- archives, manifests, receipts, restore checks, SQLite integrity, Git bundles,
  and catalog chain pass;
- no receiver lock, `.partial`, orphan helper, or overlapping process remains;
  and
- laptop free space remains at least `53,687,091,200` bytes.

Append the next ledger entry with `PASS`, `FAIL`, or `BLOCKED`, exact new paths
and hashes, and independent natural-ingest and backup outcomes. Do not edit this
entry.

### Stop conditions and preservation actions

Stop and append `BLOCKED` or `FAIL` when any of the following occurs:

- the runbook identity or this entry's source evidence does not verify;
- the Pi is dirty or not at the protected SHA;
- the timer is not enabled/active for exactly 01:00;
- an unexpected ingest lock or competing process exists;
- the dashboard, disk, memory, network, GitHub connection, database, contract,
  ledger, pointer, or raw evidence is unhealthy;
- any requested action falls within the freeze or threatens the current-day
  source window;
- the installed task differs from the recorded XML, receiver candidate,
  principal, triggers, overlap policy, retries, or limit;
- Task Scheduler reports a nonzero result or no natural 05:00 execution;
- the backup target crosses or could cross the 50 GiB free-space floor;
- a catalog/receipt/archive/restore/hash check fails; or
- a new session cannot determine the exact safe action from the runbook and
  this ledger.

On stop: preserve raw and diagnostic evidence, keep the Pi on the protected
SHA, keep the previous verified rolling payload, do not use `--force`, do not
delete or overwrite the day, do not reinstall the task, and do not advance A4.

### Next slice after A3 terminal acceptance

Only after a new appended entry marks A3 `PASS`:

1. retain the installed v1.3 proof unchanged;
2. create a fresh `origin/main` documentation or implementation worktree;
3. update embedded backup-tooling plan constants and their tests to the current
   controlled runbook identity in a separate focused PR;
4. prove that candidate without changing Pi production; and
5. plan A4 physical recovery proof as its own bounded daylight slice, with the
   natural 01:00 ingest protected on every intervening day.

No current evidence authorizes a Pi runtime deployment, PR #508, A4, or any
Phase B–G behavioral change.

### Exact read-only commands used for this entry

The entry was assembled from these read-only command families. Their output is
summarized above; source files and hashes remain authoritative:

```powershell
git -C C:\code\AR-local fetch origin main --prune
git -C C:\code\AR-local log -1 --format=%H `
  origin/main -- docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md

ssh -o BatchMode=yes -o ConnectTimeout=10 ar-local-pi5-lan `
  "git -C /srv/ar-local/AR-local rev-parse HEAD; git -C /srv/ar-local/AR-local status --porcelain=v1; systemctl show ar-local-daily.timer; systemctl show ar-local-daily.service; test ! -e /srv/ar-local/data/state/daily-ingest.lock; df -h /srv/ar-local/data; free -h; curl -fsS http://127.0.0.1:8808/api/latest"

Get-ScheduledTask -TaskName 'AR-local laptop backup'
Get-ScheduledTaskInfo -TaskName 'AR-local laptop backup'
Get-FileHash -Algorithm SHA256 -LiteralPath <each-evidence-path>
Get-PSDrive -Name C

git -C C:\code\backups\AR-local-pi5-receiver-c87cdd0 rev-parse HEAD
git -C C:\code\backups\AR-local-pi5-receiver-c87cdd0 status --porcelain=v1
```

The latest observation was additionally verified using the protected producer's
`cdr_export_contract.load_contract`, `cdr_ledger_v2.verify_reachable_generation`,
and `cdr_finalization.verify_completion_marker`, plus SQLite read-only
`PRAGMA quick_check` and table population counts.
