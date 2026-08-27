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
| Dedicated plan-control repository | `C:\code\backups\AR-local-recovery-control`; create as a no-checkout clone when absent; never use the dirty developer checkout for fetch or plan verification |
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

The task XML, completed scheduled-run records, and generation receipts are
immutable and must continue to match exactly. `generations.jsonl` is an
append-only catalog, and `latest-scheduled.json`, `latest-verified.json`,
`latest-control.json`, and `latest-macro.json` are atomic current pointers. Their
recorded hashes are exact before the natural 05:00 run. After that expected run,
the catalog may only grow from the verified 322-entry prefix with a valid hash
chain, and each changed pointer must name and hash a newly verified immutable
record. A legitimate append is not evidence tampering; truncation, rewritten
prefix bytes, a broken chain, an unbound pointer, or any change before the
expected scheduled execution is a stop condition.

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

`Export-ScheduledTask` exactly matched the recorded 2,386-character XML at the
snapshot time. After LF normalization and one trailing newline, both had
SHA-256 `714b0cb33ba3da79bac136a32a6007a1768c86e4631b1b52620a1b60dbafac68`.
The raw recorded XML file hash remains the authoritative
`6f69ec39707ffbe2fc2e79d712748250eb00133fb5948ce0fd9b8a0d673b2f28`.

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
   $controlRepo = 'C:\code\backups\AR-local-recovery-control'
   if (-not (Test-Path -LiteralPath (Join-Path $controlRepo '.git'))) {
     git clone --no-checkout https://github.com/yanniedog/AR-local.git $controlRepo
   }
   git -C $controlRepo fetch origin main --prune
   git -C $controlRepo log -1 --format=%H `
     origin/main -- docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md
   ```

   Expected document-containing commit:
   `14dd066099bba393cccf61a280243e43162eedc9`. Recompute the canonical
   SHA-256 using the algorithm in the runbook and require
   `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713`.

3. At approximately 00:25, create the laptop evidence directory and perform
   the read-only Pi preflight. The command prints `lock=ABSENT` or
   `lock=PRESENT` explicitly and returns failure for a present lock; absence
   must never be inferred from silent `test` output:

   ```powershell
   $evidenceRun = [datetimeoffset]::Now.ToString('yyyyMMddTHHmmsszzz').Replace(':','')
   $evidenceRoot = Join-Path `
     'C:\code\backups\AR-local-pi5\evidence\NATURAL-20260828' $evidenceRun
   New-Item -ItemType Directory -Path $evidenceRoot -ErrorAction Stop | Out-Null
   $preflight = ssh -o BatchMode=yes ar-local-pi5-lan `
     "set -eu; date --iso-8601=seconds; git -C /srv/ar-local/AR-local rev-parse HEAD; git -C /srv/ar-local/AR-local status --porcelain=v1; systemctl is-enabled ar-local-daily.timer; systemctl is-active ar-local-daily.timer; systemctl show ar-local-daily.timer -p NextElapseUSecRealtime -p LastTriggerUSec -p Result; systemctl show ar-local-daily.service -p ActiveState -p SubState -p InvocationID -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p ExecMainStatus -p Result; if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi; df -h /srv/ar-local/data; free -h; curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest; curl -fsS --max-time 15 -o /dev/null -w 'github_http=%{http_code}\n' https://api.github.com/"
   if ($LASTEXITCODE -ne 0) { throw "Pi preflight failed: ssh exit $LASTEXITCODE" }
   $preflight | Tee-Object -FilePath (Join-Path $evidenceRoot '0025-preflight.txt')
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

At approximately 00:58, repeat the complete safety gate immediately before the
timer fires. This is mandatory even when the 00:25 gate passed:

```powershell
$immediate = ssh -o BatchMode=yes ar-local-pi5-lan `
  "set -eu; date --iso-8601=seconds; git -C /srv/ar-local/AR-local rev-parse HEAD; git -C /srv/ar-local/AR-local status --porcelain=v1; systemctl is-enabled ar-local-daily.timer; systemctl is-active ar-local-daily.timer; systemctl show ar-local-daily.timer -p NextElapseUSecRealtime -p LastTriggerUSec -p Result; systemctl show ar-local-daily.service -p ActiveState -p SubState -p InvocationID -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p ExecMainStatus -p Result; if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi; df -h /srv/ar-local/data; free -h; curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest; curl -fsS --max-time 15 -o /dev/null -w 'github_http=%{http_code}\n' https://api.github.com/"
if ($LASTEXITCODE -ne 0) { throw "Immediate Pi gate failed: ssh exit $LASTEXITCODE" }
$immediate | Tee-Object -FilePath (Join-Path $evidenceRoot '0058-immediate-gate.txt')
```

Require the same protected SHA, clean checkout, timer, resources, connectivity,
inactive service, explicit `lock=ABSENT`, and dashboard health. A failure is a
`BLOCKED` pre-start condition to record and escalate under the controlled
runbook; it does not authorize a service start, timer edit, restart, or force.

Observe the natural timer start exactly once. Do not run `--force` and do not
manually start the service. Continue read-only observation until the service is
terminal, the lock is absent, and the dashboard returns.

Use the following exact read-only commands. Capture the start snapshot only
after `ActiveState=active`; do not write to the Pi. Each polling interval is at
most 30 seconds so the operator remains present:

```powershell
$startDeadline = [datetimeoffset]'2026-08-28T01:10:00+10:00'
do {
  $active = (ssh -o BatchMode=yes ar-local-pi5-lan `
    "systemctl show ar-local-daily.service -p ActiveState --value").Trim()
  if ([datetimeoffset]::Now -gt $startDeadline) {
    throw 'Natural service did not become active by 01:10 AEST.'
  }
  if ($active -ne 'active') { Start-Sleep -Seconds 10 }
} until ($active -eq 'active')

$start = ssh -o BatchMode=yes ar-local-pi5-lan `
  "date --iso-8601=seconds; systemctl show ar-local-daily.service -p ActiveState -p SubState -p InvocationID -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p ExecMainStatus -p Result -p NRestarts; systemctl show ar-local-daily.timer -p LastTriggerUSec -p NextElapseUSecRealtime; if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; else echo lock=ABSENT; fi; pgrep -a -f '[p]i_daily_sync.py|[c]dr_daily.py' || true"
if ($LASTEXITCODE -ne 0) { throw "Start observation failed: ssh exit $LASTEXITCODE" }
$start | Tee-Object -FilePath (Join-Path $evidenceRoot '0100-start.txt')

do {
  Start-Sleep -Seconds 30
  $active = (ssh -o BatchMode=yes ar-local-pi5-lan `
    "systemctl show ar-local-daily.service -p ActiveState --value").Trim()
} while ($active -eq 'active' -or $active -eq 'activating')

$terminal = ssh -o BatchMode=yes ar-local-pi5-lan `
  "date --iso-8601=seconds; systemctl show ar-local-daily.service -p ActiveState -p SubState -p InvocationID -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p ExecMainStatus -p ExecMainCode -p Result -p NRestarts; systemctl show ar-local-daily.timer -p LastTriggerUSec -p NextElapseUSecRealtime; if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi; curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest"
if ($LASTEXITCODE -ne 0) { throw "Terminal observation failed: ssh exit $LASTEXITCODE" }
$terminal | Tee-Object -FilePath (Join-Path $evidenceRoot 'terminal-service.txt')

ssh -o BatchMode=yes ar-local-pi5-lan `
  "journalctl -u ar-local-daily.service --since '2026-08-28 00:55:00' --output=short-iso-precise --no-pager" `
  | Set-Content -LiteralPath (Join-Path $evidenceRoot 'service-journal.txt')
if ($LASTEXITCODE -ne 0) { throw "Journal capture failed: ssh exit $LASTEXITCODE" }
```

Require one new `InvocationID`, exactly one 01:00 `ExecMainStartTimestamp`, the
timer's `LastTriggerUSec` advancing exactly once from the 00:58 snapshot,
`NRestarts=0`, `Result=success`, `ExecMainStatus=0`, terminal inactive state,
and `lock=ABSENT`. Treat the journal as supporting evidence because persistent
journald is a known risk; the systemd identities and direct start observation
are the primary single-start evidence.

Validate the finalized local observation from the production checkout without
changing it. The ledger verifier re-hashes every contract artifact, including
the raw-attempt evidence. The second command verifies the marker/contract/event
binding, the source date, explicit attempt-evidence retention, provider
reconciliation, database hash/size, SQLite integrity and all table populations:

```powershell
ssh -o BatchMode=yes ar-local-pi5-lan `
  "cd /srv/ar-local/AR-local && python3 cdr_ledger_v2.py verify --state /srv/ar-local/data/state" `
  | Tee-Object -FilePath (Join-Path $evidenceRoot 'ledger-verify.json')
if ($LASTEXITCODE -ne 0) { throw "Ledger verification failed: ssh exit $LASTEXITCODE" }

@'
import hashlib, json, sqlite3
from pathlib import Path
from cdr_finalization import verify_completion_marker

def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

DATE = "2026-08-28"
DATA = Path("/srv/ar-local/data").resolve()
STATE = (DATA / "state").resolve()
pointer_path = STATE / "observation-pointers-v2/latest-observation.json"
pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
if pointer.get("observation_date") != DATE:
    raise SystemExit(f"latest observation is {pointer.get('observation_date')}, not {DATE}")
marker_path = (STATE / pointer["marker_path"]).resolve()
marker_path.relative_to(STATE)
marker = json.loads(marker_path.read_text(encoding="utf-8"))
if not verify_completion_marker(marker, STATE, DATE):
    raise SystemExit("completion/contract/ledger/artifact verification failed")
contract_path = (STATE / marker["export_contract_path"]).resolve()
contract_path.relative_to(STATE)
contract = json.loads(contract_path.read_text(encoding="utf-8"))
if pointer.get("generation_id") != marker.get("generation_id") or pointer.get("generation_id") != contract.get("generation_id"):
    raise SystemExit("generation binding mismatch")
if pointer.get("ledger_event_digest") != marker.get("ledger_event_digest"):
    raise SystemExit("pointer/marker ledger digest mismatch")
attempt = marker.get("attempt_evidence") or {}
if attempt.get("verified") is not True or int(attempt.get("attempts") or 0) <= 0:
    raise SystemExit("raw-attempt evidence is absent or unverified")
coverage = contract.get("coverage") or {}
registered = int(coverage.get("providers_registered") or 0)
attempted = int(coverage.get("providers_attempted") or 0)
complete = int(coverage.get("providers_complete") or 0)
partial = int(coverage.get("providers_partial") or 0)
failed = int(coverage.get("providers_failed") or 0)
if registered <= 0 or attempted != registered or complete + partial + failed != registered:
    raise SystemExit("provider accounting does not reconcile")
source = (DATA / contract["source_path"]).resolve()
source.relative_to(DATA)
db_artifacts = [a for a in contract["artifacts"] if a["path"].endswith(".sqlite")]
if len(db_artifacts) != 1:
    raise SystemExit(f"expected one contracted SQLite file, found {len(db_artifacts)}")
db_meta = db_artifacts[0]
db_path = (source / db_meta["path"]).resolve()
db_path.relative_to(source)
digest = sha256_file(db_path)
if db_path.stat().st_size != int(db_meta["bytes"]) or digest != db_meta["sha256"]:
    raise SystemExit("SQLite bytes differ from the export contract")
with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
    quick_check = con.execute("PRAGMA quick_check").fetchone()[0]
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    required = ["runs", "schema_meta", "bank_products", "bank_rates", "bank_items", "bank_product_facts", "bank_product_changes"]
    missing = sorted(set(required) - set(tables))
    if quick_check != "ok" or missing:
        raise SystemExit(f"SQLite invalid: quick_check={quick_check!r}, missing={missing}")
    populations = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in required}
if populations["bank_products"] <= 0 or populations["bank_rates"] <= 0 or populations["bank_items"] <= 0 or populations["bank_product_facts"] <= 0:
    raise SystemExit("daily database lacks credible product/rate/item/fact populations")
report = {
    "result": "PASS", "date": DATE, "pointer": pointer,
    "banks": marker.get("banks") or {},
    "marker_path": str(marker_path), "marker_sha256": hashlib.sha256(marker_path.read_bytes()).hexdigest(),
    "contract_path": str(contract_path), "contract_digest": contract["contract_digest"],
    "ledger_event_digest": marker["ledger_event_digest"], "attempt_evidence": attempt,
    "coverage": coverage, "provider_states": contract.get("provider_states", []),
    "quarantines": contract.get("quarantines", []), "sqlite_path": str(db_path),
    "sqlite_bytes": db_path.stat().st_size, "sqlite_sha256": digest,
    "quick_check": quick_check, "tables": tables, "populations": populations,
}
print(json.dumps(report, indent=2, sort_keys=True))
'@ | ssh -o BatchMode=yes ar-local-pi5-lan `
  "cd /srv/ar-local/AR-local && python3 -" `
  | Tee-Object -FilePath (Join-Path $evidenceRoot 'observation-verify.json')
if ($LASTEXITCODE -ne 0) { throw "Observation verification failed: ssh exit $LASTEXITCODE" }
```

Finally, download and hash the public dated v1, rolling v1, dates index, and the
independent v2 manifest. This creates laptop evidence only; it does not alter a
release. Every v1 asset named by each manifest is downloaded and checked before
the manifest is accepted:

```powershell
$ErrorActionPreference = 'Stop'
$date = '2026-08-28'
$publicRoot = Join-Path $evidenceRoot 'public-github'
New-Item -ItemType Directory -Path $publicRoot -ErrorAction Stop | Out-Null
$publicReport = [ordered]@{ date = $date; result = 'RUNNING'; manifests = @{} }
foreach ($tag in @("app-payload-$date", 'app-payload-latest')) {
  $tagRoot = Join-Path $publicRoot $tag
  New-Item -ItemType Directory -Path $tagRoot -ErrorAction Stop | Out-Null
  $manifestPath = Join-Path $tagRoot 'manifest.json'
  Invoke-WebRequest -UseBasicParsing -TimeoutSec 60 `
    -Uri "https://github.com/yanniedog/AR-local/releases/download/$tag/manifest.json" `
    -OutFile $manifestPath
  $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  if ($manifest.schema_version -ne 1 -or $manifest.run_date -ne $date -or $manifest.tag -ne $tag) {
    throw "$tag manifest identity mismatch"
  }
  $localObservation = Get-Content -LiteralPath (Join-Path $evidenceRoot 'observation-verify.json') -Raw | ConvertFrom-Json
  $localCountNames = @($localObservation.banks.PSObject.Properties.Name | Sort-Object)
  $publicCountNames = @($manifest.counts.PSObject.Properties.Name | Sort-Object)
  if (($localCountNames -join ',') -ne ($publicCountNames -join ',')) {
    throw "$tag manifest count fields differ from the finalized marker"
  }
  foreach ($countName in $localCountNames) {
    if ([int64]$manifest.counts.$countName -ne [int64]$localObservation.banks.$countName) {
      throw "$tag manifest count mismatch for $countName"
    }
  }
  $verifiedFiles = @()
  foreach ($property in $manifest.files.PSObject.Properties) {
    $asset = $property.Value
    $assetPath = Join-Path $tagRoot $asset.name
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 120 -Uri $asset.url -OutFile $assetPath
    $actualHash = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $actualBytes = (Get-Item -LiteralPath $assetPath).Length
    if ($actualHash -ne $asset.sha256 -or $actualBytes -ne [int64]$asset.bytes) {
      throw "$tag/$($asset.name) public-byte verification failed"
    }
    $env:AR_PUBLIC_ASSET = $assetPath
    python -c "import gzip,json,os; p=os.environ['AR_PUBLIC_ASSET']; v=json.load(gzip.open(p,'rt',encoding='utf-8')); assert isinstance(v,(dict,list)), p"
    if ($LASTEXITCODE -ne 0) { throw "$tag/$($asset.name) is not valid gzip JSON" }
    $verifiedFiles += [ordered]@{ role=$property.Name; name=$asset.name; bytes=$actualBytes; sha256=$actualHash }
  }
  $publicReport.manifests[$tag] = [ordered]@{
    run_date=$manifest.run_date; counts=$manifest.counts; files=$verifiedFiles
    manifest_sha256=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
  }
}
$indexPath = Join-Path $publicRoot 'dates-index.json'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 60 `
  -Uri 'https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/dates-index.json' `
  -OutFile $indexPath
$index = Get-Content -LiteralPath $indexPath -Raw | ConvertFrom-Json
if ($index.schema_version -ne 1 -or $index.latest_date -ne $date -or $index.dates -notcontains $date) {
  throw 'Public dates index does not independently select 2026-08-28'
}
$v2Path = Join-Path $publicRoot 'manifest-v2.json'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 60 `
  -Uri 'https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest-v2.json' `
  -OutFile $v2Path
$publicReport.dates_index = [ordered]@{
  latest_date=$index.latest_date; count=$index.count
  sha256=(Get-FileHash -LiteralPath $indexPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
$publicReport.v2 = [ordered]@{
  status='RECORDED_INDEPENDENTLY_NOT_A_V1_GATE'
  sha256=(Get-FileHash -LiteralPath $v2Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
$publicReport.result = 'PASS'
$publicReport | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $publicRoot 'verification.json')
Get-FileHash -LiteralPath (Join-Path $publicRoot 'verification.json') -Algorithm SHA256
```

Compare both public v1 manifests' counts with the validated local marker's
`banks` counts and record any discrepancy as `FAIL`; schema/date/hash success
alone is insufficient. The legacy v1 manifest has no generation or contract
digest field, so this stable-runtime limitation must be disclosed rather than
inventing an identity. Public v1 acceptance for this protected release is the
combination of exact current date, matching populations, and verified public
bytes. Record v2's own date/status separately; stale or failed v2 does not turn
v1 into either success or failure.

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
$receiver = 'C:\code\backups\AR-local-pi5-receiver-c87cdd0'
$receiverHead = (git -C $receiver rev-parse HEAD).Trim()
$receiverDirty = @(git -C $receiver status --porcelain=v1)
if ($LASTEXITCODE -ne 0 -or $receiverHead -ne 'c87cdd0077e209d1824bbe485c0f5ad30723d0c4' -or $receiverDirty.Count -ne 0) {
  throw 'Accepted A3 receiver is missing, dirty, or at the wrong commit.'
}
$liveXml = Export-ScheduledTask -TaskName 'AR-local laptop backup'
$recordedXmlPath = 'C:\code\backups\AR-local-pi5\catalog\task-definitions\installed-c87cdd0-20260827T112050Z.xml'
$recordedXml = Get-Content -LiteralPath $recordedXmlPath -Raw
if ($liveXml -cne $recordedXml) {
  throw 'Installed task definition differs from the accepted A3 XML.'
}
$recordedXmlSha = (Get-FileHash -LiteralPath $recordedXmlPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($recordedXmlSha -ne '6f69ec39707ffbe2fc2e79d712748250eb00133fb5948ce0fd9b8a0d673b2f28') {
  throw 'Accepted A3 task XML hash mismatch.'
}
$task | Select-Object TaskName, State, Principal, Triggers, Actions, Settings
$info | Select-Object LastRunTime, LastTaskResult, NextRunTime
$latestPointerPath = 'C:\code\backups\AR-local-pi5\catalog\latest-scheduled.json'
$latestPointer = Get-Content -LiteralPath $latestPointerPath -Raw | ConvertFrom-Json
$targetRoot = [IO.Path]::GetFullPath('C:\code\backups\AR-local-pi5')
$recordPathText = [string]$latestPointer.record_path
$recordPath = if ([IO.Path]::IsPathRooted($recordPathText)) {
  [IO.Path]::GetFullPath($recordPathText)
} else {
  [IO.Path]::GetFullPath((Join-Path $targetRoot $recordPathText))
}
if (-not $recordPath.StartsWith($targetRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
  throw 'Scheduled-run record escapes the backup target.'
}
if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) {
  throw 'Scheduled-run record named by latest-scheduled.json is missing.'
}
$actualRecordSha = (Get-FileHash -LiteralPath $recordPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualRecordSha -ne ([string]$latestPointer.record_sha256).ToLowerInvariant()) {
  throw 'Scheduled-run pointer hash does not match its execution record.'
}
$executionRecord = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
if ($executionRecord.result -ne 'PASS' -or $executionRecord.action -notin @('BACKUP-LATEST','NO_BACKUP_DATA_WRITE')) {
  throw "Natural scheduled backup did not produce an accepted PASS action: $($executionRecord.action)"
}
if ($executionRecord.candidate_code_sha -ne 'c87cdd0077e209d1824bbe485c0f5ad30723d0c4' -or
    $executionRecord.protected_code_sha -ne '9302890fcc752cbf90da97d597e972c157d913e3' -or
    $executionRecord.plan_document_id -ne 'ARL-OPS-001' -or
    $executionRecord.plan_version -ne '1.3' -or
    $executionRecord.plan_git_commit -ne '8efefe10890a295ef87f97b46d3cb981193cfddc' -or
    $executionRecord.plan_sha256 -ne '8834990f8c3cfbe86d4006b0d4fca3c564c760362a0928bf2a688f6dacd83a3d' -or
    $executionRecord.operator -ne 'jkoka' -or
    $executionRecord.deviations.Count -ne 0 -or
    $null -ne $executionRecord.deviation_authorization) {
  throw 'Natural scheduled execution record has an identity or deviation mismatch.'
}
$latestPointer | ConvertTo-Json -Depth 10
$executionRecord | ConvertTo-Json -Depth 20
```

Exact XML equality is mandatory and covers the action path and arguments,
receiver/candidate/protected/plan identities, principal and logon mode, both
triggers, startup delay, `IgnoreNew`, three `PT30M` retries, and the `PT6H`
execution limit. Also require the receiver checkout to remain clean at
`c87cdd0077e209d1824bbe485c0f5ad30723d0c4`. Task state and exit zero alone are
not acceptance. Require the newly resolved execution record itself—not only its
pointer—to show the expected action, `PASS`, exact candidate/protected/plan
identities, operator, source identities, backup/restore detail, timestamps and
no unauthorized deviation. Preserve both its absolute path and verified hash.

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
git -C C:\code\backups\AR-local-runbook-multiday log -1 --format=%H `
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
