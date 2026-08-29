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

---

## Entry `HANDOFF-20260828T052104+1000`

### Control record

| Field | Value |
|---|---|
| Previous handoff entry | `HANDOFF-20260827T220351+1000` |
| Created, Australia/Hobart | `2026-08-28T05:21:04+10:00` |
| Created, UTC | `2026-08-27T19:21:04Z` |
| Operator | `Codex for jkoka` |
| Result | `BLOCKED` |
| Current phase | `A3 — terminal evidence complete; acceptance blocked pending controlled decision` |
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
| Previous handoff-containing commit | `012cae64988c7637ea90b88aee1490d78c943de0` |
| Previous handoff raw Git-blob SHA-256 | `e5dcd67f2611750b55467fa3735025ddc579ba64d22bed31c0c6273c730b9eae` |
| Deviations | Mandatory natural-ingest preflight evidence at 00:25 and 00:58 was missed |
| Deviation authorization | None; the missing evidence is not waived |

This entry terminally supersedes the `RUNNING` status of the previous entry. It
does not change the controlled runbook, relabel the completed v1.3 proof, or
authorise A4. The natural data capture, finalization, public v1 publication,
and 05:00 laptop backup all passed. A3 nevertheless remains `BLOCKED` because
the two mandatory pre-run evidence points were not observed and cannot be
reconstructed after the fact.

### Terminal gate matrix

| Gate | Result | Evidence-backed meaning |
|---|---|---|
| Runbook v1.4 identity | `PASS` | Commit and canonical controlled checksum verified; raw Git-blob SHA-256 verified |
| Previous handoff identity | `PASS` | Commit `012cae649...` contains the expected raw Git-blob bytes |
| 00:25 natural-ingest preflight | `BLOCKED` | No contemporaneous evidence exists; the hourly heartbeat next ran at 01:01 |
| 00:58 final lock/resource preflight | `BLOCKED` | No contemporaneous evidence exists and post-run state cannot substitute for it |
| Natural 01:00 scheduled start | `PASS` | Exactly one start at 01:00; invocation `a30dfd78d17e412b8164425418b55d11`; zero restarts |
| Current-day CDR capture | `PASS` | `2026-08-28`, 3,839 retained attempts, all 119 registered providers attempted |
| Observation finalization | `PASS` | Marker, contract, ledger, pointer, SQLite and populations verified |
| Product/provider accounting | `PASS` | 112 complete, 7 partial, 0 failed providers; 17 attributable failures; corrupt/unattributed zero |
| Dashboard automatic return | `PASS` | Dashboard returned without restart or operator intervention |
| Dated v1 publication | `PASS` | Public manifest and every named public asset downloaded and hash-checked |
| Rolling v1 publication | `PASS` | Public manifest and every named public asset downloaded and hash-checked |
| Dates index | `PASS` | Public index independently selects `2026-08-28` |
| v2 | `FAIL` | Independently stale at `2026-08-21`; this does not invalidate v1 |
| Natural 05:00 scheduled start | `PASS` | Task Scheduler start `2026-08-28T05:00:01+10:00`; never manually triggered |
| Task terminal state | `PASS` | `Ready`, `LastTaskResult=0`, next run `2026-08-29T05:00:00+10:00` |
| Task XML and receiver identity | `PASS` | Exact accepted XML and clean exact receiver commit verified |
| Selective backup action | `PASS` | `BACKFILL` copied only genuinely missing date `2026-08-28`; post-state has no missing dates |
| Observation restore proof | `PASS` | Archive bytes/hash, full extraction, metadata, marker/pointer, populations and SQLite verified |
| Control restore proof | `PASS` | Archive, files, Git bundles, secret locations and retained SQLite verified |
| Macro restore proof | `PASS` | Archive, file inventory and macro SQLite verified |
| Catalog append-only chain | `PASS` | Existing 322-entry prefix retained; only sequences 323–325 appended; full 325-entry chain verified |
| Post-task hygiene | `PASS` | No lock, partials, helpers, overlap, or relevant local/Pi process remains |
| Laptop capacity floor | `PASS` | `159,253,090,304` bytes free in terminal correction evidence, above `53,687,091,200` |
| A3 acceptance | `BLOCKED` | Successful runtime evidence cannot conversationally waive the missing mandatory preflights |
| A4 and Phases B–G | `NOT_STARTED` | Prohibited pending a controlled decision and a new authorising handoff entry |

### Natural `2026-08-28` observation

| Field | Verified value |
|---|---|
| Generation | `obs-2026-08-28-3c534348347d3f4e` |
| Observation state | `partial` |
| SQLite bytes | `1,108,135,936` |
| SQLite SHA-256 | `6db087a83874e6cce6516a9f34d2deba048f4010d5afef57f715baf5bd84c684` |
| SQLite quick check | `ok` |
| Export-contract digest | `ce7f51d3d7622a5b0b5cfac52172feee1ea6d6e5e5c674f493828e47aa298f38` |
| Ledger digest | `7a9d1b4b0a23be781fbcef02ba2863da49dd2f44c60941e210a16aa1af6d673e` |
| Raw attempts | `3,839` |
| Providers | `119 registered / 119 attempted / 112 complete / 7 partial / 0 failed` |
| Failure integrity | `17 failures / 0 corrupt / 0 unattributed` |
| Products | `3,012` |
| Rates | `17,052` |
| Fees | `29,882` |
| Features | `18,449` |
| Eligibility records | `8,514` |
| Constraints | `5,088` |
| Product facts | `661,741` |
| Natural service terminal | `2026-08-28T01:18:47+10:00`, result `success`, exit `0` |
| Validation completed | `2026-08-28T01:25:00.3824810+10:00` |
| Next ingest timer | `2026-08-29T01:00:00+10:00` |

The partial state is not a whole-observation failure. All providers were
attempted, no provider failed completely, and the 17 failures remain
attributable while unrelated valid products were retained and published. This
matches D-003's product-day principle. The legacy protected runtime cannot add
the future per-product quality contract; this entry records only what the
current marker, contract, ledger, database, and public v1 bytes prove.

### Independent public payload evidence

| Component | Public SHA-256 | Result |
|---|---|---|
| Dated v1 manifest, `app-payload-2026-08-28` | `2a542c0b14d037f00c65e8307a4b627bea14b12060416afb12ec79c62dfba2b9` | `PASS` |
| Rolling v1 manifest, `app-payload-latest` | `f2b9f5e915bd5d34597abce0c2680ee32ddafce1fd2732e3baa6ea78fe7cbac7` | `PASS` |
| Dates index | `ec15504011cebb7817887fea28bc53f926eac66b89ba1aa65be9abec7a24bc01` | `PASS` |
| v2 manifest | `02e14f71b604dbfd652fef7c1a3c46932ad9b32beef7cc90e99ddc14a1ca4acb` | `FAIL` — stale `2026-08-21`, recorded independently |

Every v1 asset named by the dated and rolling manifests was downloaded from
public GitHub, checked for exact byte count and SHA-256, decompressed, parsed as
JSON, and reconciled to the protected runtime's finalized populations. The
dates index was separately downloaded and checked. No publication was modified
by this verification.

### Natural 05:00 backup and restore proof

The scheduled execution record is:

`C:\code\backups\AR-local-pi5\catalog\scheduled-runs\20260827T191348Z-d1c09a9cc980481a86eb07a1e8237310.json`

- bytes: `2,439`;
- SHA-256: `c202ff010679ce0a08344103875adf98d8d600f92f28a679553f415ef97a2035`;
- action: `BACKFILL`;
- result: `PASS`;
- completed: `2026-08-27T19:13:48Z`;
- exact candidate, protected SHA, v1.3 plan identity, operator, command, and
  empty deviation fields: verified.

The previous entry forecast `BACKUP-LATEST`, but the receiver's preflight found
exactly one missing completed date, `2026-08-28`. Its designed inventory route
therefore selected `BACKFILL`. This is accepted for the backup component only:

- before: missing completed dates exactly `["2026-08-28"]`;
- after: missing completed dates `[]`, stale diagnostics `[]`, status
  `UP_TO_DATE`;
- no historical observation was recopied or rewritten;
- the verified catalog prefix through sequence 322 was unchanged;
- sequence 323 is the new observation, 324 the current control pack, and 325
  the current macro pack; and
- the full chain through 325 verifies.

The action is consistent with the operator's explicit requirement that
selective backfill transfer only genuinely missing dates and with D-005. It is
not an authorisation to reinterpret the missing natural-ingest preflights.

#### Observation receipt, catalog sequence 323

`C:\code\backups\AR-local-pi5\observations\2026-08-28\81c03779a4d203b3fdbea660c9cd897888ac1f6cce0e729e8989899fa8894f61\receipt.json`

- receipt bytes `3,394`, SHA-256
  `066554a67e41f2463a9db306edcfc17bd306973974e1e9b465f126f44752ec757b35`;
- source manifest SHA-256
  `81c03779a4d203b3fdbea660c9cd897888ac1f6cce0e729e8989899fa8894f61`;
- archive bytes `240,169,360`, archive SHA-256
  `db98067e11835b06fdba5d80d29c5c5f145ec35b9c3a0670050e2bd341d1d286`;
- restored bytes `2,776,556,753` across `10,995` files;
- completion marker and latest pointer valid for the same generation;
- SQLite quick check `ok`; and
- restored dashboard/database populations reconcile.

#### Control receipt, catalog sequence 324

`C:\code\backups\AR-local-pi5\control\20260827T191250Z-6f4ef5220f31b0e8\receipt.json`

- receipt bytes `2,482`, SHA-256
  `19a35eae9132228db306edcfc17bd306973974e1e9b465f126f44752ec757b35`;
- source manifest SHA-256
  `6f4ef5220f31b0e8b960d3ef77890b674efba67ce52764556b8ce0f4ee912d7f`;
- archive bytes `80,242,711`, archive SHA-256
  `a514ce2b436c850d87b97f22ef1d48694c91cd20c0a1b512327640d1a14d662e`;
- restored bytes `223,740,481` across `321` files;
- both repository Git bundles verified; and
- secret locations were inventoried without copying secret values into Git.

#### Macro receipt, catalog sequence 325

`C:\code\backups\AR-local-pi5\macro\77358d47b44012db2c2ddd4bbf3bb95b9e3d969c96491ebb7b8c6d3358cf0278\receipt.json`

- receipt bytes `2,223`, SHA-256
  `8ec4675f7cb0040e3be5530eac7b245afa71f3dfcb37abe4e3da3eed29b2512e`;
- source manifest SHA-256
  `77358d47b44012db2c2ddd4bbf3bb95b9e3d969c96491ebb7b8c6d3358cf0278`;
- archive bytes `166,665`, archive SHA-256
  `5fd7e59e2f58a315e06bb7f570cd36dbc44a5706a434bae5a6cab5b6d4365a9e`;
- restored bytes `995,328`, one file; and
- macro SQLite quick check `ok` with `ingest_runs` and
  `series_observations` present.

### Immutable execution evidence

| Evidence | Bytes | SHA-256 |
|---|---:|---|
| `C:\code\backups\AR-local-pi5\evidence\NATURAL-20260828\20260828T010247+1000\natural-result.json` | 8,443 | `c38b2ffc2ecc6269fccc55630976a78822d3cb31569ccbac16092fa7ceff3b1f` |
| `C:\code\backups\AR-local-pi5\evidence\A3-20260828-0500\20260828T050102+1000\a3-terminal-result.json` | 12,777 | `ba5da62c07f196fd1686a90f27f31d7bb14bef29e49652d6df21250c7cea8fde` |
| `C:\code\backups\AR-local-pi5\evidence\A3-20260828-0500\20260828T050102+1000\terminal-task-and-record.json` | 4,391 | `02bf8b6c1460829b3320dd31364f0817ece8023cc1aef795e3fa5dfe755cbe8c` |
| `C:\code\backups\AR-local-pi5\evidence\A3-20260828-0500\20260828T050102+1000\catalog-chain-verify.json` | 829 | `536858ddc6831d51d5139e2acb0ba2962022e7285c363a01e6f4486735032fbe` |
| `C:\code\backups\AR-local-pi5\evidence\A3-20260828-0500\20260828T050102+1000\post-task-preflight.json` | 11,802 | `d56c23b82ac4f2927851cefa9a6a0857bd8f6fd9bbb2f3d19773f6f1e97cb2ab` |
| `C:\code\backups\AR-local-pi5\evidence\A3-20260828-0500\20260828T050102+1000\hygiene-verify-correction.json` | 1,137 | `6490c35d8f67f49137c84fd44bdfc2a2354759eeba2b02a30cfb414151e213c8` |
| `C:\code\backups\AR-local-pi5\evidence\A3-20260828-0500\20260828T050102+1000\0500-start-snapshot.json` | 4,906 | `bce9da953256f977ff00a6562ad2a16c891cf8e207cbfc3c9d498dbfc0540240` |

The original `hygiene-verify.json` is retained unchanged even though it reported
a failure. Its remote `pgrep` matched the observer's own command text because
the helper path string appeared in that command. The append-only correction
above uses a non-self-matching process expression and separately checks helper
paths. It reports no receiver lock, no partials, no local or Pi relevant
process, and no Pi helper path. This is an evidence-query correction, not a
production or policy deviation.

### Exact commands and mutation boundary

The immutable JSON records contain the exact executable command and command
families. The scheduled task's exact command was:

```text
"C:\Users\jkoka\.pyenv\pyenv-win\versions\3.10.9\python.exe" "C:\code\backups\AR-local-pi5-receiver-c87cdd0\laptop_backup_scheduled.py" "--target" "C:\code\backups\AR-local-pi5" "--recovery-image" "C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21" "--candidate-code-sha" "c87cdd0077e209d1824bbe485c0f5ad30723d0c4" "--protected-code-sha" "9302890fcc752cbf90da97d597e972c157d913e3" "--plan-git-commit" "8efefe10890a295ef87f97b46d3cb981193cfddc" "--operator" "jkoka"
```

Read-only validation used `Get-ScheduledTask`, `Get-ScheduledTaskInfo`,
`Export-ScheduledTask`, `Get-FileHash`, `Get-PSDrive`, receiver `git rev-parse`
and `git status`, the receiver's read-only preflight and catalog-chain parser,
explicit lock/partial/process/helper checks, Pi `systemctl`/Git/dashboard checks,
the protected producer's contract/finalization/ledger validators, SQLite
`PRAGMA quick_check`, and public HTTP downloads with independent SHA-256 and
gzip-JSON validation.

No command in this execution deployed code, changed the Pi checkout, restarted
a service, forced or reran ingestion, manually started the scheduled task, or
manipulated GitHub publication. The only backup-data mutation was the natural
scheduled receiver action described above. The documentation change that adds
this entry is isolated in a fresh worktree based on `origin/main`.

### Blocker, risk, and preservation action

The missing 00:25 and 00:58 evidence is a procedural blocker, not evidence of a
failed ingest. The automation was hourly and next activated at 01:01, after the
natural service had begun. The run itself was not interrupted or altered. A
post-run snapshot cannot prove every exact pre-run condition at those required
times, so neither the successful observation nor the successful backup is
allowed to silently convert the overall A3 result to `PASS`.

Until a controlled decision is appended:

- keep production clean at protected SHA
  `9302890fcc752cbf90da97d597e972c157d913e3`;
- preserve the current daily 01:00 timer and D-006 freeze/validation cadence;
- preserve every raw attempt, completed observation, receipt, catalog entry,
  public v1 byte, and diagnostic record;
- leave the completed v1.3 scheduled task installed and unchanged;
- do not deploy, run PR #508, start A4, or advance Phases B–G;
- do not use `--force` or rerun a prior day's ingest; and
- keep at least 50 GiB free on the laptop.

The hourly heartbeat cadence is not sufficient to prove future 00:25 and 00:58
gates. Before relying on another daily cycle for acceptance, schedule or
otherwise arrange exact preflight-capable activations before those times. A
mere hourly retry is not an accepted compensating control.

### Exact next action and acceptance boundary

The next operator must obtain and append one controlled decision choosing one
of these paths:

1. accept the complete post-run ingest evidence plus complete natural 05:00
   backup/restore proof as sufficient to close A3 despite the missed preflight
   timestamps, with an explicit authorised deviation containing reason, risk,
   compensating controls, and revised acceptance criteria; or
2. keep A3 blocked and observe another full natural daily cycle with both
   required preflights, terminal ingest validation, and the natural 05:00
   backup proof.

The safe default is option 2 until explicit authorisation exists. If option 2
is selected, the monitor must be capable of acting before 00:25 and 00:58; it
must not manually trigger ingestion or backup, and it must preserve that day's
current-only CDR window. A successful later cycle requires a new append-only
entry. Only that entry may mark A3 `PASS` and authorise planning—not execution—
of A4 as a separate daylight slice.

No further technical action is required from the completed 2026-08-28 05:00
backup proof itself. Its task is `Ready`, its next natural trigger is
`2026-08-29T05:00:00+10:00`, and its verified free-space measurement remains
well above the controlled floor.

---

## Entry `HANDOFF-20260828T052556+1000-CORRECTION`

### Correction control record

| Field | Value |
|---|---|
| Previous handoff entry | `HANDOFF-20260828T052104+1000` |
| Previous handoff-containing commit | `3ed39126d159b77b03744887c9c12b8a37dd40e3` |
| Previous handoff raw Git-blob SHA-256 | `f15bac9ac1a3035cff387824dd1fc4f1be055f30f49a48d35c96c7826134750b` |
| Created, Australia/Hobart | `2026-08-28T05:25:56+10:00` |
| Created, UTC | `2026-08-27T19:25:56Z` |
| Operator | `Codex for jkoka` |
| Result | `BLOCKED` |
| Current phase | `A3 — terminal evidence complete; acceptance blocked pending controlled decision` |
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
| Correction reason | Post-merge review of PR #537 identified an invalid runbook-level state label and omitted repository path/cleanliness fields |
| Risk | A later operator could misclassify the accepted observation or rely on a stale repository snapshot |
| Compensating control | Preserve the prior entry unchanged; append this correction with the normative state and independently captured repository evidence |
| Revised acceptance criteria | Interpret the observation as runbook state `degraded`, require both named repositories to be revalidated live before any future action, and retain A3 as `BLOCKED` |
| Authorization | Mandatory correction of substantive review findings under the append-only handoff rules; no gate waiver or phase advancement |

This entry corrects two fields of interpretation and completeness in the
previous entry. It does not alter any source observation, immutable execution
evidence, backup receipt, protected Pi state, A3 result, or prohibition.

### Observation-state correction

The previous entry recorded the protected producer's raw state value
`partial`. That raw value remains evidence of what the pinned runtime emitted,
but it is not the normative ARL-OPS-001 v1.4 observation state.

ARL-OPS-001 v1.4 defines observation `state=complete` only when every registered
provider is complete or proven empty, population uncertainty is zero, every
discovered product is fully published, and issue total is zero. Every other
accepted observation is `degraded`. Because this observation has seven partial
providers and 17 attributable issues, its normative state is:

| Field | Correct value |
|---|---|
| Protected producer raw value | `partial` |
| ARL-OPS-001 v1.4 observation state | `degraded` |
| Provider-level partial count | `7` |
| Acceptance | Accepted v1 product-day with attributable gaps; A3 procedure remains `BLOCKED` independently |

Every later operator must use `degraded` only for the runbook-level label.
Machine-readable export contracts, completion markers, ledger events, backup
receipts, and validator inputs must retain the pinned runtime's schema-valid
`partial` value until their schemas and implementations are changed. Never
rewrite an existing artifact merely to normalize its vocabulary. This
correction implements the first substantive Sourcery finding on PR #537
without rewriting completed evidence.

### Authoritative repository paths and cleanliness

The following read-only state was captured at
`2026-08-28T05:25:56.2308940+10:00`:

| Repository | Host | Authoritative path | HEAD | Cleanliness |
|---|---|---|---|---|
| Pi production | `ar-local-pi5-lan` | `/srv/ar-local/AR-local` | `9302890fcc752cbf90da97d597e972c157d913e3` | `PASS` — `git status --porcelain=v1` empty |
| Laptop receiver | Windows laptop | `C:\code\backups\AR-local-pi5-receiver-c87cdd0` | `c87cdd0077e209d1824bbe485c0f5ad30723d0c4` | `PASS` — `git status --porcelain=v1` empty |

At that snapshot, the Pi daily service was inactive, the timer was enabled,
`/srv/ar-local/data/state/daily-ingest.lock` was absent, and
`http://127.0.0.1:8808/api/latest` was healthy for `2026-08-28`. These are
point-in-time facts only. The next operator must re-run the live checks before
acting and must stop on any mismatch.

The immutable correction evidence is:

`C:\code\backups\AR-local-pi5\evidence\HANDOFF-CORRECTION-20260828\20260828T052556+1000\repository-state.json`

- bytes: `2,214`;
- SHA-256:
  `bbc71f264adb1d2bcff6bde3af830892168210ab9c20a39efc7582c40c311542`;
- result: `PASS`;
- deviations: none.

It records the exact read-only command families, both repository paths, HEADs,
empty status results, Pi service/timer/lock/dashboard state, and the raw versus
normative observation-state distinction. No secret values are present.

### Disposition and next action

Both late PR #537 findings are `Implemented` by this append-only correction:

1. the normative observation state is now unambiguously `degraded`, while the
   source producer's raw `partial` value remains preserved; and
2. the production and candidate repository paths, exact commits, and current
   cleanliness results are now explicit and hash-bound to source evidence.

The terminal result remains `BLOCKED`. The exact next action and acceptance
boundary is reproduced below so this last chronological entry is independently
actionable. A4, deployment, PR #508, and Phases B–G remain prohibited.

### Complete resume procedure

#### Decision and timing

The next action is a controlled documentation decision, not a Pi action. The
operator must choose and append exactly one of these outcomes:

1. authorise a formal deviation accepting the complete post-run ingest evidence
   and natural 05:00 backup/restore proof as sufficient to close A3; or
2. require another fully observed natural daily cycle.

The safe default is option 2. No conversational statement, automation prompt,
or chat summary is deviation authorization. Option 1 must append the reason,
risk, compensating controls, revised acceptance criteria, named authorizer,
and timestamp before A3 can become `PASS`.

For option 2, use the first daily cycle for which exact monitoring can be
guaranteed. Earliest preflight is `00:25:00` Australia/Hobart on that calendar
day. The second preflight is `00:58:00`. Production's quiet window begins at
`00:30:00` and lasts through terminal ingest validation. All development,
deployment, canary, manual ingest, service restart, package change, and
publication manipulation must stop by `00:30:00`. Read-only observation may
continue. If either preflight is missed, that cycle cannot close A3; record it
without interrupting the natural ingest.

#### Exact preflight commands

Run these from a clean plan-control checkout of current `origin/main`. Replace
`YYYY-MM-DD` only with the current Australia/Hobart source date; do not use a
prior or next date:

```powershell
$ErrorActionPreference = 'Stop'
$expectedPi = '9302890fcc752cbf90da97d597e972c157d913e3'
$expectedReceiver = 'c87cdd0077e209d1824bbe485c0f5ad30723d0c4'
$receiver = 'C:\code\backups\AR-local-pi5-receiver-c87cdd0'

git fetch origin --prune
git log -1 --format=%H origin/main -- docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md
git show origin/main:docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md
git show origin/main:docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md
git -C $receiver rev-parse HEAD
git -C $receiver status --porcelain=v1

ssh -o BatchMode=yes -o ConnectTimeout=10 ar-local-pi5-lan `
  "git -C /srv/ar-local/AR-local rev-parse HEAD; git -C /srv/ar-local/AR-local status --porcelain=v1; systemctl is-enabled ar-local-daily.timer; systemctl is-active ar-local-daily.timer; systemctl is-active ar-local-daily.service; test ! -e /srv/ar-local/data/state/daily-ingest.lock; df -B1 /srv/ar-local/data; free -b; curl -fsS http://127.0.0.1:8808/api/latest; git ls-remote https://github.com/yanniedog/AR-local.git HEAD"
```

At both preflights, independently require:

- runbook document commit
  `14dd066099bba393cccf61a280243e43162eedc9` and controlled SHA-256
  `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713`;
- the latest chronological handoff entry and its Git-blob SHA verified from the
  then-current merged `origin/main`;
- Pi production path `/srv/ar-local/AR-local`, clean at `$expectedPi`;
- receiver path `$receiver`, clean at `$expectedReceiver`;
- timer enabled and active for the natural 01:00 schedule;
- daily service inactive and ingest lock absent before start;
- no competing ingest process;
- adequate Pi disk, memory, and swap without OOM evidence;
- healthy dashboard and GitHub connectivity; and
- the previous observation, pending-publication state, and backup target
  unambiguous.

Write every command, timestamp, stdout/stderr, exit status, resolved path, and
SHA-256 to a new unique evidence directory. Never overwrite evidence from a
prior cycle.

#### Natural ingest observation and validation

Never start, force, restart, or rerun the ingest. Observe the scheduled unit
from before 01:00 until terminal completion:

```powershell
ssh -o BatchMode=yes ar-local-pi5-lan `
  "systemctl show ar-local-daily.service -p ActiveState -p SubState -p Result -p ExecMainStatus -p InvocationID -p NRestarts -p ExecMainStartTimestamp -p ExecMainExitTimestamp; systemctl list-timers ar-local-daily.timer --all; test ! -e /srv/ar-local/data/state/daily-ingest.lock; curl -fsS http://127.0.0.1:8808/api/latest"

ssh -o BatchMode=yes ar-local-pi5-lan `
  "cd /srv/ar-local/AR-local && python3 cdr_ledger_v2.py verify --state /srv/ar-local/data/state"
```

Then run the ledger's protected Python observation validator for the current
date, changing only its `DATE` constant. Require one scheduled invocation, zero
competing ingests, terminal service success, absent lock, automatic dashboard
return, raw attempts present and verified, marker/contract/ledger/pointer bound
to one generation, SQLite `PRAGMA quick_check=ok`, expected tables, credible
nonzero populations, and exact provider accounting. Preserve product/provider
gaps; do not discard valid unrelated products. Classify the runbook-level state
as `complete` or `degraded`, while retaining the protected runtime's
machine-readable `complete`, `partial`, or `failed` value unchanged.

Download the current dated v1 manifest and assets, rolling v1 manifest and
assets, and dates index from public GitHub. Verify every byte count, SHA-256,
gzip/JSON schema, source date, and population independently. Record v2
separately. A stale or failed v2 neither passes nor fails v1.

#### Natural 05:00 backup validation

Do not trigger the task. After the ingest has terminally validated and the
dashboard has returned, wait for the natural 05:00 task. Use:

```powershell
$task = Get-ScheduledTask -TaskName 'AR-local laptop backup'
$info = Get-ScheduledTaskInfo -TaskName 'AR-local laptop backup'
$liveXml = Export-ScheduledTask -TaskName 'AR-local laptop backup'
$recordedXmlPath = 'C:\code\backups\AR-local-pi5\catalog\task-definitions\installed-c87cdd0-20260827T112050Z.xml'
$recordedXml = Get-Content -LiteralPath $recordedXmlPath -Raw
if ($liveXml -cne $recordedXml) { throw 'Installed task XML changed.' }
Get-FileHash -Algorithm SHA256 -LiteralPath $recordedXmlPath
git -C 'C:\code\backups\AR-local-pi5-receiver-c87cdd0' rev-parse HEAD
git -C 'C:\code\backups\AR-local-pi5-receiver-c87cdd0' status --porcelain=v1
Get-PSDrive -Name C
```

Safely resolve `catalog/latest-scheduled.json` beneath
`C:\code\backups\AR-local-pi5`, verify its named record hash, and parse that
immutable execution record. Require task state `Ready`, `LastTaskResult=0`,
exact task XML, clean exact receiver, exact v1.3 plan/candidate/protected/operator
identities, truthful `PASS`, current observation/control/macro/diagnostic
identities, complete catalog chain, restore verification, SQLite checks, no
lock/partial/helper/overlap, and at least `53,687,091,200` free bytes.
`BACKFILL` is acceptable only when the pre-state identifies exact genuinely
missing dates and the post-state proves no unrelated history changed.

#### Acceptance, stop conditions, and preservation

Mark the later cycle `PASS` only when both timed preflights, the complete natural
ingest validation, public v1 verification, dashboard return, and natural 05:00
backup/restore proof pass with immutable evidence. Append a new handoff entry
containing its exact paths and hashes. That entry may close A3 and may authorise
planning of A4; it must not execute A4 or deploy.

Stop and record `BLOCKED` or `FAIL` if any identity, cleanliness, timer, lock,
process, resource, dashboard, network, database, contract, ledger, pointer,
raw-attempt, provider-accounting, publication, task XML, receiver, catalog,
receipt, restore, hygiene, or capacity check fails or is uncertain. Also stop
if the monitoring activation misses either preflight or threatens the current
source window.

On stop, preserve all raw and diagnostic evidence, retain the day's immutable
observation if it completed, keep the Pi at the protected SHA, keep the previous
verified rolling payload if publication is not valid, leave the installed task
unchanged, and do not use `--force`, rerun another date, deploy, or start A4.
There is no rollback action because this resume procedure permits no production
mutation. If an unauthorised mutation is detected, stop without attempting an
ad-hoc reversal and follow the controlled rollback procedure in ARL-OPS-001.

---

## Entry `HANDOFF-20260828T063742+1000-A3-DECISION`

### Control record

| Field | Value |
|---|---|
| Previous handoff entry | `HANDOFF-20260828T052556+1000-CORRECTION` |
| Previous handoff-containing commit | `efce38d7db074217791acc9408b8e8d1c1719705` |
| Previous handoff raw Git-blob SHA-256 | `0412984f22202ca4f8af3d7439bd879e82ed25cb4774f3be934f0849f6586ef6` |
| Created, Australia/Hobart | `2026-08-28T06:37:42+10:00` |
| Created, UTC | `2026-08-27T20:37:42Z` |
| Operator | `Codex for jkoka` |
| Result | `PASS` |
| Current phase | `A3 accepted; next bounded slice is the non-production backup-tooling plan-identity update` |
| Controlling plan document | `ARL-OPS-001` |
| Controlling plan version | `1.4` |
| Controlling plan Git commit | `14dd066099bba393cccf61a280243e43162eedc9` |
| Controlling plan SHA-256 | `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Controlling plan raw Git-blob SHA-256 | `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4` |
| Completed A3 plan version | `1.3` |
| Completed A3 plan Git commit | `8efefe10890a295ef87f97b46d3cb981193cfddc` |
| Completed A3 plan SHA-256 | `8834990f8c3cfbe86d4006b0d4fca3c564c760362a0928bf2a688f6dacd83a3d` |
| Completed receiver candidate SHA | `c87cdd0077e209d1824bbe485c0f5ad30723d0c4` |
| Protected Pi code SHA | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Decision ID | `DEC-A3-001` |
| Decision | Accept A3 from its complete backup/restore evidence; retain the missed natural-ingest preflights as an independent procedural blocker for `NATURAL-20260828` |
| Authorization | Direct operator instruction on 2026-08-28 rejecting the wait-only interpretation and directing continuation of the runbook and plan |

### Reason and scope correction

The preceding handoff incorrectly coupled two independent results:

1. the `NATURAL-20260828` execution missed its mandatory 00:25 and 00:58
   contemporaneous preflight evidence and therefore remains procedurally
   `BLOCKED`; and
2. A3's backup crash-recovery and scheduled backup/restore acceptance evidence
   passed completely.

ARL-OPS-001 v1.4 defines A3 as backup crash recovery: partial/orphan handling,
retention reserve enforcement, lock coordination, a successful manual backup
and restore before timer enablement, then safe scheduled operation under the A2
resource and time controls. The A3 evidence proves those requirements. The
runbook's daily-cycle section separately requires each natural ingest to carry
its own capture, finalization, publication, dashboard, and backup outcomes.
One result must not silently redefine the other.

The operator rejected the interpretation that the missed natural preflight
timestamps require all daylight development to idle until another daily cycle.
This entry implements that instruction without rewriting either completed
execution. It does not declare `NATURAL-20260828` procedurally complete and does
not weaken future timed preflights.

### Formal deviation decision

| Required field | Decision record |
|---|---|
| Reason | The previous handoff treated an independent natural-ingest evidence defect as if it invalidated the fully proven A3 backup subsystem and prohibited the runbook's explicit daylight bounded-slice cadence. |
| Risk | Separating the results could be misread as excusing missed daily preflights or allowing an unsafe deployment. |
| Compensating controls | Preserve the natural execution as `BLOCKED`; retain every immutable artifact; keep exact 00:25/00:58 monitoring active; keep production pinned and clean; permit only an isolated non-production plan-identity update; keep A4 execution and all deployment prohibited. |
| Revised A3 acceptance criteria | Require the accepted manual backup/restore gate, exact installed task/receiver identities, natural scheduled task result zero, selective transfer limited to genuinely missing dates, observation/control/macro restore proofs, full catalog chain, hygiene, and capacity floor. These all passed. Natural-ingest preflight completeness is recorded independently and is not an A3 backup acceptance criterion. |
| Authorization | AR-local operator instruction: the wait-only conclusion was “not right”, followed by “Proceed with runbook and plan”, on 2026-08-28. |
| Effective result | A3 `PASS`; `NATURAL-20260828` remains procedurally `BLOCKED`; no production deployment or A4 execution is authorised. |

### Evidence supporting A3 acceptance

| Component | Result | Authoritative evidence |
|---|---|---|
| Manual backup and full restore prerequisite | `PASS` | Prior A3 installation and manual proof retained under the v1.3 identity |
| Natural 05:00 Task Scheduler execution | `PASS` | Start `2026-08-28T05:00:01+10:00`, task returned `Ready`, result `0` |
| Exact task and receiver identity | `PASS` | Task XML SHA-256 `6f69ec39707ffbe2fc2e79d712748250eb00133fb5948ce0fd9b8a0d673b2f28`; clean receiver `c87cdd0077...` |
| Selective observation transfer | `PASS` | Only genuinely missing date `2026-08-28` transferred; no missing dates afterward |
| Observation restore | `PASS` | Catalog sequence 323; receipt SHA-256 `066554a67e41f2463a9db306edcfc17bd306973974e1e9b465f126f44752ec757b35` |
| Control restore | `PASS` | Catalog sequence 324; receipt SHA-256 `19a35eae9132228db306edcfc17bd306973974e1e9b465f126f44752ec757b35` |
| Macro restore | `PASS` | Catalog sequence 325; receipt SHA-256 `8ec4675f7cb0040e3be5530eac7b245afa71f3dfcb37abe4e3da3eed29b2512e` |
| Catalog chain | `PASS` | Complete append-only chain through sequence 325 |
| Post-task hygiene | `PASS` | No lock, partial, helper, overlap, or relevant residual process |
| Capacity | `PASS` | More than 159 GB free at acceptance checks; controlled floor is 53,687,091,200 bytes |

The terminal A3 record remains:

`C:\code\backups\AR-local-pi5\evidence\A3-20260828-0500\20260828T050102+1000\a3-terminal-result.json`

- bytes: `12,777`;
- SHA-256:
  `ba5da62c07f196fd1686a90f27f31d7bb14bef29e49652d6df21250c7cea8fde`.

Its overall `BLOCKED` value is preserved as the result produced before this
scope decision. This entry is the append-only authorised decision that changes
the phase-level interpretation; it does not edit that file.

The latest read-only no-drift audit is:

`C:\code\backups\AR-local-pi5\evidence\DRIFT-AUDIT-20260828\20260828T063323+1000\drift-audit.json`

- bytes: `4,835`;
- SHA-256:
  `962cc0ce8171db0f1a1c05bcc6a78663748db759e2e13f39e59347f85d725913`;
- result: `PASS`.

It reconfirmed the protected clean Pi, enabled/active next 01:00 timer, absent
lock, healthy current dashboard, exact clean receiver and task XML, 325-entry
catalog, no lock or partials, capacity floor, and unchanged public v1 bytes.

### Phase state after this decision

| Gate or slice | State | Authority |
|---|---|---|
| A3 backup crash recovery | `PASS` | This append-only decision plus immutable A3 evidence |
| `NATURAL-20260828` procedure | `BLOCKED` | Missed 00:25 and 00:58 evidence remains recorded |
| Daily natural ingest continuity | `RUNNING` | Timed 00:25/00:58 monitor remains mandatory every day |
| Backup-tooling v1.4 plan-identity update | `NOT_STARTED` | Authorised as the next isolated non-production slice |
| A4 planning | `NOT_STARTED` | May begin only after the plan-identity update passes and its handoff is appended |
| A4 physical execution | `NOT_STARTED` | Not authorised by this entry |
| Pi deployment or runtime change | `NOT_STARTED` | Prohibited |
| Phases B–G | `NOT_STARTED` | Not authorised |

### Next bounded daylight slice

Create a fresh worktree from the exact post-decision `origin/main`. Update the
backup receiver's embedded plan identity and tests from the completed v1.3
identity to the controlling v1.4 identity. This is a code-and-test compatibility
slice only; it must not reinstall the accepted v1.3 Windows task, alter backup
catalog data, connect a writable operation to the Pi, start A4, or deploy.

Before editing, identify every embedded plan version, Git commit, controlled
digest, normalized/raw digest expectation, fixture, installer default, and
scheduled-wrapper assertion. Do not mechanically replace unrelated historical
evidence or the immutable v1.3 task proof.

The candidate must:

- derive from exact current `origin/main` after this documentation PR merges;
- use ARL-OPS-001 v1.4 commit
  `14dd066099bba393cccf61a280243e43162eedc9` and controlled digest
  `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713`;
- validate the v1.4 raw and normalized document identities without relabelling
  any completed v1.3 execution;
- retain protected Pi SHA `9302890...` only as an explicit input, never a
  hidden default for future production;
- pass focused backup, scheduler, restore, plan-identity, and regression tests;
- pass exact-head CI and substantive review closure; and
- be proven only from an isolated non-production checkout.

### Timing, commands, and acceptance boundary

Earliest start is immediately after this decision PR merges. The latest safe
stop is `2026-08-28T23:30:00+10:00`; stop earlier if CI, review, or proof cannot
finish cleanly. No work from this slice may continue into the 00:30 freeze.

Initial read-only discovery commands are:

```powershell
git fetch origin --prune
git worktree add -b codex/a3-plan-identity-v14 <fresh-path> origin/main
rg -n "1\.3|8efefe10890a295ef87f97b46d3cb981193cfddc|8834990f8c3cfbe86d4006b0d4fca3c564c760362a0928bf2a688f6dacd83a3d|PLAN_SHA256|plan_git_commit|plan_version" laptop_pull_backup.py laptop_backup_scheduled.py install tests
```

Verification must be discovered from the exact changed paths and CI, and must
include at minimum:

```powershell
python -m pytest tests/test_laptop_pull_backup.py -q
python -m pytest tests/test_pi_backup_foundation.py -q
git diff --check
```

Acceptance requires one focused PR, exact post-decision base, clean worktree,
all targeted tests passing, required CI green, every substantive review finding
disposed and resolved, and no Pi/Task Scheduler/backup-catalog/public-payload
mutation. Append a new handoff entry after the PR reaches a terminal result.

Stop on any unexpected plan identity, historical-evidence rewrite, test failure,
dirty base, merge conflict, receiver incompatibility, Pi contact capable of
writing, task alteration, backup-data mutation, or risk of crossing the daily
freeze. Rollback is to leave or close the unmerged topic branch; production and
the installed v1.3 task remain unchanged. A merged candidate is not authorised
for installation until a later entry explicitly permits it.

---

## Entry `HANDOFF-20260828T070253+1000-A3-PLAN-V14`

### Control record

| Field | Value |
|---|---|
| Previous handoff entry | `HANDOFF-20260828T063742+1000-A3-DECISION` |
| Previous handoff-containing commit | `e000d22c03077b364441a903673912160ca041a4` |
| Previous handoff raw Git-blob SHA-256 | `83dae48c1bf207fde508febeb00e751daef5605e2c5aa2076b95df6c535606a4` |
| Created, Australia/Hobart | `2026-08-28T07:02:53+10:00` |
| Created, UTC | `2026-08-27T21:02:53Z` |
| Operator | `Codex for jkoka` |
| Result | `PASS` |
| Current phase | `A3 complete; v1.4 backup-tooling identity update complete; v1.4 scheduled-task transition is the next bounded slice` |
| Controlling plan document | `ARL-OPS-001` |
| Controlling plan version | `1.4` |
| Controlling plan Git commit | `14dd066099bba393cccf61a280243e43162eedc9` |
| Controlling plan SHA-256 | `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Controlling plan raw Git-blob SHA-256 | `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4` |
| Completed code candidate | `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Protected Pi code SHA | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Completed A3 plan document | `ARL-OPS-001` |
| Completed A3 plan version | `1.3` |
| Completed A3 plan Git commit | `8efefe10890a295ef87f97b46d3cb981193cfddc` |
| Completed A3 plan SHA-256 | `8834990f8c3cfbe86d4006b0d4fca3c564c760362a0928bf2a688f6dacd83a3d` |
| Completed A3 plan raw file SHA-256 | `6c90c3dadce6906ff98e01af4ab038b9a5d91a7325662d526d5bcce018f7a444` |
| Installed receiver SHA | `c87cdd0077e209d1824bbe485c0f5ad30723d0c4` — intentionally unchanged |
| Decision ID | `DEC-A3-002` |
| Decision | Accept the v1.4 plan-identity code slice after post-merge exact-head, exact-tree, review-closure, and no-mutation controls; preserve the premature-merge incident in immutable evidence |
| Authorization | Direct operator instruction to proceed with the controlled runbook and plan; advancement remains bounded by this entry |

### Authoritative repositories and cleanliness

| Purpose | Path and state |
|---|---|
| Pi production | `/srv/ar-local/AR-local`; clean at protected `9302890fcc752cbf90da97d597e972c157d913e3` |
| Merged v1.4 verification checkout | `C:\code\backups\AR-local-a3-plan-v14-merged-f214e32`; clean detached checkout at `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Installed A3 receiver | `C:\code\backups\AR-local-pi5-receiver-c87cdd0`; clean at `c87cdd0077e209d1824bbe485c0f5ad30723d0c4` |
| Laptop backup root | `C:\code\backups\AR-local-pi5`; immutable catalog remains at sequence 325 |
| Historical recovery-image candidate | `C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21`; retained unchanged; not an accepted boot proof |
| This documentation worktree | `C:\code\backups\AR-local-a3-plan-v14-handoff`; branch `codex/docs-a3-plan-v14-result-20260828`, created from exact `f214e324...` |
| User checkout — prohibited for controlled work | `C:\code\AR-local`; at `a0bd0f54200c91ef7aaa2fb163e752005ddb71e8`, modified `.cursor/skills/pi-deploy-agent/SKILL.md`, untracked `.codex/`; do not clean or use |

### Completed slice

PR #540, `Advance laptop backup tooling to runbook v1.4`, was created from
exact base `e000d22c03077b364441a903673912160ca041a4`. Its PR head was
`156e5af45757ff5baf2ac23aa2c69bd072599410`; it squash-merged as
`f214e3249c7968d574e3449edb14792904e1cc1f`. The PR head and merge commit
have the identical tree SHA `3330c4483ee7b6188b230161281a32f0b743291e`.

The merged implementation:

- embeds exact ARL-OPS-001 v1.4 plan commit, controlled checksum, normalized
  Git-blob checksum, and accepted LF/CRLF raw checksums;
- rejects an incorrect plan commit before target creation, execution-record
  creation, or remote contact;
- permits immutable historical receipts only under the exact completed v1.3
  document/version/commit/controlled/raw identity tuple;
- keeps every new manifest, receipt, and scheduled record on v1.4;
- reuses exact v1.3 historical coverage without relabelling it or initiating a
  redundant complete backfill; and
- records raw and normalized plan hashes in scheduled execution evidence.

PR #540 was code availability only and did not itself change the installed
Windows task, which remains at receiver `c87cdd0...` and plan v1.3 at the time
of this entry. The later review-correction section of this same entry separately
authorises the bounded v1.4 laptop-task transition. Neither the merge nor that
transition authorises changing Pi production.

### Immutable execution evidence

The create-once execution record is:

`C:\code\backups\AR-local-pi5\evidence\A3-PLAN-V14-20260828\20260828T070051+1000\a3-plan-v14-result.json`

- bytes: `8,618`;
- SHA-256:
  `1e3be821c54c6fa0fae88546981c66c055c2094844e799a2f0386dbeb7227e08`;
- original execution result: `BLOCKED` pending this append-only decision.

That file is not edited by this decision. Its technical checks and the merge
incident remain preserved exactly as recorded.

### Verification and review evidence

| Gate | Result | Evidence |
|---|---|---|
| Focused backup/scheduler/restore/plan tests on PR tree | `PASS` | `120 passed, 1 skipped` |
| Full server-side test suite on PR tree | `PASS` | `1008 passed, 11 skipped, 4 warnings` |
| GitHub app-ci on exact PR head | `PASS` | Run `33115723102`, head `156e5af...` |
| PR/merge tree identity | `PASS` | Both tree SHAs `3330c448...` |
| Fresh exact merged-candidate checkout | `PASS` | Clean detached `f214e324...`; focused suite `120 passed, 1 skipped` |
| Existing receipt compatibility | `PASS` | All `326` stored receipts accepted under the exact allowlist; zero rejected; read-only scan |
| Historical evidence preservation | `PASS` | No receipt or catalog file rewritten; catalog remains 325 entries |
| Review closure | `PASS` | Sourcery finding declined with code-path evidence, replied to, and resolved |
| Post-resolution feedback gate | `PASS` | Run `33115934002` |
| Gemini advisory review | `UNAVAILABLE` | Workflow returned `503 UNAVAILABLE`; no finding was produced and it is not a required gate |
| Diff integrity | `PASS` | `git diff --check` |

Sourcery asserted that the copied helper would reject v1.4 against the Pi's
v1.3 `/etc/ar-local/backup.env`. The finding was declined because the laptop
receiver installs `pi_laptop_backup_source.py` at a unique temporary path and
passes its plan tuple directly. That helper does not import
`ar_local_backup_policy.py` or read `/etc/ar-local/backup.env`; its preflight
checks the quiet window, protected production SHA and cleanliness, ingest
service/lock/timer, and dashboard. The v1.3 environment example belongs to the
separate Pi-mounted-storage backup foundation, which this slice neither deploys
nor invokes.

### Formal deviation decision `DEV-A3-PLAN-V14-001`

| Required field | Decision record |
|---|---|
| Event | PR #540 merged immediately instead of merely arming auto-merge. |
| Reason | The documented `pr:arm-and-park` npm script is absent. The allowed fallback wrapper then failed because the user's existing checkout owns `main`. Direct `gh pr merge --auto --squash` interpreted the request as immediate merge because the sole enforced check had already passed. |
| Risk | Merge occurred 21 seconds before non-required app-ci completed and before Sourcery posted its finding, violating the intended gate order. |
| Compensating controls | No production/runtime/task/catalog/payload mutation; exact PR-head app-ci later passed; PR and merge trees are identical; a fresh exact merged checkout passed focused tests; the late finding was substantively evaluated and resolved; the post-resolution feedback gate passed; post-slice drift checks passed. |
| Revised acceptance criteria | Require exact-head app-ci PASS, byte-identical PR/merge trees, exact merged-candidate focused tests PASS, complete finding disposition and thread closure, post-resolution feedback gate PASS, and read-only proof that Pi, task, catalog, and public v1 remained unchanged. |
| Revised acceptance result | `PASS` — every compensating criterion is satisfied. |
| Authorization | This append-only decision is made within the operator-authorized code slice. `DEC-A3-002` alone does not broaden authority to installation, deployment, A4 execution, or later phases; the separately stated review correction below controls the next task-transition slice. |
| Preservation | The original `BLOCKED` evidence record remains immutable. This entry changes only the controlled phase interpretation. |

### Post-slice no-drift state

Read-only checks after PR #540 confirmed:

- Pi production remains clean at
  `9302890fcc752cbf90da97d597e972c157d913e3`;
- `ar-local-daily.service` is inactive; `ar-local-daily.timer` is enabled and
  active for `2026-08-29T01:00:00+10:00`;
- the ingest lock is absent and no ingest process competes;
- the dashboard is HTTP-healthy on run date `2026-08-28`;
- the installed task remains `Ready`, last result `0`, and next run
  `2026-08-29T05:00:00+10:00`;
- live task XML still equals the accepted file with SHA-256
  `6f69ec39707ffbe2fc2e79d712748250eb00133fb5948ce0fd9b8a0d673b2f28`;
- the accepted receiver remains clean at `c87cdd0077...`;
- no receiver lock or partial exists and free space is `159,177,940,992`
  bytes, above the `53,687,091,200`-byte floor;
- the catalog remains valid through sequence 325 with file SHA-256
  `0f3517c61ae5c9fb13a2ecc634895b8c0ee935d3d005e4b6d7cf68086e4d5704`;
- the latest scheduled record remains the v1.3 `BACKFILL` `PASS` record with
  SHA-256 `c202ff010679ce0a08344103875adf98d8d600f92f28a679553f415ef97a2035`;
  and
- dated v1 manifest `2a542c0b...`, rolling v1 manifest `f2b9f5e9...`, and
  dates index `ec155040...` remain unchanged from the pre-slice audit.

### Phase state after this decision

| Gate or slice | State | Authority |
|---|---|---|
| A3 backup crash recovery | `PASS` | `DEC-A3-001` and immutable A3 evidence |
| Backup-tooling v1.4 plan identity | `PASS` | PR #540, immutable execution evidence, and `DEC-A3-002` |
| Installed daily laptop task | `TRANSITION REQUIRED` | The accepted v1.3 task must not execute again after terminal A3; replace it with exact v1.4 only after the gate below passes |
| `NATURAL-20260828` procedure | `BLOCKED` | Missed timed preflight evidence remains independent and unchanged |
| Daily natural ingest continuity | `RUNNING` | Exact 00:25/00:58 observation remains mandatory every day |
| v1.4 scheduled-task transition | `NOT_STARTED`, now authorised | Must complete or fail closed before the next 00:30 freeze |
| A4 planning | `BLOCKED` | Do not begin until the v1.4 task transition and its first natural 05:00 execution are terminally accepted |
| A4 tooling implementation | `NOT_STARTED` | Not authorised |
| A4 physical execution | `NOT_STARTED` | Prohibited; requires explicit later entry, spare-media identity, and operator-present controls |
| Pi deployment or runtime change | `NOT_STARTED` | Prohibited |
| Phases B through G | `NOT_STARTED` | Not authorised |

### Latest observation and independent continuity states

The latest accepted observation remains `2026-08-28`, generation
`obs-2026-08-28-3c534348347d3f4e`. Its observation state is `partial`, with
3,839 raw attempts; 119 registered and attempted providers; 112 complete,
seven partial, and zero failed providers; 17 attributable failures; zero
corrupt or unattributed failures; and SQLite `PRAGMA quick_check=ok`.

| Independent outcome | State | Evidence or interpretation |
|---|---|---|
| Timed natural-ingest procedure | `BLOCKED` | Mandatory 00:25 and 00:58 evidence was missed; this remains unwaived |
| CDR source capture | `PASS` | Raw attempts retained; immutable natural record `c38b2ffc...` |
| Observation finalization | `PASS` | Marker, contract, ledger, pointer, database and provider accounting validated |
| Dated v1 publication | `PASS` | Manifest SHA-256 `2a542c0b14d037f00c65e8307a4b627bea14b12060416afb12ec79c62dfba2b9` and named assets publicly verified |
| Rolling v1 publication | `PASS` | Manifest SHA-256 `f2b9f5e915bd5d34597abce0c2680ee32ddafce1fd2732e3baa6ea78fe7cbac7` and seven named assets publicly verified |
| Dates index | `PASS` | SHA-256 `ec15504011cebb7817887fea28bc53f926eac66b89ba1aa65be9abec7a24bc01`; latest date `2026-08-28` |
| v2 | `FAIL`, independent | Public v2 remains stale at `2026-08-21`; it neither passes nor invalidates v1 |
| Dashboard return | `PASS` | HTTP healthy and serving `2026-08-28` |
| Laptop observation/control/macro backup | `PASS` | Natural 05:00 selective backfill, restore checks, catalog sequence 325 |
| Next natural ingest | `RUNNING` continuity obligation | `2026-08-29` at 01:00; exact 00:25/00:58 observation remains mandatory |
| Next natural laptop backup | `BLOCKED_PENDING_TRANSITION` | The active v1.3 definition must be replaced by exact v1.4 before it may execute at `2026-08-29T05:00:00+10:00` |

### Review correction: the v1.4 task transition precedes A4

Late exact-head review correctly identified that the accepted v1.3 task cannot
remain enabled for a new execution after terminal A3. ARL-OPS-001 v1.4 says that
the installed v1.3 task and receiver remain authoritative only through their
first natural 05:00 proof after the 2026-08-28 ingest; after that terminal A3
execution, every new execution uses v1.4. Keeping the v1.3 task enabled for
`2026-08-29T05:00:00+10:00` would create evidence under the wrong controlled
identity. This entry therefore replaces the earlier A4-planning next step.

### Next bounded daylight slice: transition the scheduled task to v1.4

This is a laptop-only control-plane slice. It may read the Pi through the
existing pull-only SSH path and may append verified immutable generations to
the existing laptop backup catalog. It must not change the Pi checkout, data,
services, timer, lock, ingest, dashboard, or publication. It must not start A4.

The exact new receiver candidate is the already merged and verified commit
`f214e3249c7968d574e3449edb14792904e1cc1f`. The receiver is bound to:

- document `ARL-OPS-001`;
- version `1.4`;
- plan commit `14dd066099bba393cccf61a280243e43162eedc9`;
- controlled SHA-256
  `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713`;
- normalized Git-blob SHA-256
  `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4`;
  and
- protected Pi SHA `9302890fcc752cbf90da97d597e972c157d913e3`.

The transition has two ordered write gates. First, run one foreground v1.4
scheduled-wrapper execution. Because the current catalog identity is v1.3, the
normal expected action is `BACKUP-LATEST` with `PASS`; it creates current v1.4
observation, control, and macro generations while retaining every historical
v1.3 receipt unchanged. It must not initiate a full historical backfill. Second,
only after that pass, run the installer. The installer performs a v1.4
`--check-only` gate, registers the replacement task disabled, verifies its exact
definition, enables it, and verifies the enabled definition. Activation or
read-back failure must leave the task disabled.

#### Time and collision boundary

- Earliest start: after this documentation PR is merged and its exact commit and
  handoff raw Git-blob hash are recorded.
- Latest start: only when enough daylight remains to finish or safely disable
  the old task by `2026-08-28T23:30:00+10:00`.
- Mandatory stop: `2026-08-28T23:30:00+10:00`.
- Freeze: `2026-08-29T00:30:00+10:00` through terminal validation of the natural
  `2026-08-29` ingest.
- No backup transition command may run during the freeze, while
  `ar-local-daily.service` is active, while the production ingest lock exists,
  or while another receiver/helper process is active.
- The production 01:00 timer is never disabled, delayed, restarted, or modified.

#### Gate 1 — create and verify the exact clean receiver

Run in a normal PowerShell session. Replace only `<HANDOFF-MERGE-SHA>` and
`<HANDOFF-RAW-SHA256>` with the immutable values recorded after this PR merges.

```powershell
$ErrorActionPreference = 'Stop'
$controlRepo = 'C:\code\backups\AR-local-a3-plan-v14-handoff'
$candidate = 'f214e3249c7968d574e3449edb14792904e1cc1f'
$protected = '9302890fcc752cbf90da97d597e972c157d913e3'
$planCommit = '14dd066099bba393cccf61a280243e43162eedc9'
$receiver = 'C:\code\backups\AR-local-pi5-receiver-f214e32'
$expectedHandoffCommit = '<HANDOFF-MERGE-SHA>'
$expectedHandoffHash = '<HANDOFF-RAW-SHA256>'

git -C $controlRepo fetch origin --prune
if ((git -C $controlRepo rev-parse origin/main).Trim() -ne $expectedHandoffCommit) {
  throw 'origin/main does not equal the authorised handoff merge.'
}
if (Test-Path -LiteralPath $receiver) { throw "Receiver path already exists: $receiver" }
git -C $controlRepo worktree add --detach $receiver $candidate
if ((git -C $receiver rev-parse HEAD).Trim() -ne $candidate) { throw 'Receiver SHA mismatch.' }
if (@(git -C $receiver status --porcelain=v1).Count -ne 0) { throw 'Receiver is dirty.' }

Set-Location $receiver
Get-Content docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md -Raw
Get-Content docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md -Raw
python -c "import hashlib,subprocess; b=subprocess.run(['git','-C',r'$controlRepo','show','origin/main:docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'],capture_output=True,check=True).stdout; h=hashlib.sha256(b).hexdigest(); print(h); assert h=='$expectedHandoffHash'"
python -c "import laptop_pull_backup as r; p=r.verify_plan_document(); assert p['plan_document_id']=='ARL-OPS-001'; assert p['plan_version']=='1.4'; assert p['plan_git_commit']=='14dd066099bba393cccf61a280243e43162eedc9'; assert p['plan_sha256']=='78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713'; print(p)"
```

Abort before any backup write if any identity, checkout, or checksum differs.
Do not delete or repair an unexpected receiver path; record the collision.

#### Gate 2 — read-only Pi and laptop preflight

Run outside the freeze. These commands must show the protected clean Pi,
inactive ingest, absent lock, active/enabled timer, healthy dashboard, no
competing backup process, valid laptop target, and at least 50 GiB free.

```powershell
$target = 'C:\code\backups\AR-local-pi5'
$image = 'C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21'
$floor = 53687091200
$now = [DateTimeOffset]::Now
if ($now -ge [DateTimeOffset]'2026-08-28T23:30:00+10:00') { throw 'Safe transition window has closed.' }
if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw 'Backup target is absent.' }
if (-not (Test-Path -LiteralPath $image -PathType Leaf)) { throw 'Recovery image is absent.' }
$free = (Get-Volume -DriveLetter C).SizeRemaining
if ($free -lt $floor) { throw "Laptop free space is below 50 GiB: $free" }
if (Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
  $_.CommandLine -like "*$receiver*" -and $_.ProcessId -ne $PID
}) {
  throw 'A receiver process is already active.'
}
if (Test-Path -LiteralPath "$target\catalog\.receiver.lock") { throw 'Receiver lock exists.' }
if (Get-ChildItem -LiteralPath $target -Recurse -Force -Filter '*.partial' -ErrorAction Stop) {
  throw 'Partial backup artifacts exist.'
}

$pi = @'
set -eu
test "$(git -C /srv/ar-local/AR-local rev-parse HEAD)" = "9302890fcc752cbf90da97d597e972c157d913e3"
test -z "$(git -C /srv/ar-local/AR-local status --porcelain=v1)"
test "$(systemctl is-active ar-local-daily.service || true)" = "inactive"
test "$(systemctl is-active ar-local-daily.timer)" = "active"
test "$(systemctl is-enabled ar-local-daily.timer)" = "enabled"
test ! -e /srv/ar-local/data/state/daily-ingest.lock
! pgrep -af '[c]dr_daily.py|[p]i_daily_sync.py'
curl --fail --silent --show-error http://127.0.0.1:8808/api/latest
systemctl show ar-local-daily.timer -p NextElapseUSecRealtime
df -B1 /srv/ar-local/data
free -b
'@
ssh ar-local-pi5 $pi
if ($LASTEXITCODE -ne 0) { throw 'Pi preflight failed.' }
```

Any preflight uncertainty is `BLOCKED`. Do not use `--force`, restart a service,
remove a lock, repair a partial, or modify the Pi to make the gate pass.

#### Gate 3 — foreground v1.4 backup and verification

Run the scheduled wrapper without `--check-only`. Capture its full stdout and
stderr in the new immutable transition evidence directory. The command may
append only genuinely current v1.4 generations and catalog entries.

```powershell
$python = (Get-Command python -ErrorAction Stop).Source
$operator = 'jkoka'
$evidence = Join-Path $target ('evidence\A3-V14-TASK-TRANSITION-20260828\' + (Get-Date -Format 'yyyyMMddTHHmmssK').Replace(':',''))
New-Item -ItemType Directory -Path $evidence -ErrorAction Stop | Out-Null
$stdout = Join-Path $evidence 'manual-v14-backup.stdout.txt'
$stderr = Join-Path $evidence 'manual-v14-backup.stderr.txt'
$arguments = @(
  (Join-Path $receiver 'laptop_backup_scheduled.py'),
  '--target', $target,
  '--recovery-image', $image,
  '--candidate-code-sha', $candidate,
  '--protected-code-sha', $protected,
  '--plan-git-commit', $planCommit,
  '--operator', $operator
)
& $python @arguments 1> $stdout 2> $stderr
if ($LASTEXITCODE -ne 0) { throw "Foreground v1.4 backup failed; evidence: $evidence" }
$result = Get-Content -LiteralPath $stdout -Raw
$result
if ($result -notmatch '"result":\s*"PASS"') { throw 'Foreground result is not PASS.' }
if ($result -notmatch '"status":\s*"UP_TO_DATE"') { throw 'Post-backup state is not UP_TO_DATE.' }
if ($result -notmatch '"backfill_required":\s*false') { throw 'Unexpected historical backfill requirement.' }
```

`BACKUP-LATEST` is the normal expected action. `NO_BACKUP_DATA_WRITE` is not
accepted merely because the wrapper exits zero: it requires independent proof
that the latest run/observation, control, macro, diagnostics, history, and plan
identity were already v1.4 and unchanged. `BACKFILL` is `BLOCKED` for this
transition because the 326 historical receipts already passed the exact legacy
allowlist scan; investigate rather than recopying history.

Before installation, verify and record all of the following:

- the latest scheduled execution record is create-once and has result `PASS`;
- its plan, candidate, protected SHA, operator, action, before/after identities,
  and evidence path are exact;
- every new receipt records v1.4 without altering historical v1.3 receipts;
- all 326 pre-transition receipts still parse under the exact legacy allowlist;
- completed-date inventory has no missing dates and no stale diagnostics;
- the catalog prefix is byte-identical and the appended hash chain validates;
- observation, control, and macro source identities equal the live Pi listing;
- every required restore verification reports `PASS`;
- no receiver lock, `.partial`, helper, or overlapping process remains; and
- laptop free space remains at least `53,687,091,200` bytes.

Hash the stdout, stderr, new execution record, new receipts, catalog, and a
create-once transition-result JSON. The transition result includes the plan
identity, candidate and protected SHAs, operator, timestamps, exact commands,
pre/post catalog sequence and hashes, source identities, evidence paths and
hashes, deviations, and terminal `PASS`, `FAIL`, or `BLOCKED`. Never edit it
after creation.

#### Gate 4 — install and verify the v1.4 scheduled task

This gate requires a new elevated Windows PowerShell session under
`yanniedog\jkoka`. Do not use another account and do not run it until Gate 3 is
`PASS`. The installer performs its own `--check-only` proof before registration.

```powershell
$ErrorActionPreference = 'Stop'
whoami
# Must print: yanniedog\jkoka
([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
# Must print: True

$receiver = 'C:\code\backups\AR-local-pi5-receiver-f214e32'
$target = 'C:\code\backups\AR-local-pi5'
$image = 'C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21'
$candidate = 'f214e3249c7968d574e3449edb14792904e1cc1f'
$protected = '9302890fcc752cbf90da97d597e972c157d913e3'
$planCommit = '14dd066099bba393cccf61a280243e43162eedc9'

if ((git -C $receiver rev-parse HEAD).Trim() -ne $candidate) { throw 'Receiver SHA mismatch.' }
if (@(git -C $receiver status --porcelain=v1).Count -ne 0) { throw 'Receiver is dirty.' }
& "$receiver\install_laptop_backup_task.ps1" `
  -Target $target `
  -RecoveryImage $image `
  -CandidateCodeSha $candidate `
  -ProtectedCodeSha $protected `
  -PlanGitCommit $planCommit `
  -Operator 'jkoka'
if ($LASTEXITCODE -ne 0) { throw 'v1.4 task installation failed.' }

$task = Get-ScheduledTask -TaskName 'AR-local laptop backup' -ErrorAction Stop
$info = Get-ScheduledTaskInfo -TaskName 'AR-local laptop backup' -ErrorAction Stop
$xml = Export-ScheduledTask -TaskName 'AR-local laptop backup' -ErrorAction Stop
$task | Format-List TaskName,State
$info | Format-List LastRunTime,LastTaskResult,NextRunTime,NumberOfMissedRuns
$xml
```

Acceptance requires exact read-back of one action rooted in receiver
`f214e32`, candidate `f214e324...`, plan commit `14dd066...`, protected SHA
`9302890...`, operator `jkoka`, principal `yanniedog\jkoka`, `S4U`, `Limited`,
enabled state, one 05:00 daily trigger, one startup trigger delayed `PT5M`,
`IgnoreNew`, three retries at `PT30M`, `PT6H` execution limit, and
start-when-available. Save the live XML in immutable evidence and record its
SHA-256. The task must be `Ready` after installation. Do not manually trigger
it.

The retained v1.3 receiver, its accepted XML, execution records, receipts, and
A3 proof remain immutable historical evidence. They are not relabelled,
deleted, overwritten, or used for another execution.

#### Stop conditions and rollback

Stop immediately and preserve evidence if:

- plan, handoff, candidate, protected SHA, repository cleanliness, or path
  identity differs;
- the Pi service is active, ingest lock exists, timer is unhealthy, dashboard
  is unavailable, a backup/ingest helper overlaps, or the freeze is near;
- the wrapper requests a historical backfill, rewrites a historical receipt,
  breaks the catalog prefix/hash chain, fails restoration, or drops below the
  free-space floor;
- the check-only installer gate is not current; or
- task registration, disabled read-back, enablement, or enabled read-back fails.

Before Gate 4, rollback is to leave the accepted v1.3 task definition untouched
while preserving the failed v1.4 attempt. However, because D-006 prohibits any
new v1.3 execution after terminal A3, if Gate 4 cannot reach exact enabled v1.4
acceptance by `2026-08-28T23:30:00+10:00`, disable `AR-local laptop backup`,
verify it is disabled, hash and preserve the resulting XML, and record
`BLOCKED`. Do not re-enable v1.3 for the 05:00 run.

If Gate 4 has replaced the definition but any acceptance check fails, leave or
make the task disabled. Do not restore an enabled v1.3 definition. Preserve the
accepted old XML for evidence and use it only for comparison. The production
01:00 ingest remains unaffected; a missed laptop backup can be recovered after
the freeze from retained Pi data, whereas a missed current-day CDR source
capture cannot.

#### First natural v1.4 proof and next resume point

After exact installation acceptance, append a new handoff entry and stop this
slice. The next natural execution is the installed task at
`2026-08-29T05:00:00+10:00`, only after the independent natural 01:00 ingest is
terminally validated and the dashboard has returned. Do not trigger the task
manually. Its expected action is `BACKUP-LATEST` with `PASS` if the 2026-08-29
observation advanced; `NO_BACKUP_DATA_WRITE` requires independent proof that all
source identities genuinely remained unchanged. Validate task result zero,
exact execution-record identity, catalog append-only integrity, receipts,
restores, Pi identity equality, no locks/partials/helpers/overlaps, and the
50 GiB floor.

A4 planning remains `BLOCKED` until both the transition entry and the first
natural v1.4 05:00 proof entry are terminal `PASS`. No authority in this entry
permits A4 implementation or execution, Pi deployment, runtime modification,
manual ingest, forced ingest, publication manipulation, or Phase B advancement.

---

## Entry `HANDOFF-20260828T073037+1000-A3-V14-TASK-TRANSITION`

### Control record

| Field | Value |
|---|---|
| Previous entry | `HANDOFF-20260828T070253+1000-A3-PLAN-V14` |
| Previous entry merge commit | `d2ceb39adb31cf4268af2dfeee1e7d69dafed3a9` |
| Previous handoff raw Git-blob SHA-256 | `62d7c23bd7fad502ef9ff8ee5237d6ebd6f7d5568ab8b9a0d36fe0ec624c6dbd` |
| Created, Australia/Hobart | `2026-08-28T07:30:37+10:00` |
| Created, UTC | `2026-08-27T21:30:37Z` |
| Operator | `Codex for jkoka` |
| Result | `BLOCKED` — administrator-only Gate 4 remains for the operator |
| Current phase | `A3 v1.4 scheduled-task transition: Gates 1 through 3 PASS; Gate 4 pending` |
| Plan document | `ARL-OPS-001` |
| Plan version | `1.4` |
| Plan commit | `14dd066099bba393cccf61a280243e43162eedc9` |
| Controlled plan SHA-256 | `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Normalized plan Git-blob SHA-256 | `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4` |
| Candidate code SHA | `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Protected Pi SHA | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Operator identity required for Gate 4 | `yanniedog\jkoka`, elevated administrator shell |
| Deviations | None |

### Authoritative paths and initial state

| Purpose | Path and state |
|---|---|
| Pi production | `/srv/ar-local/AR-local`; clean at protected SHA; not changed |
| Exact v1.4 receiver | `C:\code\backups\AR-local-pi5-receiver-f214e32`; clean detached checkout at candidate SHA |
| Backup target | `C:\code\backups\AR-local-pi5`; intentionally advanced append-only through catalog sequence 328 |
| Recovery image | `C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21`; unchanged |
| Old installed receiver | `C:\code\backups\AR-local-pi5-receiver-c87cdd0`; retained unchanged as historical A3 evidence |
| Old installed task | `AR-local laptop backup`; still enabled and `Ready` on v1.3 pending Gate 4 |
| Dirty user checkout | `C:\code\AR-local`; prohibited and untouched |
| This documentation worktree | `C:\code\backups\AR-local-a3-v14-task-transition-handoff`; fresh branch from exact previous merge |

### Gate results

| Gate | Result | Evidence |
|---|---|---|
| Documentation authority | `PASS` | Previous merge and raw handoff hash exact; runbook verifier returned v1.4 identity |
| Exact receiver | `PASS` | Clean detached `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Laptop preflight | `PASS` | Target/image present, 158,916,251,648 free bytes, no receiver lock/partial/helper |
| Pi read-only preflight | `PASS` | Protected clean SHA, ingest inactive, lock absent, timer active/enabled for 01:00, dashboard healthy for `2026-08-28` |
| Foreground v1.4 wrapper | `PASS` | Expected `BACKUP-LATEST`; no historical backfill; post-state `UP_TO_DATE` |
| Historical catalog prefix | `PASS` | First 325 lines retain SHA-256 `0f3517c61ae5c9fb13a2ecc634895b8c0ee935d3d005e4b6d7cf68086e4d5704` |
| Current catalog | `PASS` | 328 valid hash-linked entries; SHA-256 `0758084ea8ac5708c568c407682382acdf7c006829705addf8a0e4d21aef27a6`; tip digest `b9cb51490976782661f73ba0773d24856accf892d1fa366ca4c3ed374b80c5ba` |
| Receipt identities | `PASS` | 325 catalogued v1.3 receipts accepted only through the exact legacy allowlist; three new receipts are exact v1.4 |
| Observation restore | `PASS` | 10,995 files and 2,776,556,753 source bytes verified; SQLite quick check `ok`; 3,012 products; 17,052 rates |
| Control restore | `PASS` | 321 files and 223,783,395 source bytes verified; both Git bundles present; SQLite checks `ok` |
| Macro restore | `PASS` | One file and 995,328 source bytes verified; SQLite quick check `ok` |
| Post-run hygiene | `PASS` | No receiver lock, partial, or helper; 158,597,357,568 free bytes |
| v1.4 task installation/read-back | `BLOCKED` | Requires the operator's elevated Windows shell; current Codex shell is not elevated |

### Immutable v1.4 backup evidence

The scheduled execution record is:

`C:\code\backups\AR-local-pi5\catalog\scheduled-runs\20260827T212833Z-5f79ead38f3f45a989da9d19221dc122.json`

- SHA-256:
  `7818886261AFAC38558625171E00886CC6926834869CE4AF3ECD9FAFA8E344CF`;
- action `BACKUP-LATEST`;
- result `PASS`;
- inventory `UP_TO_DATE` with no missing completed dates and no stale
  diagnostics; and
- observation, control, and macro all `UP_TO_DATE`.

| Catalog sequence | Exact receipt path under `C:\code\backups\AR-local-pi5` | Receipt SHA-256 | Archive SHA-256 | Archive bytes |
|---:|---|---|---|---:|
| 326 | `observations\2026-08-28\b9027f6e3b870fc49770daf412bbedabefa36498283a8e96fa31bb1b95e94632\receipt.json` | `B6DE77630C6F5772C897CA74149C6A275C773FE69413FDD6369C80A7B78A2F56` | `db98067e11835b06fdba5d80d29c5c5f145ec35b9c3a0670050e2bd341d1d286` | 240,169,360 |
| 327 | `control\20260827T212745Z-e04bdadaae10b8ab\receipt.json` | `B250386D2245B7A9FDD9C45C7AE8891FF909D3AA2BB615BFE89FC2E6E752B4A5` | `8d836989ed525972c99cd2d86aa4598e690032225c85b5b0fc13b503d62a2fd9` | 80,275,369 |
| 328 | `macro\19afe13e46d63568f858f832adbd548bd4761a5815d30e67bb3e06b843c027f2\receipt.json` | `F2EEEC162C6D84E1A0F6108E3EA1C050AA2E0B92340FBF89C1A2E2EFA6420EB9` | `ca4f75992aacba746523d6c7c958b2f41451e9cc9b9730eb2fcfb24e15fdc4c5` | 166,665 |

The latest observation remains `2026-08-28`, generation
`obs-2026-08-28-3c534348347d3f4e`: capture `PASS`, finalization `PASS`, dated
v1 `PASS`, rolling v1 `PASS`, dates index `PASS`, dashboard return `PASS`, and
laptop backup `PASS`. v2 remains independently stale/`FAIL`; the missed 00:25
and 00:58 proof leaves the timed natural-ingest procedure independently
`BLOCKED`. None of those independent outcomes is relabelled by this entry.

### Exact Gate 4 operator action

Run this block once in a new **administrator** Windows PowerShell window. Do not
run it in the non-elevated Codex terminal. Do not manually start the task after
installation.

```powershell
$ErrorActionPreference = 'Stop'
whoami
# Must print: yanniedog\jkoka
([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
# Must print: True

$receiver = 'C:\code\backups\AR-local-pi5-receiver-f214e32'
$target = 'C:\code\backups\AR-local-pi5'
$image = 'C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21'
$candidate = 'f214e3249c7968d574e3449edb14792904e1cc1f'
$protected = '9302890fcc752cbf90da97d597e972c157d913e3'
$planCommit = '14dd066099bba393cccf61a280243e43162eedc9'

if ((git -C $receiver rev-parse HEAD).Trim() -ne $candidate) { throw 'Receiver SHA mismatch.' }
if (@(git -C $receiver status --porcelain=v1).Count -ne 0) { throw 'Receiver is dirty.' }
if (Test-Path -LiteralPath "$target\catalog\.receiver.lock") { throw 'Receiver lock exists.' }
if (Get-ChildItem -LiteralPath $target -Recurse -Force -Filter '*.partial') { throw 'Partial artifact exists.' }
if ((Get-Volume -DriveLetter C).SizeRemaining -lt 53687091200) { throw 'Less than 50 GiB remains.' }

& "$receiver\install_laptop_backup_task.ps1" `
  -Target $target `
  -RecoveryImage $image `
  -CandidateCodeSha $candidate `
  -ProtectedCodeSha $protected `
  -PlanGitCommit $planCommit `
  -Operator 'jkoka'
if ($LASTEXITCODE -ne 0) { throw 'v1.4 task installation failed.' }

$task = Get-ScheduledTask -TaskName 'AR-local laptop backup' -ErrorAction Stop
$info = Get-ScheduledTaskInfo -TaskName 'AR-local laptop backup' -ErrorAction Stop
$xml = Export-ScheduledTask -TaskName 'AR-local laptop backup' -ErrorAction Stop
$task | Format-List TaskName,State
$info | Format-List LastRunTime,LastTaskResult,NextRunTime,NumberOfMissedRuns
$xml
```

Expected installer precheck: `NO_BACKUP_DATA_WRITE`, result `PASS`, every
component `UP_TO_DATE`. Expected task: `Ready`, enabled, exact receiver and
candidate above, plan commit `14dd066...`, protected SHA `9302890...`, operator
`jkoka`, principal `yanniedog\jkoka`, `S4U`, `Limited`, one daily 05:00 trigger,
one startup-plus-five-minute trigger, `IgnoreNew`, three 30-minute retries,
six-hour limit, and start-when-available.

Return the complete output to the controlling session. The next session then
hashes and preserves the live XML, validates the new installer-created
scheduled record, performs a final read-only Pi/laptop no-drift check, and
appends a terminal transition entry. If installation or read-back fails, leave
the task disabled and return the exact error; do not restore an enabled v1.3
definition.

### Time boundary and resume state

Gate 4 must reach exact acceptance by `2026-08-28T23:30:00+10:00`. If it cannot,
an elevated operator must disable `AR-local laptop backup`, verify disabled
read-back, preserve its XML, and record `BLOCKED`. The v1.3 task must not execute
again after terminal A3. The 00:30 freeze still takes precedence, and the natural
2026-08-29 01:00 Pi ingest remains untouched.

A4 planning, A4 execution, deployment, manual ingest, force, publication
manipulation, and Phases B through G remain prohibited. After exact task
installation passes, the first natural v1.4 05:00 run on 2026-08-29 must be
observed and accepted before A4 planning can begin.

---

## Entry `HANDOFF-20260828T080245+1000-A3-V14-TASK-PASS`

### Control record

| Field | Value |
|---|---|
| Previous entry | `HANDOFF-20260828T073037+1000-A3-V14-TASK-TRANSITION` |
| Previous entry merge commit | `3f626c7e08885b3fa7f2e5f0c433d4fde4a3b35d` |
| Previous handoff raw Git-blob SHA-256 | `c0824d46f041ec258e3d2acb4568248933640cea7a8b0f72d036c48cd2a624e9` |
| Created, Australia/Hobart | `2026-08-28T08:02:45+10:00` |
| Created, UTC | `2026-08-27T22:02:45Z` |
| Operator | `Codex for jkoka`; elevated registration executed as `yanniedog\jkoka` |
| Result | `PASS` |
| Current phase | `A3 v1.4 scheduled-task transition complete; first natural v1.4 05:00 proof pending` |
| Plan document/version | `ARL-OPS-001` / `1.4` |
| Plan commit | `14dd066099bba393cccf61a280243e43162eedc9` |
| Controlled plan SHA-256 | `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Normalized plan Git-blob SHA-256 | `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4` |
| Candidate code SHA | `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Protected Pi SHA | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Deviations | None |

### Terminal evidence

Create-once result:

`C:\code\backups\AR-local-pi5\evidence\A3-V14-TASK-TRANSITION-20260828\20260828T080004+1000\transition-result.json`

- bytes: `4,976`;
- SHA-256:
  `72A395FCC67C23D57E5CD0C6C1BFFB6069EA918432817373A9A7439B49E53933`;
- result: `PASS`.

Preserved exact live Task Scheduler XML:

`C:\code\backups\AR-local-pi5\evidence\A3-V14-TASK-TRANSITION-20260828\20260828T080004+1000\installed-task.xml`

- encoding: UTF-16LE with BOM;
- bytes: `4,774`;
- SHA-256:
  `AA539FB4BB2F1768B2EA57539E7D5201A930E88EECF9192F4F94518B08E9D9E2`.

The elevated operator output is retained at
`C:\Users\jkoka\.codex\attachments\294655f6-4b6c-4eb0-8160-9a61a8ce8b04\pasted-text.txt`,
SHA-256
`1FA10E0F981449E9F4188AF45365810A67FE634CDB3166D8C38FE6BAB31264BD`.

The installer-created check-only record is:

`C:\code\backups\AR-local-pi5\catalog\scheduled-runs\20260827T215815Z-a0712f88d7e74dd8b3b4708a4c69e3c7.json`

- SHA-256:
  `66C7A84AB8E7FDE7A2278909285517EE078E4338A86681C254B54A858E2AB567`;
- action `NO_BACKUP_DATA_WRITE`;
- result `PASS`;
- exact v1.4 plan, candidate, protected SHA, and operator identities;
- observation sequence 326, control sequence 327, and macro sequence 328 all
  `UP_TO_DATE`; and
- no missing completed dates or stale diagnostics.

### Acceptance results

| Gate | Result | Evidence |
|---|---|---|
| Exact clean receiver | `PASS` | Detached `f214e324...`; no dirty paths |
| Installer check-only | `PASS` | Exact record and hash above; no backup-data write |
| Exact task action | `PASS` | Receiver, script, target, image, candidate, protected SHA, plan commit, and operator all exact |
| Task principal | `PASS` | SID `S-1-5-21-689213601-40760280-3596424081-1001`, `S4U`, `Limited` |
| Triggers | `PASS` | Daily 05:00 and startup delay `PT5M` |
| Overlap/retry/runtime | `PASS` | `IgnoreNew`, three retries at `PT30M`, execution limit `PT6H` |
| Enabled/read-back | `PASS` | `Ready`, enabled, zero missed runs; full core assertion passed |
| Previous task result | `PASS` | Last natural v1.3 A3 run remains result zero and historical evidence is unchanged |
| Next natural task run | `RUNNING` obligation | `2026-08-29T05:00:00+10:00`; do not trigger manually |
| Catalog integrity | `PASS` | Still 328 entries; SHA-256 `0758084ea8ac5708c568c407682382acdf7c006829705addf8a0e4d21aef27a6`; no generation was appended by installation |
| Hygiene/capacity | `PASS` | No receiver lock or partial; 158,551,814,144 free bytes |
| Pi no-drift | `PASS` | Protected clean SHA, ingest inactive, lock absent, timer active/enabled for 01:00 |
| Dashboard | `PASS` | HTTP healthy for observation date `2026-08-28` |
| Current observation | `PASS` unchanged | `2026-08-28`, generation `obs-2026-08-28-3c534348347d3f4e`; capture and finalization remain `PASS` |
| Current public v1 | `PASS` unchanged | Dated v1, rolling v1, and dates index remain independently `PASS` |
| Current public v2 | `FAIL` unchanged | v2 remains independently stale; this task-transition result does not supersede it |
| Timed natural-ingest procedure | `BLOCKED` unchanged | The 2026-08-28 00:25 and 00:58 evidence was missed; the next complete timed proof is 2026-08-29 |

The superseded v1.3 task is no longer active. Its receiver, accepted XML,
receipts, and execution records remain immutable historical evidence. No Pi
production state or production backup data/generation was modified or appended
by this transition. The installer wrote the scheduled-run JSON evidence record
listed above and updated the backup target's latest-scheduled pointer.

### Operating policy and exact resume point

The operator directs future controlling agents to execute safe, authorised
commands themselves using available permissions and automation. Do not delegate
routine PowerShell, SSH, Git, validation, or evidence commands back to the
operator. Request human action only when an unavoidable interactive boundary
cannot be completed through the available tools, such as physical hardware,
UAC that cannot be satisfied by the execution environment, or unavailable
credentials. Such a boundary is reported precisely and remains fail-closed.

Daily capture remains the overriding D-006 obligation. The commands below are
the self-contained v1.4 continuation for 2026-08-29. Do not substitute the
superseded v1.3 receiver/XML commands elsewhere in this ledger.

At 00:25 Australia/Hobart, run this block. It creates a unique laptop-only
evidence directory and records its path for later unattended invocations:

```powershell
$ErrorActionPreference = 'Stop'
$sourceDate = '2026-08-29'
$expectedPi = '9302890fcc752cbf90da97d597e972c157d913e3'
$expectedReceiver = 'f214e3249c7968d574e3449edb14792904e1cc1f'
$receiver = 'C:\code\backups\AR-local-pi5-receiver-f214e32'
$target = 'C:\code\backups\AR-local-pi5'
$evidenceParent = Join-Path $target 'evidence\NATURAL-20260829'
$activePointer = Join-Path $evidenceParent 'ACTIVE_EVIDENCE_PATH.txt'
New-Item -ItemType Directory -Path $evidenceParent -Force -ErrorAction Stop | Out-Null
if (Test-Path -LiteralPath $activePointer) { throw 'An unclosed 2026-08-29 evidence run already exists.' }
$evidenceRun = [datetimeoffset]::Now.ToString('yyyyMMddTHHmmsszzz').Replace(':','')
$evidenceRoot = Join-Path $evidenceParent $evidenceRun
New-Item -ItemType Directory -Path $evidenceRoot -ErrorAction Stop | Out-Null
[IO.File]::WriteAllText($activePointer, $evidenceRoot, [Text.UTF8Encoding]::new($false))

git fetch origin --prune
$runbookCommit = (git log -1 --format=%H origin/main -- docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md).Trim()
if ($runbookCommit -ne '14dd066099bba393cccf61a280243e43162eedc9') { throw 'Runbook commit mismatch.' }
Push-Location $receiver
try {
  $plan = python -c "import json,laptop_pull_backup as r; print(json.dumps(r.verify_plan_document(),sort_keys=True))"
  if ($LASTEXITCODE -ne 0) { throw 'Controlled-plan verification failed.' }
} finally { Pop-Location }
$planObject = $plan | ConvertFrom-Json
if ($planObject.plan_document_id -ne 'ARL-OPS-001' -or
    $planObject.plan_version -ne '1.4' -or
    $planObject.plan_git_commit -ne '14dd066099bba393cccf61a280243e43162eedc9' -or
    $planObject.plan_sha256 -ne '78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713') {
  throw 'Controlled-plan identity mismatch.'
}
if ((git -C $receiver rev-parse HEAD).Trim() -ne $expectedReceiver) { throw 'Receiver SHA mismatch.' }
if (@(git -C $receiver status --porcelain=v1).Count -ne 0) { throw 'Receiver is dirty.' }
$authority = [ordered]@{
  observed_at=[datetimeoffset]::Now.ToString('o'); source_date=$sourceDate
  origin_main=(git rev-parse origin/main).Trim(); runbook_commit=$runbookCommit
  plan=$planObject; receiver_sha=$expectedReceiver; protected_pi_sha=$expectedPi
}
$authority | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $evidenceRoot 'authority.json')

$preflight = ssh -o BatchMode=yes -o ConnectTimeout=10 ar-local-pi5-lan `
  "set -eu; date --iso-8601=seconds; git -C /srv/ar-local/AR-local rev-parse HEAD; git -C /srv/ar-local/AR-local status --porcelain=v1; systemctl is-enabled ar-local-daily.timer; systemctl is-active ar-local-daily.timer; systemctl show ar-local-daily.timer -p NextElapseUSecRealtime -p LastTriggerUSec -p Result; systemctl show ar-local-daily.service -p ActiveState -p SubState -p InvocationID -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p ExecMainStatus -p Result; if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi; pgrep -a -f '[p]i_daily_sync.py|[c]dr_daily.py' || true; df -B1 /srv/ar-local/data; free -b; journalctl -k --since '24 hours ago' --no-pager | grep -Ei 'oom|out of memory|killed process' || true; curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest; curl -fsS --max-time 15 -o /dev/null -w 'github_http=%{http_code}\n' https://api.github.com/"
$preflight | Set-Content -LiteralPath (Join-Path $evidenceRoot '0025-preflight.txt')
if ($LASTEXITCODE -ne 0) { throw "00:25 Pi preflight failed: ssh exit $LASTEXITCODE" }
if (($preflight -join "`n") -notmatch [regex]::Escape($expectedPi) -or
    ($preflight -join "`n") -notmatch 'lock=ABSENT') { throw '00:25 protected identity or lock gate failed.' }
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $evidenceRoot 'authority.json'),(Join-Path $evidenceRoot '0025-preflight.txt') |
  Format-Table -AutoSize | Out-String | Set-Content -LiteralPath (Join-Path $evidenceRoot '0025-hashes.txt')
```

The freeze begins at 00:30 and continues through terminal ingest validation.
During it, do not deploy, run a canary/manual ingest, force, restart services,
change the task, run a backup, or manipulate publication. At 00:58, recover the
exact active evidence directory and repeat the fail-closed read-only gate:

```powershell
$ErrorActionPreference = 'Stop'
$expectedPi = '9302890fcc752cbf90da97d597e972c157d913e3'
$evidenceParent = 'C:\code\backups\AR-local-pi5\evidence\NATURAL-20260829'
$activePointer = Join-Path $evidenceParent 'ACTIVE_EVIDENCE_PATH.txt'
$evidenceRoot = [IO.Path]::GetFullPath((Get-Content -LiteralPath $activePointer -Raw).Trim())
if (-not $evidenceRoot.StartsWith([IO.Path]::GetFullPath($evidenceParent) + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
  throw 'Active evidence path escapes its controlled parent.'
}
$immediate = ssh -o BatchMode=yes -o ConnectTimeout=10 ar-local-pi5-lan `
  "set -eu; date --iso-8601=seconds; git -C /srv/ar-local/AR-local rev-parse HEAD; git -C /srv/ar-local/AR-local status --porcelain=v1; systemctl is-enabled ar-local-daily.timer; systemctl is-active ar-local-daily.timer; systemctl show ar-local-daily.timer -p NextElapseUSecRealtime -p LastTriggerUSec -p Result; systemctl show ar-local-daily.service -p ActiveState -p SubState -p InvocationID -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p ExecMainStatus -p Result; if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi; pgrep -a -f '[p]i_daily_sync.py|[c]dr_daily.py' || true; df -B1 /srv/ar-local/data; free -b; curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest; curl -fsS --max-time 15 -o /dev/null -w 'github_http=%{http_code}\n' https://api.github.com/"
$immediate | Set-Content -LiteralPath (Join-Path $evidenceRoot '0058-immediate-gate.txt')
if ($LASTEXITCODE -ne 0) { throw "00:58 Pi gate failed: ssh exit $LASTEXITCODE" }
if (($immediate -join "`n") -notmatch [regex]::Escape($expectedPi) -or
    ($immediate -join "`n") -notmatch 'lock=ABSENT') { throw '00:58 protected identity or lock gate failed.' }
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $evidenceRoot '0058-immediate-gate.txt') |
  Format-Table -AutoSize | Out-String | Set-Content -LiteralPath (Join-Path $evidenceRoot '0058-hash.txt')
```

Observe, but never start, force, restart, or rerun, the natural service. Use the
following exact terminal capture after directly observing its single start:

```powershell
$startDeadline = [datetimeoffset]'2026-08-29T01:10:00+10:00'
do {
  $active = (ssh -o BatchMode=yes ar-local-pi5-lan "systemctl show ar-local-daily.service -p ActiveState --value").Trim()
  if ([datetimeoffset]::Now -gt $startDeadline) { throw 'Natural service did not start by 01:10.' }
  if ($active -ne 'active') { Start-Sleep -Seconds 10 }
} until ($active -eq 'active')
$start = ssh -o BatchMode=yes ar-local-pi5-lan `
  "date --iso-8601=seconds; systemctl show ar-local-daily.service -p ActiveState -p SubState -p InvocationID -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p ExecMainStatus -p Result -p NRestarts; systemctl show ar-local-daily.timer -p LastTriggerUSec -p NextElapseUSecRealtime; if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; else echo lock=ABSENT; fi; pgrep -a -f '[p]i_daily_sync.py|[c]dr_daily.py' || true"
$start | Set-Content -LiteralPath (Join-Path $evidenceRoot '0100-start.txt')
if ($LASTEXITCODE -ne 0) { throw 'Natural start capture failed.' }
do {
  Start-Sleep -Seconds 30
  $active = (ssh -o BatchMode=yes ar-local-pi5-lan "systemctl show ar-local-daily.service -p ActiveState --value").Trim()
} while ($active -in @('active','activating'))
$terminal = ssh -o BatchMode=yes ar-local-pi5-lan `
  "set -eu; date --iso-8601=seconds; systemctl show ar-local-daily.service -p ActiveState -p SubState -p InvocationID -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p ExecMainStatus -p ExecMainCode -p Result -p NRestarts; systemctl show ar-local-daily.timer -p LastTriggerUSec -p NextElapseUSecRealtime; if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi; curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest"
$terminal | Set-Content -LiteralPath (Join-Path $evidenceRoot 'terminal-service.txt')
if ($LASTEXITCODE -ne 0) { throw 'Natural terminal capture failed.' }
ssh -o BatchMode=yes ar-local-pi5-lan `
  "journalctl -u ar-local-daily.service --since '2026-08-29 00:55:00' --output=short-iso-precise --no-pager" |
  Set-Content -LiteralPath (Join-Path $evidenceRoot 'service-journal.txt')
if ($LASTEXITCODE -ne 0) { throw 'Journal capture failed.' }
ssh -o BatchMode=yes ar-local-pi5-lan `
  "cd /srv/ar-local/AR-local && python3 cdr_ledger_v2.py verify --state /srv/ar-local/data/state" |
  Set-Content -LiteralPath (Join-Path $evidenceRoot 'ledger-verify.json')
if ($LASTEXITCODE -ne 0) { throw 'Ledger verification failed.' }
```

Run the complete observation and public-GitHub validators from entry
`HANDOFF-20260827T220351+1000-A3` exactly as printed there, with their date
literal set to `2026-08-29` and their existing `$evidenceRoot` retained. This is
the only authorised literal substitution: the observation validator must write
`observation-verify.json`, and the public validator must write
`public-github\verification.json`. Require raw-attempt, marker, contract,
ledger, generation, SQLite, provider accounting, dated v1, rolling v1, dates
index, dashboard, and public-byte checks all to pass. Record v2 independently;
its existing stale/`FAIL` state is not silently promoted and does not invalidate
otherwise valid v1.

After the ingest terminally validates and the dashboard returns, wait for the
installed task's natural triggers; never trigger it manually. A laptop boot
after the observation advances may legitimately execute the startup-plus-five-
minute trigger before 05:00. Therefore validate every scheduled-run record
after the installation baseline, not merely `latest-scheduled.json`. Use this
exact block at 05:15 or after the task is terminal:

```powershell
$ErrorActionPreference = 'Stop'
$taskName = 'AR-local laptop backup'
$receiver = 'C:\code\backups\AR-local-pi5-receiver-f214e32'
$target = 'C:\code\backups\AR-local-pi5'
$candidate = 'f214e3249c7968d574e3449edb14792904e1cc1f'
$protected = '9302890fcc752cbf90da97d597e972c157d913e3'
$planCommit = '14dd066099bba393cccf61a280243e43162eedc9'
$planSha = '78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713'
$baselineCompleted = [datetimeoffset]'2026-08-27T21:58:15Z'
$recordedXmlPath = 'C:\code\backups\AR-local-pi5\evidence\A3-V14-TASK-TRANSITION-20260828\20260828T080004+1000\installed-task.xml'
$recordedXmlSha = 'aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2'
$evidenceParent = Join-Path $target 'evidence\NATURAL-20260829'
$evidenceRoot = [IO.Path]::GetFullPath((Get-Content -LiteralPath (Join-Path $evidenceParent 'ACTIVE_EVIDENCE_PATH.txt') -Raw).Trim())
if (-not $evidenceRoot.StartsWith([IO.Path]::GetFullPath($evidenceParent) + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
  throw 'Active evidence path escapes its controlled parent.'
}

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
$info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
if ($task.State -ne 'Ready' -or -not $task.Settings.Enabled -or $info.LastTaskResult -ne 0) {
  throw 'Natural task is not Ready/enabled or LastTaskResult is nonzero.'
}
if ((git -C $receiver rev-parse HEAD).Trim() -ne $candidate -or
    @(git -C $receiver status --porcelain=v1).Count -ne 0) { throw 'v1.4 receiver drifted.' }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $recordedXmlPath).Hash.ToLowerInvariant() -ne $recordedXmlSha) {
  throw 'Recorded accepted task XML changed.'
}
$liveXml = Export-ScheduledTask -TaskName $taskName -ErrorAction Stop
$recordedXml = Get-Content -LiteralPath $recordedXmlPath -Raw
if ($liveXml -cne $recordedXml) { throw 'Live task differs from accepted v1.4 XML.' }
if (Test-Path -LiteralPath (Join-Path $target 'catalog\.receiver.lock')) { throw 'Receiver lock exists.' }
if (Get-ChildItem -LiteralPath $target -Recurse -Force -Filter '*.partial') { throw 'Partial artifact exists.' }
if ((Get-Volume -DriveLetter C).SizeRemaining -lt 53687091200) { throw 'Less than 50 GiB remains.' }

$records = Get-ChildItem -LiteralPath (Join-Path $target 'catalog\scheduled-runs') -File -Filter '*.json' |
  ForEach-Object {
    $record = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
    [pscustomobject]@{ Path=$_.FullName; Sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant(); Record=$record; Completed=[datetimeoffset]$record.timestamps.completed_at }
  } | Where-Object { $_.Completed -gt $baselineCompleted } | Sort-Object Completed
if ($records.Count -lt 1) { throw 'No natural v1.4 scheduled execution record exists.' }
foreach ($item in $records) {
  $r = $item.Record
  if ($r.result -ne 'PASS' -or $r.action -notin @('BACKUP-LATEST','NO_BACKUP_DATA_WRITE') -or
      $r.candidate_code_sha -ne $candidate -or $r.protected_code_sha -ne $protected -or
      $r.plan_document_id -ne 'ARL-OPS-001' -or $r.plan_version -ne '1.4' -or
      $r.plan_git_commit -ne $planCommit -or $r.plan_sha256 -ne $planSha -or
      $r.operator -ne 'jkoka' -or @($r.deviations).Count -ne 0 -or $null -ne $r.deviation_authorization) {
    throw "Scheduled record identity/result mismatch: $($item.Path)"
  }
}
$backupRecords = @($records | Where-Object { $_.Record.action -eq 'BACKUP-LATEST' })
if ($backupRecords.Count -lt 1) { throw 'No BACKUP-LATEST record captured the advanced 2026-08-29 observation.' }
$acceptedBackup = @($backupRecords | Where-Object {
  $_.Record.detail.observation.status -eq 'UP_TO_DATE' -and
  $_.Record.detail.observation.observation_date -eq '2026-08-29' -and
  $_.Record.detail.control.status -eq 'UP_TO_DATE' -and
  $_.Record.detail.macro.status -eq 'UP_TO_DATE' -and
  $_.Record.detail.inventory.status -eq 'UP_TO_DATE'
})
if ($acceptedBackup.Count -lt 1) { throw 'No BACKUP-LATEST record proves all current identities.' }
foreach ($component in @('observation','control','macro')) {
  $receiptPath = [IO.Path]::GetFullPath([string]$acceptedBackup[-1].Record.detail.$component.receipt_path)
  if (-not $receiptPath.StartsWith([IO.Path]::GetFullPath($target) + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw "$component receipt escapes target." }
  $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
  if ($receipt.result -ne 'PASS' -or $receipt.candidate_code_sha -ne $candidate -or
      $receipt.protected_code_sha -ne $protected -or $receipt.plan_git_commit -ne $planCommit -or
      $receipt.plan_sha256 -ne $planSha) { throw "$component receipt verification failed." }
}
$records | Select-Object Completed,Path,Sha256,@{n='Action';e={$_.Record.action}},@{n='Result';e={$_.Record.result}} |
  ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidenceRoot 'scheduled-records.json')
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $evidenceRoot 'scheduled-records.json')
```

Thus `BACKUP-LATEST` may occur at the startup trigger and a subsequent natural
05:00 `NO_BACKUP_DATA_WRITE` is accepted only after the earlier backup record,
all three identity receipts, every intervening record, and the 05:00 zero result
are preserved and verified. Also require the full catalog prefix/hash chain,
restore checks, Pi source-identity equality, no locks/partials/helpers/overlap,
and at least 50 GiB free. Remove `ACTIVE_EVIDENCE_PATH.txt` only after the new
immutable terminal handoff entry and all evidence hashes have been committed.

Any missed timed gate or ambiguous/mismatched identity is `BLOCKED`; any corrupt
artifact, failed integrity check, invalid public byte, or failed natural process
is `FAIL`. Preserve the evidence directory, raw data, last verified rolling
payload, and all scheduled records. Do not deploy, force, rerun ingest, rerun a
publication-only failure, manually trigger backup, delete/overwrite the day, or
repair state inside the freeze. Append the terminal outcome and exact hashes;
never edit completed evidence.

A4 planning remains `BLOCKED` until that first natural v1.4 execution is
terminal `PASS`. A4 implementation/execution, Pi deployment, runtime changes,
manual or forced ingest, publication manipulation, and Phases B through G remain
prohibited.

## Entry `HANDOFF-20260829T052121+1000-A3-NATURAL-BACKUP-BLOCKED`

This is an append-only terminal record for the natural 2026-08-29 ingest and
the first natural v1.4 Windows backup proof. It does not rewrite or relabel any
earlier result.

### Authority and immutable identities

| Field | Value |
|---|---|
| Plan | `ARL-OPS-001` v1.4 |
| Plan document-containing commit | `14dd066099bba393cccf61a280243e43162eedc9` |
| Controlled plan SHA-256 | `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Normalized plan SHA-256 | `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4` |
| Prior handoff merge | `799b090c2cc5167c67ec6a7cc5317c6b1995453d` |
| Prior handoff raw SHA-256 | `d6df576b0c30978c58a5fd0436d9009be10f78f88aeb1261003e62b3284c78bc` |
| Receiver | `C:\code\backups\AR-local-pi5-receiver-f214e32` |
| Candidate code SHA | `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Protected Pi SHA | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Operator | Codex unattended for `jkoka` |
| A4 status | `BLOCKED` |

### Natural ingest outcome

The natural 2026-08-29 ingest independently passed all data and publication
checks. Invocation `28480326733b49a2a2206bcb402f6236` ran once from
01:00:00 through 01:17:15 Australia/Hobart, returned systemd `success` with
`ExecMainStatus=0` and `NRestarts=0`, left no lock, and restored the dashboard.
Ledger verification passed 18/18 with no findings or warnings. Observation
`obs-2026-08-29-85d1deba454330c8` was a valid bounded partial observation:
3,839 hash-bound raw attempts; 119/119 providers attempted; 112 complete, 7
partial, and 0 failed providers; 17 attributable product failures; zero corrupt
or unattributed failures; 3,012 products; 17,050 rates; SQLite quick check
`ok`; and no quarantines. Dated v1, rolling v1, dates index, and every referenced
public asset passed independent public-byte verification. v2 remains separately
stale at 2026-08-21 and was not promoted.

The overall timed-ingest procedure remains `BLOCKED`, not `PASS`, because the
00:58 heartbeat arrived at 00:59:47 and the gate executed at 01:00:10 after the
natural ingest lock already existed. The independently valid ingest is not
relabelled, and the procedural miss is not concealed.

Authoritative ingest evidence remains under
`C:\code\backups\AR-local-pi5\evidence\NATURAL-20260829\20260829T002709+1000`:

- `ingest-validation-summary.json`: `E2124D0925EB45E89FB17340036CDEEF69ACD33A16076B3340113B661CAEB944`;
- `observation-verify.json`: `0CA5FF6247C9A630D653010138863F46690DE28EEC1C74544BBE84EA5FFAF1EE`;
- `ledger-verify.json`: `93BCB37B7A397C4764BAB9243DA551FEC3474AF153D51BA91A91A7F210CA1875`;
- `public-github\verification.json`: `EFCC3009F823745562C30BD4F7AA2F296948A2C6789490AF0FA0938412A4D066`.

### First natural v1.4 backup outcome

The installed task started naturally at 05:00:01 and completed its immutable
record at 05:13:17 Australia/Hobart. It was not manually triggered or
reinstalled. The task remained enabled and `Ready`, `LastTaskResult` was zero,
the accepted XML matched byte-for-byte, the receiver was clean at the exact
candidate, no receiver lock, partial artifacts, helper processes, or overlap
remained, and 144.21 GiB was free.

The backup bytes and restoration checks independently `PASS`:

- observation 2026-08-29 is current at catalog sequence 329, archive SHA-256
  `a309f5d516336f58e9974dbffde26309ffaac4b289bc66b201660118b99e5625`,
  with 10,995 files and 2,709,341,187 restored bytes verified, generation
  `obs-2026-08-29-85d1deba454330c8`, and SQLite quick check `ok`;
- control is current at sequence 330, archive SHA-256
  `3676f7061fa472d9adc2a3ce978bf2c6351581749333d9c68599ae4d911676ea`,
  with 326 restored files, both Git bundles verified, two SQLite quick checks
  `ok`, and all four secret locations excluded from copied bytes;
- macro is current at sequence 331, archive SHA-256
  `9c0f1fa50fa7500e1aed2d990c223f916e35ed1018292bf4c8efb207f60a861d`,
  with its SQLite quick check `ok`;
- all source manifests, archives, receipts, plan identities, candidate and
  protected SHAs, and Pi source identities match;
- the full 331-entry catalog hash chain validates; catalog SHA-256 is
  `acb15773fe069c863a0d00daea368f45c838c570b7ca32f1875b7f813470ce8d`;
  the first 328 entries retain SHA-256
  `0758084ea8ac5708c568c407682382acdf7c006829705addf8a0e4d21aef27a6`.

Controlled acceptance is nevertheless `BLOCKED`. The only natural scheduled
record after the baseline is
`C:\code\backups\AR-local-pi5\catalog\scheduled-runs\20260828T191317Z-5b3033fc4db54962bb2fd53b9af5c1aa.json`,
SHA-256 `2753be7b5d87af3d1ab5a581be83f1668a9695f2b5cce58822d675a920e42764`.
It truthfully records `result=PASS` but `action=BACKFILL`; the controlled gate
requires `BACKUP-LATEST`, or `NO_BACKUP_DATA_WRITE` only after an accepted
`BACKUP-LATEST`. No deviation was authorized, so this action is not relabelled.

The cause is deterministic in candidate `f214e324`: `scheduled_status()` sets
`backfill_required` whenever the protected inventory has any missing completed
date, and `main()` selects `backfill` whenever that Boolean is true. Therefore
the ordinary newly created 2026-08-29 observation was classified as historical
backfill. The transfer is complete and valid, but the action semantics do not
match the controlled proof.

The append-only backup validation record is
`C:\code\backups\AR-local-pi5\evidence\NATURAL-20260829\20260829T002709+1000\backup-validation-result.json`,
SHA-256 `763A2C01B03D5FECDE1675A2AAC495F8FDDF951318DD1C6F28FE86023A9C3766`.
It records component-level passes separately from the terminal controlled
`BLOCKED` result. Completed evidence and the scheduled record must never be
edited.

### Controlled next actions

Daily current-day-only CDR capture remains the overriding priority under D-006.
The existing scheduled backup remains installed because it safely captured and
verified all required bytes; do not manually trigger or relabel it. Before the
next natural 01:00 ingest, no Pi runtime, production checkout, publication, or
task mutation is authorized.

Resume A3 only. In daylight, prepare one focused code PR from fresh
`origin/main` that distinguishes:

1. the ordinary newest completed observation, which must use
   `backup-latest` and record `BACKUP-LATEST`;
2. genuinely missing older completed dates, which must use selective
   `backfill` and record `BACKFILL`;
3. an already current target, which must record `NO_BACKUP_DATA_WRITE`.

The PR must add exact boundary tests for new-latest-only, historical-gap-only,
both conditions together, and already-current state. It must preserve the
50-GiB floor, immutable catalog, restore verification, identity binding,
overlap prevention, and fail-closed behavior. It must not deploy to the Pi,
start A4, or manipulate publication. Do not replace the installed task until
that correction is reviewed, merged, exact-head tested against isolated backup
state, and an append-only decision entry explicitly authorizes the transition.

For the natural 2026-08-30 ingest, schedule unattended continuity checks early
enough that the final pre-start gate completes before 01:00. Run the full
read-only preflight at 00:25 Australia/Hobart and begin the final gate no later
than 00:55. Freeze begins at 00:30 and lasts through terminal validation. Observe
the natural service only; never start, restart, force, or rerun it. Preserve the
same raw-attempt, completion, contract, ledger, SQLite, provider accounting,
dashboard-return, dated-v1, rolling-v1, dates-index, asset-byte, and independent
v2 checks used for 2026-08-29. After terminal validation, observe the natural
05:00 laptop task without triggering it and record its immutable action exactly.

A4 and Phases B through G remain `BLOCKED` until a corrected A3 candidate has a
terminal natural proof or a formal append-only deviation decision revises the
acceptance criteria with its reason, risk, compensating controls, and explicit
authorization.

## Entry `HANDOFF-20260829T110711+1000-A3-CLASSIFIER-MERGED`

### Required control record

| Field | Value |
|---|---|
| Created at, Australia/Hobart | `2026-08-29T11:07:11+10:00` |
| Created at, UTC | `2026-08-29T01:07:11Z` |
| Previous handoff entry | `HANDOFF-20260829T052121+1000-A3-NATURAL-BACKUP-BLOCKED` |
| Previous handoff merge | `c879227a267c144560563efc933addcfe858c59a` |
| Previous handoff raw SHA-256 | `6d8a0b1dd9368f16160b3d88bd1fce452c4918d92741044d1e91cf775a2caf24` |
| Plan | `ARL-OPS-001` v1.4 |
| Plan document-containing commit | `14dd066099bba393cccf61a280243e43162eedc9` |
| Controlled plan SHA-256 | `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Normalized plan SHA-256 | `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4` |
| Corrected code merge | `9643b2e22a342ef106025377f02b0179501db1ca` |
| Corrected PR head | `49588081161a7d7caee1a831d4fd7f435c139a23` |
| Protected Pi SHA | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Operator | Codex unattended for `jkoka` |
| Overall result | `BLOCKED` |
| Completed component | `A3 scheduler-classification code and isolated verification: PASS` |
| Current phase | `A3 corrected merge proven; receiver/task transition NOT_STARTED` |
| A4 and Phases B-G | `BLOCKED` |
| Deviations | none |
| Deviation authorization | none |

The overall result is `BLOCKED`, rather than `PASS`, because the corrected code
has not replaced the installed receiver or task, no natural run has exercised
it, and exact-head review found source-identity inputs that the merged candidate
does not yet reject before transfer. The Pi later recovered after the operator
restored power; that recovery does not remove the source-identity blocker. This
entry does not authorize a Pi deployment, task replacement, manual backup,
manual ingest, publication manipulation, or A4 work.

### Append-only corrections to the preceding entry

The 2026-08-29 producer observation retains raw value `partial`; its controlled
ARL-OPS-001 state is `degraded`. It remains acceptable v1 data because all
available provenance, provider accounting, SQLite, ledger, contract,
public-byte, and protected-runtime disclosure checks passed. Numeric failure
counts and ratios remain disclosure and alerting metrics only; D-003 supersedes
them as publication eligibility thresholds. Future product-scoped publication
still requires D-003 membership reconciliation and whole-observation controls.

Both timed pre-start gates were missed. The evidence directory timestamp proves
that the nominal 00:25 block began at 00:27:09, and the nominal 00:58 block began
at 01:00:10 after the lock existed. The independently valid natural ingest does
not change either procedural gate from `BLOCKED`.

The combined-action decision is now explicit and non-conversational:

- only the authoritative newest completed observation missing means one
  `backup-latest` request and immutable action `BACKUP-LATEST`;
- any strictly older completed observation missing means one `backfill` request
  and immutable action `BACKFILL`;
- if newest and older dates are both missing, the request remains one
  `BACKFILL`, only the older dates are supplied as `--include-date`, and the
  receiver captures the newest observation first in that same invocation;
- a fully current target remains `NO_BACKUP_DATA_WRITE`;
- malformed, unordered, duplicate, or internally inconsistent date lists that
  the merged validator recognizes are `BLOCKED` before transfer;
- a blocked or malformed post-transfer verification is immutable
  `FAIL/POST_BACKUP_VERIFY`, retaining the attempted action; and
- a structurally valid post-transfer verification that remains `STALE` is
  immutable `FAIL` under the attempted `BACKUP-LATEST` or `BACKFILL` action.

Reason: this preserves one atomic receiver invocation and existing restore,
capacity, catalog, and lock controls while distinguishing normal daily advance
from genuine historical recovery. Risk: a mixed invocation is labelled by its
historical-repair purpose even though it also captures latest. Compensating
controls: `backfill_dates` exposes the exact older set, the receiver always
processes latest first, and success requires terminal `UP_TO_DATE` for latest,
inventory, diagnostics, control, and macro. Revised acceptance: latest-only
must record `BACKUP-LATEST`; mixed or historical-only may record `BACKFILL` only
with exact older `backfill_dates` and full post-verification.

The merged validator does **not** yet prove the broader fail-closed statement
that appeared in the first version of this proposed entry. In particular, a
source listing with no completed observation and empty component identities can
reach `backup-latest`, and syntactically valid future dates are not compared
with the source preflight time. These are active A3 blockers. Before any receiver
or task transition, a separate focused code PR must reject absent latest
identity, zero completed observations, empty or malformed component identities,
and future retained/latest/diagnostic dates before any receiver transfer call.

### Corrected code and exact-merge verification

PR #545, `Fix scheduled backup classification`, was squash-merged at
`2026-08-29T01:05:49Z` as
`9643b2e22a342ef106025377f02b0179501db1ca`. Required
`bot-feedback-gate`, payload-builder pytest, and Sourcery review passed on exact
head `49588081161a7d7caee1a831d4fd7f435c139a23`; all review threads were
dispositioned and resolved. The final Gemini rerun failed only with external
`503 UNAVAILABLE`; Gemini is advisory and its preceding exact-head review had
reported the implementation ready. The post-merge `sync-matrix` bookkeeping
check is also advisory and does not authorize runtime change.

Exact-head and exact-merge commands and results:

- `python -m pytest tests/test_laptop_backup_scheduled.py tests/test_laptop_pull_backup.py tests/test_pi_backup_foundation.py tests/test_laptop_backup_task_installer.py -q`: `132 passed, 1 skipped` on PR head and again on detached merge;
- `python -m pytest tests/ -q`: `1026 passed, 11 skipped` on exact PR head;
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\test_laptop_backup_task_installer.ps1`: exit zero on PR head and detached merge;
- `git diff --check`, Python compile, clean detached merge status: pass;
- `git diff --exit-code 49588081161a7d7caee1a831d4fd7f435c139a23 9643b2e22a342ef106025377f02b0179501db1ca -- install_laptop_backup_task.ps1 laptop_backup_scheduled.py tests/test_laptop_backup_scheduled.py`: pass, proving identical corrected file content after squash merge.

No real backup target was used by tests. Test backup state was confined to
pytest temporary directories.

### Preserved production and laptop state

At `2026-08-29T11:07:11+10:00`, the installed Windows task remained enabled and
`Ready`, `LastTaskResult=0`, and its live XML remained byte-identical to the
accepted v1.4 XML SHA-256
`aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`.
The installed receiver remained clean at
`f214e3249c7968d574e3449edb14792904e1cc1f`. The real backup catalog remained
unchanged at SHA-256
`acb15773fe069c863a0d00daea368f45c838c570b7ca32f1875b7f813470ce8d`;
no receiver lock or partial artifact existed; 143.59 GiB remained free.

Catalog sequence receipts required by the preceding schema correction are:

| Sequence | Kind | Exact receipt path | Bytes | SHA-256 |
|---:|---|---|---:|---|
| 329 | observation | `C:\code\backups\AR-local-pi5\observations\2026-08-29\544a35bd7648590f42ae0c895aafb289ab243612874952c8b28bf42e5f6fdf56\receipt.json` | 3392 | `fef41f36eb73568fd4ad932a5dcfc054a0e66e2303193241e6e4281358d1163f` |
| 330 | control | `C:\code\backups\AR-local-pi5\control\20260828T191210Z-7f2e5999a02216eb\receipt.json` | 2482 | `3f3b1ec27a08cdebaeb3de3d3fa83ec833cd0e0dd29431c174fba923df3d9e11` |
| 331 | macro | `C:\code\backups\AR-local-pi5\macro\f7de21b246b60e20af693c5a5bedb34b9896f08ec9466f7e0efbb59134dffd4c\receipt.json` | 2223 | `f07fd2fc63e88320a67a1f891fdb7302e14ed2076da1716e0c663b761ac63927` |

The installed receiver, task, catalog, receipts, archives, completed evidence,
Pi production data, and public payload were not changed by this slice.

### Pi power recovery and evidence boundary

The Pi was physically powered off. The original approximately 10:42 through
11:07 Australia/Hobart reachability output was not written to a create-once
artifact. That is an immutable evidence deficiency: this entry does not
reconstruct the outage, assign a reboot cause beyond the operator's statement,
or use the undurable output as an acceptance fact.

After the operator restored power, two recovery probes were preserved as
`BLOCKED`: LAN SSH timed out during banner exchange, then Tailscale SSH required
an interactive additional check. Their result records are:

- `C:\code\backups\AR-local-pi5\evidence\PI-POWER-RECOVERY-20260829\20260829T174808+1000\recovery-result.json`, 1,072 bytes, SHA-256 `7a8ae22fa3f7c2e255f95279bf73011746d36d9428cf4985b9df7cff6f37802a`;
- `C:\code\backups\AR-local-pi5\evidence\PI-POWER-RECOVERY-20260829\20260829T174909+1000\recovery-result.json`, 1,098 bytes, SHA-256 `4562e01da342f36dd135e9be1b7e8fafb06b7257d454827652cfd8506c93c14b`.

The terminal read-only recovery record is
`C:\code\backups\AR-local-pi5\evidence\PI-POWER-RECOVERY-20260829\20260829T175037+1000\recovery-result.json`,
1,616 bytes, SHA-256
`28519a5b3da79720f9e981c30e793031a5ed9faa69c5303f1c914e817e4a8a85`.
Its bound `reachability.txt` is 223 bytes, SHA-256
`06ba9d0c62f647ed3f9749415702240da5016df6cee6213387e29851b6dcadcd`;
its `pi-health.txt` is 1,110 bytes, SHA-256
`4efb9d984e357c74d64f8c369c7a64237de33875b4c45cd6cc59be05c38484c9`.
Strict known-host SSH passed, production was clean at protected `9302890`, the
ingest service was inactive, the lock absent, the timer enabled and active for
01:00, the dashboard healthy for 2026-08-29, and storage/memory healthy. This
proves recovery only; every later action still requires a fresh preflight.

### Mandatory next resume point

Resume this entry at A3; do not start A4. Merge this corrected documentation
entry only after exact-head checks and all substantive review threads pass.
Then create one fresh, focused code PR from the new `origin/main` to implement
the source-identity and future-date blockers above. Its tests must use isolated
temporary backup state and must prove no receiver call occurs for every rejected
input. Do not point a test at the real backup target or change the installed
task, receiver, catalog, Pi, or publication.

After that code PR passes exact-head tests, review, thread closure, guarded
merge, and a clean detached exact-merge proof, append another decision entry.
Only that later entry may authorize a controlled Windows task transition. The
transition must not deploy or modify Pi production and must retain an immediate
rollback to the currently accepted task XML and receiver `f214e324`. The first
corrected task proof must be natural and must not be manually triggered.

D-006 remains overriding. For 2026-08-30, begin the full preflight at 00:25 and
the final gate no later than 00:55 so it completes before 01:00. The 00:30
freeze continues through terminal natural-ingest validation. If the Pi is not
healthy well before the freeze, report `BLOCKED` immediately; do not improvise
a deployment, force an ingest, or alter publication. Preserve the last verified
rolling payload and all local backup evidence.

## Entry `HANDOFF-20260829T183043+1000-A3-SOURCE-IDENTITY-MERGED`

### Required control record

| Field | Value |
|---|---|
| Created at, Australia/Hobart | `2026-08-29T18:30:43+10:00` |
| Created at, UTC | `2026-08-29T08:30:43Z` |
| Previous handoff entry | `HANDOFF-20260829T110711+1000-A3-CLASSIFIER-MERGED` |
| Previous handoff merge | `9ccd46f4c62c36431298bc5a55f9d301b4c2f4ce` |
| Previous complete handoff raw SHA-256 | `9678672cf2a63673459d0a2f825abeb8e847a019cd307c98bdcdfc7b156b9a8f` |
| Plan | `ARL-OPS-001` v1.4 |
| Plan document-containing commit | `14dd066099bba393cccf61a280243e43162eedc9` |
| Controlled plan SHA-256 | `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Normalized plan SHA-256 | `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4` |
| Source-identity code merge | `46e2aeba55fe3f97ace4143ba08fc00e36225dc1` |
| Source-identity PR head | `868f118fa2e463ec78c32bef1739cf4f1eb9bcf2` |
| Protected Pi SHA | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Operator | Codex unattended for `jkoka` |
| Overall result | `BLOCKED` |
| Completed component | `A3 source/preflight identity guard and exact-merge proof: PASS` |
| Current phase | `A3 transition-harness code slice authorized; real transition BLOCKED` |
| A4 and Phases B-G | `BLOCKED` |
| Deviations | none |
| Deviation authorization | none |

The overall result remains `BLOCKED`, rather than `PASS`, because the accepted
Windows task and receiver have not transitioned to the corrected merge and no
natural 05:00 run has proved the corrected task. This entry authorizes only the
bounded A3 transition-harness code slice described below; it does not authorize
the real task transition. It also does not authorize Pi deployment, manual or
forced ingest, a manual task trigger, publication manipulation, A4, or any
Phase B-G implementation.

### Source-identity guard result

PR #547, `Fail closed on invalid laptop backup source identity`, was
squash-merged at `2026-08-29T08:27:44Z` as
`46e2aeba55fe3f97ace4143ba08fc00e36225dc1`. The implementation rejects a
source listing before any `backup-latest` or `backfill` transfer unless all of
the following are true:

- the source reports success with a fresh, offset-aware Hobart timestamp;
- the independent laptop clock is outside the 00:30-03:30 Hobart quiet window;
- Pi production is clean at the exact protected SHA;
- the daily service is inactive, or failed with a canonical failure record
  bound below the reported state root;
- the daily timer is both enabled and active, the ingest lock is absent, and
  the dashboard is healthy;
- control and macro identities contain real string SHA-256 revisions and
  positive source-byte counts;
- at least one completed observation exists and the completed-date list,
  retained-run list, latest observation, diagnostic identities, completion
  marker, and observation pointer reconcile exactly; and
- retained, latest, diagnostic, and terminal-failure dates are valid calendar
  dates and are not future-dated.

The Pi source helper now independently requires and reports
`daily_timer_active=active`. Tests cover unsuccessful and missing preflights,
naive/wrong/stale/future timestamps, both quiet-window clock-skew edges, dirty
or wrong production, active/unauthorized failed services, disabled/inactive
timers, lock and dashboard contradictions, wrong-root and traversal failure
records, empty/malformed component identities, numeric fake digests, zero
completed observations, invalid/unordered/duplicate/future dates, inconsistent
completed/latest/diagnostic populations, and incomplete latest hashes. Every
rejected case proves the receiver call list remains exactly `preflight` and the
immutable outcome is `BLOCKED/PREFLIGHT_FAILED`.

### Exact-head, GitHub, and exact-merge evidence

PR head `868f118fa2e463ec78c32bef1739cf4f1eb9bcf2` was based directly on prior
authority merge `9ccd46f4c62c36431298bc5a55f9d301b4c2f4ce`. Required
`bot-feedback-gate`, path-filtered payload-builder pytest, Codex review, and
Sourcery review passed; Codex and Sourcery reported no actionable findings and
the thread gate reported zero unresolved threads. Gemini is advisory and both
its initial run and single failed-job rerun ended only with external
`503 UNAVAILABLE`; this was not relabelled as a successful Gemini review and no
further retry was made. The guarded squash wrapper performed the merge; its
nonzero terminal status arose only when post-merge local branch cleanup found
the user's existing `main` worktree.

The clean detached exact-merge checkout is
`C:\code\backups\AR-local-a3-source-identity-proof-46e2aeb`. It remained clean
at exact merge `46e2aeba55fe3f97ace4143ba08fc00e36225dc1` after these commands:

- `python -m py_compile laptop_backup_scheduled.py pi_laptop_backup_source.py laptop_pull_backup.py`: PASS;
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\test_laptop_backup_task_installer.ps1`: PASS;
- `python -m pytest tests/test_laptop_backup_scheduled.py tests/test_laptop_pull_backup.py tests/test_pi_backup_foundation.py tests/test_laptop_backup_task_installer.py tests/test_pi_laptop_backup_source_preflight.py -q`: `206 passed, 1 skipped`;
- `python -m pytest tests -q`: `1100 passed, 11 skipped`, with four known
  openpyxl no-default-style warnings;
- `git diff --check`: PASS; and
- `npm run verify:pi`: PASS against `http://100.78.28.10/`.

No test used the real backup target. All backup-state mutations were confined
to pytest temporary directories. Independent safety, test, and 2IC reviews
found no remaining actionable defect. The append-only execution record is
`C:\code\backups\AR-local-pi5\evidence\A3-SOURCE-IDENTITY-GUARD-20260829\20260829T183043+1000\execution-record.json`,
3,402 bytes, SHA-256
`693a838a26569c75cd34ebc63e820ff609f481ac50963f4fcc1d8a7d2985fd64`.

### Preserved runtime and D-006 state

At `2026-08-29T18:23:38+10:00`, after the operator-restored power and a
temporary LAN banner delay, read-only LAN SSH again passed. Pi production was
clean at protected `9302890fcc752cbf90da97d597e972c157d913e3`, the daily
service was inactive, the lock was absent, and the timer was enabled and active
for `2026-08-30T01:00:00+10:00`. The dashboard API returned HTTP 200 for
2026-08-29 with 3,012 products, 17,050 rates, 119 holder attempts, and 17
attributable failures. `npm run verify:pi` passed. This is a point-in-time
check; the mandatory 00:25 and 00:55 preflights remain required.

The installed task and receiver remain unchanged and accepted at receiver
`f214e3249c7968d574e3449edb14792904e1cc1f` and task XML SHA-256
`aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`.
The live exported XML matched the accepted XML; the task was enabled and
`Ready`, `LastTaskResult=0`, with its next run at
`2026-08-30T05:00:00+10:00`. The receiver was clean at the exact old SHA, the
catalog remained SHA-256
`acb15773fe069c863a0d00daea368f45c838c570b7ca32f1875b7f813470ce8d`,
no receiver lock or partial existed, and 146.05 GiB was free.
No task trigger, backup, restore, catalog mutation, Pi deployment, ingest,
publication change, or A4 action occurred during the source-identity slice.

### Controlled A3 transition-harness authorization

The direct task-transition draft was independently rejected before execution.
No foreground backup, catalog mutation, pointer advancement, task replacement,
or rollback was performed. The accepted task therefore remains safely bound to
receiver `f214e3249c7968d574e3449edb14792904e1cc1f`.

The reason is concrete: any exact post-harness candidate must first create
candidate-bound observation, control, and macro receipts because the current
receipts correctly remain bound to the accepted old candidate. A foreground
`BACKUP-LATEST` can partially append or advance pointers before a later failure.
The rejected command sequence did not authenticate every preserved artifact
before rollback, structurally bind one coherent execution record, assert every
post-install task/catalog/runtime gate, or make the hard daylight deadline
fail closed. Executing it would permit a false `PASS` or leave the old task
with mixed-candidate pointers.

After this documentation-only entry passes exact-head review, thread, and CI
gates and is merged, exactly one additional code-only A3 safety slice is
authorized. It must add a self-contained, checked-in Windows transition harness
and deterministic tests. It must not use the real backup target in tests, alter
the installed task, run a foreground real backup, deploy or modify the Pi,
trigger an ingest, trigger the scheduled task, manipulate publication, begin
A4, or begin any Phase B-G work.

The harness must be additive and must:

1. bind exact immutable inputs: plan `ARL-OPS-001` v1.4, plan commit
   `14dd066099bba393cccf61a280243e43162eedc9`, controlled plan SHA-256
   `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713`,
   source-identity base `46e2aeba55fe3f97ace4143ba08fc00e36225dc1`, protected Pi SHA
   `9302890fcc752cbf90da97d597e972c157d913e3`, operator
   `yanniedog\\jkoka`/`jkoka`, task `AR-local laptop backup`, target
   `C:\code\backups\AR-local-pi5`, recovery image
   `C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21`,
   and old receiver `C:\code\backups\AR-local-pi5-receiver-f214e32`. The
   harness candidate SHA, new receiver path, expected latest observation date,
   containing handoff merge, and complete handoff raw SHA-256 are intentionally
   not guessed here: a later append-only entry must bind them to the exact
   merged harness candidate before any real transition;
2. require an elevated `yanniedog\\jkoka` process and make every native
   command exit code fail closed;
3. verify fresh merged authority bytes and hashes, a clean exact candidate
   checkout, the accepted old task XML SHA-256
   `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`,
   the complete old task definition, old receiver cleanliness, task
   enabled/`Ready`, and `LastTaskResult=0`;
4. stop before mutation if the task is running, a receiver/helper/overlap exists,
   a lock or partial exists, capacity is below 50 GiB, the Pi is not clean at
   the protected SHA, the daily service is not safely inactive, the timer is not
   enabled and active for the exact next 01:00, the ingest lock exists, or the
   dashboard is unhealthy;
5. acquire the active transition as an atomic create-new ownership lock so two
   unattended contenders cannot both pass. A new invocation must refuse an
   unterminated lock unless it uses an explicit authenticated
   `resume/recover-existing-transition-id` mode. That mode must reuse the exact
   evidence root, verify lock ownership and all preserved evidence hashes, run
   no new foreground backup or installer action, perform only remaining
   recovery/finalization, and atomically create the single terminal result. A
   terminal lock must bind the terminal-result path and SHA-256 before it is
   closed; it must never be silently overwritten;
6. create a unique evidence directory and authenticate the preserved old XML,
   all old current pointers, the copied catalog prefix, live task state, source
   identities, and exact command list before the first backup mutation;
7. immediately before the first foreground mutation, disable the accepted old
   task and prove it is disabled and not running. This is the first recoverable
   task mutation and prevents a reboot/startup trigger from launching the old
   receiver against mixed or new candidate-bearing pointers while the
   transition is active. Any disable failure or ambiguous/partial state must
   stop before backup and enter authenticated recovery;
8. start only early enough to complete before the hard 22:00
   Australia/Hobart deadline, impose a bounded runtime, recheck the deadline
   immediately before foreground mutation and task replacement, and stop or
   recover when the remaining safety window is insufficient;
9. invoke the checked-in foreground backup once without manually triggering the
   task, require structurally parsed `PASS/BACKUP-LATEST/UP_TO_DATE` for the
   exact latest observation date bound by the later transition entry, and
   resolve the create-once execution record canonically beneath
   `catalog/scheduled-runs`;
10. verify one coherent execution record with exact plan, candidate, protected
   SHA, operator, action, result, before/after state, no missing completed dates,
   no stale diagnostics, and exact observation/control/macro receipts and
   source identities; validate receipt hashes, archive and SQLite restore proof,
   catalog prefix and append-only chain, and allow only expected new
   candidate-bound observation/control/macro generations and scheduled records;
11. treat any `BACKFILL`, diagnostic generation, different source date,
    `NO_BACKUP_DATA_WRITE` at the first candidate-bound transfer, `FAIL`,
    `BLOCKED`, malformed output, unexpected append, or identity mismatch as a
    non-`PASS` terminal outcome;
12. invoke the existing installer only after the foreground gate passes; require
    its internal no-write proof, then independently assert the complete installed
    action, arguments, working directory, principal, enabled/`Ready` state,
    `LastTaskResult=0`, 05:00 trigger, startup-plus-five-minute trigger,
    `IgnoreNew`, three 30-minute retries, six-hour limit, and
    start-when-available;
13. run a standalone structural `--check-only` and require
    `PASS/NO_BACKUP_DATA_WRITE`, then revalidate scheduled records, receipts,
    pointers, catalog chain, locks, partials, helpers, overlap, capacity, Pi
    identity, dashboard, and exact next 01:00 timer;
14. authorize recovery after any mutation begins, starting with attempted task
    disable and not merely after task replacement. On failure, authenticate
    saved XML and pointer bytes against pre-mutation hashes before any restore;
    restore the exact old task XML and enabled/`Ready` state after any attempted
    disable or installed-task mutation; restore only candidate-bearing
    component pointers such as `latest-verified`, `latest-control`, and
    `latest-macro` atomically; and never roll back `latest-scheduled`, which must
    continue to identify the newest preserved hash-bound execution record;
15. preserve every appended generation, receipt, restore record, and scheduled
    record. Never truncate, rewrite, or delete immutable evidence. Recovery must
    prove the old catalog remains an exact prefix, old pointers/receipts validate,
    the old task is exact and healthy, no residue exists, and Pi/dashboard/timer
    health passes; and
16. create exactly one immutable terminal result containing plan and code
    identity, operator, timestamps, exact commands, source identities, old/new
    task XML hashes, old/new pointer and catalog hashes, execution and receipt
    paths/hashes, restore results, capacity, Pi/dashboard/timer results,
    deviations and authorization, and one of `PASS`, `FAIL`, `BLOCKED`, or
    `ROLLED_BACK`.

Required deterministic tests must inject failure or interruption:

- before mutation and after each observation, control, macro, pointer, scheduled
  record, installer, task-enable, and standalone-check boundary;
- with stale/tampered authority, XML, pointer, receipt, catalog prefix, execution
  record, output, source identity, and restore evidence;
- for active/running/disabled/drifted tasks, nonzero last result, helper/lock/
  partial/overlap residue, insufficient disk, wrong Pi SHA, dirty Pi, active
  ingest, wrong timer state/time, dashboard failure, and quiet/deadline edges;
- for concatenated or conflicting JSON objects, path escape, symlink/reparse
  escape, wrong candidate/plan/operator/date, unexpected `BACKFILL` or
  diagnostics, and invalid appended generation kinds/counts;
- for recovery both before and after task replacement, including recovery
  interruption, corrupt saved artifacts, atomic pointer restore, preserved
  append-only records, exact old task restoration, and create-once terminal
  evidence;
- for hard kill and authenticated restart after active-lock creation and at
  every recovery boundary, proving the same transition ID and evidence root are
  reused and exactly one terminal result is created;
- with two concurrent contenders, proving atomic ownership allows exactly one
  process to reach mutation and closes the lock with the terminal path and hash;
- for pre- and post-installer recovery, proving only candidate-bearing component
  pointers roll back while `latest-scheduled` remains bound to the newest
  preserved execution record; and
- with call-count and side-effect assertions proving every invalid preflight
  invokes backup, installer, task mutation, and pointer mutation zero times;
  every rejected foreground result invokes installer/task replacement zero
  times; success invokes foreground backup exactly once with no retry; and only
  the explicitly authorized pointer/catalog writes occur; and
- for old-task disable failure and partial disable, crash immediately after
  disable, reboot/startup-trigger attempts while the transition lock is active
  (which must invoke backup zero times), and authenticated exact old-task XML
  restoration plus re-enable/`Ready` proof on every non-`PASS` path after task
  disable or replacement was attempted.

Acceptance for this code-only slice requires exact-head focused and full tests,
PowerShell parser and installer tests, clean-tree and diff checks, independent
safety/test/2IC review with every substantive finding resolved, normal CI and
thread gates, guarded merge, and a clean detached exact-merge rerun. Only a
later append-only handoff entry may authorize the real backup/task transition.
Do not manually trigger the corrected task. After a later handoff authorizes
and records the real transition, its first acceptance proof must be the next
natural 05:00 execution after a fully validated natural 01:00 ingest. A3 is
not terminally complete until that run contains at least one valid
`BACKUP-LATEST` for the immediately preceding ingest date, any later
`NO_BACKUP_DATA_WRITE` is correctly identity-bound, all intervening records and
receipts pass, Pi identities match, restoration checks pass where required, no
overlap or residue exists, and at least 50 GiB remains free.

D-006 overrides the transition. At 00:25 run the complete read-only preflight;
finish it before the 00:30 freeze. Begin the final read-only gate at 00:55 so it
finishes before 01:00. From 00:30 through terminal ingest validation, prohibit
all deployment, canary, manual ingest, force, restart, task change/trigger,
package, backup, restore, storage-maintenance, and publication actions. Observe
the natural ingest once, validate all raw, completion, contract, ledger,
pointer, SQLite, provider/product, dashboard, dated-v1, rolling-v1,
dates-index, public-asset, and independent-v2 evidence, then wait for the
natural 05:00 task. Preserve the previous verified rolling payload on any
failure.

A4 and Phases B-G remain `BLOCKED`. Only a later append-only entry recording
the controlled transition and natural 05:00 result may advance A3 or authorize
the next phase.

## Entry `HANDOFF-20260829T231200+1000-A3-TRANSITION-AUTHORIZED`

### Control record and current outcome

| Field | Value |
|---|---|
| Created at, Australia/Hobart | `2026-08-29T23:12:00+10:00` |
| Previous handoff entry | `HANDOFF-20260829T183043+1000-A3-SOURCE-IDENTITY-MERGED` |
| Previous handoff-containing merge | `7e9651cec6bf5facf07c98dedd65913775f95911` |
| Previous complete handoff Git-blob SHA-256 | `c8608be633bcfb9db4f6e339abcaf4bee6478c1e440eedc320416a6ee0875b6b` |
| Plan | `ARL-OPS-001` v1.4 |
| Plan document-containing commit | `14dd066099bba393cccf61a280243e43162eedc9` |
| Controlled plan SHA-256 | `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Normalized plan Git-blob SHA-256 | `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4` |
| Final eligible A3 candidate | `88557b96d4a240dca640285bcb3457751b381667` |
| Candidate receiver | `C:\code\backups\AR-local-pi5-receiver-88557b9` |
| Accepted old receiver | `C:\code\backups\AR-local-pi5-receiver-f214e32` at `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Protected Pi SHA | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Operator | Codex unattended for `jkoka`; normal Windows UAC consent is the only permitted human boundary |
| Current result | `BLOCKED` pending the natural 2026-08-30 ingest, old-task continuity proof, real transition, and first natural new-task proof |
| A4 | `BLOCKED`; after A3 terminal `PASS`, begin A4 planning automatically in a separate controlled slice |
| Deployment and Phases B-G | `BLOCKED` |

This entry replaces the unmerged and closed PR #552 draft. That draft is not
authority. It named superseded candidate `089238c7...`, claimed review closure
before late findings arrived, and did not contain self-contained dated natural
gates. It was closed without merge or runtime use.

The final harness train is now code-complete through PRs #549-#551, #553 and
#554. PR #553 merged as `e4bcb071a1266b8cd5cc08437b19ac5480625ecd`
after fixing complete predecessor authentication, unique legacy-anchor recovery,
dangling-link mutex rejection, and live-pointer digest binding. PR #554 then
merged as the final eligible candidate above after a read-only real-state check
proved that the accepted old task's latest immutable result is truthfully
`PASS/BACKFILL`. The candidate now accepts that action only during explicit
old-candidate pre-transition validation, with complete immutable-envelope,
expected missing-date, receipt, source, and current after-state verification.
New-candidate, third-candidate, failed, flagless, malformed, and all
post-transition `BACKFILL` cases remain rejected.

Exact-merge evidence for PR #554 is
`C:\code\backups\AR-local-pi5\evidence\A3-LEGACY-BACKFILL-COMPAT-20260829\20260829T230900+1000\execution-record.json`,
2,532 bytes, SHA-256
`6e720d6ce5b31608937b6e35700f8aecdb2bd5acf96f1839b6fb78d85bbfdb13`.
The clean detached exact-merge receiver passed the focused suite with 116 tests
and the full suite with 1,293 passed and 11 skipped. The real current legacy
record is
`catalog/scheduled-runs/20260828T191317Z-5b3033fc4db54962bb2fd53b9af5c1aa.json`,
SHA-256 `2753be7b5d87af3d1ab5a581be83f1668a9695f2b5cce58822d675a920e42764`;
its full envelope and `PASS/BACKFILL` detail authenticated read-only. Three
independent reviews passed. No task, backup catalog, Pi, ingest, deployment, or
publication mutation occurred.

### Append-only deviation decisions

`DEV-A3-HARNESS-001` records that PR #549 merged before its final late review
closeout. `DEV-A3-HARNESS-002` records that PR #551 merged before three late
Codex findings appeared. Neither was an authorised bypass. Runtime remained
prohibited; PRs #550, #551, #553, and #554 corrected every concrete finding;
original review threads were answered and resolved; exact-head and exact-merge
tests were rerun; and no affected code was installed or used against the real
target. Revised acceptance is the exact final candidate above plus every gate
below. Gemini's latest exact-head workflows failed externally with 503 and
remain advisory, not `PASS`. These decisions waive no runtime, evidence, D-006,
or UAC control.

### Machine-readable transition authority

This authority becomes effective only after this entry is squash-merged, the
document-containing merge is resolved by the exact algorithm below, and that
merge is still the current `origin/main`. Any later `main` advance, missed gate,
identity difference, or date difference makes it `BLOCKED` and requires a new
append-only entry.

<!-- ARL_A3_TRANSITION_AUTHORIZATION_BEGIN -->
{"accepted_old_xml_sha256":"aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2","candidate_code_sha":"88557b96d4a240dca640285bcb3457751b381667","deadline":"2026-08-30T22:00:00+10:00","expected_observation_date":"2026-08-30","host":"ar-local-pi5-lan","new_receiver":"C:\\code\\backups\\AR-local-pi5-receiver-88557b9","old_candidate_code_sha":"f214e3249c7968d574e3449edb14792904e1cc1f","old_receiver":"C:\\code\\backups\\AR-local-pi5-receiver-f214e32","operator":"jkoka","plan_document_id":"ARL-OPS-001","plan_git_commit":"14dd066099bba393cccf61a280243e43162eedc9","plan_sha256":"78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713","plan_version":"1.4","principal":"yanniedog\\jkoka","protected_code_sha":"9302890fcc752cbf90da97d597e972c157d913e3","recovery_image":"C:\\code\\AR-local-pi-image-2026-05-21\\AR-local-pi-image-2026-05-21","schema_version":1,"source_identity_base":"46e2aeba55fe3f97ace4143ba08fc00e36225dc1","target":"C:\\code\\backups\\AR-local-pi5","task_name":"AR-local laptop backup"}
<!-- ARL_A3_TRANSITION_AUTHORIZATION_END -->

### Exact 2026-08-30 00:25 gate

Run this exact block at 00:25 Australia/Hobart. It creates the sole active
evidence directory and proves the controlled document, current authority, old
task receiver, Pi identity, lock, timer, resources, dashboard, and GitHub
connectivity. It writes only laptop evidence.

```powershell
$ErrorActionPreference = 'Stop'
$sourceDate = '2026-08-30'
$expectedPi = '9302890fcc752cbf90da97d597e972c157d913e3'
$candidate = '88557b96d4a240dca640285bcb3457751b381667'
$receiver = 'C:\code\backups\AR-local-pi5-receiver-88557b9'
$oldReceiver = 'C:\code\backups\AR-local-pi5-receiver-f214e32'
$authorityRepo = 'C:\code\backups\AR-local-a3-transition-authority'
$target = 'C:\code\backups\AR-local-pi5'
$marker = 'HANDOFF-20260829T231200+1000-A3-TRANSITION-AUTHORIZED'
$evidenceParent = Join-Path $target 'evidence\NATURAL-20260830'
$activePointer = Join-Path $evidenceParent 'ACTIVE_EVIDENCE_PATH.txt'
if (-not (Test-Path -LiteralPath (Join-Path $authorityRepo '.git'))) {
  git clone --branch main --single-branch https://github.com/yanniedog/AR-local.git $authorityRepo
  if ($LASTEXITCODE -ne 0) { throw "Authority clone failed: git exit $LASTEXITCODE" }
}
git -C $authorityRepo fetch origin main --prune
if ($LASTEXITCODE -ne 0) { throw "Authority fetch failed: git exit $LASTEXITCODE" }
if (@(git -C $authorityRepo status --porcelain=v1).Count -ne 0) { throw 'Authority checkout is dirty before resolution.' }
$authorityCommit = (& python -c 'import subprocess,sys; r,m,p=sys.argv[1:]; cs=subprocess.check_output(["git","-C",r,"rev-list","--reverse","--first-parent","origin/main","--",p],text=True).split(); hits=[c for c in cs if m.encode() in subprocess.check_output(["git","-C",r,"show",f"{c}:{p}"])]; print(hits[0] if hits else "")' $authorityRepo $marker 'docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md').Trim()
if ($LASTEXITCODE -ne 0 -or $authorityCommit -notmatch '^[0-9a-f]{40}$') { throw 'Document-containing authority merge was not uniquely resolved.' }
if ((git -C $authorityRepo rev-parse origin/main).Trim() -ne $authorityCommit) { throw 'origin/main advanced beyond this transition authority.' }
git -C $authorityRepo checkout --detach $authorityCommit
if (@(git -C $authorityRepo status --porcelain=v1).Count -ne 0 -or
    @(git -C $receiver status --porcelain=v1).Count -ne 0 -or
    @(git -C $oldReceiver status --porcelain=v1).Count -ne 0) { throw 'A controlled checkout is dirty.' }
if ((git -C $receiver rev-parse HEAD).Trim() -ne $candidate -or
    (git -C $oldReceiver rev-parse HEAD).Trim() -ne 'f214e3249c7968d574e3449edb14792904e1cc1f') { throw 'Receiver SHA mismatch.' }
Push-Location $receiver
try {
  $plan = & python -c 'import json,laptop_pull_backup as r; print(json.dumps(r.verify_plan_document(),sort_keys=True))'
  if ($LASTEXITCODE -ne 0) { throw 'Controlled plan verification failed.' }
} finally { Pop-Location }
$planObject = $plan | ConvertFrom-Json
if ($planObject.plan_document_id -ne 'ARL-OPS-001' -or $planObject.plan_version -ne '1.4' -or
    $planObject.plan_git_commit -ne '14dd066099bba393cccf61a280243e43162eedc9' -or
    $planObject.plan_sha256 -ne '78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713' -or
    $planObject.plan_normalized_raw_sha256 -ne 'c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4') { throw 'Plan identity mismatch.' }
$handoffSha = (& python -c 'import hashlib,subprocess,sys; print(hashlib.sha256(subprocess.check_output(["git","-C",sys.argv[1],"show",sys.argv[2]+":docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md"])).hexdigest())' $authorityRepo $authorityCommit).Trim()
New-Item -ItemType Directory -Path $evidenceParent -Force | Out-Null
if (Test-Path -LiteralPath $activePointer) { throw 'An active 2026-08-30 evidence run already exists.' }
$runId = [datetimeoffset]::Now.ToString('yyyyMMddTHHmmsszzz').Replace(':','')
$evidenceRoot = Join-Path $evidenceParent $runId
New-Item -ItemType Directory -Path $evidenceRoot | Out-Null
[IO.File]::WriteAllText($activePointer,$evidenceRoot,[Text.UTF8Encoding]::new($false))
[ordered]@{plan=$planObject;authority_commit=$authorityCommit;handoff_sha256=$handoffSha;candidate=$candidate;source_date=$sourceDate;run_id=$runId;evidence_root=$evidenceRoot;observed_at=[datetimeoffset]::Now.ToString('o')} |
  ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $evidenceRoot 'authority.json')
$remote0025 = @'
set -eu
echo "observed_at=$(date --iso-8601=seconds)"
echo "head=$(git -C /srv/ar-local/AR-local rev-parse HEAD)"
if test -z "$(git -C /srv/ar-local/AR-local status --porcelain=v1)"; then echo checkout_clean=true; else echo checkout_clean=false; fi
echo "timer_enabled=$(systemctl is-enabled ar-local-daily.timer || true)"
echo "timer_active=$(systemctl is-active ar-local-daily.timer || true)"
echo "timer_next=$(systemctl show ar-local-daily.timer -p NextElapseUSecRealtime --value)"
echo "timer_last=$(systemctl show ar-local-daily.timer -p LastTriggerUSec --value)"
echo "service_active=$(systemctl is-active ar-local-daily.service || true)"
echo "service_invocation=$(systemctl show ar-local-daily.service -p InvocationID --value)"
echo "service_restarts=$(systemctl show ar-local-daily.service -p NRestarts --value)"
if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi
if pgrep -f '[p]i_daily_sync.py|[c]dr_daily.py' >/dev/null; then echo competing_process=PRESENT; exit 43; else echo competing_process=ABSENT; fi
echo "disk_available_bytes=$(df -B1 --output=avail /srv/ar-local/data | tail -1 | tr -d ' ')"
echo "memory_available_bytes=$(free -b | awk '/^Mem:/ {print $7}')"
echo "swap_free_bytes=$(free -b | awk '/^Swap:/ {print $4}')"
if journalctl -k --since '24 hours ago' --no-pager | grep -Eiq 'oom|out of memory|killed process'; then echo oom_recent=PRESENT; else echo oom_recent=ABSENT; fi
curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest | python3 -c "import json,sys; v=json.load(sys.stdin); b=v.get('banks_counts') or {}; assert v.get('run_date')=='2026-08-29'; assert int(b.get('products',0))>0; assert int(b.get('rates',0))>0"
echo dashboard=HEALTHY
echo "github_http=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' https://api.github.com/)"
'@
$preflight = ssh -o BatchMode=yes -o ConnectTimeout=10 ar-local-pi5-lan $remote0025
$preflight | Set-Content -LiteralPath (Join-Path $evidenceRoot '0025-preflight.txt')
if ($LASTEXITCODE -ne 0) { throw "00:25 Pi preflight failed: ssh exit $LASTEXITCODE" }
function Convert-GateLines([string[]]$lines) {
  $values=[ordered]@{}
  foreach($line in $lines){$pair=$line -split '=',2;if($pair.Count -eq 2){$values[$pair[0].Trim()]=$pair[1].Trim()}}
  return [pscustomobject]$values
}
$gate0025=Convert-GateLines $preflight
$observed0025=[datetimeoffset]::Parse($gate0025.observed_at)
if($observed0025 -lt [datetimeoffset]'2026-08-30T00:20:00+10:00' -or $observed0025 -ge [datetimeoffset]'2026-08-30T00:30:00+10:00' -or
   $gate0025.head -ne $expectedPi -or $gate0025.checkout_clean -ne 'true' -or
   $gate0025.timer_enabled -ne 'enabled' -or $gate0025.timer_active -ne 'active' -or
   $gate0025.timer_next -cne 'Sun 2026-08-30 01:00:00 AEST' -or $gate0025.service_active -ne 'inactive' -or
   [int]$gate0025.service_restarts -ne 0 -or $gate0025.lock -ne 'ABSENT' -or
   $gate0025.competing_process -ne 'ABSENT' -or [int64]$gate0025.disk_available_bytes -lt 10737418240 -or
   [int64]$gate0025.memory_available_bytes -lt 268435456 -or [int64]$gate0025.swap_free_bytes -lt 67108864 -or
   $gate0025.oom_recent -ne 'ABSENT' -or $gate0025.dashboard -ne 'HEALTHY' -or $gate0025.github_http -ne '200') { throw '00:25 fail-closed health gate failed.' }
$gate0025 | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidenceRoot '0025-gate-values.json')
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $evidenceRoot 'authority.json'),(Join-Path $evidenceRoot '0025-preflight.txt') |
  ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidenceRoot '0025-hashes.json')
```

At 00:30 the D-006 freeze begins and continues through terminal ingest
validation. Do not deploy, canary, manually or forcibly ingest, restart, change
or trigger the task, update packages, back up, restore, maintain storage, or
manipulate publication.

### Exact 00:55, natural-ingest, observation, and public-byte gate

Begin this block at 00:55 so the second gate completes before 01:00. It observes
the natural timer exactly once; it never starts, restarts, forces, or reruns it.

```powershell
$ErrorActionPreference = 'Stop'
$expectedPi = '9302890fcc752cbf90da97d597e972c157d913e3'
$candidate = '88557b96d4a240dca640285bcb3457751b381667'
$date = '2026-08-30'
$evidenceParent = 'C:\code\backups\AR-local-pi5\evidence\NATURAL-20260830'
$activePointer = Join-Path $evidenceParent 'ACTIVE_EVIDENCE_PATH.txt'
$parentFull=[IO.Path]::GetFullPath($evidenceParent);$pointerRoot=[IO.Path]::GetFullPath((Get-Content -LiteralPath $activePointer -Raw).Trim());$bound=@()
foreach($dir in @(Get-ChildItem -LiteralPath $parentFull -Directory -ErrorAction Stop)){
 $authorityPath=Join-Path $dir.FullName 'authority.json';if(-not(Test-Path -LiteralPath $authorityPath -PathType Leaf)){continue}
 try{$authority=Get-Content -Raw -LiteralPath $authorityPath|ConvertFrom-Json}catch{continue}
 $root=[IO.Path]::GetFullPath($dir.FullName)
 if($root.StartsWith($parentFull+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -and $authority.evidence_root -ceq $root -and $authority.run_id -ceq $dir.Name -and $authority.source_date -ceq $date -and $authority.candidate -ceq $candidate){$bound+=,[pscustomobject]@{root=$root;authority_path=$authorityPath}}
}
if($bound.Count -ne 1 -or $pointerRoot -cne $bound[0].root){throw 'The active evidence pointer is not uniquely bound to the original 00:25 authority.'}
$evidenceRoot=$bound[0].root;$authorityHash=(Get-FileHash -LiteralPath $bound[0].authority_path -Algorithm SHA256).Hash
$recordedAuthority=@(Get-Content -Raw (Join-Path $evidenceRoot '0025-hashes.json')|ConvertFrom-Json|Where-Object {[IO.Path]::GetFullPath($_.Path) -ceq [IO.Path]::GetFullPath($bound[0].authority_path)})
if($recordedAuthority.Count -ne 1 -or $recordedAuthority[0].Hash -cne $authorityHash){throw 'The 00:25 authority record is not hash-bound.'}
$remote0055 = @'
set -eu
echo "observed_at=$(date --iso-8601=seconds)"
echo "head=$(git -C /srv/ar-local/AR-local rev-parse HEAD)"
if test -z "$(git -C /srv/ar-local/AR-local status --porcelain=v1)"; then echo checkout_clean=true; else echo checkout_clean=false; fi
echo "timer_enabled=$(systemctl is-enabled ar-local-daily.timer || true)"
echo "timer_active=$(systemctl is-active ar-local-daily.timer || true)"
echo "timer_next=$(systemctl show ar-local-daily.timer -p NextElapseUSecRealtime --value)"
echo "timer_last=$(systemctl show ar-local-daily.timer -p LastTriggerUSec --value)"
echo "service_active=$(systemctl is-active ar-local-daily.service || true)"
echo "service_invocation=$(systemctl show ar-local-daily.service -p InvocationID --value)"
echo "service_restarts=$(systemctl show ar-local-daily.service -p NRestarts --value)"
if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi
if pgrep -f '[p]i_daily_sync.py|[c]dr_daily.py' >/dev/null; then echo competing_process=PRESENT; exit 43; else echo competing_process=ABSENT; fi
echo "disk_available_bytes=$(df -B1 --output=avail /srv/ar-local/data | tail -1 | tr -d ' ')"
echo "memory_available_bytes=$(free -b | awk '/^Mem:/ {print $7}')"
echo "swap_free_bytes=$(free -b | awk '/^Swap:/ {print $4}')"
if journalctl -k --since '24 hours ago' --no-pager | grep -Eiq 'oom|out of memory|killed process'; then echo oom_recent=PRESENT; else echo oom_recent=ABSENT; fi
curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest | python3 -c "import json,sys; v=json.load(sys.stdin); b=v.get('banks_counts') or {}; assert v.get('run_date')=='2026-08-29'; assert int(b.get('products',0))>0; assert int(b.get('rates',0))>0"
echo dashboard=HEALTHY
echo "github_http=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' https://api.github.com/)"
'@
$gate = ssh -o BatchMode=yes -o ConnectTimeout=10 ar-local-pi5-lan $remote0055
$gate | Set-Content -LiteralPath (Join-Path $evidenceRoot '0055-immediate-gate.txt')
if ($LASTEXITCODE -ne 0) { throw "00:55 Pi preflight failed: ssh exit $LASTEXITCODE" }
function Convert-GateLines([string[]]$lines) {
  $values=[ordered]@{}
  foreach($line in $lines){$pair=$line -split '=',2;if($pair.Count -eq 2){$values[$pair[0].Trim()]=$pair[1].Trim()}}
  return [pscustomobject]$values
}
$baseline=Get-Content -Raw (Join-Path $evidenceRoot '0025-gate-values.json') | ConvertFrom-Json
$gate0055=Convert-GateLines $gate
$observed0055=[datetimeoffset]::Parse($gate0055.observed_at)
if($observed0055 -lt [datetimeoffset]'2026-08-30T00:55:00+10:00' -or $observed0055 -ge [datetimeoffset]'2026-08-30T01:00:00+10:00' -or
   $gate0055.head -ne $expectedPi -or $gate0055.checkout_clean -ne 'true' -or
   $gate0055.timer_enabled -ne 'enabled' -or $gate0055.timer_active -ne 'active' -or
   $gate0055.timer_next -cne 'Sun 2026-08-30 01:00:00 AEST' -or $gate0055.timer_last -ne $baseline.timer_last -or
   $gate0055.service_active -ne 'inactive' -or $gate0055.service_invocation -ne $baseline.service_invocation -or
   [int]$gate0055.service_restarts -ne 0 -or $gate0055.lock -ne 'ABSENT' -or
   $gate0055.competing_process -ne 'ABSENT' -or [int64]$gate0055.disk_available_bytes -lt 10737418240 -or
   [int64]$gate0055.memory_available_bytes -lt 268435456 -or [int64]$gate0055.swap_free_bytes -lt 67108864 -or
   $gate0055.oom_recent -ne 'ABSENT' -or $gate0055.dashboard -ne 'HEALTHY' -or $gate0055.github_http -ne '200') { throw '00:55 fail-closed health gate failed.' }
$gate0055 | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidenceRoot '0055-gate-values.json')
$deadline=[datetimeoffset]'2026-08-30T01:10:00+10:00'
do {
  $active=(ssh -o BatchMode=yes ar-local-pi5-lan "systemctl show ar-local-daily.service -p ActiveState --value").Trim()
  if ([datetimeoffset]::Now -gt $deadline) { throw 'Natural service did not start by 01:10.' }
  if ($active -ne 'active') { Start-Sleep -Seconds 10 }
} until ($active -eq 'active')
$remoteStart = @'
set -eu
echo "observed_at=$(date --iso-8601=seconds)"
echo "active=$(systemctl is-active ar-local-daily.service || true)"
echo "invocation=$(systemctl show ar-local-daily.service -p InvocationID --value)"
echo "start_timestamp=$(systemctl show ar-local-daily.service -p ExecMainStartTimestamp --value)"
echo "restarts=$(systemctl show ar-local-daily.service -p NRestarts --value)"
echo "timer_last=$(systemctl show ar-local-daily.timer -p LastTriggerUSec --value)"
echo "timer_next=$(systemctl show ar-local-daily.timer -p NextElapseUSecRealtime --value)"
if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; else echo lock=ABSENT; fi
service_cgroup=$(systemctl show ar-local-daily.service -p ControlGroup --value); echo "service_cgroup=$service_cgroup"
count=0; bad=0
for pid in $(pgrep -f '[p]i_daily_sync.py|[c]dr_daily.py' || true); do count=$((count+1)); process_cgroup=$(cut -d: -f3 /proc/$pid/cgroup | tail -1); echo "ingest_pid_$count=$pid:$process_cgroup"; case "$process_cgroup" in "$service_cgroup"|"$service_cgroup"/*) ;; *) bad=1 ;; esac; done
echo "ingest_process_count=$count"
if test "$bad" -eq 0; then echo competing_process=ABSENT; else echo competing_process=PRESENT; fi
'@
$startAttempts=@();$start=$null;$startValues=$null
for($attempt=1;$attempt -le 30;$attempt++){
  $capture=ssh -o BatchMode=yes ar-local-pi5-lan $remoteStart
  if($LASTEXITCODE -ne 0){throw 'Start capture failed.'}
  $startAttempts+="--- attempt $attempt ---";$startAttempts+=$capture
  $candidateStart=Convert-GateLines $capture
  if($candidateStart.active -eq 'active' -and $candidateStart.lock -eq 'PRESENT' -and [int]$candidateStart.ingest_process_count -gt 0){$start=$capture;$startValues=$candidateStart;break}
  Start-Sleep -Seconds 2
}
$startAttempts | Set-Content -LiteralPath (Join-Path $evidenceRoot '0100-start-attempts.txt')
if($null -eq $startValues){throw 'Natural service never reached a lock-bound ingest process.'}
$start | Set-Content -LiteralPath (Join-Path $evidenceRoot '0100-start.txt')
if($startValues.active -ne 'active' -or [string]::IsNullOrWhiteSpace($startValues.invocation) -or
   $startValues.invocation -eq $baseline.service_invocation -or $startValues.start_timestamp -notmatch '2026-08-30 01:00:' -or
   [int]$startValues.restarts -ne 0 -or $startValues.timer_last -eq $baseline.timer_last -or
   $startValues.lock -ne 'PRESENT' -or [int]$startValues.ingest_process_count -lt 1 -or
   $startValues.competing_process -ne 'ABSENT') { throw 'Natural start identity, cgroup, or lock gate failed.' }
$startValues | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidenceRoot '0100-start-values.json')
$terminalDeadline=[datetimeoffset]'2026-08-30T03:00:00+10:00'
do {
  Start-Sleep -Seconds 30
  $active=(ssh -o BatchMode=yes ar-local-pi5-lan "systemctl show ar-local-daily.service -p ActiveState --value").Trim()
  if([datetimeoffset]::Now -ge $terminalDeadline -and $active -in @('active','activating')){
    ssh -o BatchMode=yes ar-local-pi5-lan "date --iso-8601=seconds; systemctl show ar-local-daily.service -p ActiveState -p SubState -p InvocationID -p ExecMainStartTimestamp -p NRestarts; if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; else echo lock=ABSENT; fi" |
      Set-Content -LiteralPath (Join-Path $evidenceRoot 'terminal-deadline-blocked.txt')
    throw 'Natural ingest remained active at the 03:00 terminal deadline; preserve it and remain BLOCKED.'
  }
} while ($active -in @('active','activating'))
$remoteTerminal = @'
set -eu
echo "observed_at=$(date --iso-8601=seconds)"
echo "active=$(systemctl is-active ar-local-daily.service || true)"
echo "invocation=$(systemctl show ar-local-daily.service -p InvocationID --value)"
echo "start_timestamp=$(systemctl show ar-local-daily.service -p ExecMainStartTimestamp --value)"
exit_timestamp=$(systemctl show ar-local-daily.service -p ExecMainExitTimestamp --value); echo "exit_timestamp=$exit_timestamp"; echo "exit_iso=$(date --date="$exit_timestamp" --iso-8601=seconds)"
echo "status=$(systemctl show ar-local-daily.service -p ExecMainStatus --value)"
echo "code=$(systemctl show ar-local-daily.service -p ExecMainCode --value)"
echo "result=$(systemctl show ar-local-daily.service -p Result --value)"
echo "restarts=$(systemctl show ar-local-daily.service -p NRestarts --value)"
echo "timer_last=$(systemctl show ar-local-daily.timer -p LastTriggerUSec --value)"
echo "timer_next=$(systemctl show ar-local-daily.timer -p NextElapseUSecRealtime --value)"
if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi
if pgrep -f '[p]i_daily_sync.py|[c]dr_daily.py' >/dev/null; then echo competing_process=PRESENT; exit 43; else echo competing_process=ABSENT; fi
curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest | python3 -c "import json,sys; v=json.load(sys.stdin); b=v.get('banks_counts') or {}; assert v.get('run_date')=='2026-08-30'; assert int(b.get('products',0))>0; assert int(b.get('rates',0))>0"
echo dashboard=HEALTHY
'@
$terminal=ssh -o BatchMode=yes ar-local-pi5-lan $remoteTerminal
$terminal | Set-Content -LiteralPath (Join-Path $evidenceRoot 'terminal-service.txt')
if ($LASTEXITCODE -ne 0) { throw "Terminal Pi capture failed: ssh exit $LASTEXITCODE" }
$terminalValues=Convert-GateLines $terminal
if($terminalValues.active -ne 'inactive' -or $terminalValues.invocation -ne $startValues.invocation -or
   $terminalValues.start_timestamp -ne $startValues.start_timestamp -or $terminalValues.timer_last -ne $startValues.timer_last -or
   [datetimeoffset]::Parse($terminalValues.exit_iso) -ge $terminalDeadline -or
   $terminalValues.status -ne '0' -or $terminalValues.code -ne 'exited' -or $terminalValues.result -ne 'success' -or
   [int]$terminalValues.restarts -ne 0 -or $terminalValues.lock -ne 'ABSENT' -or
   $terminalValues.competing_process -ne 'ABSENT' -or $terminalValues.dashboard -ne 'HEALTHY') { throw 'Natural service terminal identity gate failed.' }
$terminalValues | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidenceRoot 'terminal-service-values.json')
ssh -o BatchMode=yes ar-local-pi5-lan "journalctl -u ar-local-daily.service --since '2026-08-30 00:55:00' --output=short-iso-precise --no-pager" |
  Set-Content -LiteralPath (Join-Path $evidenceRoot 'service-journal.txt')
if ($LASTEXITCODE -ne 0) { throw 'Journal capture failed.' }
ssh -o BatchMode=yes ar-local-pi5-lan "cd /srv/ar-local/AR-local && python3 cdr_ledger_v2.py verify --state /srv/ar-local/data/state" |
  Set-Content -LiteralPath (Join-Path $evidenceRoot 'ledger-verify.json')
if ($LASTEXITCODE -ne 0) { throw 'Ledger verification failed.' }
@'
import hashlib,json,sqlite3
from pathlib import Path
from cdr_finalization import verify_completion_marker
D='2026-08-30'; data=Path('/srv/ar-local/data').resolve(); state=(data/'state').resolve()
def h(p):
 d=hashlib.sha256(); f=p.open('rb')
 with f:
  for b in iter(lambda:f.read(1048576),b''): d.update(b)
 return d.hexdigest()
p=json.loads((state/'observation-pointers-v2/latest-observation.json').read_text())
assert p['observation_date']==D
m_path=(state/p['marker_path']).resolve(); m_path.relative_to(state); m=json.loads(m_path.read_text())
assert verify_completion_marker(m,state,D)
c_path=(state/m['export_contract_path']).resolve(); c_path.relative_to(state); c=json.loads(c_path.read_text())
assert p['generation_id']==m['generation_id']==c['generation_id']
assert p['ledger_event_digest']==m['ledger_event_digest']
a=m.get('attempt_evidence') or {}; assert a.get('verified') is True and int(a.get('attempts') or 0)>0
v=c.get('coverage') or {}; reg=int(v.get('providers_registered') or 0); att=int(v.get('providers_attempted') or 0)
complete=int(v.get('providers_complete') or 0); partial=int(v.get('providers_partial') or 0); failed=int(v.get('providers_failed') or 0)
failures=int(v.get('failure_records') or 0); corrupt=int(v.get('corrupt_failure_records') or 0); unattributed=int(v.get('unattributed_failure_records') or 0)
discovered=int(v.get('products_discovered') or 0); register_attempted=int(v.get('register_sources_attempted') or 0); register_complete=int(v.get('register_sources_complete') or 0)
states=c.get('provider_states') or []; state_counts={k:sum(1 for x in states if x.get('state')==k) for k in ('complete','partial','failed')}
assert reg>0 and att==reg and len(states)==reg and complete+partial+failed==reg and state_counts=={'complete':complete,'partial':partial,'failed':failed}
assert c.get('observation_state') in {'complete','partial'} and v.get('failure_provenance_complete') is True and v.get('register_provenance_complete') is True
assert register_attempted>0 and register_complete==register_attempted and failed==0 and corrupt==0 and unattributed==0
if c.get('observation_state')=='partial': assert 1<=failures<=50 and failures*100<=discovered and partial*100<=15*reg
else: assert failures==0 and partial==0
assert int((m.get('banks') or {}).get('products') or 0)==discovered and int((m.get('banks') or {}).get('failures') or 0)==failures
assert not (c.get('quarantines') or [])
unavailable=set(v.get('unavailable_populations') or [])
assert {'consumer_eligible_products','priced_products','rate_tiers_by_classification'}<=unavailable
source=(data/c['source_path']).resolve(); source.relative_to(data)
dbs=[x for x in c['artifacts'] if x['path'].endswith('.sqlite')]; assert len(dbs)==1
meta=dbs[0]; db=(source/meta['path']).resolve(); db.relative_to(source); digest=h(db)
assert db.stat().st_size==int(meta['bytes']) and digest==meta['sha256']
with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as con:
 qc=con.execute('PRAGMA quick_check').fetchone()[0]; assert qc=='ok'
 tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
 required={'runs','schema_meta','bank_products','bank_rates','bank_items','bank_product_facts','bank_product_changes'}; assert required<=tables
 counts={t:con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in sorted(required)}
 assert all(counts[t]>0 for t in ('bank_products','bank_rates','bank_items','bank_product_facts'))
 banks=m.get('banks') or {}
 assert counts['bank_products']==int(banks.get('products') or 0)==discovered
 assert counts['bank_rates']==int(banks.get('rates') or 0)
 assert counts['bank_product_facts']==int(banks.get('product_facts') or 0)
 assert counts['bank_product_changes']==int(banks.get('product_changes') or 0)
 assert counts['bank_items']==sum(int(banks.get(k) or 0) for k in ('fees','features','eligibility','constraints'))
assert sum(int(x.get('failure_records') or 0) for x in states)==failures
local_v1={}
for key,folder,tag,required,allowed in (
 ('dated','v1-dated',f'app-payload-{D}',{'core','details'},{'core','details'}),
 ('rolling','v1-latest','app-payload-latest',{'core','details'},{'bank_history','bank_spread_history','core','details','history_banks','rba_calendar','search_index'}),
):
 root=(state/'app-payload/v1'/folder).resolve(); root.relative_to(state)
 manifest_path=(root/'manifest.json').resolve(); manifest_path.relative_to(root)
 payload=json.loads(manifest_path.read_text())
 assert payload.get('schema_version')==1 and payload.get('run_date')==D and payload.get('tag')==tag
 roles=set((payload.get('files') or {}).keys()); assert required<=roles<=allowed
 assets={}
 for role,meta in payload['files'].items():
  name=meta['name']; assert Path(name).name==name
  asset=(root/name).resolve(); asset.relative_to(root)
  asset_sha=h(asset); asset_bytes=asset.stat().st_size
  assert asset_sha==meta['sha256'] and asset_bytes==int(meta['bytes'])
  assets[role]={'name':name,'sha256':asset_sha,'bytes':asset_bytes}
 local_v1[key]={'tag':tag,'manifest_sha256':h(manifest_path),'assets':assets}
print(json.dumps({'result':'PASS','date':D,'pointer':p,'marker_sha256':h(m_path),'contract_digest':c['contract_digest'],'banks':m.get('banks') or {},'attempt_evidence':a,'coverage':v,'provider_states':states,'quarantines':c.get('quarantines',[]),'sqlite':{'path':str(db),'bytes':db.stat().st_size,'sha256':digest,'quick_check':qc,'populations':counts},'local_v1':local_v1},sort_keys=True,indent=2))
'@ | ssh -o BatchMode=yes ar-local-pi5-lan "cd /srv/ar-local/AR-local && python3 -" |
  Set-Content -LiteralPath (Join-Path $evidenceRoot 'observation-verify.json')
if ($LASTEXITCODE -ne 0) { throw 'Observation verification failed.' }
$publicRoot=Join-Path $evidenceRoot 'public-github'; New-Item -ItemType Directory -Path $publicRoot -Force | Out-Null
$local=Get-Content -Raw (Join-Path $evidenceRoot 'observation-verify.json') | ConvertFrom-Json
$report=[ordered]@{date=$date;result='RUNNING';manifests=@{}}
foreach($tag in @("app-payload-$date",'app-payload-latest')){
 $tagRoot=Join-Path $publicRoot $tag; New-Item -ItemType Directory -Path $tagRoot -Force | Out-Null
 $manifestPath=Join-Path $tagRoot 'manifest.json'; Invoke-WebRequest -UseBasicParsing -TimeoutSec 60 -Uri "https://github.com/yanniedog/AR-local/releases/download/$tag/manifest.json" -OutFile $manifestPath
 $env:AR_PUBLIC_MANIFEST=$manifestPath;python -c "import json,os; h=lambda p: (_ for _ in ()).throw(ValueError('duplicate JSON key')) if len(p)!=len(dict(p)) else dict(p); json.load(open(os.environ['AR_PUBLIC_MANIFEST'],encoding='utf-8'),object_pairs_hook=h)";if($LASTEXITCODE -ne 0){throw "$tag manifest JSON is ambiguous"}
 $m=Get-Content -Raw $manifestPath|ConvertFrom-Json; if($m.schema_version -ne 1 -or $m.run_date -ne $date -or $m.tag -ne $tag){throw "$tag identity mismatch"}
 $localKey=if($tag -eq "app-payload-$date"){'dated'}else{'rolling'};$producer=$local.local_v1.$localKey
 $publicManifestSha=(Get-FileHash $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant();if($publicManifestSha -cne $producer.manifest_sha256){throw "$tag public manifest differs from the independently recorded Pi staging manifest"}
 $requiredRoles=@($producer.assets.PSObject.Properties.Name|Sort-Object);$actualRoles=@($m.files.PSObject.Properties.Name|Sort-Object);if(($actualRoles -join ',') -cne ($requiredRoles -join ',')){throw "$tag public role set differs from independently recorded Pi staging"}
 foreach($n in $local.banks.PSObject.Properties.Name){if([int64]$m.counts.$n -ne [int64]$local.banks.$n){throw "$tag count mismatch: $n"}}
 $assets=@(); foreach($f in $m.files.PSObject.Properties){$a=$f.Value;$producerAsset=$producer.assets.PSObject.Properties[$f.Name].Value;if($null -eq $producerAsset){throw "$tag has no independently recorded Pi staging asset: $($f.Name)"};$roleName=$f.Name.Replace('_','-');if($a.sha256 -notmatch '^[0-9a-f]{64}$'){throw "$tag unsafe asset digest: $($f.Name)"};$expectedName="${roleName}-${date}-$($a.sha256.Substring(0,12)).json.gz";if($a.name -cne $expectedName -or [IO.Path]::GetFileName($a.name) -cne $a.name){throw "$tag unsafe asset identity: $($f.Name)"};if($a.name -cne $producerAsset.name -or $a.sha256 -cne $producerAsset.sha256 -or [int64]$a.bytes -ne [int64]$producerAsset.bytes){throw "$tag manifest asset differs from independently recorded Pi staging: $($f.Name)"};$canonicalUrl="https://github.com/yanniedog/AR-local/releases/download/$tag/$expectedName";if($a.url -cne $canonicalUrl){throw "$tag noncanonical asset URL: $($f.Name)"};$out=[IO.Path]::GetFullPath((Join-Path $tagRoot $expectedName));if(-not $out.StartsWith([IO.Path]::GetFullPath($tagRoot)+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'asset path escaped evidence root'};Invoke-WebRequest -UseBasicParsing -TimeoutSec 120 -Uri $canonicalUrl -OutFile $out;$sha=(Get-FileHash $out -Algorithm SHA256).Hash.ToLowerInvariant();$bytes=(Get-Item $out).Length;if($sha -ne $a.sha256 -or $bytes -ne [int64]$a.bytes -or $sha -cne $producerAsset.sha256 -or $bytes -ne [int64]$producerAsset.bytes){throw "$tag public asset mismatch: $($a.name)"};$env:AR_PUBLIC_ASSET=$out;$env:AR_PUBLIC_DATE=$date;python -c "import gzip,json,os; x=json.load(gzip.open(os.environ['AR_PUBLIC_ASSET'],'rt',encoding='utf-8')); assert isinstance(x,(dict,list)); assert not isinstance(x,dict) or x.get('run_date',os.environ['AR_PUBLIC_DATE'])==os.environ['AR_PUBLIC_DATE']";if($LASTEXITCODE -ne 0){throw 'asset schema/date failure'};$assets+=[ordered]@{role=$f.Name;name=$a.name;sha256=$sha;bytes=$bytes}}
 $report.manifests[$tag]=[ordered]@{sha256=$publicManifestSha;producer_manifest_sha256=$producer.manifest_sha256;assets=$assets}
}
$datedAssets=@{};foreach($a in $report.manifests["app-payload-$date"].assets){$datedAssets[$a.role]=$a.sha256}
foreach($role in @('core','details')){$rollingAsset=$report.manifests['app-payload-latest'].assets|Where-Object {$_.role -eq $role};if($datedAssets[$role] -ne $rollingAsset.sha256){throw "dated/rolling asset mismatch: $role"}}
$corePath=(Get-ChildItem (Join-Path $publicRoot 'app-payload-latest') -Filter 'core-*.json.gz' -File -ErrorAction Stop).FullName
$env:AR_PUBLIC_CORE=$corePath;$env:AR_LOCAL_OBSERVATION=(Join-Path $evidenceRoot 'observation-verify.json');$env:AR_PUBLIC_DATE=$date
python -c "import gzip,json,os; x=json.load(gzip.open(os.environ['AR_PUBLIC_CORE'],'rt',encoding='utf-8')); l=json.load(open(os.environ['AR_LOCAL_OBSERVATION'],encoding='utf-8')); c=x['coverage']; n=c['counts']; b=l['banks']; assert x['schema_version']==1 and x['run_date']==os.environ['AR_PUBLIC_DATE'] and c['observed_on']==os.environ['AR_PUBLIC_DATE']; assert int(n['products'])==int(b['products']) and int(n['rates'])==int(b['rates']) and int(n['failure_records'])==int(b['failures']) and int(n['providers_attempted'])==int(l['coverage']['providers_attempted']); assert c.get('failure_provenance_complete') is True; pf=c.get('provider_failures'); fs=c.get('failures'); assert isinstance(pf,list) and isinstance(fs,list) and pf==fs; aggregate={}; [(aggregate.__setitem__(v['provider'],aggregate.get(v['provider'],0)+int(v['count']))) for v in pf]; expected={v['brand_name']:int(v['failure_records']) for v in l['provider_states'] if int(v.get('failure_records') or 0)>0}; assert aggregate==expected and sum(aggregate.values())==int(b['failures'])"
if($LASTEXITCODE -ne 0){throw 'public core coverage/date/count binding failed'}
$indexPath=Join-Path $publicRoot 'dates-index.json';Invoke-WebRequest -UseBasicParsing -TimeoutSec 60 -Uri 'https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/dates-index.json' -OutFile $indexPath
$index=Get-Content -Raw $indexPath|ConvertFrom-Json;if($index.schema_version -ne 1 -or $index.latest_date -ne $date -or $index.dates -notcontains $date){throw 'dates index mismatch'}
$report.dates_index=[ordered]@{sha256=(Get-FileHash $indexPath -Algorithm SHA256).Hash.ToLowerInvariant();latest_date=$index.latest_date}
try{$v2Path=Join-Path $publicRoot 'manifest-v2.json';Invoke-WebRequest -UseBasicParsing -TimeoutSec 60 -Uri 'https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest-v2.json' -OutFile $v2Path;$v2=Get-Content -Raw $v2Path|ConvertFrom-Json;$v2Current=($v2.run_date -eq $date);$report.v2=[ordered]@{status=$(if($v2Current){'PASS_CURRENT_INDEPENDENT_NOT_A_V1_GATE'}else{'STALE_FAIL_INDEPENDENT_NOT_A_V1_GATE'});result=$(if($v2Current){'PASS'}else{'FAIL'});run_date=$v2.run_date;sha256=(Get-FileHash $v2Path -Algorithm SHA256).Hash.ToLowerInvariant()}}
catch{$report.v2=[ordered]@{status='FAIL_INDEPENDENT_NOT_A_V1_GATE';result='FAIL';error=$_.Exception.Message}}
$report.result='PASS';$report|ConvertTo-Json -Depth 15|Set-Content (Join-Path $publicRoot 'verification.json')
Get-ChildItem $evidenceRoot -Recurse -File | Get-FileHash -Algorithm SHA256 | ConvertTo-Json |
  Set-Content -LiteralPath (Join-Path $evidenceRoot 'terminal-evidence-hashes.json')
```

Require exactly one invocation, dashboard automatic return, raw attempts,
marker/contract/ledger/generation binding, SQLite integrity, exact provider and
product accounting, and separately verified dated v1, rolling v1, dates index,
and every public asset. Individual product/provider gaps remain preserved and
disclosed; they do not discard unrelated valid data. v2 remains independent and
must not be relabelled.

### Exact natural old-task continuity gate at 05:15

Do not trigger or reinstall the task. At 05:15, after the ingest is terminally
accepted, run this read-only block. A truthful old-candidate `PASS/BACKFILL` is
accepted only as continuity evidence; it is not A3 terminal proof.

```powershell
$ErrorActionPreference='Stop'
$taskName='AR-local laptop backup';$target='C:\code\backups\AR-local-pi5'
$receiver='C:\code\backups\AR-local-pi5-receiver-88557b9';$oldReceiver='C:\code\backups\AR-local-pi5-receiver-f214e32'
$oldXml='C:\code\backups\AR-local-pi5\evidence\A3-V14-TASK-TRANSITION-20260828\20260828T080004+1000\installed-task.xml'
$evidenceParent=[IO.Path]::GetFullPath('C:\code\backups\AR-local-pi5\evidence\NATURAL-20260830')
$activePointer=Join-Path $evidenceParent 'ACTIVE_EVIDENCE_PATH.txt';$pointerRoot=[IO.Path]::GetFullPath((Get-Content -Raw $activePointer).Trim());$bound=@()
foreach($dir in @(Get-ChildItem -LiteralPath $evidenceParent -Directory -ErrorAction Stop)){
 $authorityPath=Join-Path $dir.FullName 'authority.json';if(-not(Test-Path -LiteralPath $authorityPath -PathType Leaf)){continue}
 try{$authority=Get-Content -Raw -LiteralPath $authorityPath|ConvertFrom-Json}catch{continue}
 $root=[IO.Path]::GetFullPath($dir.FullName)
 if($root.StartsWith($evidenceParent+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -and $authority.evidence_root -ceq $root -and $authority.run_id -ceq $dir.Name -and $authority.source_date -ceq '2026-08-30' -and $authority.candidate -ceq '88557b96d4a240dca640285bcb3457751b381667'){$bound+=,[pscustomobject]@{root=$root;authority_path=$authorityPath}}
}
if($bound.Count -ne 1 -or $pointerRoot -cne $bound[0].root){throw '05:15 evidence pointer is not uniquely bound to the original 00:25 authority.'}
$evidenceRoot=$bound[0].root;$authorityHash=(Get-FileHash -LiteralPath $bound[0].authority_path -Algorithm SHA256).Hash
$recordedAuthority=@(Get-Content -Raw (Join-Path $evidenceRoot '0025-hashes.json')|ConvertFrom-Json|Where-Object {[IO.Path]::GetFullPath($_.Path) -ceq [IO.Path]::GetFullPath($bound[0].authority_path)})
if($recordedAuthority.Count -ne 1 -or $recordedAuthority[0].Hash -cne $authorityHash){throw '05:15 authority record is not hash-bound.'}
$task=Get-ScheduledTask -TaskName $taskName;$info=Get-ScheduledTaskInfo -TaskName $taskName
if($task.State -ne 'Ready' -or -not $task.Settings.Enabled -or $info.LastTaskResult -ne 0 -or
   $info.LastRunTime -lt [datetime]'2026-08-30T05:00:00' -or $info.LastRunTime -ge [datetime]'2026-08-30T05:05:00'){throw 'Natural old task did not run once in its expected 05:00 window.'}
if((git -C $receiver rev-parse HEAD).Trim() -ne '88557b96d4a240dca640285bcb3457751b381667' -or @(git -C $receiver status --porcelain=v1).Count -ne 0){throw 'Candidate receiver drift.'}
if((git -C $oldReceiver rev-parse HEAD).Trim() -ne 'f214e3249c7968d574e3449edb14792904e1cc1f' -or @(git -C $oldReceiver status --porcelain=v1).Count -ne 0){throw 'Old receiver drift.'}
if((Get-FileHash $oldXml -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2' -or (Export-ScheduledTask -TaskName $taskName) -cne (Get-Content -Raw $oldXml)){throw 'Old task XML drift.'}
$transitionRoot=Join-Path $target 'evidence\A3-LAPTOP-TASK-TRANSITION'
$residue=@((Join-Path $target 'catalog\.receiver.lock'),(Join-Path $transitionRoot 'ACTIVE_TRANSITION.json'),(Join-Path $transitionRoot '.transition-runtime.lock')) | Where-Object {Test-Path -LiteralPath $_}
$helpers=Get-CimInstance Win32_Process | Where-Object {$_.ProcessId -ne $PID -and $_.CommandLine -match 'laptop_backup_(scheduled|transition|source)|laptop_pull_backup'}
if((Get-Volume C).SizeRemaining -lt 53687091200 -or $residue -or $helpers){throw 'Capacity, operational lock, helper, or overlap gate failed.'}
$env:AR_TARGET=$target
$env:AR_TASK_START=$info.LastRunTime.ToUniversalTime().ToString('o')
Push-Location $receiver
try {
@'
import json,os
from datetime import datetime,timezone
from pathlib import Path
import laptop_backup_transition_contract as c
import laptop_pull_backup as r
root=Path(os.environ['AR_TARGET']).resolve(); task_start=datetime.fromisoformat(os.environ['AR_TASK_START'].replace('Z','+00:00'))
candidate='f214e3249c7968d574e3449edb14792904e1cc1f'; protected='9302890fcc752cbf90da97d597e972c157d913e3'
hygiene=c.validate_hygiene(root,[])
baseline_relative='catalog/scheduled-runs/20260828T191317Z-5b3033fc4db54962bb2fd53b9af5c1aa.json'; baseline_sha='2753be7b5d87af3d1ab5a581be83f1668a9695f2b5cce58822d675a920e42764'
baseline=(root/baseline_relative).resolve(); baseline.relative_to(root); assert baseline.is_file() and c.sha256_file(baseline)==baseline_sha
baseline_value=json.loads(baseline.read_text()); baseline_completed=datetime.fromisoformat(baseline_value['timestamps']['completed_at'].replace('Z','+00:00'))
records=[]
for path in (root/'catalog/scheduled-runs').glob('*.json'):
 value=json.loads(path.read_text()); ts=value.get('timestamps',{}).get('completed_at')
 if not isinstance(ts,str): raise ValueError(f'missing completed_at: {path}')
 completed=datetime.fromisoformat(ts.replace('Z','+00:00'))
 if completed>baseline_completed: records.append((completed,path.resolve(),value))
records.sort(key=lambda x:(x[0],x[1].name)); assert records
writes=[]; previous=(baseline_relative,baseline_sha); evidence=[]; natural_records=[]
for completed,path,record in records:
 action=record.get('action'); assert action in {'BACKFILL','BACKUP-LATEST','NO_BACKUP_DATA_WRITE'}
 detail=record.get('detail') or {}; state=detail.get('after') if action in {'BACKFILL','BACKUP-LATEST'} else detail
 observation=(state or {}).get('observation') or {}; record_date=observation.get('observation_date'); assert isinstance(record_date,str)
 c.validate_execution_record(record,action=action,candidate_sha=candidate,protected_sha=protected,plan_commit=r.PLAN_GIT_COMMIT,plan_sha256=r.PLAN_SHA256,operator='jkoka',expected_date=record_date)
 digest=c.sha256_file(path); link=record.get('previous_execution')
 assert link=={'record_path':previous[0],'record_sha256':previous[1]}
 relative=path.relative_to(root).as_posix(); previous=(relative,digest)
 if action in {'BACKFILL','BACKUP-LATEST'}: writes.append({'path':relative,'observation_date':record_date})
 if completed>=task_start: natural_records.append({'path':relative,'observation_date':record_date})
 evidence.append({'path':str(path),'sha256':digest,'action':action,'observation_date':record_date,'completed_at':record['timestamps']['completed_at']})
assert any(x['observation_date']=='2026-08-30' for x in writes) and len(natural_records)==1 and natural_records[0]['observation_date']=='2026-08-30'
pointer=json.loads((root/'catalog/latest-scheduled.json').read_text()); assert pointer['record_path']==previous[0] and pointer['record_sha256']==previous[1] and pointer['result']=='PASS'
catalog=r.catalog_entries(root/'catalog/generations.jsonl'); assert catalog and all(x.get('result')=='PASS' for x in catalog)
receipts=c.validate_receipts(root,candidate_sha=candidate,protected_sha=protected,plan_commit=r.PLAN_GIT_COMMIT,expected_date='2026-08-30')
print(json.dumps({'result':'PASS','baseline':{'path':str(baseline),'sha256':baseline_sha},'task_start':task_start.isoformat(),'natural_record':natural_records[0],'records':evidence,'write_records':writes,'latest_pointer':pointer,'catalog_entries':len(catalog),'receipts':c.receipt_evidence(receipts),'hygiene':hygiene},sort_keys=True,indent=2))
'@ | & python - | Set-Content -LiteralPath (Join-Path $evidenceRoot '0500-old-task-continuity.json')
  if($LASTEXITCODE -ne 0){throw 'Old-task continuity record failed authentication.'}
} finally { Pop-Location }
$remote0515=@'
set -eu
echo "head=$(git -C /srv/ar-local/AR-local rev-parse HEAD)"
if test -z "$(git -C /srv/ar-local/AR-local status --porcelain=v1)"; then echo checkout_clean=true; else echo checkout_clean=false; fi
service_state=$(systemctl is-active ar-local-daily.service || true); echo "service_active=$service_state"; test "$service_state" = inactive
echo "timer_enabled=$(systemctl is-enabled ar-local-daily.timer || true)"
echo "timer_active=$(systemctl is-active ar-local-daily.timer || true)"
if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi
curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest | python3 -c "import json,sys; v=json.load(sys.stdin); b=v.get('banks_counts') or {}; assert v.get('run_date')=='2026-08-30'; assert int(b.get('products',0))>0; assert int(b.get('rates',0))>0"
echo dashboard=HEALTHY
'@
$readback=ssh -o BatchMode=yes ar-local-pi5-lan $remote0515
$readback |
  Set-Content -LiteralPath (Join-Path $evidenceRoot '0515-pi-readback.txt')
if($LASTEXITCODE -ne 0){throw '05:15 Pi readback failed.'}
$readbackValues=[ordered]@{};foreach($line in $readback){$pair=$line -split '=',2;if($pair.Count -eq 2){$readbackValues[$pair[0].Trim()]=$pair[1].Trim()}}
if($readbackValues.head -ne '9302890fcc752cbf90da97d597e972c157d913e3' -or $readbackValues.checkout_clean -ne 'true' -or
   $readbackValues.service_active -ne 'inactive' -or $readbackValues.timer_enabled -ne 'enabled' -or
   $readbackValues.timer_active -ne 'active' -or $readbackValues.lock -ne 'ABSENT' -or
   $readbackValues.dashboard -ne 'HEALTHY'){throw '05:15 Pi identity/readiness gate failed.'}
```

### Exact real transition command and rollback boundary

Only after all three dated blocks above are `PASS`, run the harness before the
22:00 deadline. The caller must be elevated `yanniedog\jkoka`; if normal UAC
consent is unavailable, record `BLOCKED` without mutation. Do not create a
privileged workaround. In that elevated process, retain the variables from the
00:25 authority block and run exactly:

```powershell
$ErrorActionPreference='Stop'
$candidate='88557b96d4a240dca640285bcb3457751b381667'
$receiver='C:\code\backups\AR-local-pi5-receiver-88557b9'
$oldReceiver='C:\code\backups\AR-local-pi5-receiver-f214e32'
$authorityRepo='C:\code\backups\AR-local-a3-transition-authority'
$target='C:\code\backups\AR-local-pi5'
$expectedPi='9302890fcc752cbf90da97d597e972c157d913e3'
$marker='HANDOFF-20260829T231200+1000-A3-TRANSITION-AUTHORIZED'
git -C $authorityRepo fetch origin main --prune
$authorityCommit=(& python -c 'import subprocess,sys; r,m,p=sys.argv[1:]; cs=subprocess.check_output(["git","-C",r,"rev-list","--reverse","--first-parent","origin/main","--",p],text=True).split(); hits=[c for c in cs if m.encode() in subprocess.check_output(["git","-C",r,"show",f"{c}:{p}"])]; print(hits[0] if hits else "")' $authorityRepo $marker 'docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md').Trim()
if((git -C $authorityRepo rev-parse origin/main).Trim() -ne $authorityCommit){throw 'Transition authority is stale.'}
$handoffSha=(& python -c 'import hashlib,subprocess,sys; print(hashlib.sha256(subprocess.check_output(["git","-C",sys.argv[1],"show",sys.argv[2]+":docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md"])).hexdigest())' $authorityRepo $authorityCommit).Trim()
if(@(git -C $authorityRepo status --porcelain=v1).Count -ne 0 -or @(git -C $receiver status --porcelain=v1).Count -ne 0 -or
   (git -C $receiver rev-parse HEAD).Trim() -ne $candidate){throw 'Transition checkout identity failed.'}
$python=(Get-Command python -ErrorAction Stop).Source
$oldPython='C:\Users\jkoka\.pyenv\pyenv-win\shims\python.bat'
$oldXml='C:\code\backups\AR-local-pi5\evidence\A3-V14-TASK-TRANSITION-20260828\20260828T080004+1000\installed-task.xml'
& $python "$receiver\laptop_backup_transition.py" --target $target `
 --recovery-image 'C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21' `
 --receiver $receiver --old-receiver $oldReceiver --old-task-xml $oldXml `
 --candidate-code-sha $candidate --old-candidate-code-sha 'f214e3249c7968d574e3449edb14792904e1cc1f' `
 --protected-code-sha $expectedPi --plan-git-commit '14dd066099bba393cccf61a280243e43162eedc9' `
 --plan-sha256 '78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713' `
 --authority-repo $authorityRepo --authority-commit $authorityCommit --handoff-sha256 $handoffSha `
 --expected-observation-date '2026-08-30' --operator 'jkoka' --principal 'yanniedog\jkoka' `
 --python-path $python --old-python-path $oldPython --task-name 'AR-local laptop backup' `
 --deadline '2026-08-30T22:00:00+10:00' --host 'ar-local-pi5-lan' `
 --accepted-old-xml-sha256 'aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2'
if($LASTEXITCODE -ne 0){throw 'A3 transition did not PASS.'}
```

Never invent a resume ID. If interrupted after active-lock creation, read and
authenticate `ACTIVE_TRANSITION.json`; only the same command with the exact
authenticated `--resume-transition-id` may recover/finalize. It must not repeat
backup or install. The terminal record must prove one candidate
`PASS/BACKUP-LATEST/UP_TO_DATE` for 2026-08-30, candidate-bound receipts and
restore checks, catalog-prefix/lineage preservation, exact installed task,
standalone `PASS/NO_BACKUP_DATA_WRITE`, no residue, Pi/dashboard/timer health,
50 GiB free, and a closed hash-bound transition pointer. Any failure uses only
authenticated recovery, restores the exact old task and eligible component
pointers, preserves all immutable generations/records, and never rolls back
`latest-scheduled`.

After transition `PASS`, append its exact terminal evidence in a fresh
documentation-only PR and bind the natural 2026-08-31 01:00 and first new-task
05:00 proof to the installed XML and terminal hashes. A3 becomes terminal
`PASS` only after that natural backup proves the 2026-08-31 observation. Then,
without waiting for conversational reauthorization, begin A4 planning as a
separate daylight, no-runtime-mutation slice. A4 physical boot execution still
requires exact spare-media identity and any unavoidable physical/UAC boundary;
it must not endanger the next 01:00 capture. Pi deployment, PR #508, and Phases
B-G remain blocked until their own later gates.

## Entry `HANDOFF-20260830T083100+1000-A3-COMPENSATED-TRANSITION`

### Control record

| Field | Value |
|---|---|
| Created at, Australia/Hobart | `2026-08-30T08:31:00+10:00` |
| Previous handoff-containing merge | `59b42701154e1e421581b47069772bbcf2af5230` |
| Previous complete handoff Git-blob SHA-256 | `57d27cc293e6e5c1782a641117d8c03deeeb5149fd86d215844bb02bbb773eda` |
| Plan | `ARL-OPS-001` v1.4 |
| Plan document-containing commit | `14dd066099bba393cccf61a280243e43162eedc9` |
| Controlled plan SHA-256 | `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Candidate | `88557b96d4a240dca640285bcb3457751b381667` |
| Protected Pi SHA | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Operator | Codex unattended for `jkoka`; Windows UAC consent remains the only human boundary |
| Current result | `RUNNING`; compensated transition is authorized below, then A3 remains pending its first natural new-task proof |

### Append-only decision `DEV-A3-TIMED-GATE-003`

The scheduled 00:25 and 00:55 continuation did not execute. This is a
procedural `BLOCKED` result and is never relabelled `PASS`. The natural ingest
was not missed, forced, restarted, or duplicated: systemd ran invocation
`893b9b8ab55f45f28c9d71014b048b5c` once from 01:00:03 to 01:16:57 with
`Result=success`, `ExecMainStatus=0`, and `NRestarts=0`; the lock and ingest
processes were absent terminally and the dashboard returned.

Risk: there is no contemporaneous 00:25/00:55 evidence proving the pre-start
lock/process/resource state. Compensating controls are a complete post-terminal
service journal, clean protected Pi identity, 19/19 ledger verification,
hash-bound raw attempts, marker/contract/generation reconciliation, SQLite
integrity, provider/product accounting, independently matched Pi-staged and
public dated/rolling payload bytes, and the natural 05:00 backup record. These
controls prove the resulting observation and backup are internally complete
and authentic, but do not rewrite the procedural miss.

The independent ingest evidence root is
`C:\code\backups\AR-local-pi5\evidence\NATURAL-20260830-LATE-VALIDATION\20260830T013500+1000`:

- `validation-summary.json`: `5e10dcbee493465e2d898df448d029383d7016d137b89da9efe5a5ecf4e8b800`;
- `observation-and-producer.json`: `8f2055d0ccb34a25ce1229f5d73fea607804d5f24e647195d01b20b984e6ba61`;
- `public-verification.json`: `700f756a9676ef4b38f03855e7519ab7cbc72b1c47deeebbb1d4960f7b96c167`;
- `ledger-verify.json`: `58c4ef3add3aced0a866b6ac54037f258f3fa19d253d82ec89d7f677af2ef63e`;
- `service-journal-late.txt`: `0c2d373af5673926ac0c1600fa027dafbd52f27b7f923e18560ae66f7755fee5`;
- `supplemental-binding-verifier.py`: `d11e7df28a61c81aac2998e2ba41691b3f3adb9c616e4f0374356a2c3f5f0759`;
- `supplemental-binding.json`: `409509bb1b3d677031e15ceab51d591a14b866c012cfd631ebf7dffdba2f6c57`;
- `supplemental-command-ledger-v2.json`: `452d2858261e8e7434903baccf80252d4c6a2122deec3830ea9c567838770e41`.

The supplemental binding reran from its saved, hashed source and records the
exact commands. It binds pointer SHA-256
`1b28c00659282781016820e7f2f18ce50f6222d0a6e52ed61a7f632bcd01d42c`,
marker SHA-256
`59c03052d4fce710ab6b298c4fb43a8010bfe8e3b40b364b3a7ec426c886f22c`,
contract SHA-256
`9555fa261fbcbc3be0efaae6a318671dc09dc6dedbc8e8e8ad9bbe0f8e3d80d1`,
contract digest
`e306489f4a5a3002d003260e393e14b9ef41d948f2e32ca0dafcf278bc1100d5`,
ledger-event raw SHA-256
`b311a5c554d28470c2031b89b8df3435f73449c128acc1c1be4d56531120f599`
and event digest
`5e27b5c4c7d4d171e212b62348e98e5af91dd4ca5798df9168defa6cb9101eae`.
Raw attempt evidence is independently retained as head
`99355453a936db8bd5799ccc3942aebcc0bc46c70082888cf97b0cab619144f5`,
tree `8509eaf6891804bb695fee3dcd94886e93bd4007bcdb31dfca88b2f16b43e97a`,
promotion manifest
`050ea48723b783be0796cf9c4874ae7daaeeb5b2f4178b4c38966fd4c6f8fbde`,
10,981 files, and 42,660,057 bytes.

Observation `obs-2026-08-30-69a34aa4c745bb2e` is a valid bounded partial:
3,841 attempts; 119/119 providers attempted; 112 complete, seven partial, zero
failed; 17 attributable failures; zero corrupt/unattributed; 3,012 products;
17,050 rates; SQLite SHA-256
`f246fd77d3215ac631e7c0255ba550f9bfb6e49f0e9c866041040f740fa6f834`
with `quick_check=ok`. Dated v1, rolling v1, every referenced asset, and the
dates index independently match Pi staging. Individual gaps remain disclosed;
they did not discard unrelated valid products.

The natural old task ran once at 05:00:01 and produced immutable
`PASS/BACKFILL` record
`catalog/scheduled-runs/20260829T191444Z-3a75034934e640cdbd694f957805206d.json`,
SHA-256 `40bfca76438b0de7eb047c4eacbf3beb58ecf81bb9a976deb0481b5084d976ae`,
for observation date `2026-08-30`. The task is Ready/enabled with result zero,
next run 2026-08-31 05:00, and 151,989,071,872 bytes free. Its concise evidence
`0500-task-summary-late.json` has SHA-256
`6346113a080f61911cbe181e03c577d63d484962ca9fd4335bf5edab42016af7`.

Two defects in the previous manual continuity block are recorded without
editing it: .NET `o` format contains seven fractional digits that Python's
`datetime.fromisoformat` rejects, and the manual loop demands a predecessor
from a legacy record whose authenticated format intentionally has
`previous_execution=null`. The candidate's tested transition contract is the
authority for unique legacy-anchor recovery and live-pointer binding. Revised
acceptance therefore requires its own elevated `static_preflight` and
`runtime_preflight` to accept this exact record before any mutation.

### Revised transition authority

This decision authorizes the prior entry's exact real transition command today
before 22:00, despite the recorded timed-procedure miss, only when all evidence
and identities above still hash-match and these substitutions are made:

1. Resolve this entry's document-containing merge using marker
   `HANDOFF-20260830T083100+1000-A3-COMPENSATED-TRANSITION`; require it to equal
   current `origin/main`, and calculate the complete handoff Git-blob SHA-256
   from that merge.
2. Pass that merge and hash as `--authority-commit` and `--handoff-sha256`.
3. Retain expected observation date `2026-08-30`, deadline
   `2026-08-30T22:00:00+10:00`, candidate/protected/plan identities, old task
   XML, receivers, recovery image, operator, principal, and every other argument
   from the prior exact command unchanged.
4. Run only in an elevated `yanniedog\jkoka` process. UAC denial or absence is
   `BLOCKED`; no privilege workaround is authorized.

The substitutions above are implemented by this self-contained replacement;
it supersedes the previous entry's executable block:

```powershell
$ErrorActionPreference='Stop'
if(-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'A3 transition requires normal UAC elevation.'}
$candidate='88557b96d4a240dca640285bcb3457751b381667';$receiver='C:\code\backups\AR-local-pi5-receiver-88557b9';$oldReceiver='C:\code\backups\AR-local-pi5-receiver-f214e32'
$authorityRepo='C:\code\backups\AR-local-a3-transition-authority';$target='C:\code\backups\AR-local-pi5';$expectedPi='9302890fcc752cbf90da97d597e972c157d913e3'
$marker='HANDOFF-20260830T083100+1000-A3-COMPENSATED-TRANSITION';$handoff='docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'
git -C $authorityRepo fetch origin main --prune
if($LASTEXITCODE -ne 0){throw "Transition authority fetch failed: git exit $LASTEXITCODE"}
$authorityCommit=(& python -c 'import subprocess,sys; r,m,p=sys.argv[1:]; cs=subprocess.check_output(["git","-C",r,"rev-list","--reverse","--first-parent","origin/main","--",p],text=True).split(); hits=[c for c in cs if m.encode() in subprocess.check_output(["git","-C",r,"show",f"{c}:{p}"])]; print(hits[0] if hits else "")' $authorityRepo $marker $handoff).Trim()
if($LASTEXITCODE -ne 0 -or $authorityCommit -notmatch '^[0-9a-f]{40}$' -or (git -C $authorityRepo rev-parse origin/main).Trim() -ne $authorityCommit){throw 'Compensated transition authority is absent or stale.'}
git -C $authorityRepo checkout --detach $authorityCommit
if($LASTEXITCODE -ne 0){throw 'Authority checkout failed.'}
$handoffSha=(& python -c 'import hashlib,subprocess,sys; print(hashlib.sha256(subprocess.check_output(["git","-C",sys.argv[1],"show",sys.argv[2]+":"+sys.argv[3]])).hexdigest())' $authorityRepo $authorityCommit $handoff).Trim()
if($LASTEXITCODE -ne 0 -or $handoffSha -notmatch '^[0-9a-f]{64}$'){throw 'Handoff digest resolution failed.'}
$late='C:\code\backups\AR-local-pi5\evidence\NATURAL-20260830-LATE-VALIDATION\20260830T013500+1000'
$evidence=@{
 'validation-summary.json'='5e10dcbee493465e2d898df448d029383d7016d137b89da9efe5a5ecf4e8b800';
 'observation-and-producer.json'='8f2055d0ccb34a25ce1229f5d73fea607804d5f24e647195d01b20b984e6ba61';
 'public-verification.json'='700f756a9676ef4b38f03855e7519ab7cbc72b1c47deeebbb1d4960f7b96c167';
 'ledger-verify.json'='58c4ef3add3aced0a866b6ac54037f258f3fa19d253d82ec89d7f677af2ef63e';
 'service-journal-late.txt'='0c2d373af5673926ac0c1600fa027dafbd52f27b7f923e18560ae66f7755fee5';
 '0500-task-summary-late.json'='6346113a080f61911cbe181e03c577d63d484962ca9fd4335bf5edab42016af7';
 'supplemental-binding-verifier.py'='d11e7df28a61c81aac2998e2ba41691b3f3adb9c616e4f0374356a2c3f5f0759';
 'supplemental-binding.json'='409509bb1b3d677031e15ceab51d591a14b866c012cfd631ebf7dffdba2f6c57';
 'supplemental-command-ledger-v2.json'='452d2858261e8e7434903baccf80252d4c6a2122deec3830ea9c567838770e41'
}
foreach($name in $evidence.Keys){$path=Join-Path $late $name;if(-not(Test-Path -LiteralPath $path -PathType Leaf) -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $evidence[$name]){throw "Compensating evidence mismatch: $name"}}
if(@(git -C $authorityRepo status --porcelain=v1).Count -ne 0 -or @(git -C $receiver status --porcelain=v1).Count -ne 0 -or (git -C $receiver rev-parse HEAD).Trim() -ne $candidate){throw 'Transition checkout identity failed.'}
$python=(Get-Command python -ErrorAction Stop).Source;$oldPython='C:\Users\jkoka\.pyenv\pyenv-win\shims\python.bat';$oldXml='C:\code\backups\AR-local-pi5\evidence\A3-V14-TASK-TRANSITION-20260828\20260828T080004+1000\installed-task.xml'
& $python "$receiver\laptop_backup_transition.py" --target $target `
 --recovery-image 'C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21' `
 --receiver $receiver --old-receiver $oldReceiver --old-task-xml $oldXml `
 --candidate-code-sha $candidate --old-candidate-code-sha 'f214e3249c7968d574e3449edb14792904e1cc1f' `
 --protected-code-sha $expectedPi --plan-git-commit '14dd066099bba393cccf61a280243e43162eedc9' `
 --plan-sha256 '78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713' `
 --authority-repo $authorityRepo --authority-commit $authorityCommit --handoff-sha256 $handoffSha `
 --expected-observation-date '2026-08-30' --operator 'jkoka' --principal 'yanniedog\jkoka' `
 --python-path $python --old-python-path $oldPython --task-name 'AR-local laptop backup' `
 --deadline '2026-08-30T22:00:00+10:00' --host 'ar-local-pi5-lan' `
 --accepted-old-xml-sha256 'aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2'
if($LASTEXITCODE -ne 0){throw 'A3 compensated transition did not PASS.'}
```

The transition harness must itself reauthenticate the current task, exact
legacy record, source identities, current observation/control/macro/inventory,
receipts, restoration checks, disk floor, locks, helpers, authority, and
deadline before disabling anything. It must complete foreground backup,
candidate task installation, standalone check-only proof, rollback validation,
closed evidence, and zero residue. On failure use only its authenticated
recovery path. Do not deploy or modify Pi production.

After transition `PASS`, append its exact evidence and bind the 2026-08-31
natural ingest and first candidate-task 05:00 proof. A3 becomes terminal `PASS`
only after that proof; then begin A4 planning automatically in a separate
documentation-only slice. No physical A4 work or Pi deployment is authorized
by this decision.
