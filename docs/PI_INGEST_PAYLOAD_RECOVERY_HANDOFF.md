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

## Entry `HANDOFF-20260830T084500+1000-A3-DEVIATION-AUTHORIZATION`

This append-only addendum records the operator authorization that was omitted
from the already-merged compensated-transition entry above. It does not edit,
rewrite, relabel, or weaken that entry or any completed evidence.

| Field | Value |
|---|---|
| Previous decision merge | `790e6f2cba601d0f2fc8e3b07d04012e3f5dfbef` |
| Previous complete handoff Git-blob SHA-256 | `397f76e6f1b23413f2eec5c9324fa4cdbd16769a120a3038b28f36761a8b75d0` |
| Controlled plan | ARL-OPS-001 v1.4; commit `14dd066099bba393cccf61a280243e43162eedc9`; SHA-256 `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Deviation | Permit the exact compensated A3 laptop-task transition despite the truthfully retained 2026-08-30 timed-preflight `BLOCKED` result. |
| Authorizer | AR-local operator `jkoka` |
| Durable authorization source | Controlled task instruction after disclosure of the procedural miss: “I want you to PROGRESS through the runbook and plan!!!” |
| Executor | Codex, acting unattended except for the unavoidable Windows UAC consent boundary |
| Result | `RUNNING` until the transition harness produces terminal immutable evidence; A3 remains nonterminal until the first natural candidate-task proof on 2026-08-31. |

The authorization is deliberately narrow. It does not waive or relabel the
timed-preflight miss, any evidence hash, UAC, static/runtime preflight,
authenticated rollback, deadline, disk floor, Pi-cleanliness requirement,
2026-08-31 natural-ingest proof, or first natural 05:00 candidate-task proof.
It does not authorize a Pi deployment, a manual/forced ingest, publication
manipulation, or physical A4 implementation.

The only authorized launcher is:

`C:\code\backups\AR-local-pi5\evidence\NATURAL-20260830-LATE-VALIDATION\20260830T013500+1000\run-compensated-a3-transition.ps1`

Its required SHA-256 is
`b0d2ab393b35cf2251c4a8c01706061c75cbbeecfe6661a98f30e7f171ee95c6`.
It resolves this entry's first-parent document-containing commit, requires that
commit to equal current `origin/main`, calculates the complete handoff Git-blob
SHA-256, re-verifies all listed immutable evidence, and invokes the tested
candidate transition harness with the unchanged controlled arguments.

Exact launch block:

```powershell
$ErrorActionPreference='Stop'
$script='C:\code\backups\AR-local-pi5\evidence\NATURAL-20260830-LATE-VALIDATION\20260830T013500+1000\run-compensated-a3-transition.ps1'
$expected='b0d2ab393b35cf2251c4a8c01706061c75cbbeecfe6661a98f30e7f171ee95c6'
if((Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected){throw 'Authorized A3 launcher hash mismatch.'}
$command='$ErrorActionPreference=''Stop'';$script='''+$script.Replace("'","''")+''';$expected='''+$expected+''';if((Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected){throw ''Authorized A3 launcher hash mismatch inside elevated process.''};& $script'
$encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
$process=Start-Process -FilePath 'C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe' -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded)
if($process.ExitCode -ne 0){throw "A3 compensated transition failed with exit code $($process.ExitCode)."}
```

After a transition `PASS`, append the exact transition evidence in a fresh
documentation-only slice and bind the 2026-08-31 natural ingest plus first
natural candidate-task 05:00 proof. Only after that proof may A3 be declared
terminal `PASS` and A4 planning begin. No A4 implementation or Pi deployment
is authorized by this addendum.

## Entry `HANDOFF-20260830T101500+1000-A3-LAUNCHER-REPAIR-AUTHORIZATION`

This append-only entry records the exact failure of the first compensated A3
launcher and authorizes a mechanically repaired launcher. It does not edit or
relabel the preceding authorization, the two UAC `BLOCKED` attempts, or any
completed ingest, publication, or backup evidence.

| Field | Value |
|---|---|
| Previous authority merge | `92c6e9969119ba19807ddf2d4222f3b357aa5e7e` |
| Previous complete handoff Git-blob SHA-256 | `e6f33b976e8252302f93d249687f565d856dcbe12ec64eaf56c87fd781be653e` |
| Controlled plan | ARL-OPS-001 v1.4; commit `14dd066099bba393cccf61a280243e43162eedc9`; SHA-256 `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713` |
| Candidate | `88557b96d4a240dca640285bcb3457751b381667` |
| Protected Pi | `9302890fcc752cbf90da97d597e972c157d913e3` |
| Failed launcher | `run-compensated-a3-transition.ps1`; SHA-256 `b0d2ab393b35cf2251c4a8c01706061c75cbbeecfe6661a98f30e7f171ee95c6` |
| Failure transcript | `compensated-transition-launch-20260830T100742+1000.txt`; SHA-256 `f364db502ecc8d3ed2d0ed73c571c1c93156cd7e8f6cec2cd9d5d643110e1346` |
| Failed-launch result | `FAIL`, before transition-harness invocation and before mutation |
| Operator authorization | AR-local operator `jkoka`, renewed by the controlled task instruction `resume` after the prior UAC boundary was disclosed |
| Result | `RUNNING` until the repaired launcher produces terminal transition evidence |

The failure is reproducible and narrow: the first launcher passed a Python
program through `python.bat -c`. Windows shim argument handling removed the
program's embedded double quotes, producing a Python `SyntaxError` during
authority resolution. The installed task remained Ready and enabled at
candidate `f214e3249c7968d574e3449edb14792904e1cc1f`, with `LastTaskResult=0`;
Pi production remained clean, pinned, idle, and without `daily-ingest.lock`.
No recovery or rollback action was necessary because no mutation began.

The repair replaces only inline `python -c` authority resolution with this
content-addressed helper:

`C:\code\backups\AR-local-pi5\evidence\NATURAL-20260830-LATE-VALIDATION\20260830T013500+1000\resolve-compensated-authority.py`

Required helper SHA-256:
`04478d68491360db2128c6e0417d21b8646122868e1422e3236ed6415893fd19`.
The helper was executed against the preceding marker and reproduced authority
commit `92c6e9969119ba19807ddf2d4222f3b357aa5e7e` and complete handoff digest
`e6f33b976e8252302f93d249687f565d856dcbe12ec64eaf56c87fd781be653e`.

The only authorized repaired launcher is:

`C:\code\backups\AR-local-pi5\evidence\NATURAL-20260830-LATE-VALIDATION\20260830T013500+1000\run-compensated-a3-transition-v2.ps1`

Required launcher SHA-256:
`edf636c63b67e96d08b86b9c886c5b08bfd928a16a7cc69d0c8c2173558f732c`.
It preserves the candidate, protected Pi, plan, deadline, prior-task XML,
receivers, observation date, evidence hashes, transition harness, rollback,
disk, residue, and acceptance gates from the preceding decision. It adds the
failed-attempt evidence, pins and invokes the helper as a file, resolves this
entry's first document-containing commit, and requires that commit to equal
current `origin/main` before any transition mutation.

Exact execution block:

```powershell
$ErrorActionPreference='Stop'
$script='C:\code\backups\AR-local-pi5\evidence\NATURAL-20260830-LATE-VALIDATION\20260830T013500+1000\run-compensated-a3-transition-v2.ps1'
$expected='edf636c63b67e96d08b86b9c886c5b08bfd928a16a7cc69d0c8c2173558f732c'
if((Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected){throw 'Authorized A3 v2 launcher hash mismatch.'}
if(([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
  & $script
  if($LASTEXITCODE -ne 0){throw "A3 v2 transition failed with exit code $LASTEXITCODE."}
}else{
  $command='$ErrorActionPreference=''Stop'';$script='''+$script.Replace("'","''")+''';$expected='''+$expected+''';if((Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected){throw ''Authorized A3 v2 launcher hash mismatch inside elevated process.''};& $script'
  $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
  $process=Start-Process -FilePath 'C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe' -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded)
  if($process.ExitCode -ne 0){throw "A3 v2 transition failed with exit code $($process.ExitCode)."}
}
```

UAC denial remains `BLOCKED`; no privilege workaround is authorized. A3 still
becomes terminal `PASS` only after the 2026-08-31 natural ingest and first
natural candidate-task 05:00 proof. Only then may A4 planning begin. This entry
does not authorize A4 implementation or any Pi production deployment.

## Entry `HANDOFF-20260830T120000+1000-A3-FIXED-DISPATCHER-AUTHORIZATION`

This append-only decision supersedes only the preceding statement that no
privilege workaround is authorised. It does not edit or relabel the prior UAC
attempts, launcher failure, completed ingest/publication/backup evidence, or the
A3 and A4 phase outcomes.

| Field | Value |
|---|---|
| Previous authority merge | `8640ccbbcf9453ada3fc5a28071044d7667c32a5` |
| Previous complete handoff Git-blob SHA-256 | `43ffa1b7d0379d88ecda76fc82831f175140b03e676d9c13a7eb612dd78ad545` |
| New controlled plan | ARL-OPS-001 v1.5 / DOC-05; document-containing commit and controlled digest resolve after this documentation-only PR merges |
| Existing installed receiver | `C:\code\backups\AR-local-pi5-receiver-f214e32` at `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Existing task | `\AR-local laptop backup`; operator `jkoka`; `S4U`; `Limited`; Ready, enabled, `LastTaskResult=0` at last verified inspection |
| Existing task XML SHA-256 | `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2` |
| Existing task SDDL SHA-256 | `029938b17a9fa24fcb50cf31e870aec61e787f6fc91b92f3b04d6505d7287376` |
| Protected Pi | `9302890fcc752cbf90da97d597e972c157d913e3`; no Pi deployment authorised |
| Operator authorisation | `jkoka`, 2026-08-30: “Do whatever is required to NOT require run as administrator ... unless you can set the privileges permanently once” and “If you want me to run ONE command from admin elevated powershell, I can. But I'm not going to hang around to do it multiple times.” |
| A3 result | `RUNNING`; prior repeated-UAC transition route remains `BLOCKED` and must not be retried |
| A4 result | `BLOCKED` pending terminal A3 natural-run evidence |

### Finding and revised decision

The task already runs without elevation, but its definition contains a boot
trigger. Windows can require administrator membership when a boot-trigger task
is created or replaced. Merely adding write permission to this task therefore
does not prove that later definition updates will work non-elevated. A durable
SYSTEM service, highest-privilege task, stored credential, disabled UAC, broad
Task Scheduler ACL, or arbitrary privileged command broker would solve the
wrong problem and create a larger security and recovery boundary.

The controlled solution is the fixed non-elevated dispatcher specified by
ARL-OPS-001 v1.5 D-007. One final elevated, content-addressed bootstrap may
install administrator-write-protected dispatcher bytes and update this exact
task once. The task continues to execute as ordinary `jkoka` using S4U and
`Limited`. All future candidate transitions atomically activate a validated,
hash-bound manifest and never alter Task Scheduler.

### Mandatory implementation order

1. Merge this documentation-only v1.5 authority and calculate its controlled
   digest, document-containing commit, merge commit, and complete handoff hash.
2. From that exact `origin/main`, implement the fixed dispatcher, immutable
   manifests and receipts, atomic pointer, transition lease, one-time bootstrap,
   rollback, non-elevated probe, and tests in a separate code PR.
3. Pass exact-head product CI, security review, substantive feedback disposition,
   thread resolution, and repository merge gates. Recalculate the candidate SHA.
4. Append a new documentation-only execution authorization binding the exact
   merged code, bootstrap bytes and hash, old task XML/SDDL, initial manifest,
   plan and handoff authority, Pi preconditions, deadline, rollback, and one
   self-contained elevated PowerShell command.
5. Outside D-006 freeze, the operator runs that one command once. No preliminary
   or follow-up administrator command may be delegated to the operator.
6. The same transaction must prove the installed state and a fresh non-elevated
   semantic probe or restore the exact old task before its elevated process exits.
7. Codex then performs all routine manifest activation, verification, evidence,
   and recovery commands itself without UAC.

The bootstrap is not authorised during an active ingest, while
`daily-ingest.lock` exists, during the 00:30-through-terminal-validation freeze,
or without a clean/pinned Pi, healthy dashboard, exact old task, at least 50 GiB
free, and rollback evidence. It must never trigger a backup or ingest merely to
test privileges.

### Acceptance and continuation

Implementation is acceptable only when malformed/duplicate-key manifests,
hash and Git mismatches, traversal/reparse paths, replay/downgrade/sequence
errors, expired authority, transition collisions, partial writes, crashes at
each commit boundary, dispatcher/ACL drift, bootstrap failure, and rollback are
tested. The live task must read back with the accepted daily and boot triggers,
S4U/Limited principal, overlap/retry/timeout settings, fixed action, enabled
state, and no privilege increase. Dispatcher code must be non-user-writable;
the active manifest must bind an immutable receiver and launcher and contain no
secret.

A successful bootstrap advances A3 only to the natural-run proof. A3 becomes
terminal `PASS` only after the fixed dispatcher survives the next protected
natural 01:00 ingest boundary and then produces a verified natural 05:00 or
startup backup execution with exact candidate, observation, control, macro,
catalog, restore, residue, Pi-identity, and free-space evidence. A4 begins only
after a later append-only handoff entry records that terminal result.

## Entry `HANDOFF-20260830T161300+1000-A3-FIXED-DISPATCHER-IMPLEMENTED`

This append-only execution authorization continues D-007 and DOC-05 after the
fixed dispatcher implementation merged. It does not edit or relabel any prior
UAC failure, natural-ingest result, backup result, completed evidence, A3
outcome, or A4 gate.

| Field | Value |
|---|---|
| Previous authority merge | `9094a8e115958fcaf2cb36525736bd5e297e6b04` |
| Previous complete handoff Git-blob SHA-256 | `5b434593c4d814569b74df5ee6b86fe740b14a36caff9187ed30fa63ec78936b` |
| Controlled plan | ARL-OPS-001 v1.5 / DOC-05; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Implementation PR | `#560`, squash-merged as `b3408a29add830836dc7ddf2e8016e7ed4a0e8dc` |
| Reviewed implementation head | `cb814c08faaac769548d31b0afb3b60f2481f4b1` |
| Dispatcher source | `laptop_backup_dispatcher.py`; laptop checkout SHA-256 `907772ad32b6b8aa1428f91ccc6ab007c928a1c59087d7352bdec3ed0f785924` |
| Atomic-write module | `laptop_backup_atomic.py`; laptop checkout SHA-256 `89615eb4350afda7e71e5f9c1123928e5434c12bef9ef5a20374a795d9166842` |
| Fixed task runner | `run_laptop_backup_dispatcher.ps1`; laptop checkout SHA-256 `0b021ae8a7c509ec7824e454a257a14af5cfd65477a92ca549f95e3c35be25ab` |
| Elevated installer | `install_laptop_backup_dispatcher.ps1`; laptop checkout SHA-256 `7bd52efc2da79022445b1e20b4f3c831c157932a0c6097795ccc843eda8c0ff7` |
| Installer core | `install_laptop_backup_dispatcher_core.ps1`; laptop checkout SHA-256 `e6ddfabc9d20830b24f820bbd720599e94f56a01ac1daf1a1230c96f10713ea3` |
| Implementation receiver | `C:\code\backups\AR-local-pi5-receiver-b3408a2`, clean and detached at `b3408a29add830836dc7ddf2e8016e7ed4a0e8dc` |
| Initial active runner | Existing proven receiver `C:\code\backups\AR-local-pi5-receiver-f214e32`, clean and detached at `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Initial launcher SHA-256 | `run_laptop_backup_task.ps1`: `e132454f7f206ac3e9e7d463dae74b5cbe0354a42ce70adb430dc48dfc4f7e16` |
| Protected Pi | `9302890fcc752cbf90da97d597e972c157d913e3`; no Pi production change or deployment authorized |
| Existing task identity | `\AR-local laptop backup`; `yanniedog\jkoka`; S4U; Limited; exact accepted XML SHA-256 `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`; exact accepted SDDL SHA-256 `029938b17a9fa24fcb50cf31e870aec61e787f6fc91b92f3b04d6505d7287376` |
| Operator SID | `S-1-5-21-689213601-40760280-3596424081-1001` |
| Verification | Full local repository suite `1306 passed, 11 skipped`; final focused dispatcher/installer suite `16 passed`; exact-head payload-builder CI and bot-feedback gate passed; all substantive review threads received an `Implemented` or reasoned `Declined` disposition and were resolved. Gemini's advisory action exhausted its external quota and is not a deterministic or required gate. |
| A3 result | `RUNNING`; implementation is merged, but bootstrap and natural dispatcher proof remain outstanding |
| A4 result | `BLOCKED` pending terminal A3 evidence |

### Exact continuation authority

After this documentation-only entry merges, Codex shall perform every
non-administrator operation itself. It shall create a fresh clean detached
authority checkout at the exact new `origin/main`, calculate and retain the
complete handoff Git-blob SHA-256, and prepare a canonical initial manifest
whose authority commit is that exact current `origin/main`. No later commit may
intervene before activation.

The manifest is constrained to:

- candidate `f214e3249c7968d574e3449edb14792904e1cc1f` and the initial launcher
  digest above;
- protected Pi `9302890fcc752cbf90da97d597e972c157d913e3`;
- receiver root `C:\code\backups`;
- backup target `C:\code\backups\AR-local-pi5` within allowed target root
  `C:\code\backups`;
- recovery image
  `C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21`
  within allowed recovery root `C:\code\AR-local-pi-image-2026-05-21`;
- the exact non-shim Python executable and digest measured immediately before
  preparation;
- operator `jkoka`, principal `yanniedog\jkoka`, and the SID above; and
- legacy scheduled-run plan commit
  `14dd066099bba393cccf61a280243e43162eedc9`, required by the proven initial
  runner while dispatcher authority itself remains ARL-OPS-001 v1.5.

Before constructing the single elevated command, Codex must run and preserve a
fresh foreground scheduled-backup gate and a separate `--check-only` gate with
the existing proven receiver, require both to return `PASS`, verify the Pi is
clean, pinned and idle with no ingest lock, verify the dashboard, current task,
free-space floor, receiver cleanliness, Python bytes, old XML/SDDL, and absence
of unexplained dispatcher control state, then write a canonical hash-bound gate
record and manifest into a unique append-only evidence directory. A `FAIL`,
`BLOCKED`, ambiguity, active backup, active ingest, freeze, source-identity
mismatch, or less than 50 GiB free stops before elevation.

The operator is then asked to run exactly one self-contained command from an
already elevated Windows PowerShell. That command must authenticate the
installer, installer core, dispatcher, atomic module, runner, manifest, old
task XML/SDDL, authority and Pi preconditions before mutation. The installer
must either return terminal `PASS` after exact task/ACL readback and a fresh
S4U/Limited non-elevated semantic proof, or restore and reauthenticate the exact
old task and quarantine all new state as `ROLLED_BACK`. A preliminary privilege
probe, second elevated command, repeated UAC prompt, stored credential, SYSTEM
task, privileged service, UAC change, broad ACL delegation, manual backup task
trigger, Pi deployment, manual ingest, or publication manipulation is not
authorized.

After bootstrap `PASS`, Codex validates the installed fixed task and dispatcher
without elevation and records the exact evidence and hashes. A3 remains
`RUNNING` until the task survives the next D-006-protected natural 01:00 ingest
and its first natural 05:00 or startup backup execution. A terminal append-only
handoff entry then records A3 `PASS`, `FAIL`, or `BLOCKED`; only `PASS`
authorizes automatic progression to A4 planning. Physical A4 work remains
unauthorized by this entry.

## Entry `HANDOFF-20260830T164500+1000-A3-PS51-BOOTSTRAP-REPAIR`

This append-only entry records the terminal result of the first fixed-dispatcher
bootstrap attempt and authorizes the exact Windows PowerShell 5.1 compatibility
repair. It does not rewrite the preceding implementation entry, reuse its
manifest or command, relabel the failed attempt, weaken D-006/D-007, or advance
A3 or A4.

| Field | Value |
|---|---|
| Previous authority merge | `815919d65a95fbb42c3e1e69b96fd5ceeffb8cb3` |
| Previous complete handoff Git-blob SHA-256 | `647510de4f6325fce2b23f12cf63ccb3edae9d6fc5a6e9e785a44ac7b5cf78e9` |
| Failed manifest | `initial-manifest-v2.json`; SHA-256 `87d1a1a1e2e7626c5e62c191e740dd2657ca78dd4e90ee90a152b22593b304bc`; permanently revoked |
| Failed command evidence | `C:\code\backups\AR-local-pi5\evidence\A3-FIXED-DISPATCHER-BOOTSTRAP-20260830\20260830T161622+1000`; prior command SHA-256 `5f818f2364395ad73c35eb6959ff279995e0213cccedabf6bb57b316182d7dac`; permanently revoked |
| Failed-attempt result | `FAIL` before the first mutation: Windows PowerShell 5.1 rejected the PowerShell 7-only `ConvertFrom-Json -AsHashtable` parameter while parsing the authenticated manifest. |
| Post-failure task | Ready and enabled; S4U/Limited; `LastTaskResult=0`; exact XML SHA-256 `aa539fb4bb2f176b8b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`; exact SDDL SHA-256 `029938b17a9fa24fcb50cf31e870aec61e787f6fc91b92f3b04d6505d7287376`. |
| Post-failure filesystem | Protected dispatcher install root absent; dispatcher control root empty; 143.63 GiB free at inspection. |
| Compatibility PR | `#562`, squash-merged as `b852f272438083489ff75d61b785e7374954b8bc` |
| Reviewed compatibility head | `9ce2c8e0e3737bb8348dce2be2986451053a9a5b` |
| Corrected dispatcher SHA-256 | `bb19cee620e8792dbc2eb015af8f53a7e46afda9414d048eebcd010db3fbdbfc` |
| Corrected installer SHA-256 | `c25446c3490f74b758a448167d814973a3446ea83c3f9c4d2c36efaa50c1795f` |
| Unchanged atomic module SHA-256 | `89615eb4350afda7e71e5f9c1123928e5434c12bef9ef5a20374a795d9166842` |
| Unchanged task runner SHA-256 | `0b021ae8a7c509ec7824e454a257a14af5cfd65477a92ca549f95e3c35be25ab` |
| Unchanged installer core SHA-256 | `e6ddfabc9d20830b24f820bbd720599e94f56a01ac1daf1a1230c96f10713ea3` |
| Verification | Full local suite `1310 passed, 11 skipped`; focused dual-host suite `17 passed`; exact-head Linux payload CI passed; exact-head Windows job required Windows PowerShell major version 5 and passed the dispatcher plus dual-host installer contracts; bot-feedback and Sourcery gates passed; every substantive thread was dispositioned and resolved. Gemini remained advisory and unavailable due its external quota. |
| A3 result | `RUNNING`; no dispatcher was installed and no task transition occurred |
| A4 result | `BLOCKED` pending terminal A3 natural proof |

After this entry merges, Codex shall perform every non-administrator operation
itself. It must create a clean detached implementation receiver at
`b852f272438083489ff75d61b785e7374954b8bc`, a clean detached authority checkout
at the exact new `origin/main`, a new activation ID, a new canonical gate record,
a new canonical manifest, a new unique evidence generation and a new
authenticated command. It must not edit, reactivate or pass forward any prior
gate, activation ID, manifest, command, expiry or failed evidence.

The fresh gate may reuse the completed 2026-08-30 foreground result only after
its source files and execution record are rehash-verified, current
observation/control/macro identities remain equal, and a fresh `--check-only`
run passes. A new data-writing backup is not required merely because the
installer defect occurred after those gates. All Pi, task, receiver, disk,
process, authority, deadline and freeze preflights must be repeated immediately
before preparation and are repeated again inside the corrected installer.

Only the corrected checkout hashes in this entry may be supplied to the
installer. The replacement remains one self-contained invocation in an already
elevated Windows PowerShell. It must return terminal `PASS` after a real
S4U/Limited non-elevated semantic proof, or exact authenticated `ROLLED_BACK`.
The prior attempt made no mutation; this entry nevertheless recognizes the
operator's one-command limit and forbids exploratory or staged elevated probes.
No further administrator command is authorized after the corrected bootstrap.

After corrected bootstrap `PASS`, Codex performs all readback and continuation
work non-elevated. A3 remains `RUNNING` until the next protected natural 01:00
ingest and first natural dispatcher-backed 05:00 or startup backup both pass.
Only a later append-only terminal A3 `PASS` authorizes progression to A4
planning; physical A4 implementation and Pi deployment remain unauthorized.

## Entry `HANDOFF-20260830T165000+1000-A3-XML-HASH-CORRECTION`

This append-only correction supersedes one malformed value in the immediately
preceding entry without editing or relabelling that completed entry.

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260830T165000+1000-A3-XML-HASH-CORRECTION` |
| Previous handoff entry | `HANDOFF-20260830T164500+1000-A3-PS51-BOOTSTRAP-REPAIR` |
| Created, Australia/Hobart | `2026-08-30T16:50:00+10:00` |
| Created, UTC | `2026-08-30T06:50:00Z` |
| Author | Codex unattended for AR-local operator `jkoka` |
| Repository | `yanniedog/AR-local`; documentation-only branch `codex/correct-dispatcher-xml-hash-authority`; reviewed head resolves from this entry's PR and its squash merge becomes the next authority commit |
| Controlling plan | `ARL-OPS-001` v1.5 / DOC-05; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Candidate implementation | Compatibility merge `b852f272438083489ff75d61b785e7374954b8bc`; corrected dispatcher `bb19cee620e8792dbc2eb015af8f53a7e46afda9414d048eebcd010db3fbdbfc`; corrected installer `c25446c3490f74b758a448167d814973a3446ea83c3f9c4d2c36efaa50c1795f` |
| Protected Pi | `9302890fcc752cbf90da97d597e972c157d913e3`; no Pi production change or deployment authorized |
| Correction result | `PASS`; the malformed value is revoked and the correct live-read task digest is authoritative |
| Interrupted preparation result | `BLOCKED` safely before gate preparation, manifest creation, elevation, task mutation, dispatcher installation, or control-state activation |
| A3 result | `RUNNING`; corrected bootstrap and subsequent natural dispatcher proof remain outstanding |
| A4 result | `BLOCKED` pending terminal A3 natural proof |
| Authorization | D-007 and the operator's one-command fixed-dispatcher authorization; this entry authorizes only fresh non-administrator preparation followed by the single corrected bootstrap invocation already allowed by the preceding entry |

| Field | Value |
|---|---|
| Previous authority merge | `35a9903acde4c8ef29158105738d6644f7205c93` |
| Previous complete handoff Git-blob SHA-256 | `363182933a95832c37781d95ee697895e85598aa6e51841e37e13409620bf08b` |
| Incorrect value | The post-failure task row recorded the 65-character string `aa539fb4bb2f176b8b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`. It is not a SHA-256 digest and is revoked. |
| Correct accepted task XML SHA-256 | `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2` |
| Independent live readback | The task remained Ready and enabled with `LastTaskResult=0`; `Get-ArTaskXmlBytes` produced the correct digest above; SDDL remained `029938b17a9fa24fcb50cf31e870aec61e787f6fc91b92f3b04d6505d7287376`; dispatcher install root remained absent and dispatcher control root empty. |
| Discovery result | `BLOCKED` before gate preparation, manifest preparation, elevation or mutation. |
| A3 result | `RUNNING` |
| A4 result | `BLOCKED` pending terminal A3 natural proof |

Every continuation must use only the corrected 64-character digest. After this
entry merges, Codex must create a fresh authority checkout and unique evidence
generation, repeat all preflights, use a new activation ID and manifest, and
preserve this safely blocked preflight as immutable diagnostic evidence. No Pi
deployment, manual ingest, task trigger or publication operation is authorized.

### Current gate state, evidence and exact next action

The accepted legacy task remains `\AR-local laptop backup`, Ready and enabled,
S4U/Limited, with `LastTaskResult=0`. The protected dispatcher install root is
absent and `C:\code\backups\AR-local-pi5\dispatcher-control` is empty. These
read-only observations are the evidence for the safely blocked preparation;
they are not bootstrap evidence and must be measured again into a new unique
evidence generation.

The exact next action after this documentation-only entry is merged is:

1. create a fresh clean detached authority checkout at that exact merge and
   calculate both the complete handoff Git-blob digest and working-file digest;
2. rerun the full Pi, task, disk, process, receiver, Python, authority, deadline
   and D-006 freeze preflights using the corrected 64-character XML digest;
3. reauthenticate the already completed foreground-backup evidence, run a fresh
   `--check-only` gate, and require `PASS`;
4. create a new activation ID, canonical gate record, canonical manifest,
   expiry and unique append-only evidence generation; and
5. provide the operator one final self-contained corrected Windows PowerShell
   invocation using only compatibility merge `b852f272438083489ff75d61b785e7374954b8bc`.

Any mismatch remains `BLOCKED` before elevation. The revoked manifest, command,
activation ID, expiry and malformed digest must never be reused. The corrected
bootstrap must return terminal `PASS` or authenticated `ROLLED_BACK`; no later
administrator command is authorized. On `PASS`, Codex performs all readback and
continuation work non-elevated. A3 still requires the next protected natural
01:00 ingest and first natural dispatcher-backed 05:00 or startup backup before
a later append-only entry may record terminal `PASS` and authorize A4 planning.

## Entry `HANDOFF-20260830T170600+1000-A3-NONADMIN-RUNNER-REDESIGN`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260830T170600+1000-A3-NONADMIN-RUNNER-REDESIGN` |
| Previous handoff entry | `HANDOFF-20260830T165000+1000-A3-XML-HASH-CORRECTION` |
| Created, Australia/Hobart | `2026-08-30T17:06:00+10:00` |
| Created, UTC | `2026-08-30T07:06:00Z` |
| Author | Codex unattended for AR-local operator `jkoka` |
| Previous authority merge | `0efa20cc94be52fd545b0503206eee8e99ff40e9` |
| Previous complete handoff Git-blob SHA-256 | `5ca406ae2fbb989a2476704b465e6fa1ec66ab4664cf27d4e3abc7295b28be8b` |
| Controlling plan | `ARL-OPS-001` v1.5 / DOC-05; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Protected Pi | `9302890fcc752cbf90da97d597e972c157d913e3`; clean, idle, lock absent and dashboard healthy after the incident; no Pi production change or deployment authorized |
| Failed bootstrap result | `FAIL`; never relabelled `PASS` or `ROLLED_BACK` |
| Continuity recovery | `PASS_FOR_CONTINUITY`: legacy task Ready/enabled, `LastTaskResult=0`, next run 2026-08-31 05:00, exact prior XML, original action/triggers/settings and S4U/Limited principal |
| Recovery deviation | `RECOVERED_WITH_SDDL_CANONICALIZATION_DRIFT`; effective ACE set is preserved, but Task Scheduler reordered it and added the auto-inherited descriptor flag |
| A3 result | `RUNNING`; fixed non-administrator runner transition and natural proof remain outstanding |
| A4 result | `BLOCKED` pending terminal A3 `PASS` |
| Operator authorization | “Do whatever is required to NOT require run as administrator” and “I'm not going to hang around to do it multiple times”; the one corrected elevated attempt has been consumed and no further administrator command is authorized |

### Immutable incident evidence

Evidence root:
`C:\code\backups\AR-local-pi5\evidence\A3-FIXED-DISPATCHER-PS51-REPAIR-20260830\20260830T165400+1000`.

- `bootstrap-incident-recovery.json`: SHA-256
  `9bbc5f3d21962b4814a0ab5ee09881f990249fbc23023548c1308bfdf80490b1`;
- terminal failed `bootstrap-result.json`: SHA-256
  `731537206f678ccc42d0e4d0c58ed38472f14d3bc9a99e2fdea949f07ce388d7`;
- authenticated pre-task and restored-task XML: identical SHA-256
  `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`;
- authenticated pre-task SDDL: SHA-256
  `029938b17a9fa24fcb50cf31e870aec61e787f6fc91b92f3b04d6505d7287376`;
- restored live SDDL: SHA-256
  `6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b`.

The pre/post descriptors have the same owner, group and four ACE identities,
types, masks and inherited flags. The only descriptor difference is canonical
ACE ordering plus `DiscretionaryAclAutoInherited`. The task action still points
to `C:\code\backups\AR-local-pi5-receiver-f214e32`, candidate
`f214e3249c7968d574e3449edb14792904e1cc1f`, and protected Pi
`9302890fcc752cbf90da97d597e972c157d913e3`.

### Root cause and retained residue

Three independent defects are recorded:

1. the elevated installer's PowerShell here-string crossed SSH with CRLF line
   endings; Bash reported invalid `set`/`cd` input, and the script did not fail
   closed on that malformed remote program;
2. `icacls` applied container/object-inherit ACEs directly to leaf files after
   removing inheritance, leaving the protected dispatcher files unreadable;
3. rollback incorrectly required raw SDDL string identity after Task Scheduler
   canonicalized the restored descriptor.

`C:\Program Files\AR-local Backup Dispatcher` contains the unreadable failed
installation. It is not referenced by the live task. Dispatcher control state
is empty. The residue must not be used, edited, deleted, or described as an
installed dispatcher. It may be removed only by a later separately authorized
maintenance action; its presence does not affect the legacy task or Pi ingest.

### Append-only deviation decision `D-008`

D-007's administrator-protected fixed dispatcher is withdrawn as the live A3
route. Repeating elevation is prohibited. The replacement preserves the live
task definition and its privilege level and changes only the existing
user-owned runner file that the task already trusts. This does not introduce a
new privilege boundary: the legacy task already executes code from the same
operator-writable checkout.

The non-administrator design shall:

1. leave Task Scheduler XML, SDDL, triggers, principal, action and settings
   unchanged;
2. build and review a small PowerShell 5.1-compatible runner shim plus a
   non-elevated transactional installer in a separate exact-main code PR;
3. hard-bind the shim to an exact clean detached dispatcher checkout, Python
   executable, dispatcher/atomic-module hashes, control root, candidate and
   protected-Pi identities; no manifest may redirect dispatcher code;
4. prepare and activate the strict content-addressed dispatcher manifest before
   replacing the runner, so the legacy runner remains functional until the
   final atomic file replacement;
5. replace only `run_laptop_backup_task.ps1` using same-volume atomic replace,
   retain and hash the exact original as rollback evidence, and make the shim
   fall back to the authenticated original only while no active manifest exists;
6. run a foreground limited-user semantic probe without starting the scheduled
   task; on any failure atomically restore the exact original runner;
7. record the intentional managed checkout modification explicitly instead of
   claiming the legacy receiver is clean; all candidate receivers and the
   dispatcher implementation checkout remain exact, clean and detached;
8. make future candidate changes manifest-only and non-administrator, with
   sequence/replay/expiry/authority/lease/hash/receipt controls unchanged; and
9. add independent drift checks for the shim, implementation bytes, active
   pointer, task XML/SDDL, candidate receiver, residue, catalog and free space.

The primary risk is that the runner and dispatcher launcher are protected from
accidental drift by content hashes and receipts rather than by an administrator
ACL. Compensating controls are the unchanged S4U/Limited task, hard-coded exact
dispatcher hashes, clean detached implementation and candidate checkouts,
atomic replacement and rollback, fail-closed pointer validation, append-only
activation receipts, daily drift evidence and the 50 GiB floor. This trade-off
is explicitly accepted to achieve genuinely unattended operation without UAC.

### Exact continuation and acceptance

After this documentation-only decision merges, create the non-administrator
implementation PR from that exact `origin/main`. Tests must cover PowerShell
5.1, CRLF/LF inputs, unreadable or drifted dispatcher files, malformed and
replayed manifests, missing/partial control state, failure before and after
atomic runner replacement, exact rollback, concurrent task start, laptop
restart boundaries, dirty candidate checkout, stale authority, protected Pi
mismatch, active ingest/lock, freeze, and disk floor.

Outside D-006 freeze, prepare fresh authority, gate, manifest and evidence. The
transition is acceptable only if no backup/task process is active, the Pi is
clean/pinned/idle, the task is Ready and exact, the original runner hash is
authenticated, the manifest activation and foreground semantic probe pass, the
new runner is atomically installed, and a second probe passes through the
installed runner. No task trigger, manual backup, manual ingest, Pi deployment
or publication manipulation is authorized.

A3 remains `RUNNING` after transition. It becomes terminal `PASS` only after
the unchanged task survives the next D-006-protected natural 01:00 ingest and
then produces a verified natural 05:00 or startup dispatcher-backed backup for
that observation. On terminal A3 `PASS`, append a fresh handoff entry and begin
A4 planning automatically; A4 physical implementation remains separately
gated.

## Entry `HANDOFF-20260830T173100+1000-A3-NONADMIN-TRANSITION-AUTHORITY`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260830T173100+1000-A3-NONADMIN-TRANSITION-AUTHORITY` |
| Previous handoff entry | `HANDOFF-20260830T170600+1000-A3-NONADMIN-RUNNER-REDESIGN` |
| Created, Australia/Hobart | `2026-08-30T17:31:00+10:00` |
| Created, UTC | `2026-08-30T07:31:00Z` |
| Author | Codex unattended for AR-local operator `jkoka` |
| Previous authority merge | `572108ffb364ac008635a60c3add7a73bb3cf26e` |
| Previous complete handoff Git-blob SHA-256 | `71c00337db62a7137afc4197c2defc4a46a8d3e6de130aed9f0d0152b64c15cf` |
| Controlling plan | `ARL-OPS-001` v1.5 / DOC-05; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Implementation PR | `#566`; reviewed head `46a267deaadcd6315b428ac96f5d8f9a6c38d452`; squash merge `68faf7e13c650af7b1d713f4a604f9978897ce79` |
| Exact implementation checkout | `C:\code\backups\AR-local-pi5-receiver-68faf7e`; clean and detached at the implementation merge |
| Exact candidate checkout | `C:\code\backups\AR-local-pi5-candidate-f214e32-d008`; clean and detached at `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Protected Pi | `9302890fcc752cbf90da97d597e972c157d913e3`; no Pi production change or deployment authorized |
| Live legacy task | `\AR-local laptop backup`; Ready/enabled, S4U/Limited, `LastTaskResult=0`; XML SHA-256 `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`; recovered SDDL SHA-256 `6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b` |
| Live legacy runner | `C:\code\backups\AR-local-pi5-receiver-f214e32\run_laptop_backup_task.ps1`; SHA-256 `e132454f7f206ac3e9e7d463dae74b5cbe0354a42ce70adb430dc48dfc4f7e16` |
| Verification | Local full suite `1315 passed, 11 skipped`; final focused suites `22 passed`; exact-head Linux full product CI and Windows PowerShell 5.1 dispatcher CI passed; LF-only SSH program was executed read-only against the Pi and returned only `AR_PI_PREFLIGHT_PASS`; two substantive Sourcery findings were implemented and resolved; Gemini remained advisory and unavailable due external quota |
| A3 result | `RUNNING`; live non-administrator transition and natural proof remain outstanding |
| A4 result | `BLOCKED` pending terminal A3 `PASS` |

### Authenticated implementation bytes

The following SHA-256 values are measured from the clean Windows checkout at
the exact implementation merge and are mandatory transition inputs:

| File | SHA-256 |
|---|---|
| `install_laptop_backup_nonadmin_dispatcher.ps1` | `b04fdd59e5b200f712d6f989554ffb5d03065c4b7f24a00694554914b52880a5` |
| `install_laptop_backup_nonadmin_dispatcher_core.ps1` | `28e30fe8680d83de883e104f0d87364cd16d9572da5b9b5357f2704e303aaaaa` |
| `install_laptop_backup_dispatcher_core.ps1` | `e6ddfabc9d20830b24f820bbd720599e94f56a01ac1daf1a1230c96f10713ea3` |
| `run_laptop_backup_nonadmin_dispatcher.ps1` template | `48eed68e1e172aebad810d40de0eae8f5f57076036ac531e6aab8bc2cf2421e7` |
| `laptop_backup_dispatcher.py` | `bb19cee620e8792dbc2eb015af8f53a7e46afda9414d048eebcd010db3fbdbfc` |
| `laptop_backup_atomic.py` | `89615eb4350afda7e71e5f9c1123928e5434c12bef9ef5a20374a795d9166842` |
| Python 3.10.9 executable | `53e910971cbb20c3223cc44c696254ccfba9595dc4be8e16f56f6c954fff831f` |

### Exact transition authority

After this documentation-only entry merges, Codex shall perform every command
itself in the ordinary, non-administrator `yanniedog\jkoka` token. No UAC,
administrator PowerShell, task registration, task trigger, service restart,
manual backup, manual ingest, Pi deployment or publication manipulation is
authorized.

Codex must create a fresh clean detached authority checkout at the exact new
`origin/main` and calculate both the complete handoff Git-blob SHA-256 and the
working-file SHA-256. It must then create a new unique append-only evidence
generation, activation ID, exact gate, strict initial manifest and canonical
runner configuration. No artifact from either failed elevated attempt may be
reactivated or reused.

The manifest must bind:

- candidate checkout
  `C:\code\backups\AR-local-pi5-candidate-f214e32-d008` at
  `f214e3249c7968d574e3449edb14792904e1cc1f`;
- protected Pi `9302890fcc752cbf90da97d597e972c157d913e3`;
- scheduled plan commit `14dd066099bba393cccf61a280243e43162eedc9`;
- exact non-shim Python and launcher hashes;
- target `C:\code\backups\AR-local-pi5`, recovery image and their existing
  allowed roots; and
- the fresh v1.5 authority merge, handoff working-file digest, gate and expiry.

The runner configuration must bind only the implementation checkout and hashes
above, the non-shim Python bytes, and
`C:\code\backups\AR-local-pi5\dispatcher-control`. Its exact file digest must
be embedded once into the generated managed runner; the generated runner digest
must be calculated before transition and supplied to the transactional
installer.

Immediately before transition, require the Pi clean/pinned/idle with absent
lock and healthy dashboard, task Ready and exact, no backup/dispatcher helper,
control root empty, implementation and candidate checkouts exact/clean/detached,
fresh check-only `PASS`, at least 50 GiB free, current authority unchanged, and
daylight outside D-006 freeze. The retained unreadable Program Files residue is
inert and must remain unreferenced.

The installer must run non-elevated and return terminal `PASS` or
`ROLLED_BACK`. `PASS` requires manifest activation, a `PASS` receipt, canonical
runner configuration, same-volume atomic replacement of only the legacy runner,
an exact preserved legacy-runner backup, a real installed-runner `PROBE` under
the ordinary token, and unchanged task XML/SDDL/state. Any failure restores the
exact legacy runner and empties live dispatcher control state while preserving
diagnostic evidence. A mismatch or ambiguous state is `BLOCKED`; it is never
worked around.

After transition `PASS`, append its exact evidence in a fresh documentation-only
entry and bind the next natural 01:00 ingest plus first natural 05:00 or startup
dispatcher-backed backup. Only those natural proofs make A3 terminal `PASS` and
authorize automatic progression to A4 planning.

## Entry `HANDOFF-20260830T174043+1000-A3-NONADMIN-TRANSITION-PASS`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260830T174043+1000-A3-NONADMIN-TRANSITION-PASS` |
| Previous handoff entry | `HANDOFF-20260830T173100+1000-A3-NONADMIN-TRANSITION-AUTHORITY` |
| Created, Australia/Hobart | `2026-08-30T17:40:43+10:00` |
| Created, UTC | `2026-08-30T07:40:43Z` |
| Author | Codex unattended for AR-local operator `jkoka` |
| Previous authority merge | `2d5ce74eb22fdb5aacaf27b2fe4ea2f6acbacc7b` |
| Previous complete handoff Git-blob SHA-256 | `bd3eb04c1e8175c1756700a064a81e22f3ce49896d73bbd297e44a19667ba059` |
| Previous complete handoff checkout SHA-256 | `a614387ed6620811352d11ce68fa6e8a028f1944104666b8a3c322b05e4a471c` |
| Controlling plan | `ARL-OPS-001` v1.5 / DOC-05; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Implementation | PR `#566`; merge `68faf7e13c650af7b1d713f4a604f9978897ce79`; clean detached checkout `C:\code\backups\AR-local-pi5-receiver-68faf7e` |
| Candidate | Clean detached checkout `C:\code\backups\AR-local-pi5-candidate-f214e32-d008` at `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Protected Pi | Clean, pinned and unchanged at `9302890fcc752cbf90da97d597e972c157d913e3`; ingest inactive; lock absent; timer enabled/active; dashboard healthy |
| In-flight scheduled plan identity | `ARL-OPS-001` v1.4; commit `14dd066099bba393cccf61a280243e43162eedc9`; controlled SHA-256 `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713`; normalized raw SHA-256 `c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4` |
| Current phase | `A3 — non-administrator transition complete; first natural dispatcher-backed proof pending` |
| Completed gates | D-008 design and implementation merged/reviewed; non-admin transactional transition `PASS`; independent post-transition validation `PASS` |
| Open gates | Natural `2026-08-31` 01:00 ingest; first subsequent natural dispatcher-backed backup; append-only A3 terminal decision |
| Prohibited advancement | A4 planning and implementation, and all Pi deployment/runtime remediation, remain blocked until terminal A3 `PASS` |
| Transition result | `PASS` under the ordinary non-administrator token; Task Scheduler was not changed or triggered |
| A3 result | `RUNNING`; transition passed, but the first D-006-protected natural ingest and natural dispatcher-backed backup remain mandatory |
| A4 result | `BLOCKED` pending terminal A3 `PASS` |

### Immutable transition evidence

The unique evidence root is:

`C:\code\backups\AR-local-pi5\evidence\A3-NONADMIN-DISPATCHER-TRANSITION-20260830\20260830T173300+1000`

The transactional installer ran non-elevated and returned `PASS`. It atomically
replaced only the operator-owned legacy runner, preserved the exact old runner,
activated the authenticated manifest, wrote the `PASS` activation receipt,
executed a real installed-runner `PROBE`, and proved that the scheduled task
remained byte-for-byte and security-descriptor equivalent to its prestate.

| Evidence | Bytes | SHA-256 |
|---|---:|---|
| `executions\20260830T073534Z-0c1227d91c934fa093ed8c0c2f09da1b\transition-result.json` | `8844` | `7b8a8c6eb8a1465fa25e97f57077f84c014ddd3a5a7dfc7e8ccc6034f898cb05` |
| `executions\20260830T073534Z-0c1227d91c934fa093ed8c0c2f09da1b\installed-runner-probe.txt` | `284` | `76334d6008997542742469570ef6bbe60f70899ea7340611ee5428b0db1938d4` |
| `post-transition-validation.json` | `3201` | `5929c550e9b99c3f16f1a4c5456a52c22f7d2ec991f1df0abf99019764a534ba` |
| `post-transition-validate.ps1` | `8893` | `c3ea20afb0ee7a4ecfba2dbcaef34e6ba581bafe7e2621f78142e93dff2a15d9` |
| `initial-manifest.json` | `1861` | `af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092` |
| `runner-config.json` | `572` | `b4597ca8c2e4bf205f2c92e904ee9a33b762fc0f5badfc012689635a3023dc00` |
| `gate-evidence.json` | `619` | `9a7943550de7cfd5c8ced37414be78aa300e898ca1b5d103ab25d5c659c986a3` |

The independent post-transition validation at
`2026-08-30T17:40:06.9811842+10:00` returned `PASS` and proved:

- task `\AR-local laptop backup` is Ready/enabled with `LastTaskResult=0`;
- task XML SHA-256 remains
  `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`;
- task SDDL SHA-256 remains
  `6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b`;
- the managed runner SHA-256 is
  `dd642c7ce8520494104abe9c66f2b0cab9ea9864bc7368e45396f618d67952b8`;
- the live activation points to manifest
  `af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092`,
  sequence `1`, with a `PASS` receipt;
- the real installed-runner probe returned `PASS`, `is_admin=false`, candidate
  `f214e3249c7968d574e3449edb14792904e1cc1f`, and the exact manifest above;
- implementation and candidate checkouts are clean, detached and exact;
- no backup or dispatcher helper remained active;
- laptop free space was `156235186176` bytes, above the 50 GiB floor; and
- Pi production remained pinned, clean, idle, unlocked, timer-active and
  dashboard-healthy.

Two non-mutating verification-wrapper defects are retained, not relabelled: the
first wrapper used invalid `Select-Object -Single`; the corrected wrapper first
lacked a local byte-array hashing helper. Both stopped before writing a result,
made no runtime transition, and were corrected in the hashed validation script
above. The underlying transition and both installed-runner probes passed.

### Latest validated observation, catalog and independent states

The latest validated laptop observation remains the independently proven
natural `2026-08-30` observation
`obs-2026-08-30-69a34aa4c745bb2e`. The ingest's late-timed procedure remains
`BLOCKED` because its pre-start gate was not contemporaneous; the captured
observation itself remains valid and is not relabelled.

| State | Exact current identity and result |
|---|---|
| Capture | `PASS`, one natural systemd invocation; 3,841 raw attempts; 119/119 providers attempted; 112 complete, seven partial, zero failed; 17 attributable failures; zero corrupt/unattributed |
| Finalization | `PASS`; generation `obs-2026-08-30-69a34aa4c745bb2e`; 3,012 products; 17,050 rates; SQLite SHA-256 `f246fd77d3215ac631e7c0255ba550f9bfb6e49f0e9c866041040f740fa6f834`; `quick_check=ok` |
| Publication | Dated v1, rolling v1, every referenced asset and dates index independently matched Pi staging; individual gaps disclosed; v2 remains an independent stale/failing state and is not relabelled |
| Dashboard | `PASS`; automatically returned after ingest and is currently healthy |
| Backup | Observation `PASS` at catalog sequence `332`; archive SHA-256 `abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b`; old-task natural backup already passed, while first managed-dispatcher natural backup is `NOT_STARTED` |
| Current control | `PASS` at catalog sequence `335`; source manifest `14acb3481a4a103ecff9f0a8d259b75c01f404def127305bc7e40ed3391d4d64` |
| Current macro | `PASS` at catalog sequence `336`; source manifest `1949485d4f1c1e5b294eb4914d84967b6689a4f8221d1f7dba9ef3e2b5ad0381` |
| Catalog | Append-only through sequence `336`; `generations.jsonl` is `236234` bytes, SHA-256 `7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511` |
| Latest check-only record | `PASS/NO_BACKUP_DATA_WRITE`, completed `2026-08-30T07:35:43Z`; candidate `f214e3249c7968d574e3449edb14792904e1cc1f`; protected SHA `9302890fcc752cbf90da97d597e972c157d913e3`; scheduled plan commit `14dd066099bba393cccf61a280243e43162eedc9` |

The authoritative observation receipt is
`C:\code\backups\AR-local-pi5\observations\2026-08-30\f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d\receipt.json`,
`3392` bytes, SHA-256
`7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea`.
The current pointer hashes are: `latest-verified.json`
`737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389`,
`latest-control.json`
`1ae3cf71760511dd49ded2c50f13632ac519058c0fb7600e59be4aeb5386b4e7`,
`latest-macro.json`
`d63bd59482dbac9b7a76efe5aa960e5cfe6085cafc6242c7d49b7bd3ed307135`,
and `latest-scheduled.json`
`d18ea4b6f29008a00d810b86be656ce1dfaa7f854b3e50c437d8ac72f2bca1f4`.

### Exact completed commands and mutation boundary

The exact non-administrator transition command, LF-only Pi preflight command,
timestamps, operator, plan/candidate/protected identities, deviations and all
evidence paths are embedded without abbreviation in `exact_commands` within
the immutable `transition-result.json` above. The exact independent validation
command was:

```powershell
& 'C:\code\backups\AR-local-pi5\evidence\A3-NONADMIN-DISPATCHER-TRANSITION-20260830\20260830T173300+1000\post-transition-validate.ps1'
```

No task trigger, backup run, ingest, service change, deployment or publication
mutation was performed by validation. The only authorized live mutation was
the transactional, same-volume replacement of the operator-owned runner and
activation of its append-only dispatcher control records.

### Mandatory natural proof and next authority

Exact next action: at `2026-08-31T00:25:00+10:00`, create one unique evidence
generation, record `ACTIVE_EVIDENCE_PATH.txt`, and execute these read-only
preflight commands under the ordinary token. Earliest start is 00:20; the first
gate must finish by 00:30. The second gate starts at 00:55 and must finish before
01:00. The natural ingest may run to terminal completion; there is no arbitrary
kill deadline. The natural backup validation starts at 05:15 and must not
trigger the task.

The approved LF-terminated UTF-8 bytes of the following fenced block are
`10702` bytes with SHA-256
`d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a`.
Do not copy it manually. Extract it from this file in the exact authority merge
using the authenticated command below, require that published digest, and
create `timed-preflight.ps1` exclusively inside the unique evidence directory.
Invoke it first with `-Phase 0025`, then invoke that same hash-bound file with
`-Phase 0055`. Both invocations persist their complete local and Pi results and
SHA-256 manifests; console-only evidence is invalid.

```powershell
param(
  [Parameter(Mandatory=$true)][ValidateSet('0025','0055')][string]$Phase,
  [Parameter(Mandatory=$true)][string]$EvidenceRoot
)
$ErrorActionPreference='Stop'
$EvidenceRoot=[IO.Path]::GetFullPath($EvidenceRoot)
$parent='C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831'
$active=Join-Path $parent 'ACTIVE_EVIDENCE_PATH.txt'
if(-not $EvidenceRoot.StartsWith([IO.Path]::GetFullPath($parent)+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Evidence root escaped its parent.'}
if([IO.Path]::GetFullPath((Get-Content -LiteralPath $active -Raw).Trim()) -cne $EvidenceRoot){throw 'Active evidence pointer mismatch.'}
$scriptHash=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
function Write-NewText([string]$Path,[string]$Text){
  $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try{$writer=[IO.StreamWriter]::new($stream,[Text.UTF8Encoding]::new($false));try{$writer.Write($Text)}finally{$writer.Dispose()}}finally{if($stream){$stream.Dispose()}}
}
$phasePaths=@("$Phase-local.json","$Phase-pi.txt","$Phase-values.json","$Phase-hashes.json")|ForEach-Object{Join-Path $EvidenceRoot $_}
if(@($phasePaths|Where-Object{Test-Path -LiteralPath $_}).Count-ne 0){throw "Evidence for phase $Phase already exists; never overwrite or retry in place."}
if($Phase -eq '0055'){
  $recorded=Get-Content -LiteralPath (Join-Path $EvidenceRoot '0025-hashes.json') -Raw|ConvertFrom-Json
  if($recorded.script_sha256 -cne $scriptHash){throw 'Timed-preflight source changed between gates.'}
}
function Hash-Bytes([byte[]]$Bytes){$h=[Security.Cryptography.SHA256]::Create();try{([BitConverter]::ToString($h.ComputeHash($Bytes))-replace'-','').ToLowerInvariant()}finally{$h.Dispose()}}
function Hash-Text([string]$Text){Hash-Bytes ([Text.UTF8Encoding]::new($false).GetBytes($Text))}
function Exact-Checkout([string]$Path,[string]$Head){
  if((git -C $Path rev-parse HEAD).Trim() -cne $Head -or @(git -C $Path status --porcelain=v1).Count -ne 0){throw "Checkout drift: $Path"}
  git -C $Path symbolic-ref -q HEAD 2>$null|Out-Null;if($LASTEXITCODE -ne 1){throw "Checkout not detached: $Path"}
}
$implementation='C:\code\backups\AR-local-pi5-receiver-68faf7e'
$candidate='C:\code\backups\AR-local-pi5-candidate-f214e32-d008'
$receiver='C:\code\backups\AR-local-pi5-receiver-f214e32'
$control='C:\code\backups\AR-local-pi5\dispatcher-control'
Exact-Checkout $implementation '68faf7e13c650af7b1d713f4a604f9978897ce79'
Exact-Checkout $candidate 'f214e3249c7968d574e3449edb14792904e1cc1f'
$receiverStatus=@(git -C $receiver status --porcelain=v1)
if($receiverStatus.Count-ne 1-or$receiverStatus[0]-cne ' M run_laptop_backup_task.ps1'){throw 'Legacy receiver drift beyond managed runner.'}
$task=Get-ScheduledTask -TaskName 'AR-local laptop backup' -ErrorAction Stop
$taskInfo=Get-ScheduledTaskInfo -TaskName 'AR-local laptop backup' -ErrorAction Stop
$xml=Export-ScheduledTask -TaskName 'AR-local laptop backup' -ErrorAction Stop
$xmlHash=Hash-Bytes ([byte[]](0xff,0xfe)+[Text.Encoding]::Unicode.GetBytes($xml))
$svc=New-Object -ComObject 'Schedule.Service';$svc.Connect();$sddl=$svc.GetFolder('\').GetTask('\AR-local laptop backup').GetSecurityDescriptor(7)
$sddlHash=Hash-Text $sddl
$runner=Join-Path $receiver 'run_laptop_backup_task.ps1'
$manifestHash='af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092'
$config=Join-Path $control 'runner-config.json';$manifest=Join-Path $control "manifests\$manifestHash.json";$pointer=Join-Path $control 'active-runner.json'
$receipt=Join-Path $control 'activation-receipts\00000001-37f93247c88144699631d364c6ac0dee-pass.json'
if([string]$task.State -cne 'Ready' -or -not $task.Settings.Enabled -or $taskInfo.LastTaskResult -ne 0 -or
   $xmlHash -cne 'aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2' -or
   $sddlHash -cne '6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b' -or
   (Get-FileHash $runner -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'dd642c7ce8520494104abe9c66f2b0cab9ea9864bc7368e45396f618d67952b8' -or
   (Get-FileHash $config -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'b4597ca8c2e4bf205f2c92e904ee9a33b762fc0f5badfc012689635a3023dc00' -or
   (Get-FileHash $manifest -Algorithm SHA256).Hash.ToLowerInvariant() -cne $manifestHash -or
   (Get-FileHash $receipt -Algorithm SHA256).Hash.ToLowerInvariant() -cne '7d122e9f96ec22940081fe6ddaa4e54c22a89fea0187cee906b2a09e26233e8b') {throw 'Authenticated task/dispatcher state drift.'}
$p=Get-Content $pointer -Raw|ConvertFrom-Json;$m=Get-Content $manifest -Raw|ConvertFrom-Json;$r=Get-Content $receipt -Raw|ConvertFrom-Json
if($p.manifest_sha256 -cne $manifestHash -or $p.sequence -ne 1 -or $r.status -cne 'PASS' -or $r.manifest_sha256 -cne $manifestHash -or
   $m.candidate_code_sha -cne 'f214e3249c7968d574e3449edb14792904e1cc1f' -or $m.protected_code_sha -cne '9302890fcc752cbf90da97d597e972c157d913e3'){throw 'Authenticated activation state drift.'}
$helpers=@(Get-CimInstance Win32_Process|Where-Object{$_.ProcessId-ne$PID-and$_.CommandLine-and$_.CommandLine-match'(laptop_backup_(scheduled|dispatcher|atomic)|run_laptop_backup_task)'})
$free=(Get-PSDrive C).Free;if($helpers.Count-ne 0-or$free-lt 50GB){throw 'Laptop process or capacity gate failed.'}
$local=[ordered]@{observed_at=[DateTimeOffset]::Now.ToString('o');phase=$Phase;task_state=[string]$task.State;last_result=[int]$taskInfo.LastTaskResult;task_xml_sha256=$xmlHash;task_sddl_sha256=$sddlHash;runner_sha256=(Get-FileHash $runner -Algorithm SHA256).Hash.ToLowerInvariant();config_sha256=(Get-FileHash $config -Algorithm SHA256).Hash.ToLowerInvariant();manifest_sha256=$manifestHash;receipt_sha256=(Get-FileHash $receipt -Algorithm SHA256).Hash.ToLowerInvariant();implementation='68faf7e13c650af7b1d713f4a604f9978897ce79';candidate='f214e3249c7968d574e3449edb14792904e1cc1f';free_bytes=[int64]$free;helper_count=$helpers.Count}
Write-NewText (Join-Path $EvidenceRoot "$Phase-local.json") (($local|ConvertTo-Json -Depth 8)+"`n")
$remote=@'
set -eu
cd /srv/ar-local/AR-local
echo "observed_at=$(date --iso-8601=seconds)"
echo "head=$(git rev-parse HEAD)"
if test -z "$(git status --porcelain=v1)";then echo checkout_clean=true;else echo checkout_clean=false;exit 40;fi
echo "timer_enabled=$(systemctl is-enabled ar-local-daily.timer)"
echo "timer_active=$(systemctl is-active ar-local-daily.timer)"
echo "timer_next=$(systemctl show ar-local-daily.timer -p NextElapseUSecRealtime --value)"
echo "timer_last=$(systemctl show ar-local-daily.timer -p LastTriggerUSec --value)"
echo "service_active=$(systemctl is-active ar-local-daily.service)"
echo "service_invocation=$(systemctl show ar-local-daily.service -p InvocationID --value)"
echo "service_restarts=$(systemctl show ar-local-daily.service -p NRestarts --value)"
if test -e /srv/ar-local/data/state/daily-ingest.lock;then echo lock=PRESENT;exit 42;else echo lock=ABSENT;fi
if pgrep -f '[p]i_daily_sync.py|[c]dr_daily.py' >/dev/null;then echo competing_process=PRESENT;exit 43;else echo competing_process=ABSENT;fi
disk=$(df -B1 --output=avail /srv/ar-local/data|tail -1|tr -d ' ');mem=$(free -b|awk '/^Mem:/ {print $7}');swap=$(free -b|awk '/^Swap:/ {print $4}')
echo "disk_available_bytes=$disk";echo "memory_available_bytes=$mem";echo "swap_free_bytes=$swap"
test "$disk" -ge 10737418240;test "$mem" -ge 268435456;test "$swap" -ge 67108864
journal_file=$(mktemp);trap 'rm -f "$journal_file"' EXIT
if ! journalctl -k --since '24 hours ago' --no-pager >"$journal_file";then echo journal_read=FAILED;exit 45;fi
echo journal_read=PASS
if grep -Eiq 'oom|out of memory|killed process' "$journal_file";then echo oom_recent=PRESENT;exit 44;else echo oom_recent=ABSENT;fi
test "$(systemctl show ar-local-daily.timer -p NextElapseUSecRealtime --value)" = 'Mon 2026-08-31 01:00:00 AEST'
curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest|python3 -c "import json,sys;v=json.load(sys.stdin);b=v.get('banks_counts')or{};assert v.get('run_date')=='2026-08-30';assert int(b.get('products',0))>0;assert int(b.get('rates',0))>0"
echo dashboard=HEALTHY
http=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' https://api.github.com/);echo "github_http=$http";test "$http" = 200
echo AR_PI_NATURAL_PREFLIGHT_PASS
'@ -replace "`r",''
$output=@($remote|ssh -o BatchMode=yes -o ConnectTimeout=10 ar-local-pi5-lan bash -s)
$sshExit=$LASTEXITCODE;Write-NewText (Join-Path $EvidenceRoot "$Phase-pi.txt") (($output-join"`n")+"`n")
if($sshExit-ne 0-or($output-join"`n")-notmatch'AR_PI_NATURAL_PREFLIGHT_PASS'){throw "$Phase Pi gate failed."}
$values=[ordered]@{};foreach($line in $output){$pair=$line-split'=',2;if($pair.Count-eq 2){$values[$pair[0]]=$pair[1]}}
$observed=[DateTimeOffset]::Parse($values.observed_at)
if($Phase-eq'0025'){$min=[DateTimeOffset]'2026-08-31T00:20:00+10:00';$max=[DateTimeOffset]'2026-08-31T00:30:00+10:00'}else{$min=[DateTimeOffset]'2026-08-31T00:55:00+10:00';$max=[DateTimeOffset]'2026-08-31T01:00:00+10:00'}
if($observed-lt$min-or$observed-ge$max-or$values.head-cne'9302890fcc752cbf90da97d597e972c157d913e3'-or$values.checkout_clean-cne'true'-or
   $values.timer_enabled-cne'enabled'-or$values.timer_active-cne'active'-or$values.timer_next-cne'Mon 2026-08-31 01:00:00 AEST'-or
   $values.service_active-cne'inactive'-or[int]$values.service_restarts-ne 0-or$values.lock-cne'ABSENT'-or$values.competing_process-cne'ABSENT'-or
   [int64]$values.disk_available_bytes-lt 10737418240-or[int64]$values.memory_available_bytes-lt 268435456-or[int64]$values.swap_free_bytes-lt 67108864-or
   $values.journal_read-cne'PASS'-or$values.oom_recent-cne'ABSENT'-or$values.dashboard-cne'HEALTHY'-or$values.github_http-cne'200'){throw "$Phase fail-closed value gate failed."}
if($Phase-eq'0055'){$baseline=Get-Content (Join-Path $EvidenceRoot '0025-values.json') -Raw|ConvertFrom-Json;if($values.timer_last-cne$baseline.timer_last-or$values.service_invocation-cne$baseline.service_invocation){throw 'Timer/service baseline changed before natural start.'}}
Write-NewText (Join-Path $EvidenceRoot "$Phase-values.json") (($values|ConvertTo-Json -Depth 5)+"`n")
$hashes=[ordered]@{script_sha256=$scriptHash;local_sha256=(Get-FileHash (Join-Path $EvidenceRoot "$Phase-local.json") -Algorithm SHA256).Hash.ToLowerInvariant();pi_sha256=(Get-FileHash (Join-Path $EvidenceRoot "$Phase-pi.txt") -Algorithm SHA256).Hash.ToLowerInvariant();values_sha256=(Get-FileHash (Join-Path $EvidenceRoot "$Phase-values.json") -Algorithm SHA256).Hash.ToLowerInvariant();completed_at=[DateTimeOffset]::Now.ToString('o');result='PASS'}
Write-NewText (Join-Path $EvidenceRoot "$Phase-hashes.json") (($hashes|ConvertTo-Json)+"`n")
$hashes|ConvertTo-Json
```

Before the first invocation, create the evidence generation and active pointer
exactly once; never reuse a previous directory:

```powershell
$parent='C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831';New-Item -ItemType Directory -Force $parent|Out-Null
$root=Join-Path $parent ([DateTimeOffset]::Now.ToString('yyyyMMddTHHmmsszzz').Replace(':',''));if(Test-Path (Join-Path $parent 'ACTIVE_EVIDENCE_PATH.txt')){throw 'Active evidence already exists.'};New-Item -ItemType Directory $root|Out-Null
[IO.File]::WriteAllText((Join-Path $parent 'ACTIVE_EVIDENCE_PATH.txt'),$root,[Text.UTF8Encoding]::new($false))
$authorityRepo='<clean authority checkout>';$authorityCommit='<document-containing merge commit>';$scriptPath=Join-Path $root 'timed-preflight.ps1'
python -c "import hashlib,re,subprocess,sys;b=subprocess.check_output(['git','-C',sys.argv[1],'show',sys.argv[2]+':docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md']).replace(b'\r\n',b'\n');m=re.findall(br'```powershell\n(param\(.*?AR_PI_NATURAL_PREFLIGHT_PASS.*?)(?=\n```)',b,re.S);assert len(m)==1;out=m[0]+b'\n';assert len(out)==10702 and hashlib.sha256(out).hexdigest()=='d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a';open(sys.argv[3],'xb').write(out)" $authorityRepo $authorityCommit $scriptPath
if($LASTEXITCODE-ne 0){throw 'Approved timed-preflight extraction failed.'}
& "$root\timed-preflight.ps1" -Phase 0025 -EvidenceRoot $root
```

At 00:55 recover the one active pointer and run the same authenticated file:

```powershell
$parent='C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831';$root=(Get-Content (Join-Path $parent 'ACTIVE_EVIDENCE_PATH.txt') -Raw).Trim()
& "$root\timed-preflight.ps1" -Phase 0055 -EvidenceRoot $root
ssh ar-local-pi5-lan systemctl show ar-local-daily.service -p ActiveState -p SubState -p Result -p ExecMainStatus -p NRestarts -p InvocationID -p ActiveEnterTimestamp -p InactiveEnterTimestamp
ssh ar-local-pi5-lan journalctl -fu ar-local-daily.service --since '2026-08-31 00:55:00' --no-pager
```

After terminal service completion, use fresh, hash-recorded verifier source to
run the repository's observation, ledger, SQLite/provider and public-byte
verification paths against date `2026-08-31`; never infer publication success
from producer logs. At 05:15 inspect `Get-ScheduledTaskInfo`, every immutable
`catalog\scheduled-runs\*.json` after the recorded baseline, dispatcher
execution records and activation receipt; do not call `Start-ScheduledTask` or
the managed runner.

D-006 remains absolute. From `2026-08-31T00:30:00+10:00` through terminal
validation of the natural ingest, perform no deployment, canary, manual or
forced ingest, service restart, task change or trigger, package change, backup,
or publication manipulation. Execute the established fail-closed read-only
preflight before the freeze and again before 01:00, observe exactly one natural
`ar-local-daily.service` invocation, and preserve complete raw-attempt,
completion, contract, ledger, pointer, SQLite/provider-accounting, dashboard,
and independently downloaded public GitHub evidence. Product- or
provider-specific gaps must remain attributable and disclosed; they must not
invalidate otherwise valid products. Never rerun ingest for publication-only
failure and never overwrite the previous verified rolling payload.

After the natural ingest terminally validates, do not trigger the Windows task.
Observe its natural 05:00 or startup-plus-five-minute execution. Acceptance
requires the unchanged task to invoke the managed runner above, the dispatcher
to select manifest
`af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092`,
and at least one immutable `BACKUP-LATEST` `PASS` for observation date
`2026-08-31`. Validate every intervening scheduled-run record, exact candidate,
protected and scheduled-plan identities, receipts, catalog append-only hash
chain, restoration checks, Pi source identity equality, absence of locks,
partials, helpers and overlap, Ready/enabled task state with zero result, and at
least 50 GiB free. A later `NO_BACKUP_DATA_WRITE` is acceptable only after the
same observation was already backed up and all identities prove unchanged.

After terminal evidence, append a new documentation-only entry. If both the
natural ingest and first natural dispatcher-backed backup pass, mark A3
terminal `PASS` and immediately begin A4 planning under the controlled runbook.
On any failure or uncertainty, preserve the previous verified payload and
backup, record `FAIL` or `BLOCKED`, and keep A4 blocked. No administrator action
is authorized or required.

### Acceptance, stop, rollback and preservation controls

Accept only one natural 01:00 invocation with successful terminal service,
absent lock, automatic dashboard return, valid raw/marker/contract/ledger/
pointer/database/provider accounting, and independent dated/rolling/index
public bytes. Accept the backup only when a natural task invocation selects the
exact active manifest, produces `PASS/BACKUP-LATEST` for `2026-08-31`, verifies
receipts, restore checks and catalog lineage, and leaves no lock, partial,
helper or overlap with at least 50 GiB free.

Stop immediately and make no mutation if any preflight identity differs, the
lock or service is active before the natural start, the Pi is dirty or not at
the protected SHA, the task/runner/manifest/config differs, disk is below its
floor, a helper exists, or the evidence directory is ambiguous. During the
freeze, observe only. On ingest failure preserve raw attempts, the failed
generation and previous verified rolling payload; do not force or rerun. On
publication-only failure retry no ingest. On backup failure preserve the
existing backup, catalog, dispatcher records, active pointer, exact legacy
runner backup and failed evidence; do not manually trigger.

No automatic rollback is authorized after this recorded transition `PASS`.
Restoring the preserved legacy runner or changing dispatcher activation now
requires a new append-only controlled decision with authenticated bytes and
acceptance criteria. The inert unreadable Program Files residue remains
unreferenced and must not be used or removed during A3.

Known risks are: upstream current-day data disappears at midnight; stable Pi
code lacks later unproven safeguards; the timed preflight has previously been
missed; v2 remains stale independently of v1; the operator-owned managed runner
is intentionally the sole dirty file in its legacy receiver; and the first
natural managed-dispatcher invocation is not yet proven. Deviation D-008 is
explicitly authorized by
`HANDOFF-20260830T170600+1000-A3-NONADMIN-RUNNER-REDESIGN` and the exact
transition authority in the preceding entry. There are no conversational or
unrecorded deviations.

## Entry `HANDOFF-20260830T181625+1000-A3-LATE-REVIEW-CORRECTION`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260830T181625+1000-A3-LATE-REVIEW-CORRECTION` |
| Previous handoff entry | `HANDOFF-20260830T174043+1000-A3-NONADMIN-TRANSITION-PASS` |
| Created, Australia/Hobart | `2026-08-30T18:16:25+10:00` |
| Created, UTC | `2026-08-30T08:16:25Z` |
| Author/operator | Codex unattended for `jkoka` |
| Result | `RUNNING`; natural capture remains protected, but A3 terminal acceptance is blocked pending authenticated terminal verifier source |
| Controlling plan | `ARL-OPS-001` v1.5; commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Previous authority merge | `e6be1eb6127fe290c0c74d56612d99e293c3d3b4` |
| Previous handoff Git-blob bytes/SHA-256 | `320778` / `ca580125605e16c062f016a4b38d60d65d544ecc24f9c7c25674b88786e1c7ec` |
| Protected Pi | `9302890fcc752cbf90da97d597e972c157d913e3`; no deployment or Pi mutation authorized |
| Candidate/managed dispatcher | `f214e3249c7968d574e3449edb14792904e1cc1f`; transition remains independently `PASS` |
| Current phase | A3 natural ingest and first managed-dispatcher backup proof |
| Prohibited advancement | A3 may not be declared `PASS`; A4 may not begin until the verifier gate below is implemented and passed against preserved natural evidence |

### Reason for correction and immutable prior state

Codex review completed after PR #568 merged and produced five substantive late
findings. The merge and the prior entry are never rewritten. These findings do
not invalidate the non-administrator transition, alter the Pi, or justify
missing the irreplaceable current-day capture. They invalidate only use of the
prior resume procedure as sufficient evidence for terminal A3 acceptance.

The latest validated observation remains `obs-2026-08-30-69a34aa4c745bb2e`,
with capture/finalization/v1 publication/dashboard/old-task backup components
independently `PASS`, observation catalog sequence `332`, catalog through
sequence `336`, and v2 independently stale. The prior transition evidence and
hashes remain authoritative and unchanged.

### Late findings, decision and compensating controls

| Finding | Decision | Immediate control |
|---|---|---|
| The 00:55 phase trusted `0025-values.json` without rehashing every 00:25 artifact and requiring the recorded `PASS` | `IMPLEMENTED BY THIS DECISION` | Before phase 0055, rehash the 0025 local, Pi and values files; compare every digest with `0025-hashes.json`; require its `result=PASS`, exact script digest and completion timestamp. Any mismatch is `BLOCKED` before 01:00. |
| A failing SSH/value gate could throw before authenticated failure evidence existed | `IMPLEMENTED BY THIS DECISION` | The unattended caller must capture stdout and stderr separately with create-new files, then create a phase execution record and hash manifest with `FAIL` before throwing. It must never retry the same phase or overwrite evidence. |
| Timed phase records lacked complete controlled execution identity | `IMPLEMENTED BY THIS DECISION` | Each phase execution record must bind plan ID/version/commit/controlled and normalized hashes, this document-containing authority commit and handoff digest, candidate/protected SHA, operator, timestamps, exact command, evidence paths/hashes, result, deviations and authorization. |
| Terminal ingest/public-byte and 05:15 backup instructions were not packaged as approved, machine-checkable verifier source | `DEFERRED, FAIL CLOSED` | Preserve all natural evidence, but do not declare A3 `PASS` from ad-hoc inspection. After capture, add exact verifier source on a reviewed PR, publish its digest in a new entry, then run it against the immutable evidence. |
| Evidence-root creation used check-then-write and non-terminating PowerShell defaults | `IMPLEMENTED BY THIS DECISION` | Set `$ErrorActionPreference='Stop'`; create both generation directory and active pointer with `FileMode.CreateNew`; use a GUID-bearing generation name; reject any existing active pointer and any existing phase artifact. |

The late review comments are evidence on merged PR #568. Their dispositions are
append-only and do not authorize editing completed evidence. The terminal
verifier deferral changes no Pi or public state; it tightens acceptance by
making `BLOCKED` the only lawful outcome until exact source exists.

### Exact unattended capture boundary for 2026-08-31

D-006 and the natural timer remain controlling. The 00:30 freeze and all
read-only Pi/task/resource/timer/process gates in the previous entry remain in
force. Before invoking its 0055 phase, the unattended caller must execute this
additional fail-closed authentication against the unique active evidence root:

Replace the previous entry's evidence bootstrap with this exact exclusive
bootstrap. The retained initialization record is the concurrency lock; never
delete or reuse it.

```powershell
$ErrorActionPreference='Stop';$parent='C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831'
New-Item -ItemType Directory -Path $parent -Force -ErrorAction Stop|Out-Null
$lockPath=Join-Path $parent 'INITIALIZATION.json';$lock=[IO.File]::Open($lockPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try{
 $runId=([DateTimeOffset]::Now.ToString('yyyyMMddTHHmmsszzz').Replace(':',''))+'-'+[guid]::NewGuid().ToString('N');$root=Join-Path $parent $runId
 New-Item -ItemType Directory -Path $root -ErrorAction Stop|Out-Null
 $record=([ordered]@{schema_version=1;plan_document_id='ARL-OPS-001';plan_version='1.5';plan_git_commit='9094a8e115958fcaf2cb36525736bd5e297e6b04';plan_sha256='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada';candidate_code_sha='f214e3249c7968d574e3449edb14792904e1cc1f';protected_code_sha='9302890fcc752cbf90da97d597e972c157d913e3';operator='jkoka';created_at=[DateTimeOffset]::Now.ToString('o');evidence_root=$root;result='RUNNING';deviations=@();deviation_authorization=$null}|ConvertTo-Json -Compress)+"`n"
 $bytes=[Text.UTF8Encoding]::new($false).GetBytes($record);$lock.Write($bytes,0,$bytes.Length);$lock.Flush($true)
 $pointer=Join-Path $parent 'ACTIVE_EVIDENCE_PATH.txt';$stream=[IO.File]::Open($pointer,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
 try{$value=[Text.UTF8Encoding]::new($false).GetBytes($root);$stream.Write($value,0,$value.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}finally{$lock.Dispose()}
```

```powershell
$ErrorActionPreference='Stop'
$parent=[IO.Path]::GetFullPath('C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831')
$failurePath=Join-Path $parent (('0055-auth-failure-'+[guid]::NewGuid().ToString('N')+'.json'))
try{
 $pointer=Join-Path $parent 'ACTIVE_EVIDENCE_PATH.txt';$root=[IO.Path]::GetFullPath((Get-Content $pointer -Raw).Trim())
 if(-not$root.StartsWith($parent+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)-or(Split-Path $root -Leaf)-notmatch'^20260831T[0-9]{6}\+1000-[0-9a-f]{32}$'){throw 'Active evidence root escaped or has an invalid generation identity.'}
 $generations=@(Get-ChildItem -LiteralPath $parent -Directory -ErrorAction Stop|Where-Object{Test-Path (Join-Path $_.FullName '0025-hashes.json') -PathType Leaf})
 if($generations.Count-ne 1-or[IO.Path]::GetFullPath($generations[0].FullName)-cne$root){throw 'Active evidence generation is not uniquely bound.'}
 $scriptPath=Join-Path $root 'timed-preflight.ps1';$approved='d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a'
 if((Get-FileHash $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()-cne$approved){throw 'Current timed-preflight source is unauthenticated.'}
 $manifestPath=Join-Path $root '0025-hashes.json';$manifest=Get-Content $manifestPath -Raw|ConvertFrom-Json
 if($manifest.result-cne'PASS'-or$manifest.script_sha256-cne$approved){throw '00:25 manifest identity failed.'}
 $completed=[DateTimeOffset]::Parse([string]$manifest.completed_at);if($completed.Offset.TotalHours-ne 10-or$completed-lt[DateTimeOffset]'2026-08-31T00:20:00+10:00'-or$completed-ge[DateTimeOffset]'2026-08-31T00:30:00+10:00'){throw '00:25 manifest completion is outside the authorized window.'}
 $expected=@{'0025-local.json'=$manifest.local_sha256;'0025-pi.txt'=$manifest.pi_sha256;'0025-values.json'=$manifest.values_sha256};foreach($name in $expected.Keys){$path=Join-Path $root $name;if(-not(Test-Path $path -PathType Leaf)-or(Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()-cne$expected[$name]){throw "00:25 evidence authentication failed: $name"}}
 $result=[ordered]@{schema_version=1;plan_document_id='ARL-OPS-001';plan_version='1.5';plan_git_commit='9094a8e115958fcaf2cb36525736bd5e297e6b04';plan_sha256='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada';plan_normalized_sha256='f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684';candidate_code_sha='f214e3249c7968d574e3449edb14792904e1cc1f';protected_code_sha='9302890fcc752cbf90da97d597e972c157d913e3';operator='jkoka';timestamps=@{completed_at=[DateTimeOffset]::Now.ToString('o')};exact_commands=@('Authenticate 00:25 manifest, artifacts, completion window and current timed-preflight bytes before phase 0055.');evidence_paths=@($manifestPath,$scriptPath)+@($expected.Keys|ForEach-Object{Join-Path $root $_});result='PASS';deviations=@();deviation_authorization=$null}
 $success=Join-Path $root '0055-baseline-authentication.json';$raw=($result|ConvertTo-Json -Depth 8 -Compress)+"`n";$s=[IO.File]::Open($success,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$b=[Text.UTF8Encoding]::new($false).GetBytes($raw);$s.Write($b,0,$b.Length);$s.Flush($true)}finally{$s.Dispose()}
}catch{
 $record=([ordered]@{schema_version=1;plan_document_id='ARL-OPS-001';plan_version='1.5';plan_git_commit='9094a8e115958fcaf2cb36525736bd5e297e6b04';plan_sha256='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada';candidate_code_sha='f214e3249c7968d574e3449edb14792904e1cc1f';protected_code_sha='9302890fcc752cbf90da97d597e972c157d913e3';operator='jkoka';timestamps=@{failed_at=[DateTimeOffset]::Now.ToString('o')};exact_commands=@('Authenticate 00:25 baseline before phase 0055.');evidence_paths=@();result='FAIL';error=$_.Exception.Message;deviations=@();deviation_authorization=$null}|ConvertTo-Json -Depth 8 -Compress)+"`n";$s=[IO.File]::Open($failurePath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$b=[Text.UTF8Encoding]::new($false).GetBytes($record);$s.Write($b,0,$b.Length);$s.Flush($true)}finally{$s.Dispose()};throw
}
```

The caller must wrap each phase invocation, redirecting stdout and stderr to
new files, and on either success or failure create a new controlled execution
record before returning. The record schema is the runbook's mandatory schema;
omitting a field is `BLOCKED`. Never mark a failed preflight `PASS` merely
because the natural ingest subsequently succeeds.

The natural 01:00 ingest must still be observed and all terminal, database,
provider/product and public-byte evidence must still be collected and hashed.
The natural 05:00 task must still run without manual trigger and its dispatcher,
scheduled record, receipts, catalog, restoration, source identities and residue
must still be collected and hashed. These collected artifacts are diagnostic
and preservation evidence until the reviewed verifier gate passes.

### Stop, preservation and next action

No failure in evidence tooling authorizes interference with the natural ingest.
If a preflight detects an unsafe Pi state before 01:00, record `BLOCKED` and do
not start anything manually. If only the observer/evidence wrapper fails while
the Pi remains safe, continue direct read-only observation, preserve all output,
and retain a procedural `BLOCKED` result. On ingest or publication failure,
preserve raw state and the previous verified rolling payload; never force or
rerun for publication-only failure. On backup failure, preserve the existing
backup/catalog/dispatcher state and never trigger the task manually.

Immediately after the 2026-08-31 evidence is preserved, implement the exact
terminal-ingest/public-byte and natural-backup verifiers as a separate reviewed
non-production tooling PR. The verifier must create its results exclusively,
validate every acceptance condition listed in the previous entry, bind all
controlled identities, and include failure evidence. Append and merge a new
entry containing its source digest before executing it. If both verifiers then
return `PASS`, append A3 terminal `PASS` and begin A4 planning. Until then A4
remains `BLOCKED`.

## Entry `HANDOFF-20260830T195500+1000-A3-TERMINAL-VERIFIER-AUTHORIZATION`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260830T195500+1000-A3-TERMINAL-VERIFIER-AUTHORIZATION` |
| Previous handoff entry | `HANDOFF-20260830T181625+1000-A3-LATE-REVIEW-CORRECTION` |
| Created | `2026-08-30T19:55:00+10:00` / `2026-08-30T09:55:00Z` |
| Author/operator | Codex unattended for `jkoka` |
| Result | `RUNNING`; verifier source is authorized, but A3 is incomplete until both natural verifiers return controlled `PASS` |
| Controlling plan | `ARL-OPS-001` v1.5; commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Verifier code | `8ab4342fb8c9ef7b854988eb393c9a3284d0ebd2`; clean detached checkout required |
| Candidate / protected Pi | `f214e3249c7968d574e3449edb14792904e1cc1f` / `9302890fcc752cbf90da97d597e972c157d913e3` |
| Observation date | `2026-08-31` only |
| Advancement | A4 remains `BLOCKED` until a later immutable entry records terminal A3 `PASS` from both verifier results |

The document-containing merge commit and complete handoff Git-blob SHA-256 are
resolved only after this entry merges. They are mandatory runtime arguments.
The verifier requires `refs/remotes/origin/main` to equal that merge while
`HEAD` is clean, detached, and equal to the verifier code SHA.

### Reviewed source authority

PRs #570 through #575 implemented the verifiers and all substantive review
corrections. Final CI passed with `1326 passed, 11 skipped`; only existing
openpyxl warnings remained. Sourcery had no actionable final finding, Gemini
was advisory and unavailable, and no unresolved thread existed on the final
two PRs when this entry was created. Any later substantive finding requires a
new append-only correction.

| Authorized Git path | Git-blob SHA-256 |
|---|---|
| `a3_ingest_terminal_verify.py` | `da3bfc8abce19279f7dbd9ea7cad30450f35b2a67b9e1eed716669d13074e8c7` |
| `a3_backup_terminal_verify.py` | `a6de7a2e86b0cfde725987cafd65a9d867c4e68ac2a278ff3896e1f274f213a6` |
| `a3_verifier_common.py` | `f98d3279aa3bd6d4aafa8725f583d1b987626c6c4ad0033f90a543bbfbd28b19` |
| `run_a3_timed_preflight.ps1` | `587b90cec7949726f372434108a24e52f25c0be422d6555020a195106c70b7f5` |
| extracted `timed-preflight.ps1` | `d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a` |
| `pi_laptop_backup_source.py` | `e4ee21639740ebcccdefdbdeb6291b398e5467a9c5359c84dc49b667df8a9a17` |

<!-- A3-VERIFIER-AUTHORIZATION {"schema_version":1,"plan_document_id":"ARL-OPS-001","plan_version":"1.5","plan_git_commit":"9094a8e115958fcaf2cb36525736bd5e297e6b04","plan_sha256":"a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada","observation_date":"2026-08-31","verifier_code_sha":"8ab4342fb8c9ef7b854988eb393c9a3284d0ebd2","candidate_code_sha":"f214e3249c7968d574e3449edb14792904e1cc1f","protected_code_sha":"9302890fcc752cbf90da97d597e972c157d913e3","operator":"jkoka","sources":{"a3_ingest_terminal_verify.py":"da3bfc8abce19279f7dbd9ea7cad30450f35b2a67b9e1eed716669d13074e8c7","a3_backup_terminal_verify.py":"a6de7a2e86b0cfde725987cafd65a9d867c4e68ac2a278ff3896e1f274f213a6","a3_verifier_common.py":"f98d3279aa3bd6d4aafa8725f583d1b987626c6c4ad0033f90a543bbfbd28b19","run_a3_timed_preflight.ps1":"587b90cec7949726f372434108a24e52f25c0be422d6555020a195106c70b7f5","timed-preflight.ps1":"d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a","pi_laptop_backup_source.py":"e4ee21639740ebcccdefdbdeb6291b398e5467a9c5359c84dc49b667df8a9a17"},"authorization":"AUTHORIZED","result":"PASS","deviations":[],"deviation_authorization":null} -->

### Exact unattended sequence

At 00:20 create one exclusive generation under
`C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831`. Extract the approved
timed-preflight block from the authenticated handoff blob, requiring byte length
`10702` and the digest above. Copy and authenticate the wrapper, then invoke its
`0025` phase. Never reuse or delete an active pointer.

```powershell
$ErrorActionPreference='Stop';$V='C:\code\backups\AR-local-a3-terminal-verifier-8ab4342';$A='<authority merge>';$H='<handoff blob SHA-256>'
$P='C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831';New-Item -ItemType Directory -LiteralPath $P -Force|Out-Null
$R=Join-Path $P (([DateTimeOffset]::Now.ToString('yyyyMMddTHHmmsszzz').Replace(':',''))+'-'+[guid]::NewGuid().ToString('N'));New-Item -ItemType Directory -LiteralPath $R|Out-Null
$s=[IO.File]::Open((Join-Path $P 'ACTIVE_EVIDENCE_PATH.txt'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$b=[Text.UTF8Encoding]::new($false).GetBytes($R);$s.Write($b,0,$b.Length);$s.Flush($true)}finally{$s.Dispose()}
python -c "import hashlib,re,subprocess,sys;b=subprocess.check_output(['git','-C',sys.argv[1],'show',sys.argv[2]+':docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md']).replace(b'\r\n',b'\n');m=[x+b'\n' for x in re.findall(br'```powershell\n(.*?)\n```',b,re.S) if len(x+b'\n')==10702 and hashlib.sha256(x+b'\n').hexdigest()=='d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a'];assert len(m)==1;open(sys.argv[3],'xb').write(m[0])" $V $A (Join-Path $R 'timed-preflight.ps1');if($LASTEXITCODE-ne 0){throw 'Timed preflight extraction failed.'}
$W=Join-Path $V 'run_a3_timed_preflight.ps1';if((Get-FileHash $W -Algorithm SHA256).Hash.ToLowerInvariant()-cne'587b90cec7949726f372434108a24e52f25c0be422d6555020a195106c70b7f5'){throw 'Wrapper authentication failed.'}
$args=@{EvidenceRoot=$R;ScriptSha256='d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a';PlanDocumentId='ARL-OPS-001';PlanVersion='1.5';PlanGitCommit='9094a8e115958fcaf2cb36525736bd5e297e6b04';PlanSha256='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada';PlanNormalizedSha256='f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684';AuthorityCommit=$A;AuthorityHandoffSha256=$H;CandidateCodeSha='f214e3249c7968d574e3449edb14792904e1cc1f';ProtectedCodeSha='9302890fcc752cbf90da97d597e972c157d913e3';Operator='jkoka'}
& $W -Phase 0025 @args;if($LASTEXITCODE-ne 0){throw '00:20 controlled preflight failed.'}
```

At 00:55 recover the unique pointer and run `& $W -Phase 0055 @args`. At
00:58 invoke the ingest verifier below. It observes but never starts, forces,
restarts, or reruns the service.

```powershell
$ErrorActionPreference='Stop';$V='C:\code\backups\AR-local-a3-terminal-verifier-8ab4342';$A='<authority merge>';$H='<handoff blob SHA-256>'
$P='C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831';$R=(Get-Content -LiteralPath (Join-Path $P 'ACTIVE_EVIDENCE_PATH.txt') -Raw).Trim()
$W=Join-Path $V 'run_a3_timed_preflight.ps1';if((Get-FileHash $W -Algorithm SHA256).Hash.ToLowerInvariant()-cne'587b90cec7949726f372434108a24e52f25c0be422d6555020a195106c70b7f5'){throw 'Wrapper authentication failed.'}
$args=@{EvidenceRoot=$R;ScriptSha256='d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a';PlanDocumentId='ARL-OPS-001';PlanVersion='1.5';PlanGitCommit='9094a8e115958fcaf2cb36525736bd5e297e6b04';PlanSha256='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada';PlanNormalizedSha256='f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684';AuthorityCommit=$A;AuthorityHandoffSha256=$H;CandidateCodeSha='f214e3249c7968d574e3449edb14792904e1cc1f';ProtectedCodeSha='9302890fcc752cbf90da97d597e972c157d913e3';Operator='jkoka'}
& $W -Phase 0055 @args;if($LASTEXITCODE-ne 0){throw '00:55 controlled preflight failed.'}
Set-Location -LiteralPath $V
python .\a3_ingest_terminal_verify.py --date 2026-08-31 --evidence-root $R --observe-natural-start --preflight-script-sha256 d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a --preflight-wrapper-sha256 587b90cec7949726f372434108a24e52f25c0be422d6555020a195106c70b7f5 --preflight-wrapper-path .\run_a3_timed_preflight.ps1 --plan-document-id ARL-OPS-001 --plan-version 1.5 --plan-git-commit 9094a8e115958fcaf2cb36525736bd5e297e6b04 --plan-sha256 a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada --plan-normalized-sha256 f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684 --authority-commit $A --authority-handoff-sha256 $H --verifier-code-sha 8ab4342fb8c9ef7b854988eb393c9a3284d0ebd2 --verifier-source-sha256 da3bfc8abce19279f7dbd9ea7cad30450f35b2a67b9e1eed716669d13074e8c7 --candidate-code-sha f214e3249c7968d574e3449edb14792904e1cc1f --protected-code-sha 9302890fcc752cbf90da97d597e972c157d913e3 --operator jkoka
if($LASTEXITCODE-ne 0){throw 'Natural ingest verifier failed.'}
```

At 05:15, without manually triggering or reinstalling the task, invoke:

```powershell
$ErrorActionPreference='Stop';$V='C:\code\backups\AR-local-a3-terminal-verifier-8ab4342';$A='<authority merge>';$H='<handoff blob SHA-256>'
$R=(Get-Content -LiteralPath 'C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831\ACTIVE_EVIDENCE_PATH.txt' -Raw).Trim();Set-Location -LiteralPath $V
python .\a3_backup_terminal_verify.py --date 2026-08-31 --evidence-root $R --target C:\code\backups\AR-local-pi5 --receiver C:\code\backups\AR-local-pi5-receiver-f214e32 --implementation-root C:\code\backups\AR-local-pi5-receiver-68faf7e --implementation-commit 68faf7e13c650af7b1d713f4a604f9978897ce79 --candidate-root C:\code\backups\AR-local-pi5-candidate-f214e32-d008 --source-helper .\pi_laptop_backup_source.py --source-helper-sha256 e4ee21639740ebcccdefdbdeb6291b398e5467a9c5359c84dc49b667df8a9a17 --task-xml-sha256 aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2 --task-sddl-sha256 6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b --runner-sha256 dd642c7ce8520494104abe9c66f2b0cab9ea9864bc7368e45396f618d67952b8 --dispatcher-config-sha256 b4597ca8c2e4bf205f2c92e904ee9a33b762fc0f5badfc012689635a3023dc00 --dispatcher-manifest-sha256 af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092 --dispatcher-sha256 bb19cee620e8792dbc2eb015af8f53a7e46afda9414d048eebcd010db3fbdbfc --activation-receipt C:\code\backups\AR-local-pi5\dispatcher-control\activation-receipts\00000001-37f93247c88144699631d364c6ac0dee-pass.json --activation-receipt-sha256 7d122e9f96ec22940081fe6ddaa4e54c22a89fea0187cee906b2a09e26233e8b --scheduled-plan-document-id ARL-OPS-001 --scheduled-plan-version 1.4 --scheduled-plan-git-commit 14dd066099bba393cccf61a280243e43162eedc9 --scheduled-plan-sha256 78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713 --scheduled-plan-normalized-sha256 c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4 --scheduled-plan-raw-sha256 a5a679297167c37845fbacf0cdf895cad4fb2900c09c1e94e310319d3ae9118d --plan-document-id ARL-OPS-001 --plan-version 1.5 --plan-git-commit 9094a8e115958fcaf2cb36525736bd5e297e6b04 --plan-sha256 a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada --plan-normalized-sha256 f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684 --authority-commit $A --authority-handoff-sha256 $H --verifier-code-sha 8ab4342fb8c9ef7b854988eb393c9a3284d0ebd2 --verifier-source-sha256 a6de7a2e86b0cfde725987cafd65a9d867c4e68ac2a278ff3896e1f274f213a6 --candidate-code-sha f214e3249c7968d574e3449edb14792904e1cc1f --protected-code-sha 9302890fcc752cbf90da97d597e972c157d913e3 --operator jkoka
if($LASTEXITCODE-ne 0){throw 'Natural backup verifier failed.'}
```

### Acceptance, stop and preservation controls

The ingest verifier must independently prove one natural invocation, terminal
success, zero restarts/competitors, absent lock, dashboard return, hash-bound
raw attempts, valid completion/contract/ledger/pointers, SQLite integrity and
population accounting, attributable product gaps, and separately downloaded
dated v1, rolling v1, dates-index and asset bytes. V2 remains independent.
D-003 applies: exclude and disclose invalid individual products without
discarding valid products; superseded numeric whole-day thresholds do not apply.

The backup verifier must prove the unchanged enabled/Ready task with zero
result, all authenticated dispatcher identities, the bounded natural trigger
pair state machine, exactly one accepted `BACKUP-LATEST` for `2026-08-31`, all
intervening records `PASS`, catalog/receipt/restore/SQLite integrity, Pi source
identity equality, no lock/partial/helper/overlap, and at least 50 GiB free.

D-006 is absolute from 00:30 through terminal ingest validation: no deployment,
canary, manual/forced ingest, service restart, task change/trigger, package
change, backup, or publication manipulation. Unsafe preflight means `BLOCKED`
without starting anything. Preserve raw/generation state and the previous
verified payload on failure; never rerun ingest for publication-only failure.
Preserve existing backup/catalog/dispatcher state on backup failure and never
trigger the task manually.

No rollback, reinstall, relabel, administrator action, Pi mutation, or public
payload mutation is authorized. Completed evidence is immutable. After both
verifiers terminate, append a new entry. Only dual `PASS` may close A3 and
authorize A4 planning; otherwise record `FAIL` or `BLOCKED` and keep A4 blocked.

## Entry `HANDOFF-20260830T200822+1000-A3-AUTHORITY-RESOLUTION-CORRECTION`

### Control record and review disposition

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260830T200822+1000-A3-AUTHORITY-RESOLUTION-CORRECTION` |
| Previous handoff entry | `HANDOFF-20260830T195500+1000-A3-TERMINAL-VERIFIER-AUTHORIZATION` |
| Created | `2026-08-30T20:08:22+10:00` / `2026-08-30T10:08:22Z` |
| Author/operator | Codex unattended for `jkoka` |
| Result | `RUNNING`; A3 and A4 status is unchanged |
| Controlling plan | `ARL-OPS-001` v1.5; commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Late review | PR #576 Sourcery finding at the former placeholder initialization |
| Disposition | `IMPLEMENTED`: literal authority placeholders are forbidden and superseded by the exact authenticated resolution below |

PR #576 merged before its late Sourcery review arrived. Its historical entry is
immutable. The finding is correct: copying `<authority merge>` and `<handoff
blob SHA-256>` would fail closed rather than run unattended. This entry keeps
the source authorization unchanged, repeats it in the final chronological
entry as required by the verifier, and replaces every placeholder initialization
with deterministic post-merge resolution. No Pi, task, backup, or payload state
is changed.

<!-- A3-VERIFIER-AUTHORIZATION {"schema_version":1,"plan_document_id":"ARL-OPS-001","plan_version":"1.5","plan_git_commit":"9094a8e115958fcaf2cb36525736bd5e297e6b04","plan_sha256":"a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada","observation_date":"2026-08-31","verifier_code_sha":"8ab4342fb8c9ef7b854988eb393c9a3284d0ebd2","candidate_code_sha":"f214e3249c7968d574e3449edb14792904e1cc1f","protected_code_sha":"9302890fcc752cbf90da97d597e972c157d913e3","operator":"jkoka","sources":{"a3_ingest_terminal_verify.py":"da3bfc8abce19279f7dbd9ea7cad30450f35b2a67b9e1eed716669d13074e8c7","a3_backup_terminal_verify.py":"a6de7a2e86b0cfde725987cafd65a9d867c4e68ac2a278ff3896e1f274f213a6","a3_verifier_common.py":"f98d3279aa3bd6d4aafa8725f583d1b987626c6c4ad0033f90a543bbfbd28b19","run_a3_timed_preflight.ps1":"587b90cec7949726f372434108a24e52f25c0be422d6555020a195106c70b7f5","timed-preflight.ps1":"d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a","pi_laptop_backup_source.py":"e4ee21639740ebcccdefdbdeb6291b398e5467a9c5359c84dc49b667df8a9a17"},"authorization":"AUTHORIZED","result":"PASS","deviations":[],"deviation_authorization":null} -->

### Exact authority resolution and persistence

At 00:20, before the freeze, use this exact self-contained preamble. It fetches
`origin/main`, requires the reviewed detached verifier checkout, resolves the
document-containing authority commit from the fetched remote-tracking ref,
hashes the exact Git blob bytes, and persists both values create-new inside the
unique evidence generation. The verifier independently revalidates the final
authorization marker, ancestry, origin/main equality, source bytes, and working
checkout. Therefore neither a conversational substitution nor a literal
placeholder is accepted.

```powershell
$ErrorActionPreference='Stop';$V='C:\code\backups\AR-local-a3-terminal-verifier-8ab4342'
git -C $V fetch origin main;if($LASTEXITCODE-ne 0){throw 'Authority fetch failed.'}
if((git -C $V rev-parse HEAD).Trim()-cne'8ab4342fb8c9ef7b854988eb393c9a3284d0ebd2'-or(git -C $V status --porcelain)-or(git -C $V symbolic-ref -q HEAD)){throw 'Verifier checkout is not exact, clean, and detached.'}
$A=(git -C $V rev-parse refs/remotes/origin/main).Trim();if($A-cnotmatch'^[0-9a-f]{40}$'){throw 'Authority commit resolution failed.'}
$H=(python -c "import hashlib,subprocess,sys;print(hashlib.sha256(subprocess.check_output(['git','-C',sys.argv[1],'show',sys.argv[2]+':docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'])).hexdigest())" $V $A).Trim();if($LASTEXITCODE-ne 0-or$H-cnotmatch'^[0-9a-f]{64}$'){throw 'Authority handoff digest resolution failed.'}
$P='C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831';New-Item -ItemType Directory -LiteralPath $P -Force|Out-Null
$R=Join-Path $P (([DateTimeOffset]::Now.ToString('yyyyMMddTHHmmsszzz').Replace(':',''))+'-'+[guid]::NewGuid().ToString('N'));New-Item -ItemType Directory -LiteralPath $R|Out-Null
$s=[IO.File]::Open((Join-Path $P 'ACTIVE_EVIDENCE_PATH.txt'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$b=[Text.UTF8Encoding]::new($false).GetBytes($R);$s.Write($b,0,$b.Length);$s.Flush($true)}finally{$s.Dispose()}
$j=([ordered]@{schema_version=1;authority_commit=$A;authority_handoff_sha256=$H;resolved_at=[DateTimeOffset]::Now.ToString('o');verifier_code_sha='8ab4342fb8c9ef7b854988eb393c9a3284d0ebd2';result='PASS'}|ConvertTo-Json -Compress)+"`n";$s=[IO.File]::Open((Join-Path $R 'authority.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$b=[Text.UTF8Encoding]::new($false).GetBytes($j);$s.Write($b,0,$b.Length);$s.Flush($true)}finally{$s.Dispose()}
```

After this preamble, continue the preceding entry's 00:20 block from its
`python -c` timed-preflight extraction command onward, using the already
resolved `$V`, `$A`, `$H`, `$P`, and `$R`. Do not execute the superseded first
three lines containing angle-bracket placeholders.

At 00:55 and again at 05:15, start each new PowerShell process with this exact
self-contained preamble. It performs no fetch or write, recovers only the one
active generation, rejects path escape, rehashes the same authority blob, and
restores `$V`, `$A`, `$H`, `$P`, and `$R` for the corresponding exact verifier
block in the preceding entry:

```powershell
$ErrorActionPreference='Stop';$V='C:\code\backups\AR-local-a3-terminal-verifier-8ab4342';$P=[IO.Path]::GetFullPath('C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831')
$R=[IO.Path]::GetFullPath((Get-Content -LiteralPath (Join-Path $P 'ACTIVE_EVIDENCE_PATH.txt') -Raw).Trim());if(-not$R.StartsWith($P+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Evidence root escaped.'}
$j=Get-Content -LiteralPath (Join-Path $R 'authority.json') -Raw|ConvertFrom-Json;$A=[string]$j.authority_commit;$H=[string]$j.authority_handoff_sha256
if($j.result-cne'PASS'-or$A-cnotmatch'^[0-9a-f]{40}$'-or$H-cnotmatch'^[0-9a-f]{64}$'-or(git -C $V rev-parse refs/remotes/origin/main).Trim()-cne$A){throw 'Persisted authority identity failed.'}
$actual=(python -c "import hashlib,subprocess,sys;print(hashlib.sha256(subprocess.check_output(['git','-C',sys.argv[1],'show',sys.argv[2]+':docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'])).hexdigest())" $V $A).Trim();if($LASTEXITCODE-ne 0-or$actual-cne$H){throw 'Persisted handoff blob authentication failed.'}
```

At 00:55 continue the preceding entry's second block from `$W=Join-Path ...`,
including phase `0055` and the ingest verifier. At 05:15 continue its third
block from `Set-Location -LiteralPath $V`, including the backup verifier. The
resolved values are never edited after 00:20. If any resolution or comparison
fails, record `BLOCKED`, preserve evidence, and perform no mutation or manual
fallback.

All D-003, D-006, acceptance, stop, rollback, immutability and A3/A4 controls in
the preceding authorization entry remain unchanged. A3 still requires both
reviewed verifiers to return controlled `PASS`; only then may the next
append-only entry close A3 and begin A4 planning.

## Entry `HANDOFF-20260830T201249+1000-A3-AUTHORITY-REFRESH-CORRECTION`

### Control record and late-review disposition

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260830T201249+1000-A3-AUTHORITY-REFRESH-CORRECTION` |
| Previous handoff entry | `HANDOFF-20260830T200822+1000-A3-AUTHORITY-RESOLUTION-CORRECTION` |
| Created | `2026-08-30T20:12:49+10:00` / `2026-08-30T10:12:49Z` |
| Author/operator | Codex unattended for `jkoka` |
| Result | `RUNNING`; A3 and A4 status is unchanged |
| Controlling plan | `ARL-OPS-001` v1.5; commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Late review | PR #577 Sourcery finding on stale remote-tracking authority |
| Disposition | `IMPLEMENTED`: each 00:55 and 05:15 authority reauthentication must first fetch `origin/main` and require it still equals the persisted 00:20 authority |

PR #577 merged before the late review arrived, so its entry remains immutable.
The final authorization is repeated below. The 00:20 authority resolution is
unchanged. The 00:55 and 05:15 reauthentication block in the preceding entry is
superseded only by inserting the exact two lines below immediately after its
first line, before reading the active pointer or persisted authority:

```powershell
git -C $V fetch origin main
if($LASTEXITCODE-ne 0){throw 'Authority refresh failed.'}
```

This fetch is read-only with respect to Pi production, services, tasks, backups,
and public payloads and is permitted during the D-006 observation window. If
remote `main` advanced after the 00:20 authority was persisted, the existing
strict equality check must return `BLOCKED`; do not update `authority.json`, do
not select the newer commit, and do not use a manual fallback. This makes the
00:20 authority an explicit frozen invariant while still detecting remote
drift. At 05:15 the same rule applies. All other exact commands, hashes,
acceptance gates, stop controls and evidence requirements remain unchanged.

<!-- A3-VERIFIER-AUTHORIZATION {"schema_version":1,"plan_document_id":"ARL-OPS-001","plan_version":"1.5","plan_git_commit":"9094a8e115958fcaf2cb36525736bd5e297e6b04","plan_sha256":"a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada","observation_date":"2026-08-31","verifier_code_sha":"8ab4342fb8c9ef7b854988eb393c9a3284d0ebd2","candidate_code_sha":"f214e3249c7968d574e3449edb14792904e1cc1f","protected_code_sha":"9302890fcc752cbf90da97d597e972c157d913e3","operator":"jkoka","sources":{"a3_ingest_terminal_verify.py":"da3bfc8abce19279f7dbd9ea7cad30450f35b2a67b9e1eed716669d13074e8c7","a3_backup_terminal_verify.py":"a6de7a2e86b0cfde725987cafd65a9d867c4e68ac2a278ff3896e1f274f213a6","a3_verifier_common.py":"f98d3279aa3bd6d4aafa8725f583d1b987626c6c4ad0033f90a543bbfbd28b19","run_a3_timed_preflight.ps1":"587b90cec7949726f372434108a24e52f25c0be422d6555020a195106c70b7f5","timed-preflight.ps1":"d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a","pi_laptop_backup_source.py":"e4ee21639740ebcccdefdbdeb6291b398e5467a9c5359c84dc49b667df8a9a17"},"authorization":"AUTHORIZED","result":"PASS","deviations":[],"deviation_authorization":null} -->

A3 remains incomplete until the natural ingest and backup verifiers both return
controlled `PASS`. A4 remains blocked until the next append-only entry records
that dual result.

## Entry `HANDOFF-20260830T201636+1000-A3-AUTHORITY-BLOCKED-EVIDENCE-CORRECTION`

### Control record and late-review disposition

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260830T201636+1000-A3-AUTHORITY-BLOCKED-EVIDENCE-CORRECTION` |
| Previous handoff entry | `HANDOFF-20260830T201249+1000-A3-AUTHORITY-REFRESH-CORRECTION` |
| Created | `2026-08-30T20:16:36+10:00` / `2026-08-30T10:16:36Z` |
| Author/operator | Codex unattended for `jkoka` |
| Result | `RUNNING`; A3 and A4 status is unchanged |
| Controlling plan | `ARL-OPS-001` v1.5; commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Late review | PR #578 Sourcery finding on unclassified authority-drift exception |
| Disposition | `IMPLEMENTED`: reauthentication failure writes an immutable mandatory-schema `BLOCKED` record before rethrowing |

PR #578 merged before its late review arrived and remains immutable. Replace
the complete 00:55/05:15 reauthentication block from the preceding correction
with the block below. Set `$Phase='0055'` at 00:55 or `$Phase='0515'` at 05:15
before invoking it. The block fetches read-only, authenticates the frozen 00:20
authority, and on any failure attempts exactly one controlled `BLOCKED` record
inside the already-bound evidence generation before rethrowing. If evidence
storage itself fails, it emits a separate process-level `BLOCKED` JSON to
stderr containing both errors and remains fail-closed. Never retry a phase or
overwrite a record.

```powershell
$ErrorActionPreference='Stop';$V='C:\code\backups\AR-local-a3-terminal-verifier-8ab4342';$P=[IO.Path]::GetFullPath('C:\code\backups\AR-local-pi5\evidence\NATURAL-20260831')
$started=[DateTimeOffset]::Now.ToString('o');$pointer=Join-Path $P 'ACTIVE_EVIDENCE_PATH.txt';$R=$null;$authorityPath=$null;$A=$null;$H=$null;$observedRemote=$null
try{
 if($Phase-cnotin@('0055','0515')){throw 'Authority phase is invalid.'};$R=[IO.Path]::GetFullPath((Get-Content -LiteralPath $pointer -Raw).Trim())
 if(-not$R.StartsWith($P+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Evidence root escaped.'};$authorityPath=Join-Path $R 'authority.json'
 $j=Get-Content -LiteralPath $authorityPath -Raw|ConvertFrom-Json;$A=[string]$j.authority_commit;$H=[string]$j.authority_handoff_sha256
 git -C $V fetch origin main;if($LASTEXITCODE-ne 0){throw 'Authority refresh failed.'}
 $observedRemote=(git -C $V rev-parse refs/remotes/origin/main).Trim();if($LASTEXITCODE-ne 0-or$observedRemote-cnotmatch'^[0-9a-f]{40}$'){throw 'Observed remote authority resolution failed.'}
 if($j.result-cne'PASS'-or$A-cnotmatch'^[0-9a-f]{40}$'-or$H-cnotmatch'^[0-9a-f]{64}$'-or$observedRemote-cne$A){throw 'Persisted authority identity failed.'}
 $actual=(python -c "import hashlib,subprocess,sys;print(hashlib.sha256(subprocess.check_output(['git','-C',sys.argv[1],'show',sys.argv[2]+':docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'])).hexdigest())" $V $A).Trim();if($LASTEXITCODE-ne 0-or$actual-cne$H){throw 'Persisted handoff blob authentication failed.'}
}catch{
 $original=$_.Exception;$errorText=$original.Message;$phaseValue=if($Phase-cin@('0055','0515')){$Phase}else{'UNKNOWN'};$source=if($Phase-ceq'0055'){'da3bfc8abce19279f7dbd9ea7cad30450f35b2a67b9e1eed716669d13074e8c7'}elseif($Phase-ceq'0515'){'a6de7a2e86b0cfde725987cafd65a9d867c4e68ac2a278ff3896e1f274f213a6'}else{$null}
 try{
  $recordRoot=if($null-ne$R-and$R.StartsWith($P+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)-and(Test-Path -LiteralPath $R -PathType Container)){$R}else{$P};$evidence=@()
  foreach($evidencePath in @($pointer,$authorityPath)){if($null-ne$evidencePath-and(Test-Path -LiteralPath $evidencePath -PathType Leaf)){$item=Get-Item -LiteralPath $evidencePath;if(-not$item.FullName.StartsWith($recordRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){continue};$relative=$item.FullName.Substring($recordRoot.Length+1).Replace('\','/');$evidence+=,[ordered]@{path=$relative;bytes=[int64]$item.Length;sha256=(Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}}}
  $record=[ordered]@{schema_version=1;plan_document_id='ARL-OPS-001';plan_version='1.5';plan_git_commit='9094a8e115958fcaf2cb36525736bd5e297e6b04';plan_sha256='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada';plan_raw_sha256='f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684';plan_normalized_sha256='f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684';authority_commit=$A;authority_handoff_sha256=$H;verifier_code_sha='8ab4342fb8c9ef7b854988eb393c9a3284d0ebd2';verifier_source_sha256=$source;candidate_code_sha='f214e3249c7968d574e3449edb14792904e1cc1f';protected_code_sha='9302890fcc752cbf90da97d597e972c157d913e3';operator='jkoka';phase=$phaseValue;timestamps=[ordered]@{started_at=$started;completed_at=[DateTimeOffset]::Now.ToString('o')};exact_commands=@("git -C `"$V`" fetch origin main","git -C `"$V`" rev-parse refs/remotes/origin/main","git -C `"$V`" show `"$A`:docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md`" and SHA-256 authenticate");evidence=$evidence;result='BLOCKED';details=[ordered]@{authority_phase=$phaseValue;authority_evidence=$authorityPath;persisted_authority_commit=$A;observed_remote_commit=$observedRemote;reason='authority reauthentication failed'};error=$errorText;deviations=@();deviation_authorization=$null}
  $name=if($recordRoot-ceq$R){"$phaseValue-authority-reauthentication-blocked.json"}else{([DateTimeOffset]::Now.ToString('yyyyMMddTHHmmsszzz').Replace(':',''))+"-$phaseValue-authority-setup-blocked-"+[guid]::NewGuid().ToString('N')+'.json'};$raw=($record|ConvertTo-Json -Depth 8 -Compress)+"`n";$path=Join-Path $recordRoot $name;$s=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$b=[Text.UTF8Encoding]::new($false).GetBytes($raw);$s.Write($b,0,$b.Length);$s.Flush($true)}finally{$s.Dispose()}
  $verified=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json;if($verified.result-cne'BLOCKED'-or$verified.phase-cne$phaseValue-or$verified.verifier_source_sha256-cne$source){throw 'BLOCKED record verification failed.'}
 }catch{
  $recordError=$_.Exception.Message;$fallback=([ordered]@{schema_version=1;phase=$Phase;result='BLOCKED';error=$errorText;evidence_record_error=$recordError}|ConvertTo-Json -Compress);[Console]::Error.WriteLine($fallback)
  throw [InvalidOperationException]::new("Authority reauthentication blocked and its evidence record failed: $recordError",$original)
 }
 throw $original
}
```

On success, continue the exact phase `0055` wrapper and ingest-verifier command
or the exact `0515` backup-verifier command from the authorization entry. On
`BLOCKED`, stop that verifier path; do not alter `authority.json`, do not select
a newer commit, and do not use a manual fallback. Direct observation and
preservation of an already-running natural ingest remain read-only and must not
be interrupted merely because evidence tooling blocked.

<!-- A3-VERIFIER-AUTHORIZATION {"schema_version":1,"plan_document_id":"ARL-OPS-001","plan_version":"1.5","plan_git_commit":"9094a8e115958fcaf2cb36525736bd5e297e6b04","plan_sha256":"a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada","observation_date":"2026-08-31","verifier_code_sha":"8ab4342fb8c9ef7b854988eb393c9a3284d0ebd2","candidate_code_sha":"f214e3249c7968d574e3449edb14792904e1cc1f","protected_code_sha":"9302890fcc752cbf90da97d597e972c157d913e3","operator":"jkoka","sources":{"a3_ingest_terminal_verify.py":"da3bfc8abce19279f7dbd9ea7cad30450f35b2a67b9e1eed716669d13074e8c7","a3_backup_terminal_verify.py":"a6de7a2e86b0cfde725987cafd65a9d867c4e68ac2a278ff3896e1f274f213a6","a3_verifier_common.py":"f98d3279aa3bd6d4aafa8725f583d1b987626c6c4ad0033f90a543bbfbd28b19","run_a3_timed_preflight.ps1":"587b90cec7949726f372434108a24e52f25c0be422d6555020a195106c70b7f5","timed-preflight.ps1":"d3b8600cac48b7336b0d39da0d6aa60a788ce68a702126de5a6a0f1921157c9a","pi_laptop_backup_source.py":"e4ee21639740ebcccdefdbdeb6291b398e5467a9c5359c84dc49b667df8a9a17"},"authorization":"AUTHORIZED","result":"PASS","deviations":[],"deviation_authorization":null} -->

All prior D-003, D-006, acceptance, stop, rollback and immutability controls
remain unchanged. A3 still requires dual controlled `PASS`; A4 remains blocked.

## Entry `HANDOFF-20260831T074200+1000-A3-NATURAL-BACKUP-FAIL-SAFER-REPAIR`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260831T074200+1000-A3-NATURAL-BACKUP-FAIL-SAFER-REPAIR` |
| Previous handoff entry | `HANDOFF-20260830T201636+1000-A3-AUTHORITY-BLOCKED-EVIDENCE-CORRECTION` |
| Created | `2026-08-31T07:42:00+10:00` / `2026-08-30T21:42:00Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Previous authority | merge `ed6735783a2bcd3d1453d9aa5e4b7ec5adc5be28`; complete handoff Git-blob SHA-256 `d6f6b1a7262da1d5225688cc84f72715907783536952c298d95e0ff3b1428c63` |
| Protected Pi | `9302890fcc752cbf90da97d597e972c157d913e3`; clean; no deployment or production mutation |
| Natural ingest component result | `PASS`: exactly one natural invocation `d546b15b377f4415a3ea7db81bd96025` completed at 01:18:50 Australia/Hobart with systemd `Result=success`, `ExecMainStatus=0`, `NRestarts=0`, terminal lock absent and dashboard automatically returned for `2026-08-31` |
| Timed procedure result | `BLOCKED`: the 00:20/00:55 controlled preflight generation was not created; it is not reconstructed or relabelled |
| Natural laptop task result | `FAIL`: the unchanged 05:00 task ended with result `1` before any backup-data write |
| A3 / A4 | A3 `RUNNING`; A4 `BLOCKED` until a later natural ingest and natural restricted-dispatcher backup both pass |

### Immutable evidence and root cause

The dispatcher execution record is
`C:\code\backups\AR-local-pi5\dispatcher-control\dispatcher-executions\20260830T190002Z-0b43ff212991405890e7b2df662952b4.json`,
SHA-256
`88031066d9228f3acd09d97304d239df3da8698d871eb18fdf76dea3900f4165`.
It records `FAIL`, child exit `1`, no candidate or manifest execution, and the
exact error `dispatcher must not run elevated`.

The controlled diagnostic summary is
`C:\code\backups\AR-local-pi5\evidence\A3-S4U-NATURAL-FAILURE-20260831\20260831T073928+1000\diagnostic-summary.json`,
SHA-256
`c994432dd4f278d7ec3ad5ebce41a4d04cdb4f64fa58321a92378bc68268d423`.
It binds the plan, candidate, protected Pi, task state, exact commands and
supporting evidence. The production task was not manually triggered.

The failure exposes an invalid assumption in D-008. The task definition still
reports principal `jkoka`, `S4U` and `Limited`, but the natural scheduler token
made `IsUserAnAdmin` return true. That API is an administrator-group-membership
test, not a complete least-privilege-launch mechanism. The dispatcher correctly
failed closed, but the runner cannot rely on Task Scheduler's declaration alone
to establish the child process's effective restriction.

A temporary same-principal `S4U` probe task could not be registered by the
ordinary token (`Access is denied`), and no elevated or production-task probe
was attempted. A foreground proof using Windows Software Restriction Policy's
`SAFER_LEVELID_NORMALUSER` created a restricted child with
`TokenElevationTypeLimited`, `TokenElevation=0`, administrator membership
false, and only `SeChangeNotifyPrivilege` enabled. Its evidence is
`interactive-safer-token-2.json`, SHA-256
`8ca90ab3023fd55de1d236b81d1863e268b2d73d56b22f168ef5be7c95ba8845`.

### Append-only deviation decision `D-009`

D-008 remains historical evidence but its direct Python-dispatcher launch is
withdrawn. No Task Scheduler definition, trigger, SDDL, principal, run level,
Pi path, public payload or production service may be changed for this repair.
No administrator action is authorized or required.

The reviewed repair shall make the existing managed runner launch the exact
dispatcher through a small hash-bound Windows restricted-process launcher. The
launcher shall use `SaferCreateLevel` with `SAFER_SCOPEID_USER` and
`SAFER_LEVELID_NORMALUSER`, derive the child token from the task process token,
and call `CreateProcessAsUserW` only with that restricted token. It shall wait
for and return the exact child exit code. The dispatcher retains its SID and
non-administrator checks, so failure to create or prove the restricted child
remains fail-closed.

The runner must continue to authenticate the control configuration, exact clean
detached implementation commit, Python executable, dispatcher, atomic module,
new restricted launcher and active content-addressed manifest. Transition of
the operator-owned runner and runner configuration must be same-volume,
transactional, rollback-capable, evidence-bound and performed only while the
task is Ready, no backup helper exists, the Pi ingest is idle and the D-006
freeze is not in effect. The task itself must remain byte-for-byte unchanged.

### Verification and continuation gates

The implementation PR must add deterministic unit tests for Win32 call failure,
restricted-token creation, exact argument quoting, child exit propagation,
handle closure, configuration/launcher hash drift, transition interruption and
exact rollback. Windows PowerShell 5.1 and the complete repository suite must
pass at the exact PR head, with all substantive review threads dispositioned
and resolved before merge.

After merge, create a clean detached implementation checkout at the exact merge
SHA. Outside the freeze, run the reviewed non-administrator transition and two
foreground semantic probes. Require exact task XML/SDDL identity, immutable
transition evidence, a clean candidate, an exact active manifest, no helpers,
no partial files, catalog integrity and at least 50 GiB free. On any failure,
restore the exact previous runner and configuration and record `ROLLED_BACK` or
`FAIL`; never trigger the backup task as a fallback.

The next terminal proof is the natural `2026-09-01` 01:00 ingest followed by
the natural 05:00 backup. D-006 preflights must begin early enough to complete
before 00:30 and 01:00. Acceptance requires complete ingest/database/contract/
ledger/provider/public-byte evidence plus a natural dispatcher execution that
proves the restricted identity and creates `PASS/BACKUP-LATEST` for observation
date `2026-09-01`. Only a later append-only entry may mark A3 `PASS` and begin
A4 planning.

## Entry `HANDOFF-20260831T080717+1000-A3-FAIL-CLOSED-AUTHORITY-CORRECTION`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260831T080717+1000-A3-FAIL-CLOSED-AUTHORITY-CORRECTION` |
| Previous handoff entry | `HANDOFF-20260831T074200+1000-A3-NATURAL-BACKUP-FAIL-SAFER-REPAIR` |
| Created | `2026-08-31T08:07:17+10:00` / `2026-08-30T22:07:17Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; Git-blob 115868 bytes, SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684`; CRLF checkout 117749 bytes, SHA-256 `d7be2c8a437baba8babc4f777cd3022c004a5e1a08b8c41edba6d3e8e0a226a4` |
| Source repository | clean detached `C:\code\backups\AR-local-plan-control-20260831` at merged `origin/main` `211e6055ca0a21c35d2a1ea06ae4a1197acadafe`; pre-append handoff Git-blob 372477 bytes, SHA-256 `bc3786b12ec0bf9050a5257921a057d9c9f451678c53cd1bd70d6197995dfc4d`; CRLF checkout 377825 bytes, SHA-256 `7d1b6cf95f4190ed3a802ae53548db831a383f03f67157ad421174023ae445b5` |
| Protected Pi | `9302890fcc752cbf90da97d597e972c157d913e3`; clean; daily service inactive, timer enabled/active, lock absent, dashboard API HTTP 200; no deployment or production mutation |
| Overall result | `BLOCKED` |
| A3 / A4 | A3 `RUNNING` but transition blocked; A4 `BLOCKED` |
| Deviations | `D-010` below withdraws the unsafe D-009 execution authority; no transition is authorized by this entry |
| Authorization source | Operator instructions require safe unattended execution without repeated elevation and permit at most one future elevated PowerShell command. This append-only decision narrows that authorization: elevation is not authorized until reviewed implementation has merged and a later exact transition-authority entry authenticates every byte and command. |

### Corrected component outcomes

The preceding entry's natural-ingest `PASS` is too broad and is corrected
without rewriting that historical entry:

| Component | Result | Evidence or limitation |
|---|---|---|
| 00:20/00:55 timed preflight | `BLOCKED` | It did not run and is not reconstructed. |
| Natural systemd invocation | `PASS` | Exactly one invocation `d546b15b377f4415a3ea7db81bd96025`; `Result=success`, `ExecMainStatus=0`, `NRestarts=0`, terminal lock absent, dashboard returned. |
| Dashboard latest pointer | `PASS` | Read-only API returned HTTP 200 and `run_date=2026-08-31`, 2980 products, 16671 rates and 17 failures. |
| Raw attempts, completion marker, export contract and ledger binding | `UNVERIFIED` | No controlled 31 August evidence set proves these gates. |
| SQLite quick check, schema and population/provider accounting | `UNVERIFIED` | No controlled 31 August evidence set proves these gates. |
| Dated v1, rolling v1, dates index and referenced public bytes | `UNVERIFIED` | They were not independently downloaded and hashed for this observation. |
| v2 | `UNVERIFIED` and independent | No freshness claim is made. |
| Natural 05:00 laptop task | `FAIL` | `LastTaskResult=1`; dispatcher failed closed before backup-data write. |
| PR #581 implementation | `FAIL` / not accepted | Merged main is not runtime acceptance. Windows PowerShell 5.1 job `99327789650` failed three tests because the derived token still reported elevation. Late review also found unsafe pre-restriction execution and incomplete rollback. |

No complete, rich, or publicly verified `2026-08-31` observation is claimed.
The dashboard pointer proves that the producer advanced, but cannot substitute
for the missing controlled gates.

The latest accepted laptop observation remains
`obs-2026-08-30-69a34aa4c745bb2e`, catalog sequence 332. Catalog control and
macro records extend through sequence 336. This entry does not accept a
31 August observation into the laptop backup catalog.

### Immutable evidence and active baseline

| Evidence or active input | Bytes | SHA-256 / identity |
|---|---:|---|
| `C:\code\backups\AR-local-pi5\dispatcher-control\dispatcher-executions\20260830T190002Z-0b43ff212991405890e7b2df662952b4.json` | 698 | `88031066d9228f3acd09d97304d239df3da8698d871eb18fdf76dea3900f4165` |
| `C:\code\backups\AR-local-pi5\evidence\A3-S4U-NATURAL-FAILURE-20260831\20260831T073928+1000\diagnostic-summary.json` | 2126 | `c994432dd4f278d7ec3ad5ebce41a4d04cdb4f64fa58321a92378bc68268d423` |
| `C:\code\backups\AR-local-pi5\evidence\A3-S4U-TOKEN-PROBE-20260831\interactive-safer-token-2.json` | 2286 | `8ca90ab3023fd55de1d236b81d1863e268b2d73d56b22f168ef5be7c95ba8845` |
| Active runner `C:\code\backups\AR-local-pi5-receiver-f214e32\run_laptop_backup_task.ps1` | 4797 | `dd642c7ce8520494104abe9c66f2b0cab9ea9864bc7368e45396f618d67952b8`; receiver HEAD `f214e3249c7968d574e3449edb14792904e1cc1f`, but runner modified and receiver not clean |
| `C:\code\backups\AR-local-pi5\dispatcher-control\runner-config.json` | 572 | `b4597ca8c2e4bf205f2c92e904ee9a33b762fc0f5badfc012689635a3023dc00` |
| `C:\code\backups\AR-local-pi5\dispatcher-control\active-runner.json` | 170 | `fd66311c66aad9a8f16643171fdb3de54f6582361d41ce3255c7da09a086e923` |
| Active manifest `...\manifests\af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092.json` | 1861 | `af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092` |
| Active implementation dispatcher `C:\code\backups\AR-local-pi5-receiver-68faf7e\laptop_backup_dispatcher.py` | 43837 | `bb19cee620e8792dbc2eb015af8f53a7e46afda9414d048eebcd010db3fbdbfc`; clean detached implementation HEAD `68faf7e13c650af7b1d713f4a604f9978897ce79` |
| Active implementation atomic module `C:\code\backups\AR-local-pi5-receiver-68faf7e\laptop_backup_atomic.py` | 3426 | `89615eb4350afda7e71e5f9c1123928e5434c12bef9ef5a20374a795d9166842` |
| Active backup candidate | - | clean detached `C:\code\backups\AR-local-pi5-candidate-f214e32-d008` at `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Accepted pre-failure task definition | - | `AR-local laptop backup`; S4U, Limited, Ready, enabled; daily 05:00 and startup +5 minutes; immutable XML SHA-256 `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`; SDDL SHA-256 `6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b` |
| Catalog generations `C:\code\backups\AR-local-pi5\catalog\generations.jsonl` | 236234 | `7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511` |
| Latest verified pointer `C:\code\backups\AR-local-pi5\catalog\latest-verified.json` | 316 | `737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389` |
| Latest accepted receipt `...\observations\2026-08-30\f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d\receipt.json` | 3392 | `7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea` |

The active scheduled action enters an operator-writable runner before any
restriction is established. That is not an acceptable privileged boundary.

### Append-only deviation decision `D-010`

D-009 remains historical evidence but its repair and transition authority are
withdrawn. PR #581 and merge `211e6055ca0a21c35d2a1ea06ae4a1197acadafe`
must not be installed, activated or used as transition authority. The failed
task must not be manually triggered, reinstalled or modified from this entry.
The Pi, payloads and backup data remain unchanged.

The reasons are independent fail-closed defects:

1. the task executes operator-writable PowerShell under the scheduler token, so
   restriction of a later child occurs after an unsafe trust boundary;
2. active candidate `f214e3249c7968d574e3449edb14792904e1cc1f`
   chooses `BACKFILL` whenever any completed date is missing, making the required
   natural `BACKUP-LATEST` path unreachable in that state.

The compensating control is to leave the task failed closed while implementing
a trusted-parent replacement. A future task action must enter immutable,
administrator-protected code before reading or executing any operator-writable
runner, configuration, manifest or checkout. That trusted parent must derive
and prove a standard/restricted token, then launch only hash-bound backup code
under that token. Operator-owned paths may be consumed only as opaque,
authenticated bytes after the restriction boundary. ACLs must prove the
operator has read/execute but not write access to the trusted parent and its
containing path.

Implementation must also correct `BACKUP-LATEST` classification, transaction
flags and exact rollback so interruption after either atomic replacement
restores the authenticated prestate. PowerShell 5.1 compatibility, CRLF-safe SSH,
leaf-file ACL semantics and canonical task-SDDL comparison are mandatory tests
because each has already caused a real bootstrap failure.

### Authorization and acceptance gates

This entry authorizes only a code-and-test PR for the trusted-parent design and
documentation recording its review. It does not authorize an administrator
command, task mutation, foreground backup, manual trigger, Pi change, deployment
or publication change.

Before any live transition:

1. the exact implementation head passes Linux and Windows CI, the full local
   suite, security review, failure-injection rollback tests and all substantive
   review threads;
2. a clean detached checkout exists at the exact merged implementation SHA;
3. a new append-only authority entry authenticates implementation, protected
   launcher, installer, manifests, prestate, exact one-line elevated command and
   rollback command by path, byte length and SHA-256;
4. that entry proves elevation is required exactly once and all routine
   operation, validation and recovery afterward is non-administrator;
5. transition occurs in daylight outside D-006, with Pi idle, task Ready, no
   helper/lock/partial, at least 50 GiB free and a current restorable backup;
6. no backup task is manually triggered. Acceptance requires a natural 05:00
   `PASS/BACKUP-LATEST` for the current observation, then natural no-write
   idempotence only when all identities match.

Only a later append-only terminal entry may mark A3 `PASS` and authorize A4.

### Exact read-only commands used

```powershell
git fetch origin --prune
git rev-parse origin/main
gh pr view 580 --json number,state,mergeCommit,headRefOid,statusCheckRollup,reviewDecision,url
gh pr view 581 --json number,state,mergeCommit,headRefOid,statusCheckRollup,reviewDecision,url
gh run view 33337805852 --job 99327789650 --log-failed
Get-ScheduledTask -TaskName 'AR-local laptop backup'
Get-ScheduledTaskInfo -TaskName 'AR-local laptop backup'
Get-FileHash -Algorithm SHA256 -LiteralPath <each exact evidence and active-input path listed above>
git -C 'C:\code\backups\AR-local-pi5-receiver-f214e32' rev-parse HEAD
git -C 'C:\code\backups\AR-local-pi5-receiver-f214e32' status --porcelain=v1
ssh ar-local-pi5-lan "cd /srv/ar-local/AR-local || exit 2; git rev-parse HEAD; git status --porcelain=v1; systemctl is-active ar-local-daily.service || true; systemctl is-enabled ar-local-daily.timer || true; systemctl is-active ar-local-daily.timer || true; test -e /srv/ar-local/data/state/daily-ingest.lock; curl -fsS http://127.0.0.1:8808/api/latest; systemctl show ar-local-daily.service -p Result -p ExecMainStatus -p NRestarts -p InvocationID -p InactiveEnterTimestamp"
```

### Stop and rollback conditions

Stop on dirty protected checkout, Pi SHA drift, active ingest, D-006 freeze,
changed evidence, review/CI failure, unresolved substantive thread,
operator-writable trusted-parent path, token ambiguity, task drift, catalog
failure or less than 50 GiB free. Before an authorized transition, rollback
means no mutation. During a later authorized transition, rollback must restore
the exact authenticated task, ACLs, protected files, runner, configuration and
pointer, record `ROLLED_BACK`, and never trigger backup or ingest to compensate.

## Entry `HANDOFF-20260831T100733+1000-A3-TRUSTED-BOOTSTRAP-AUTHORITY`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260831T100733+1000-A3-TRUSTED-BOOTSTRAP-AUTHORITY` |
| Previous handoff entry | `HANDOFF-20260831T080717+1000-A3-FAIL-CLOSED-AUTHORITY-CORRECTION` |
| Created | `2026-08-31T10:07:33+10:00` / `2026-08-31T00:07:33Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Documentation source | clean `origin/main` worktree at `c40c57b39846866bd2b7c05c9255f50d31f9c755`; pre-append handoff Git-blob SHA-256 `330212f84565ba532373b486daa6045ed2f475c97c3cd880156f9555e016e4d8` |
| Protected Pi | `9302890fcc752cbf90da97d597e972c157d913e3`; clean; service inactive, timer enabled/active, lock absent and dashboard HTTP 200 at authorization preflight |
| Implementation | PR #584 head `43ba29ba7194e022500378b8dad9c8b8c0f3969d`, merge `c40c57b39846866bd2b7c05c9255f50d31f9c755`; PR #586 head `510d7680a21fbc31765a4be46dfeb04ea9fda286`, merge `4428f12089576523e41de40fb08c29cbf8fe60ab`; PR #587 head `80b42b2dbd63a04d0e5006d23cd26d9ca7bd7042`, merge `8182ba8245569395ddab3c5fd1e2ee549c475eb8`; PR #588 head `42cef4e33d5a5120d736da5d90720b0d8132d2b7`, merge `5dee9e0334a7ad34b49e5b95099525d6218e1e6a`; final catalog/invocation/ACL hardening PR #589 head `69f8327a34aed31254a9276826d97306c5eb7bc9`, merged as candidate `87650e250a536c0920548a4db38aa76623eb6a9f` |
| Result | implementation and authority decision `PASS`; live transition `NOT_STARTED`; A3 `RUNNING`; A4 `BLOCKED` |
| Deviations | append-only decisions `D-011` and `D-012` below |

### Reviewed implementation outcome

PR #584 replaced the withdrawn D-009 design with a trusted-parent bootstrap;
PR #586 then preserved ACE inheritance provenance in semantic SDDL and enforced
the exact candidate-and-authority-derived protected-root names. PR #587 made
the installer consume a typed, hash-bound pre-execution manifest; moved package,
canonical-manifest, authority-currentness and control-state checks before task
mutation; preserved restored raw SDDL; and made package Git metadata reproducible.
PR #588 bound the exact target and recovery paths, rejected backup residue,
preserved/restored the dispatcher-control ACL, and quarantined failed protected
roots and displaced control state into hashed evidence on every failure path.
PR #589 then moved the authenticated catalog baseline fully inside the elevated
boundary, validates every catalog chain link and pointer binding, hashes the
accepted archive bytes, binds a typed canonical invocation contract and observed
preflight, verifies the bound authority actually contains D-011/D-012 before
recording them, and requires Administrators ownership, SYSTEM/Administrators
full control, operator read/execute, no operator write and no deny ACE.
The scheduled task will enter an administrator-protected native launcher before
it reads any operator-writable configuration or code. The launcher derives a
restricted token with `CreateRestrictedToken`, proves the expected integrity
and token facts, and starts only hash-bound protected code. The one-time
installer uses a protected staging root, exact package population, protected
Python runtime, exact detached candidate and authority repositories, a disabled
production task during control mutation, a disposable semantic probe, a
mutation journal and independent rollback attempts.

Both exact PR heads passed the hosted Windows PowerShell 5.1 dispatcher
contract, Linux payload-builder suite, `bot-feedback-gate` and Sourcery review.
PR #584's complete local repository suite passed with 1342 tests and 13 skips.
On PR #586, the focused installer suite passed locally; the full local suite
reported 1340 passed and 13 skipped, with only two compiler-dependent launcher
tests unavailable because `cl.exe` was not loaded in that shell, while the
hosted Windows job passed those exact contracts. All substantive review
findings were implemented and resolved. The advisory Gemini jobs failed
independently and are not required gates. Merge alone is not runtime acceptance.

PR #587's final head also passed the hosted Windows PowerShell 5.1 dispatcher
contract, Linux payload-builder suite, `bot-feedback-gate` and Sourcery review.
Its focused local installer/dispatcher suite passed 20 tests. Findings covering
canonical JSON, pending/pointer/receipt state, expired idempotent recovery,
future timestamps and typed manifest fields were implemented and resolved.
PR #588's final head passed the same hosted Windows/Linux and feedback gates;
its focused local installer/dispatcher suite passed 20 tests, including injected
ACL-verification failure with displaced-control preservation.
PR #589's final head passed the hosted Windows PowerShell 5.1 dispatcher
contract, Linux payload-builder suite, `bot-feedback-gate` and Sourcery review.
The complete local repository suite passed with 1343 tests and 13 skips when
run inside the MSVC x64 environment; its focused installer and native-launcher
contracts passed separately. All substantive PR #589 findings were implemented
or, for the impossible manifest-self-hash, explicitly declined under D-012's
non-circular outer-command binding and resolved. Advisory Gemini failed quota.

Exact immutable source blobs at final candidate
`87650e250a536c0920548a4db38aa76623eb6a9f` are:

| Path | Bytes | Git-blob SHA-256 |
|---|---:|---|
| `install_laptop_backup_trusted_dispatcher.ps1` | 37668 | `501024d3220b2b113dc17e56f7bbfd09ab299d0512bb8af3d5d59f4cec45cd6f` |
| `install_laptop_backup_trusted_dispatcher_core.ps1` | 34477 | `6e22b4a23c8227b995ad827b5547652412320d4a31eaab983d1ded86ba3c568a` |
| `laptop_backup_trusted_package.py` | 9175 | `9c1ab77734910f1a3762250a996697f0f4cc7142dd20481bb3fbd9b2fedf7ced` |
| `native/laptop_backup_trusted_launcher.cpp` | 18969 | `03d359cdb1b3ba0e5763daad803d964a00cf25581d64088b56db86f83b140071` |
| `run_laptop_backup_task.ps1` | 919 | `50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860` |
| `run_laptop_backup_trusted_child.ps1` | 7003 | `a61fa61efe1c9d16ad0d2c5dae4d69d973063e9ee981cf5d1bbc7772619872ef` |
| `laptop_backup_dispatcher.py` | 44905 | `1757d9eb4041802961d304b240c3c07799a2a45582deb055f9fe29d382be08db` |
| `laptop_backup_atomic.py` | 3324 | `d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c` |

### Authenticated live prestate

The read-only preflight at 10:05 Australia/Hobart found the production task
Ready and enabled, with `LastTaskResult=1`, last run
`2026-08-31T05:00:01+10:00`, next run `2026-09-01T05:00:00+10:00`, and its
old action still entering
`C:\code\backups\AR-local-pi5-receiver-f214e32\run_laptop_backup_task.ps1`.
The exact accepted prestate is:

| Item | Value |
|---|---|
| UTF-16LE task XML, including BOM | 4774 bytes; SHA-256 `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2` |
| raw Task Scheduler SDDL | `O:BAG:S-1-5-21-689213601-40760280-3596424081-1001D:AI(A;;FR;;;S-1-5-21-689213601-40760280-3596424081-1001)(A;ID;0x1f019f;;;BA)(A;ID;0x1f019f;;;SY)(A;ID;FA;;;BA)` |
| raw SDDL SHA-256 | `6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b` |
| semantic SDDL SHA-256 | `d0e0ac6dbbbe519444e70161be2a447fa7b6b718a710160e578bd9f4e4bf7965` |
| laptop free space | 144.31 GiB |

### Append-only deviation decision `D-011` — Task Scheduler SDDL equivalence

The earlier requirement that rollback reproduce the Task Scheduler SDDL text
byte-for-byte is revised. Windows Task Scheduler canonicalizes equivalent SDDL
when a task is registered, so raw-text equality after a genuine restore is not
a reliable or achievable rollback gate. This does not weaken the pre-mutation
gate: the installer must first observe the exact raw SDDL SHA-256 and the exact
semantic SHA-256 above or stop before mutation.

Rollback acceptance requires the exact authenticated XML, the same owner,
group, protected-DACL state, sorted effective ACE identities, qualifiers,
flags, masks, object types and opaque data, and therefore the exact semantic
SDDL SHA-256 above. Both the original and restored raw SDDL strings and hashes
must be preserved in immutable evidence. Any semantic difference, additional
unprivileged mutation right, missing administrator/system right or XML drift is
`FAIL` or `ROLLED_BACK`, never `PASS`.

Reason: observed Task Scheduler canonicalization. Risk: a semantic normalizer
could hide a meaningful permission change. Compensating controls: exact raw
prestate binding, narrow explicit semantic fields, protected-DACL enforcement,
dangerous-right rejection, raw before/after preservation and hosted Windows
round-trip tests. Revised acceptance is semantic equality plus the unchanged
task XML and explicit access-control assertions.

### Append-only deviation decision `D-012` — post-merge bootstrap binding

D-010 required a later entry to contain the final authority commit, complete
handoff hash, protected package hash and an exact command hash. Those values are
cryptographically self-referential if the package embeds the authority checkout
and complete handoff containing its own package hash. The intent is retained
without inventing a circular digest.

This entry authorizes a two-stage, fail-closed binding:

1. merge this documentation-only entry through normal exact-head gates;
2. treat that merge as the sole authority commit only while it is the current
   canonical `origin/main`, contains this entry, and its complete handoff
   Git-blob hash is independently calculated;
3. outside D-006, create clean detached candidate and authority checkouts, build
   the native launcher reproducibly, generate an expiring dispatcher manifest,
   and build one deterministic protected package using only candidate
   `87650e250a536c0920548a4db38aa76623eb6a9f` and that authority merge;
4. before elevation, write an immutable pre-execution manifest recording every
   input/output path, byte length and SHA-256, the complete installer command,
   rollback procedure, current task/Pi/space/process gates and plan identity;
5. authenticate that pre-execution manifest and execute the installer exactly
   once with the operator's elevated token. No other elevated command is
   authorized. The installer must consume its exact path and SHA-256, require
   typed agreement with every invocation parameter, preserve it in protected
   evidence and reauthenticate all hashes and gates.

Reason: eliminate an impossible self-hash while preserving exact byte binding.
Risk: an operator-writable staging file could be replaced between validation
and elevation. Compensating controls: unique non-reused paths, `CreateNew`
evidence, complete SHA-256 binding, a single authenticated command file,
locked-stream package verification, protected staging before extraction,
revalidation inside the elevated installer and removal of all probe markers.
Revised acceptance requires the immutable pre-execution record and terminal
protected `bootstrap-result.json` to agree on every identity and hash. Any main
advance, input drift, expired manifest, ambiguous privilege, unexpected task
state or evidence mismatch stops before mutation.

### Exact transition authority

After this entry merges, Codex may perform every routine non-administrator
build, validation, SSH, Git, GitHub and evidence command unattended. Exactly one
UAC elevation is authorized solely to run the authenticated installer command.
It must occur in daylight outside D-006 while the Pi ingest is idle, the lock is
absent, the task is Ready, no backup helper/lock/partial exists, the protected
Pi is clean at `9302890fcc752cbf90da97d597e972c157d913e3`, and at least 50 GiB is
free. No backup or ingest may be manually triggered.

The protected install and bootstrap-evidence roots must be the exact distinct
direct children `%ProgramFiles%\AR-local-backup-trusted-<candidate>-<authority>`
and `%ProgramFiles%\AR-local-backup-evidence-<candidate>-<authority>`. The
installer derives and enforces those complete names. The target remains
`C:\code\backups\AR-local-pi5`; the control root
remains its `dispatcher-control`; the recovery image remains
`C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21`; operator
SID remains `S-1-5-21-689213601-40760280-3596424081-1001`; plan and protected
Pi identities remain those in this control record.

The authenticated no-write catalog baseline captured at
`2026-08-31T10:22:13+10:00` is:

| Catalog item | Exact baseline |
|---|---|
| `catalog/generations.jsonl` | 236234 bytes; SHA-256 `7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511`; final sequence 336, kind `macro`, entry SHA-256 `368ed91d6957d60eda5d76f06175e3ff00e20fb5cf5d6d2d94a478d164112420` |
| `catalog/latest-verified.json` | 316 bytes; SHA-256 `737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389`; observation catalog entry SHA-256 `6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68` |
| latest accepted receipt | `observations/2026-08-30/f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d/receipt.json`; 3392 bytes; SHA-256 `7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea` |
| accepted observation | `obs-2026-08-30-69a34aa4c745bb2e`; date `2026-08-30`; archive 237101208 bytes; SHA-256 `abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b` |

The bootstrap must hash these files immediately before and after transition and
prove exact equality. Any startup trigger, helper or external write that changes
the baseline blocks transition and requires fresh append-only authority; it
cannot be accepted as installer activity.

The elevated installer must independently reject `catalog/.receiver.lock`,
`transition.lease`, every `*.partial`/`.partial-*` residue and every matching
live backup/dispatcher/helper process before mutation. Its typed pre-execution
manifest must bind the exact recovery-image path in addition to the target and
control paths. Failed new roots are moved under protected execution evidence,
not deleted. Control rollback must restore both exact tree bytes and the
authenticated binary security descriptor; the displaced tree is preserved in
evidence even when ACL restoration or verification fails.
The typed manifest and installer arguments must also bind catalog entry
`6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68`
and the exact accepted archive size above. The installer must validate the full
336-entry catalog hash chain, its observation pointer, receipt and actual
archive bytes before and after transition.

Terminal bootstrap acceptance requires a protected-root ACL denying the
operator write access, exact package population, exact detached repositories,
restricted-token semantic probe, terminal activation receipt, enabled Ready
task with the intended native-launcher action, no probe/finalize marker, no
helper/lock/partial, catalog unchanged by transition, and a `PASS` execution
record. On failure, the installer must attempt all rollback components,
preserve evidence and report `ROLLED_BACK` or `FAIL`.

Bootstrap `PASS` does not complete A3. The task must then pass the natural
`2026-09-01` 05:00 run with `BACKUP-LATEST` for the current accepted observation
and exact catalog/receipt/restore/source-identity validation. D-006 continues to
protect the natural 01:00 capture. Only a later append-only terminal entry may
mark A3 `PASS` and start A4.

## Entry `HANDOFF-20260831T114941+1000-A3-FINAL-TRUSTED-CANDIDATE`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260831T114941+1000-A3-FINAL-TRUSTED-CANDIDATE` |
| Previous handoff entry | `HANDOFF-20260831T100733+1000-A3-TRUSTED-BOOTSTRAP-AUTHORITY` |
| Created | `2026-08-31T11:49:41+10:00` / `2026-08-31T01:49:41Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Pre-append handoff Git-blob SHA-256 | `63263d0cdc69c81c01ec21b51f0dce5b372afb7c3b86beb096f52f221dec0da6` |
| Final implementation | PR #590 head `f073a9b3712e62ad7d93fcd1e258b12e3ee80ad1`; squash merge and candidate `64d0f4a09fdcf5a15ad28effe6b8b114fd9134ff` |
| Protected Pi | remains `9302890fcc752cbf90da97d597e972c157d913e3`; no deployment, ingest, publication or production-task execution was performed by this implementation work |
| Result | final implementation and authority addendum `PASS`; live transition `NOT_STARTED`; A3 `RUNNING`; A4 `BLOCKED` |
| Deviations | D-011 and D-012 remain the complete authorized deviations; no new deviation is introduced |

### Why this addendum is authoritative

The previous entry deliberately left the transition candidate at PR #589 while
two terminal acceptance defects found during its authority review were repaired
in a separate behavioral PR. PR #590 is now merged. This addendum supersedes
only the earlier candidate and source-byte bindings; it does not rewrite the
earlier entry, relax any gate, authorize deployment, or change the authenticated
task, catalog, Pi, plan, target, recovery-image, operator or rollback identities.

PR #590 made the already-installed path validate the complete active control
tree and terminal quiescence rather than only the active pointer. It requires
every successful predecessor manifest and exact PASS receipt, rejects a stale
pointer, contradictory terminal receipts, missing lineage, activation-ID reuse,
cycles, PASS outcomes outside the active chain and Windows reparse-point control
directories. Historical predecessor identity is checked cryptographically
without reopening mutable legacy runtime paths.

The installer now holds `Global\ARLocalTrustedBootstrapGate` before enabling
the production task and through terminal evidence. Both the native launcher and
ordinary-token dispatcher activation fail closed while that gate exists. The
launcher additionally requires exact administrator-protected
`bootstrap.ready` bytes. That readiness marker is flushed only after active
control, catalog, task Ready/enabled, process, lock, lease, partial-residue and
ACL gates have passed. Therefore a scheduled trigger cannot start in the final
verification/PASS interval, an ordinary activation cannot replace the pointer,
and a hard installer exit before readiness cannot authorize production backup.
The task is never manually started by the installer.

The exact PR #590 head passed the hosted Linux payload-builder and Windows
PowerShell 5.1 dispatcher-contract jobs. Required `bot-feedback-gate` reruns
passed after every substantive Codex and Sourcery thread received an
`Implemented` disposition and was resolved. Sourcery passed. Gemini exhausted
its external free-tier quota and remained advisory under repository policy.
The complete local suite at exact head, executed inside the MSVC x64 developer
environment, passed `1348` tests with `13` intentional skips and four existing
OpenPyXL warnings. Focused dispatcher/installer tests passed `24`; native
launcher tests passed `5` with one privilege-dependent integration skip.

### Exact final candidate source bytes

The sole candidate is
`64d0f4a09fdcf5a15ad28effe6b8b114fd9134ff`. The deterministic package and
pre-execution record must use these Git-blob bytes exactly:

| Path | Bytes | Git-blob SHA-256 |
|---|---:|---|
| `install_laptop_backup_trusted_dispatcher.ps1` | 43557 | `fb283fceedbe146f0b287938d866d4f8201c77781d72b7092fcde76408931927` |
| `install_laptop_backup_trusted_dispatcher_core.ps1` | 34884 | `1fe2f2b38945066480343be4ec8ed622ce9693faa914943adb9c7e5ef320d1ea` |
| `laptop_backup_trusted_package.py` | 9175 | `9c1ab77734910f1a3762250a996697f0f4cc7142dd20481bb3fbd9b2fedf7ced` |
| `native/laptop_backup_trusted_launcher.cpp` | 20669 | `d7a5fd39b47a68d65e7bd36e87e1d65768bece824b935f3f399fd016b4e20fcb` |
| `run_laptop_backup_task.ps1` | 919 | `50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860` |
| `run_laptop_backup_trusted_child.ps1` | 7003 | `a61fa61efe1c9d16ad0d2c5dae4d69d973063e9ee981cf5d1bbc7772619872ef` |
| `laptop_backup_dispatcher.py` | 52997 | `6794266064f58a613547441100721ccbb2b3d385abe85ea027052dd08dc15dad` |
| `laptop_backup_atomic.py` | 3324 | `d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c` |

### Exact continuation authority

Merge this documentation-only authority through exact-head gates. Under D-012,
the resulting current `origin/main` merge is the sole authority commit. Compute
and record that merge and the complete handoff Git-blob SHA-256 before building.
If `origin/main` advances again, the authority expires and a new append-only
entry is required; conversational substitution is prohibited.

Outside D-006, use clean detached candidate and authority checkouts, compile the
native launcher twice and require identical hashes, build one deterministic
package, and create one expiring typed pre-execution manifest. Immediately
before elevation, reauthenticate the exact task XML/raw and semantic SDDL,
`LastTaskResult`, complete catalog chain/latest pointer/accepted receipt/archive,
free space, helper/lock/partial absence and clean protected Pi state. Any changed
baseline is `BLOCKED` until recorded by another append-only authority entry.

Exactly one UAC elevation remains authorized for the authenticated installer
command. Codex must execute every other safe Git, PowerShell, SSH, build,
validation, evidence and GitHub command unattended. No backup task, Pi ingest,
deployment or publication may be manually triggered. Installer terminal `PASS`
still does not complete A3: the natural `2026-09-01` 01:00 ingest must remain
protected by D-006, and the first natural trusted 05:00 backup must independently
pass with a current observation, exact identities, catalog/receipt/archive and
restoration evidence. Only a later append-only terminal `PASS` may close A3 and
authorize A4 planning or implementation.

## Entry `HANDOFF-20260831T120011+1000-A3-FINAL-AUTHORITY-CORRECTION`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260831T120011+1000-A3-FINAL-AUTHORITY-CORRECTION` |
| Previous handoff entry | `HANDOFF-20260831T114941+1000-A3-FINAL-TRUSTED-CANDIDATE` |
| Created | `2026-08-31T12:00:11+10:00` / `2026-08-31T02:00:11Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Pre-append handoff Git-blob SHA-256 | `cfa3c0e93c7fc2403de08c07cd7be9d5ca18910bd0398efdd33c67688807435a` |
| Final implementation | PR #591 head `580d3ea001e7b379d795263ad9f4d34049cab5c5`; squash merge and sole candidate `bce4f705136992610a44f05856b94aca2e7605c1` |
| Result | final implementation and corrected authority `PASS`; live transition `NOT_STARTED`; A3 `RUNNING`; A4 `BLOCKED` |
| Deviations | D-011 and D-012 only; no new deviation |

### Final authority-review corrections

PR #591 closes the last two behavioral defects found while reviewing the prior
authority entry. The trusted installer now runs the complete protected-Pi SHA,
cleanliness, inactive-ingest-service, absent-ingest-lock and dashboard check a
second time immediately before copying the control prestate and disabling the
production task. The exact second result is preserved as
`pi-immediate-pre-mutation.json`. A natural ingest that starts during package or
authority validation therefore blocks before the first task/control mutation.

If the disposable restricted-token probe times out, rollback now explicitly
stops the probe task, waits for it to leave `Running`, and proves that no native
launcher, dispatcher, trusted child or backup helper remains before unregistering
the probe or touching control/task/protected-root state. If this quiescence proof
fails, task/control/root rollback mutations are withheld, the protected evidence
records the condition, and the outcome is `FAIL`, never `ROLLED_BACK` or `PASS`.

The exact PR #591 head passed the hosted Linux payload-builder and Windows
PowerShell 5.1 dispatcher-contract jobs, both required feedback-gate executions,
and Sourcery with zero unresolved threads. Gemini again exhausted external quota
and is advisory. The exact-head complete local suite under the MSVC x64 developer
environment passed `1348` tests with `13` intentional skips and four existing
OpenPyXL warnings; the focused installer/dispatcher set passed `24`.

### Correct natural 05:00 acceptance

The prior statement requiring only action `BACKUP-LATEST` is superseded. At this
authority snapshot the laptop's latest accepted observation is `2026-08-30`,
while the Pi has a completed `2026-08-31` observation. After the protected natural
`2026-09-01` 01:00 ingest, the first trusted 05:00 scheduler may therefore
correctly choose the combined action `BACKFILL`: it transfers the genuinely
missing historical `2026-08-31` observation and the latest `2026-09-01`
observation in one controlled execution. Rejecting that correct action would
strand A3 and would encourage an unsafe manual pre-run backfill.

Do not manually trigger or pre-run any backup. The first natural trusted 05:00
execution is accepted only when every record is bound to this plan, final
candidate, final authority, protected Pi and operator and one of these exact
conditions holds:

1. `BACKFILL/PASS`: pre-run inventory proves `2026-08-31` was genuinely missing;
   both `2026-08-31` and the current `2026-09-01` observation are transferred,
   content-addressed, receipted and restore-verified; the post-run missing-date
   set is empty; latest-verified points to `2026-09-01`; and no existing
   observation or completed evidence is overwritten.
2. `BACKUP-LATEST/PASS`: accepted only if independent pre-run evidence proves
   `2026-08-31` had already been transferred by a natural authorized execution,
   so there was no historical gap to backfill, and the latest `2026-09-01`
   observation is fully verified.
3. `NO_BACKUP_DATA_WRITE/PASS`: accepted only if independent Pi/catalog/receipt,
   control, macro, diagnostics and history identities prove both dates and the
   latest observation were already present and unchanged. A failure of the Pi
   observation to advance can never be reclassified as no-write success.

For every accepted action, validate every intervening scheduled-run record,
append-only catalog prefix and final chain, observation/control/macro receipts,
archive hashes and sizes, SQLite restoration/integrity where required, exact Pi
source identities, task Ready/enabled with `LastTaskResult=0`, no overlap, lock,
lease, helper or partial residue, and at least 50 GiB free. Any other action,
missing date, identity drift, failed restore or unexplained no-write is terminal
`FAIL` or `BLOCKED`; A3 remains open.

### Sole candidate byte binding and continuation

The sole candidate is now
`bce4f705136992610a44f05856b94aca2e7605c1`. It supersedes the PR #590 candidate
in the immediately preceding entry. Exact Git-blob bytes are:

| Path | Bytes | Git-blob SHA-256 |
|---|---:|---|
| `install_laptop_backup_trusted_dispatcher.ps1` | 45474 | `b0430a55141bf267f4311a84f3a99e82107687725039f773ec4d6f037cd75dab` |
| `install_laptop_backup_trusted_dispatcher_core.ps1` | 34884 | `1fe2f2b38945066480343be4ec8ed622ce9693faa914943adb9c7e5ef320d1ea` |
| `laptop_backup_trusted_package.py` | 9175 | `9c1ab77734910f1a3762250a996697f0f4cc7142dd20481bb3fbd9b2fedf7ced` |
| `native/laptop_backup_trusted_launcher.cpp` | 20669 | `d7a5fd39b47a68d65e7bd36e87e1d65768bece824b935f3f399fd016b4e20fcb` |
| `run_laptop_backup_task.ps1` | 919 | `50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860` |
| `run_laptop_backup_trusted_child.ps1` | 7003 | `a61fa61efe1c9d16ad0d2c5dae4d69d973063e9ee981cf5d1bbc7772619872ef` |
| `laptop_backup_dispatcher.py` | 52997 | `6794266064f58a613547441100721ccbb2b3d385abe85ea027052dd08dc15dad` |
| `laptop_backup_atomic.py` | 3324 | `d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c` |

Merge this documentation-only authority through exact-head gates. Under D-012,
the resulting current `origin/main` merge and complete handoff Git-blob SHA-256
become the only allowed authority identity. Immediately before the single
authorized elevation, repeat every task, process, residue, catalog, free-space
and Pi gate and rebuild the deterministic package from clean detached candidate
and authority checkouts. Any later `origin/main` advance or baseline drift
expires this authority and requires another append-only decision. No manual
backup, ingest, deployment or publication is authorized. A3 remains `RUNNING`
until installer terminal `PASS` and the protected natural 01:00/05:00 proofs;
A4 remains `BLOCKED`.

## Entry `HANDOFF-20260831T125641+1000-A3-RECOVERY-SAFE-CANDIDATE`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260831T125641+1000-A3-RECOVERY-SAFE-CANDIDATE` |
| Previous handoff entry | `HANDOFF-20260831T120011+1000-A3-FINAL-AUTHORITY-CORRECTION` |
| Created | `2026-08-31T12:56:41+10:00` / `2026-08-31T02:56:41Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Pre-append handoff Git-blob SHA-256 | `815cc03c89b0a6e0152d54be448f9196a274bd129e7fb671d48fc689542c0160` |
| Final implementation | PR #592 head `e6e92c782fb743dcb9913bf158582d0f5bd0143b`; squash merge and sole code candidate `0a444caab7624499bca7ffdbbc56189e152e53e9` |
| Protected Pi | remains clean and pinned at `9302890fcc752cbf90da97d597e972c157d913e3`; this implementation performed no Pi deployment, ingest, publication or backup-task trigger |
| Result | implementation and corrected authority `PASS`; live bootstrap `NOT_STARTED`; A3 `RUNNING`; A4 `BLOCKED` |
| Deviations | D-011 and D-012 only; no new deviation |

### Correct predecessor provenance

The digest `63263d0cdc69c81c01ec21b51f0dce5b372afb7c3b86beb096f52f221dec0da6`
recorded by the `HANDOFF-20260831T114941+1000-A3-FINAL-TRUSTED-CANDIDATE`
entry is reproducible from the raw Git blob
`67723eee0d03dd8d25e68c2e748a0b4268353bc6:docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md`.
That merge commit has first parent
`8b077e6964616940feb3a84bfed0fbb82576ec7e` and second parent
`64d0f4a09fdcf5a15ad28effe6b8b114fd9134ff`; its
handoff blob is 400049 bytes and has the stated SHA-256. This append-only entry
names the canonical source commit explicitly; it does not rewrite the earlier
record.

### Terminal behavioral corrections

PR #592 closes every remaining authority-review defect before elevation.
Ordinary manifest activation now creates and owns the same global bootstrap
mutex before acquiring `transition.lease` and holds it until the lease is
released. The installer and ordinary activator therefore cannot pass separate
check-then-act windows or replace a pointer outside the state the installer
validated.

The protected task SDDL now has a semantic SHA-256 seal created before task
activation and rechecked on every installed-state recovery. A changed positive
SYSTEM, Administrators or operator grant cannot be reported as idempotent
`PASS` merely because dangerous unprivileged rights remain absent.

Terminal bootstrap publication is crash recoverable. A protected
`bootstrap.installing.json`, authenticated prior task/control evidence and the
append-only mutation journal distinguish an interrupted root publication. A
rerun under the global mutex can stop only authenticated disposable helpers,
restore the exact old task and changed control tree, recheck the immutable
catalog and quarantine the partial root. Once terminal validation is complete,
all publication intents and incomplete-sibling reconciliation finish before the
execution record hashes its evidence. The PASS result and readiness marker are
each written to a fixed sibling, flushed, and promoted with
`MoveFileExW(MOVEFILE_WRITE_THROUGH)`. The native launcher hashes the exact
durable result and accepts only the V2 readiness marker containing that digest;
altered, stale, truncated, reparse-point or contradictory bytes fail before any
backup child starts. The execution record excludes itself from its evidence
inventory so a later failure rewrite cannot invalidate its own hashes.

Exact-head hosted Linux payload-builder, Windows PowerShell 5.1 dispatcher
contract, Gemini, Sourcery and required feedback gates passed with no unresolved
threads. The complete local exact-head suite in the MSVC x64 environment passed
`1352` tests with `13` intentional skips and four existing OpenPyXL warnings.

### Exact sole-candidate source bytes

The deterministic package and authenticated manifest must use Git-blob bytes
from candidate `0a444caab7624499bca7ffdbbc56189e152e53e9` exactly:

| Path | Bytes | Git-blob SHA-256 |
|---|---:|---|
| `install_laptop_backup_trusted_dispatcher.ps1` | 65914 | `cc2fa123166c36403b10fe097a10c06c793ea286324f170e56882b4c492843a9` |
| `install_laptop_backup_trusted_dispatcher_core.ps1` | 35670 | `0199ff7d04090558cfd1f7c30532297ce145806589217935a970d68b171887ea` |
| `laptop_backup_trusted_package.py` | 9175 | `9c1ab77734910f1a3762250a996697f0f4cc7142dd20481bb3fbd9b2fedf7ced` |
| `native/laptop_backup_trusted_launcher.cpp` | 23066 | `ce27291580f3a2e0a541849ded828576be1b90350f6a57f2713464fcf4f4ad02` |
| `run_laptop_backup_task.ps1` | 919 | `50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860` |
| `run_laptop_backup_trusted_child.ps1` | 7003 | `a61fa61efe1c9d16ad0d2c5dae4d69d973063e9ee981cf5d1bbc7772619872ef` |
| `laptop_backup_dispatcher.py` | 54023 | `3c00cf2c0a101a34f3ab1d98af22348a648838d7dfe3419fa034fd3ae66b7a46` |
| `laptop_backup_atomic.py` | 3324 | `d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c` |

### Continuation authority

Merge this documentation-only authority through exact-head CI and thread gates.
Under D-012, that merge commit and the complete merged handoff Git-blob SHA-256
become the only authority identity. Build from separate clean detached candidate
and authority checkouts, compile the launcher twice with identical output,
construct one deterministic package and one short-lived typed pre-execution
manifest, and repeat the exact live task, catalog, process, residue, free-space
and protected-Pi checks immediately before the one authorized elevation. Any
identity or baseline change blocks and requires a new append-only entry.

Installer `PASS` still does not close A3. D-006 protects the natural
`2026-09-01` 01:00 ingest, and the first natural trusted 05:00 backup must meet
the action-specific conditions in the immediately preceding entry with exact
catalog, archive, restore and Pi-source equality. Never manually trigger the
backup or ingest. Only a later append-only terminal `PASS` may complete A3 and
authorize A4.

## Entry `HANDOFF-20260831T211140+1000-A3-MAXPATH-RECOVERY-AUTHORITY`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260831T211140+1000-A3-MAXPATH-RECOVERY-AUTHORITY` |
| Previous handoff entry | `HANDOFF-20260831T125641+1000-A3-RECOVERY-SAFE-CANDIDATE` |
| Created | `2026-08-31T21:11:40+10:00` / `2026-08-31T11:11:40Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Documentation source | clean `origin/main` worktree at `c9a6465d9acf90cda324c04ee596ce200269566c`; pre-append handoff Git-blob SHA-256 `12f63010ca6db237a8bd1c98f0978213c426d335ce2a72446cdaf6fcc5ced027` |
| Corrected implementation | PR #593 head `291b99ab6403bcc25773838fa22a248f5f1e002e`; squash merge and sole code candidate `c9a6465d9acf90cda324c04ee596ce200269566c` |
| Protected Pi | remains pinned to `9302890fcc752cbf90da97d597e972c157d913e3`; PR #593 performed no Pi deployment, ingest, publication, backup or production-task trigger |
| Result | prior live bootstrap `FAIL` with package staging quarantined before task/control mutation; corrected implementation and this authority `PASS`; new live bootstrap `NOT_STARTED`; A3 `RUNNING`; A4 `BLOCKED` |
| Deviations | D-011 and D-012 remain; append-only D-013 below authorizes only the corrected short staging/quarantine recovery mechanism |

### Previous elevation outcome — immutable failure, not success

The one elevated attempt against candidate
`0a444caab7624499bca7ffdbbc56189e152e53e9` and authority
`dc78b85368c020dcbcbb357b932e56110999f105` failed during protected package
staging. Its immutable evidence root is:

`C:\Program Files\AR-local-backup-evidence-0a444caab7624499bca7ffdbbc56189e152e53e9-dc78b85368c020dcbcbb357b932e56110999f105\20260831T090802Z-5b12a8455b9b4c14b36071bc498eb8eb`

The mutation journal is 514 bytes with SHA-256
`2d3345aee82b2b453d1aaf627b9c9d29146b12d1030f805b53463f782d8e2fb3`.
It contains exactly `CREATE_PACKAGE_STAGING` followed by
`ROLLBACK_QUARANTINE_NEW_ROOT`. The failed package tree remains preserved under
`failed-protected-root-581f0969148949e885236eda24ae2e06`; it was not deleted
or adopted. No `bootstrap-result.json` exists, so this attempt is permanently
`FAIL`, never `PASS` or an inferred terminal `ROLLED_BACK`.

The authenticated task XML remained 4774 bytes with SHA-256
`aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`;
its raw SDDL remained 160 bytes with SHA-256
`6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b`.
The attempt did not replace or enable a new task action, activate dispatcher
control, alter the backup catalog, trigger a backup, deploy to the Pi, run an
ingest or manipulate publication. No direct `ARLBS-*` or `ARLBQ-*` root remains
at this authority snapshot.

The concrete failure was legacy Windows `MAX_PATH`: the old long staging root
plus a content-addressed package entry produced a 265-character path. That
prevented reliable ACL/evidence handling and, in turn, prevented the terminal
result from being written. The corrected direct short-root layout has a maximum
equivalent path of 157 characters. The failed attempt's generated dispatcher
manifest also used the broad parent `C:\code\backups` as the allowed target
root. That manifest is rejected and inert; the next manifest must bind the
exact target `C:\code\backups\AR-local-pi5` and exact recovery-image root.

### Append-only deviation decision `D-013` — short protected failure roots

The D-011 instruction to move every failed new protected root beneath the
already long execution-evidence path is revised only where that nesting can
cross legacy `MAX_PATH`. Bootstrap package staging shall use a unique direct
child `%ProgramFiles%\ARLBS-<32-lowercase-hex>`. A failed or interrupted tree
shall be moved intact to a unique direct child
`%ProgramFiles%\ARLBQ-<32-lowercase-hex>`, never deleted, flattened, silently
adopted or placed outside Program Files.

Reason: the authenticated live failure proved that the prior nested layout can
make both rollback evidence and terminal status unavailable. Risk: a protected
quarantine outside its originating execution directory could become orphaned,
ambiguous, or omitted from later evidence. Compensating controls are:

- one global bootstrap mutex is acquired before reconciliation and held through
  terminal `PASS`, failure rollback, or process exit;
- every staging creation, recovery seal, quarantine publication and recovery
  completion is durably appended to a protected journal before its mutation;
- startup scans every controlled Program Files evidence root and every direct
  `ARLBS-*`/`ARLBQ-*` root, rejecting unknown, duplicate, both-present,
  both-absent, mismatched or unjournaled state;
- an interrupted inherited staging tree or legacy inherited journal is accepted
  only after reparse-point, owner, deny-ACE, effective-right and unprivileged-
  write validation, then sealed and revalidated before any move;
- journal references bind the immutable byte prefix through the referenced
  intent by line count, prefix byte length and SHA-256, so later durable appends
  cannot invalidate completed reconciliation evidence; and
- each quarantine is administrator-owned, inheritance-protected, recursively
  verified and content-inventoried with exact relative paths, sizes and SHA-256
  values in the normal protected execution evidence.

Revised acceptance requires zero unexplained direct short roots, complete
journal-prefix verification, complete quarantine inventory and ACL verification,
and a durable terminal `bootstrap-result.json`. Any ambiguity is `FAIL` before
task/control mutation. This deviation does not widen task privilege, weaken UAC,
authorize deletion, alter D-006, or permit any Pi or publication change.

### Corrected implementation and verification

PR #593 implements D-013 and fixes the terminal-evidence failure. Protected
staging and quarantine roots are short direct Program Files children. Failure
is durably observed before rollback. The global gate covers complete
reconciliation and transition. Every prior evidence journal participates in
global recovery. An interruption immediately after staging creation is
recoverable; an interrupted move is completed only from its authenticated
journal state. Journal files are synchronously flushed and sealed. Quarantine
inventories and reconciliation records are bound into terminal evidence.

Three exact-head Codex findings were implemented and resolved: safe inherited
staging trees are validated and sealed before quarantine; mutable journals are
referenced by immutable prefix identities; and safe inherited legacy journals
have an authenticated migration path. The exact PR head passed the hosted
Windows PowerShell 5.1 dispatcher contract, Linux payload-builder tests and the
required `bot-feedback-gate`, with zero unresolved review threads. Local focused
installer tests passed `6`; the non-administrator PowerShell contract passed;
and the broader suite excluding compiler-dependent native-launcher tests passed
`1347` with `12` intentional skips and four existing OpenPyXL warnings. The
hosted contract is the authoritative PowerShell 5.1/administrator recovery test.

### Exact sole-candidate source bytes

Only Git-blob bytes from candidate
`c9a6465d9acf90cda324c04ee596ce200269566c` may be packaged:

| Path | Bytes | Git-blob SHA-256 |
|---|---:|---|
| `install_laptop_backup_trusted_dispatcher.ps1` | 65214 | `8258f16b0c4fa65c8edf80a58216eb97c5340bbe3d341cac7d182c0503252c39` |
| `install_laptop_backup_trusted_dispatcher_core.ps1` | 53504 | `7d1b1810dcb93f4fec63f9b383122b92c9ad5ed81c13c8e82d6213c5a91890a7` |
| `laptop_backup_trusted_package.py` | 9175 | `9c1ab77734910f1a3762250a996697f0f4cc7142dd20481bb3fbd9b2fedf7ced` |
| `native/laptop_backup_trusted_launcher.cpp` | 23066 | `ce27291580f3a2e0a541849ded828576be1b90350f6a57f2713464fcf4f4ad02` |
| `run_laptop_backup_task.ps1` | 919 | `50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860` |
| `run_laptop_backup_trusted_child.ps1` | 7003 | `a61fa61efe1c9d16ad0d2c5dae4d69d973063e9ee981cf5d1bbc7772619872ef` |
| `laptop_backup_dispatcher.py` | 54023 | `3c00cf2c0a101a34f3ab1d98af22348a648838d7dfe3419fa034fd3ae66b7a46` |
| `laptop_backup_atomic.py` | 3324 | `d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c` |

### Exact continuation authority

Merge this documentation-only entry through exact-head gates. Under D-012, the
resulting current `origin/main` merge and complete merged handoff Git-blob
SHA-256 become the sole authority. From separate clean detached candidate and
authority checkouts, rebuild the launcher twice with identical bytes, construct
one deterministic package and one fresh expiring typed pre-execution manifest.
The manifest and installer invocation must bind the exact target root
`C:\code\backups\AR-local-pi5`, recovery-image root
`C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21`, candidate,
authority, handoff, plan, protected Pi, operator, task, catalog and package
identities.

Immediately before elevation, reauthenticate current `origin/main`, exact task
XML/SDDL/Ready state, full catalog chain and accepted bytes, free space,
process/lock/lease/partial absence, clean protected Pi state, inactive ingest,
absent ingest lock, enabled/active timer and dashboard HTTP health. Any drift
requires another append-only authority; conversational substitution is invalid.

Exactly one fresh UAC approval is authorized solely for the authenticated
installer command. It installs a fixed S4U/`Limited` ordinary-user dispatcher;
it does not grant blanket administrator permission. After installer terminal
`PASS`, no routine backup or candidate transition may require elevation.

D-006 remains controlling. No task change may begin at or after the 00:30
Australia/Hobart freeze. Installer `PASS` still does not close A3: the natural
`2026-09-01` 01:00 ingest and first natural trusted 05:00 backup must pass the
action-specific acceptance criteria in the preceding entries. No manual backup,
ingest, deployment or publication is authorized. Only a later append-only
terminal `PASS` may complete A3 and authorize A4.

## Entry `HANDOFF-20260831T220237+1000-A3-LEGACY-JOURNAL-AUTHORITY`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260831T220237+1000-A3-LEGACY-JOURNAL-AUTHORITY` |
| Previous handoff entry | `HANDOFF-20260831T211140+1000-A3-MAXPATH-RECOVERY-AUTHORITY` |
| Created | `2026-08-31T22:02:37+10:00` / `2026-08-31T12:02:37Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Documentation source | clean `origin/main` worktree at `12ea4407123843336934cc766383a89b9b69deb6`; pre-append handoff raw SHA-256 `b0324a6c14a62ea37917e977b40ab6ca717806b9e0e7c0ff7248a87002f7f085` |
| Corrected implementation | PR #595 exact head `b2bca5d576ec9acf04192a0f45fbccdc860f42cb`; squash merge and sole code candidate `12ea4407123843336934cc766383a89b9b69deb6` |
| Protected Pi | remains pinned to `9302890fcc752cbf90da97d597e972c157d913e3`; PR #595 performed no Pi deployment, ingest, publication, backup or production-task trigger |
| Result | legacy-journal compatibility implementation and exact-head gates `PASS`; new live bootstrap `NOT_STARTED`; A3 `RUNNING`; A4 `BLOCKED` |
| Deviations | D-006, D-011, D-012 and D-013 remain; append-only D-014 below narrowly governs the one historical overlong failed tree |

### Reason for this authority replacement

The D-013 implementation correctly moved all new staging and quarantine trees
to short protected Program Files roots. Its pre-mutation global reconciliation
also scans the immutable journal from the earlier failed elevation. That
historical journal intentionally names the former long staging layout, so the
otherwise correct D-013 scanner rejected it before a corrected bootstrap could
start. No new elevation was attempted with that mismatch.

The exact historical state remains:

- evidence root
  `C:\Program Files\AR-local-backup-evidence-0a444caab7624499bca7ffdbbc56189e152e53e9-dc78b85368c020dcbcbb357b932e56110999f105\20260831T090802Z-5b12a8455b9b4c14b36071bc498eb8eb`;
- journal 514 bytes, SHA-256
  `2d3345aee82b2b453d1aaf627b9c9d29146b12d1030f805b53463f782d8e2fb3`;
- exactly two non-empty physical records:
  `CREATE_PACKAGE_STAGING` immediately followed by
  `ROLLBACK_QUARANTINE_NEW_ROOT` for the identical normalized source;
- the named source is absent;
- exactly one preserved
  `failed-protected-root-581f0969148949e885236eda24ae2e06` remains under that
  execution evidence;
- no direct `ARLBS-*` or `ARLBQ-*` root exists; and
- task XML, task SDDL, dispatcher control, catalog and Pi production remain at
  their authenticated pre-attempt state.

### Append-only deviation decision `D-014` — opaque historical MAX_PATH tree

D-013's recursive ACL and content-inventory requirement continues unchanged for
every new `ARLBS-*` and `ARLBQ-*` staging or quarantine tree. It is narrowed only
for the single historical nested failed tree identified above. That tree was
created by the old layout whose descendant paths reach 330 characters and whose
PowerShell 5.1 recursive ACL/evidence operation already failed. Repeating that
same traversal is not an acceptance gate and its descendant bytes are not
trusted evidence.

The historical tree may be reconciled only as
`UNTRUSTED_OPAQUE_NOT_CONSUMED`, and only when all of these conditions hold:

- the evidence-root, execution-root, journal and failed-root names match their
  exact controlled grammars and contain no reparse point at an accepted root;
- the protected journal contains no empty physical line and parses completely;
- exactly one matching legacy create exists globally; duplicate source or
  preserved-root identity is an immediate failure;
- the immediately following physical journal record is the matching rollback
  intent for the byte-for-byte same normalized source path;
- the immutable journal-prefix identity is bound through that rollback record,
  including physical line count, byte length and SHA-256;
- the named long staging source remains absent;
- the execution contains exactly one grammar-valid preserved failed root;
- that outer root is inheritance-protected, Administrator-owned, contains no
  deny ACE, and grants no dangerous write right to any unprivileged principal;
  and
- neither installer, dispatcher, runtime, restore process nor acceptance
  evidence enumerates, hashes, executes, restores, adopts or otherwise consumes
  any descendant of the opaque tree.

Reason: recursive PowerShell 5.1 traversal of the abandoned overlong tree is the
operation already proven unsafe. Risk: its descendants might retain an unsafe
ACL or change without detection. Compensating control: the descendants are
explicitly untrusted and excluded from every code, package, runtime, restore and
acceptance input; only the protected outer container, absent source and
rollback-bound journal prefix are reconciled. This decision does not declare the
old failed attempt successful, does not authorize its deletion, does not weaken
the checks on any new short root, and does not widen task or operator privilege.

### Implementation and verification

PR #595 implements D-014. Reconciliation now accepts the controlled legacy
grammar only after the exact matching rollback and binds evidence through that
rollback line. Duplicate source/root identities and blank physical journal lines
fail closed. The record labels descendants
`UNTRUSTED_OPAQUE_NOT_CONSUMED`; normal short roots retain recursive ACL and
content-inventory verification.

All six substantive review findings were dispositioned and their threads
resolved. Duplicate detection, physical-line binding and matching rollback were
implemented. Recursive descendant trust and inventory were declined only for
this opaque non-consumed historical tree for the D-014 reason above. The exact
PR head passed the hosted Windows PowerShell 5.1 dispatcher contract, Linux
payload-builder tests, Sourcery and required `bot-feedback-gate`. Gemini returned
an advisory service-availability failure and no substantive unresolved finding.
Local focused tests passed `6`; the non-administrator PowerShell contract passed;
and the broader laptop-backup suite excluding compiler-dependent native-launcher
tests passed `317` with one intentional skip.

### Exact sole-candidate source bytes

Only Git-blob bytes from candidate
`12ea4407123843336934cc766383a89b9b69deb6` may be packaged:

| Path | Bytes | Git-blob SHA-256 |
|---|---:|---|
| `install_laptop_backup_trusted_dispatcher.ps1` | 65214 | `8258f16b0c4fa65c8edf80a58216eb97c5340bbe3d341cac7d182c0503252c39` |
| `install_laptop_backup_trusted_dispatcher_core.ps1` | 56839 | `543724ff7c0b4879aafdbdd9edf86e0ab5a726eaab8a04ebee2a3cbf2bbdf9a7` |
| `laptop_backup_trusted_package.py` | 9175 | `9c1ab77734910f1a3762250a996697f0f4cc7142dd20481bb3fbd9b2fedf7ced` |
| `native/laptop_backup_trusted_launcher.cpp` | 23066 | `ce27291580f3a2e0a541849ded828576be1b90350f6a57f2713464fcf4f4ad02` |
| `run_laptop_backup_task.ps1` | 919 | `50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860` |
| `run_laptop_backup_trusted_child.ps1` | 7003 | `a61fa61efe1c9d16ad0d2c5dae4d69d973063e9ee981cf5d1bbc7772619872ef` |
| `laptop_backup_dispatcher.py` | 54023 | `3c00cf2c0a101a34f3ab1d98af22348a648838d7dfe3419fa034fd3ae66b7a46` |
| `laptop_backup_atomic.py` | 3324 | `d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c` |

### Exact continuation authority

Merge this documentation-only entry through exact-head gates. Under D-012, that
merge commit and the complete merged handoff raw SHA-256 become the sole
authority. Prior packages, manifests and expiring invocation contracts remain
invalid and must not be elevated.

From separate clean detached candidate and authority checkouts, compile the
launcher twice and require identical bytes. Reuse only verified runtime source
bytes, then build the deterministic package twice and require identical bytes.
Create a fresh typed pre-execution manifest with a short expiry. It must bind the
exact candidate, documentation authority, complete handoff hash, plan, protected
Pi, operator, task XML/SDDL, catalog, package, target and recovery-image roots.

Immediately before the single authorized elevation, repeat the complete live
task, catalog-chain, process, residue, free-space, source-repository and
protected-Pi preflight. The legacy journal must still have its exact bytes and
state above. Any drift blocks and requires a new append-only entry.

Exactly one fresh UAC approval is authorized solely for that authenticated
installer invocation. It installs a fixed S4U/`Limited` ordinary-user dispatcher
and grants no blanket administrator access. After terminal installer `PASS`, no
routine backup or authorized candidate transition may require elevation.

D-006 remains controlling. No mutation may start at or after the 00:30
Australia/Hobart freeze. Installer `PASS` does not close A3. The natural
`2026-09-01` 01:00 ingest and first natural trusted 05:00 backup must pass before
A3 can become terminal `PASS` and before A4 may start. No manual task trigger,
backup, ingest, deployment or publication is authorized.

## Entry `HANDOFF-20260831T222652+1000-A3-DAYLIGHT-BLOCKED`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260831T222652+1000-A3-DAYLIGHT-BLOCKED` |
| Previous handoff entry | `HANDOFF-20260831T220237+1000-A3-LEGACY-JOURNAL-AUTHORITY` |
| Created | `2026-08-31T22:26:52+10:00` / `2026-08-31T12:26:52Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Documentation source | clean `origin/main` worktree at `10443b2464350a2a71b96c5e5b4e54dc49a73861`; pre-append handoff raw Git-blob SHA-256 `8817cf13d7624d5e78b90c9f5164123084fe14bac6b45707b757ff44b20393a4` |
| Code candidate | `12ea4407123843336934cc766383a89b9b69deb6` |
| Protected Pi | remains pinned to `9302890fcc752cbf90da97d597e972c157d913e3`; no Pi deployment, ingest, publication or production mutation occurred |
| Result | build and authenticated preflight `PASS`; live installer `BLOCKED` by the immutable 22:00 daylight cutoff and `NOT_EXECUTED`; A3 `RUNNING`; A4 `BLOCKED` |
| Deviations | none; D-006 and D-014 were enforced without conversational substitution |

### Completed preparation and immutable non-execution evidence

The fresh preparation root is:

`C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-20260831\20260831T220759+1000`

Its `NOT-EXECUTED.json` is 1339 bytes with SHA-256
`092376c422f5c2be42caf68bb4e5eabca31be2c8d58fe4a036be85737ab541fa`.
It records `BLOCKED`, `uac_requested:false`, `task_mutated:false` and
`pi_mutated:false`. The prior expiring invocation is permanently invalid and
must never be elevated or relabelled.

The launcher was compiled independently twice and both 301568-byte outputs had
SHA-256 `a0dbf906dace3b63c6555ba28d8da0c57271bfb36feaba83dac6a2e7144140ea`.
The deterministic package was built independently twice and both 211202006-byte
outputs had SHA-256
`c9ae0715291bd48060821da733c070071b31d71d64f1e33bbbae9b0e7666060d`.
The activation gate SHA-256 was
`aac3e27592eb39d1bfe93cc8d60050b5b9516840f923a2d57e7c4b685cbf677b`;
dispatcher-manifest SHA-256 was
`8073aee3a238efe1901a893c1fdc04105604714ae576828ffa7cd566fafd0f70`;
pre-execution-manifest SHA-256 was
`5a6e93b901f008773c01574066e275643f6e95f0dfe000da5cc553eeafaf9c3c`;
and invocation-contract SHA-256 was
`a8dc8842ff2547a1d74d1a0962b5ad6a9873d24c8313a7a4a5b97d79dae1c397`.

The Windows PowerShell 5.1 preflight passed at
`2026-08-31T12:19:57.8768647Z`. It verified the exact candidate, authority and
handoff; task XML/SDDL/semantic SDDL and `LastTaskResult=1`; catalog SHA-256
`7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511`
at final sequence 336; zero backup process/residue; 152099614720 free bytes;
D-014 journal SHA-256
`2d3345aee82b2b453d1aaf627b9c9d29146b12d1030f805b53463f782d8e2fb3`;
and `AR_PI_PREFLIGHT_PASS`.

No UAC prompt was launched because the authenticated installer itself rejects
local time at or after 22:00. Preparation completed after that boundary. This is
a safety gate, not a request for a conversational exception. A subsequent
read-only check reconfirmed task `Ready`/enabled, `LastTaskResult=1`, unchanged
catalog, zero direct `ARLBS-*`/`ARLBQ-*` roots, zero external backup helper and
more than 50 GiB free. The Pi dashboard remained HTTP 200. A later LAN SSH probe
timed out after the earlier authenticated PASS; that transient access result
does not authorize mutation and must be re-proven before any future elevation.

### Exact continuation

D-006 takes priority. At 00:20 create fresh immutable evidence, complete the
read-only gate, enter the 00:30 freeze and directly validate the natural
`2026-09-01` 01:00 ingest. Do not deploy, restart, force, rerun, trigger backup,
change task/control or manipulate publication.

Only after terminal ingest validation and no earlier than 03:30, create a new
unique bootstrap evidence root. The expired preparation above may supply no
manifest, gate, package or pre-execution authority. Rebuild the launcher and
package twice from the same candidate and authority, create fresh short-lived
activation and pre-execution records, and repeat every live task, catalog,
process, residue, free-space, legacy-journal and protected-Pi gate. Prefer the
reachable authenticated Pi transport but never weaken host-key, identity,
production-SHA, cleanliness, service, timer, lock or dashboard checks.

After all gates pass inside the 03:30–22:00 installer window, Codex shall launch
the exact authenticated installer itself with `Start-Process -Verb RunAs
-WindowStyle Hidden -Wait`. The operator need only click **Yes once** in UAC;
the operator must not be asked to type or paste routine commands. The permanent
solution is the fixed S4U/`Limited` task and protected dispatcher—not blanket
administrator permission or disabled UAC.

Installer `PASS` remains provisional. Never manually trigger the task. Observe
the first natural 05:00 backup and validate it at 05:15 against the complete A3
acceptance gate. Only a later append-only terminal `PASS` may close A3 and
authorize A4.

## Entry `HANDOFF-20260902T110352+1000-A3-LEAN-RUNTIME-AUTHORITY`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260902T110352+1000-A3-LEAN-RUNTIME-AUTHORITY` |
| Previous handoff entry | `HANDOFF-20260831T222652+1000-A3-DAYLIGHT-BLOCKED` |
| Created | `2026-09-02T11:03:52+10:00` / `2026-09-02T01:03:52Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; normalized Git-blob SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| Documentation source | clean current `origin/main` at candidate `32c74557c07a40c202a257d6d4e7eee331928dd0`; pre-append handoff Git-blob SHA-256 `ae1bd18b6ed969dfb466dc28bf9540326db94a2b7ee5e83a20cfa137a0ff4a9b` |
| Merged implementation | PR #598 head `f7eed308240b2d0712b0aa9a734e23e7dc4502a4`, merge `325ae0d5fd35f25b1a55f162b09373aeacdb733f`; PR #599 head `d3e0ebd42bc3324a56137b6d5e6ab9bb99acef05`, merge `6a3b5665731db41cbe73ec7df1c74d0238a4a278`; test-only PR #600 head `0125acb40d9695d93a72c37dd88d7cff7b034ca3`, merge and sole candidate `32c74557c07a40c202a257d6d4e7eee331928dd0` |
| SSH identity | `pi@ar-local-pi5:22`; stable Tailscale hostname required; pinned Ed25519 fingerprint `SHA256:hFaXQcJhid3wB2tMMn6EuMnfPZxgzGaI9DIZAHip6n4`; a DHCP address, SSH-config alias or different key is not equivalent |
| Protected Pi | no Pi deployment, ingest, publication, restart or backup-task trigger occurred; its exact clean production identity must be freshly re-proven before elevation |
| Result | merged lean runtime and exact source binding `PASS`; package/preflight `NOT_STARTED`; UAC/task/backup/Pi mutation `NOT_STARTED`; A3 `RUNNING`; A4 `BLOCKED` |
| Deviations | D-006, D-011, D-012, D-013 and D-014 remain; no new deviation |

### Exact merged source binding

Only candidate `32c74557c07a40c202a257d6d4e7eee331928dd0` is authorized. The
operational Git-blob bytes are:

| Path | Bytes | Git-blob SHA-256 |
|---|---:|---|
| `install_laptop_backup_trusted_dispatcher.ps1` | 69006 | `611974aa47652c1c6ad4278bb2f7860b388fa57083154e425802a5d990d75066` |
| `install_laptop_backup_trusted_dispatcher_core.ps1` | 57443 | `67b50577e73adebe1ab6a86abd468c1546758997785ebe67a30e5bcbb0bd9e45` |
| `install_laptop_backup_trusted_dispatcher_ssh.ps1` | 14515 | `61e0bd750bcc5b6f5ee0fd9d629e0e9465bb90f6e4193553ff7f7f83a63992c3` |
| `laptop_backup_trusted_package.py` | 12611 | `6c8386a3b0464e26527d709f7ee29cc2b45751d76b1d9bf9eda67e006bc9de5f` |
| `native/laptop_backup_trusted_launcher.cpp` | 24190 | `f31431ddb6ae9e6d7f7db5992dc74872303113761a01462264f50e173e7b7774` |
| `run_laptop_backup_task.ps1` | 919 | `50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860` |
| `run_laptop_backup_trusted_child.ps1` | 16600 | `8b479107748d5de8ef24ad500ae7dc2531ffb5d99aa0bcc1699148ed22be5105` |
| `laptop_backup_dispatcher.py` | 38525 | `36595c9155c0b7514c428ecd1a259b1922d810c498f398da41ea72e5a759b2bc` |
| `laptop_backup_dispatcher_security.py` | 20490 | `c52229848b75931cb576855db3093830073be48695e97610f5e82ab8e403b36b` |
| `laptop_backup_atomic.py` | 3324 | `d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c` |
| `laptop_backup_scheduled.py` | 39800 | `25e400780554e82f690822bfbaaf41f8d8e93c85106d4501e561e7558d8c44cb` |
| `laptop_backup_transport.py` | 14615 | `74ede2c24030e738c652008f74a2dff9415608a427d064e9492909c9ba9314e1` |
| `laptop_pull_backup.py` | 46804 | `ce3c80b492d04ef923aca2701169be76c35ee6d7cc45a517e2c535c7d2232d47` |

PRs #598 and #599 make the trusted runtime consume only the authenticated
Windows OpenSSH boundary and protected connection contract; #600 changes only
the cross-platform transport fixture. Candidate identity still binds the whole
tree. The fixed host-key blob SHA-256 is
`84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e`,
which is the fingerprint above.

### Narrow D-012 continuation authority

Merge this documentation-only entry through exact-head CI and thread gates.
Under D-012, that merge commit and the complete merged handoff raw SHA-256
become the sole authority identity. Only after merge may routine
non-administrator commands create separate clean detached candidate and
authority checkouts, compile the launcher twice, build the deterministic package
twice, and create a fresh short-lived activation gate, dispatcher manifest and
pre-execution manifest. Those records must bind the exact candidate, authority,
complete handoff, plan, installer/core/SSH-boundary hashes, package, protected
Pi, task, catalog, operator, target/recovery roots, `ar-local-pi5`, `pi`,
port 22, SSH executable and identity hashes, and the pinned Ed25519 key.

Exactly one UAC approval is authorized only for the resulting authenticated
installer invocation after every fresh live gate passes inside 03:30–22:00
Australia/Hobart. No other elevated command is authorized. UAC cancellation is
`BLOCKED`, not success and not authority to retry stale material. No manual task
trigger, backup, ingest, deployment, restart or publication is authorized.

Authority expires before use if canonical `origin/main` is not the authority
merge, or if any candidate, authority, handoff, source, launcher, package,
manifest, hostname, host-key, SSH executable/identity, task XML/SDDL, catalog,
accepted receipt/archive, process/residue, free-space, clock-window, protected
Pi identity/cleanliness/service/timer/lock/dashboard, or legacy-journal gate
differs. Stop without mutation and append new authority; conversational
substitution is invalid.

Installer failure must preserve evidence and follow its complete authenticated
rollback, ending only `ROLLED_BACK`, `FAIL` or `BLOCKED`. Installer `PASS` is
provisional: D-006 still protects the natural 01:00 ingest, and only the first
natural trusted 05:00 backup plus full 05:15 validation and a later append-only
terminal `PASS` may close A3 or authorize A4.

## Entry `HANDOFF-20260902T113247+1000-A3-LEAN-AUTHORITY-QUARANTINE`

### Control record

| Field | Value |
|---|---|
| Entry ID | `HANDOFF-20260902T113247+1000-A3-LEAN-AUTHORITY-QUARANTINE` |
| Previous handoff entry | `HANDOFF-20260902T110352+1000-A3-LEAN-RUNTIME-AUTHORITY` |
| Created | `2026-09-02T11:32:47+10:00` / `2026-09-02T01:32:47Z` |
| Author/operator | Codex unattended for `jkoka` |
| Controlling plan | `ARL-OPS-001` v1.5; plan commit `9094a8e115958fcaf2cb36525736bd5e297e6b04`; controlled SHA-256 `a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada`; raw file SHA-256 `d7be2c8a437baba8babc4f777cd3022c004a5e1a08b8c41edba6d3e8e0a226a4`; LF-normalized SHA-256 `f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684` |
| In-flight legacy execution | `ARL-OPS-001` v1.4; plan commit `14dd066099bba393cccf61a280243e43162eedc9`; controlled SHA-256 `78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713`; raw SHA-256 `a5a679297167c37845fbacf0cdf895cad4fb2900c09c1e94e310319d3ae9118d`; installed candidate `f214e3249c7968d574e3449edb14792904e1cc1f` |
| Documentation source | clean branch from `origin/main` `c7d92d3b24a0f12360c8b038d1228c0c35152105`; pre-append handoff 457421 bytes, raw SHA-256 `6e2c6072c1bc71a3a125fab48637b22f034c1a992af457fba78b38e5d6dd7c3a` |
| Sole code candidate | `32c74557c07a40c202a257d6d4e7eee331928dd0`; unchanged by this documentation-only correction |
| Result | `BLOCKED`; PR #601 authority quarantined; package, preflight, UAC, task mutation, backup, Pi mutation, deployment and publication all `NOT_STARTED` |
| Phase | A3 remains `RUNNING` with activation `BLOCKED`; A4 remains `BLOCKED` |
| Deviations | D-006 and D-011 through D-014 remain controlling; no new deviation |

### Quarantine of the PR #601 authority

PR #601 head `11854c50c5ee517e9bd08ce4d186c933687ed828` merged as
`c7d92d3b24a0f12360c8b038d1228c0c35152105`. Its final entry is not an
executable authority. This correction supersedes only its continuation
permission and leaves every prior byte and completed result intact. It remains
quarantined because it conflated two host-key digests, omitted the required
resume-pointer state, and did not record the intervening natural-ingest results.

No package, preflight manifest or installer invocation derived from #601 may be
created, reused, elevated or treated as current. Only a later append-only entry
that authenticates every missing fact and passes normal exact-head review may
replace this `BLOCKED` pointer.

### Host-key identity correction

The endpoint is exactly `pi@ar-local-pi5:22`. `ar-local-pi5` must be resolved
as the stable Tailscale hostname with OpenSSH configuration disabled; a DHCP IP,
SSH-config alias, different user, different port or different key is not an
equivalent endpoint.

The two required Ed25519 identities are distinct representations:

| Identity | Exact value |
|---|---|
| Raw 51-byte SSH host-key blob SHA-256, lowercase hexadecimal | `84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e` |
| OpenSSH-rendered SHA-256 fingerprint, unpadded base64 | `SHA256:hFaXQcJhid3wB2tMMn6EuMnfPZxgzGaI9DIZAHip6n4` |

A read-only `ssh-keyscan -t ed25519 ar-local-pi5` observation at this entry's
creation time produced one 51-byte blob matching both values. The hexadecimal
digest is not the rendered fingerprint and neither value may be substituted for
the other at its comparison boundary.

### Intervening natural-ingest evidence

#### `NATURAL-20260901`

The create-once local evidence root is
`C:\code\backups\AR-local-pi5\evidence\NATURAL-20260901-LATE-VALIDATION\20260901T082434+1000`.
Its controlling record is `late-validation/pass-result.json`, 49120 bytes,
SHA-256 `83cee70609b0dc0193be1386d9eee5361fd9144f5c59fa175853ad6f4f123484`.
The record binds protected Pi commit
`9302890fcc752cbf90da97d597e972c157d913e3`, service invocation
`5792bc4b1ce747819e9519ca0b94539d`, observation
`obs-2026-09-01-a2a93c9b841c9594`, ledger head
`854687253b9c5752339ec637b307f6fbae852f7d51ee062e8f8c3ca6efd16619`,
and SQLite SHA-256
`c6ff3d22908fcd7a5a8375a18002613a3e47979d78b64ef85ef9a6830bc514da`.

| Component | Result and immutable identity |
|---|---|
| Procedure | `BLOCKED`: mandatory 00:20 and 00:55 evidence gates did not run; the late validation does not relabel that miss |
| Source capture | `PASS`: 3833 attempts and 10961 retained source files; verified source-tree SHA-256 `aab9fed06459fd221a64079f3ff39eaceb7cb5e5e85999212d9b45c0efd3076b`; promotion-manifest SHA-256 `b71c5cee936b6830e622e643568d295920b7e76b2942d83cb28f3bd783a2aad6` |
| Observation finalization | `PASS`: observation state `partial`; 3008 products, 17045 rates, 119 providers attempted, 112 complete, 7 partial, 0 failed; SQLite `quick_check=ok`; ledger chain 21/21 with no finding |
| Dated v1 | `PASS`: manifest 1212 bytes, SHA-256 `bc739e194a437f5d1cec27bc69d53ce7708f240d8b8b2157d20a6d8b13200752` |
| Rolling v1 | `PASS`: manifest 2882 bytes, SHA-256 `1602bcb2e4314f05eb30872bac1b8114982c33f291942a7194f6345a92cecfbc` |
| Dates index | `PASS`: 2098 bytes, SHA-256 `f368d86e9e7764de592d92996f9dec9cc4f9322a4a1213fd5d388f975c69843a`, latest `2026-09-01` |
| v2 | independent `FAIL`: stale run date `2026-08-21`, 1217 bytes, SHA-256 `02e14f71b604dbfd652fef7c1a3c46932ad9b32beef7cc90e99ddc14a1ca4acb`; not a v1 gate |
| Dashboard/service | `PASS`: terminal values 357 bytes, SHA-256 `f6e53c8236efdebc115e9c1726ecaa6d0e47b408003a2d8c1552beb32104bcc8`; service exit 0, lock absent, dashboard healthy, timer enabled/active |
| Laptop backup | `FAIL`: the 05:00 path did not advance the catalog; dispatcher execution `dispatcher-control/dispatcher-executions/20260831T190002Z-a42b58e9fc0c44b9b101eec015e44be7.json` is 698 bytes, SHA-256 `ca6e62b12fbf07833b0dac2862b9f82c87a9663853445081d0872507e69b9db9`, child exit 1 |

Additional immutable validation files are
`late-validation/observation-verify-stdout.txt`, 42752 bytes, SHA-256
`cb3e6f54990e1f91ad1f023ba677ba9bacc154d91383ca047c19d798603110c9`,
and `late-validation/ledger-verify-stdout.txt`, 476 bytes, SHA-256
`8b5871d815a19256f1e4861f73356b2a044e4c9c579f5c671e8e663b4173055d`.

#### `NATURAL-20260902`

Only the public and dashboard components could be authenticated. They do not
prove raw capture, observation finalization, ledger identity or production
cleanliness:

| Component | Result and authenticated point-in-time identity |
|---|---|
| Source capture | `BLOCKED` / unproven: no immutable raw-attempt identity was available through the authenticated stable endpoint |
| Observation finalization | `BLOCKED` / unproven: observation ID, completion marker, ledger head, export contract and SQLite hash were unavailable |
| Dated v1 | `PASS`: `https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/manifest.json`, 1211 bytes, SHA-256 `367d2fa065511929943fcb3f154a354939474388c116e28b7d4b04f252075f47`; core 362452 bytes, SHA-256 `d1683a44c258450b2bba233d4b70e95446dad437a023f1bbb0b7dbe6f0a55f11`; details 757500 bytes, SHA-256 `0bd1ae7c5ecd556983ccecfb7747ca50cb81651e3bd05571c314a23bc2b41e46` |
| Rolling v1 | `PASS`: `https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json`, 2881 bytes, SHA-256 `a97087c046f864d5df6c8aa6205ad7b703a4feaa46e05f47e072ef2853b54236` |
| Dates index | `PASS`: 2116 bytes, SHA-256 `9426f208084a501be82504187a82954fbb2b160ec730adab3fa18f0d6a68c56e`, latest `2026-09-02` |
| v2 | independent `FAIL`: stale run date `2026-08-21`, 1217 bytes, SHA-256 `02e14f71b604dbfd652fef7c1a3c46932ad9b32beef7cc90e99ddc14a1ca4acb`; not a v1 gate |
| Dashboard | point-in-time `PASS`: `http://100.78.28.10/api/latest`, 373 bytes, SHA-256 `bbca1b65b96b06aed4702b551a507b7475739dc31c7ec9bbbcbadb7c312180b4`, run date `2026-09-02`, generated at `2026-09-02T01:11:18+10:00`, 3009 products and 17050 rates |
| Laptop backup | `FAIL`: task last ran `2026-09-02T05:00:01+10:00` with result 1; dispatcher execution `dispatcher-control/dispatcher-executions/20260901T190002Z-02dc91d7af334692b654d6d48c7abccd.json` is 698 bytes, SHA-256 `271bf6621708f13aa55a70dbfa4e315937e53b2ba5717ff5cf9c021db5e00102`, child exit 1; catalog did not advance |

The stable endpoint presented the correct Ed25519 key but Tailscale SSH required
an additional interactive check before remote command execution. Therefore the
current protected-Pi SHA, cleanliness, service invocation, raw capture,
completion, pointer, ledger and SQLite identities remain unproven. Public bytes
cannot fill that gap. This is the exact blocker and it prohibits elevation.

### Current catalog, accepted observation and task

The read-only laptop snapshot at `2026-09-02T11:32:47+10:00` is:

| Item | Exact identity/state |
|---|---|
| Catalog | `catalog/generations.jsonl`, 236234 bytes, SHA-256 `7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511`; final sequence 336, kind `macro`, entry SHA-256 `368ed91d6957d60eda5d76f06175e3ff00e20fb5cf5d6d2d94a478d164112420` |
| Latest verified | `catalog/latest-verified.json`, 316 bytes, SHA-256 `737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389`; observation catalog entry SHA-256 `6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68` |
| Accepted receipt | `observations/2026-08-30/f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d/receipt.json`, 3392 bytes, SHA-256 `7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea` |
| Accepted observation | `obs-2026-08-30-69a34aa4c745bb2e`; archive 237101208 bytes, SHA-256 `abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b` |
| Task | `\AR-local laptop backup`; enabled/Ready; S4U/`Limited`; current old-candidate action `f214e3249c7968d574e3449edb14792904e1cc1f`; XML 4774 UTF-16LE-with-BOM bytes, SHA-256 `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`; raw SDDL 160 UTF-8 bytes, SHA-256 `6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b`; last result 1 |

The latest independently evidenced capture/finalization/publication date is
`2026-09-01`, with its procedure explicitly `BLOCKED`. The latest public and
dashboard date is `2026-09-02`, but its capture/finalization identities are
unproven. The latest accepted laptop observation remains `2026-08-30`. These
three dates and meanings must not be collapsed into one "latest" state.

### Exact hash-bound resume-pointer contract

Every later A3 continuation entry must declare schema
`ARL-A3-RESUME-POINTER-V1` and bind all of the following exact fields in one
record: entry ID and timestamps; result; authority merge SHA and complete merged
handoff raw SHA-256; current and legacy plan identities including raw hashes;
candidate and current protected-production SHA plus cleanliness; A3 and A4
states; catalog file size/hash/final sequence/final entry; latest-verified
size/hash/catalog entry; accepted receipt path/size/hash; accepted observation
ID/archive size/hash; each intervening natural date with independent capture,
finalization, dated v1, rolling v1, dates-index, v2, dashboard and backup states
and evidence identities; exact next command and its UTF-8/LF SHA-256; earliest
start, latest safe stop and expiry; acceptance criteria; stop conditions;
preservation/rollback action; risks, findings, deviations and authorization.

Missing, `null`, inherited, conversational or point-in-time-substituted values
make the record `BLOCKED`. A usable record is current only while canonical
`origin/main` equals its authority merge, its complete handoff hash matches, all
listed bytes still hash identically, every intervening natural date is recorded,
the stable endpoint and both host-key representations match, and its fresh
preflight has not expired. Fresh package/pre-execution authority may last no
more than 45 minutes, may not cross 22:00 Australia/Hobart, and expires
immediately on any state change. This entry has `expires_at=NO_USE_BLOCKED` and
can never authorize elevation.

### Exact next action

Earliest start is after the operator completes the Tailscale SSH additional
check for exactly `pi@ar-local-pi5:22`. The following command is read-only; its
UTF-8 SHA-256 with LF separators and no trailing LF is
`557c9942e40e5b559ed945ea2dba98df3e3b1710b50ff41ff1f3847f6eab9163`. It disables SSH configuration,
independently verifies both host-key representations, and prints the missing
Pi and `2026-09-02` identities without changing them:

```powershell
$ErrorActionPreference = 'Stop'
$hostName = 'ar-local-pi5'
$ssh = "$env:WINDIR\System32\OpenSSH\ssh.exe"
$keyscan = "$env:WINDIR\System32\OpenSSH\ssh-keyscan.exe"
$expectedHex = '84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e'
$expectedFingerprint = 'SHA256:hFaXQcJhid3wB2tMMn6EuMnfPZxgzGaI9DIZAHip6n4'
$keyLine = @(& $keyscan -T 10 -t ed25519 $hostName 2>$null |
  Where-Object { $_ -match '^ar-local-pi5\s+ssh-ed25519\s+' })
if ($keyLine.Count -ne 1) { throw 'expected exactly one Ed25519 host key' }
$blob = [Convert]::FromBase64String(($keyLine[0] -split '\s+')[2])
$sha256 = [Security.Cryptography.SHA256]::Create()
try { $digest = $sha256.ComputeHash($blob) } finally { $sha256.Dispose() }
$hex = ($digest | ForEach-Object { $_.ToString('x2') }) -join ''
$fingerprint = 'SHA256:' + [Convert]::ToBase64String($digest).TrimEnd('=')
if ($blob.Length -ne 51 -or $hex -cne $expectedHex -or
    $fingerprint -cne $expectedFingerprint) { throw 'host-key mismatch' }
$knownScript = "[Console]::Out.WriteLine('$($keyLine[0])')"
$knownEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($knownScript))
$knownOption = "KnownHostsCommand=C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -NonInteractive -EncodedCommand $knownEncoded"
$remote = @'
set -eu
date --iso-8601=seconds
hostname
git -C /srv/ar-local/AR-local rev-parse HEAD
git -C /srv/ar-local/AR-local status --porcelain=v1
systemctl show ar-local-daily.service -p ActiveState -p SubState -p Result -p ExecMainStatus -p NRestarts -p InvocationID -p ExecMainStartTimestamp -p ExecMainExitTimestamp
systemctl show ar-local-daily.timer -p UnitFileState -p ActiveState -p LastTriggerUSec -p NextElapseUSecRealtime
test ! -e /srv/ar-local/data/state/daily-ingest.lock
curl -fsS http://127.0.0.1:8808/api/latest
cd /srv/ar-local/AR-local
python3 cdr_ledger_v2.py verify --state /srv/ar-local/data/state
for p in /srv/ar-local/data/state/2026-09-02.done.json /srv/ar-local/data/state/observation-pointers-v2/latest-observation.json /srv/ar-local/data/state/ledger-v2/head.json /srv/ar-local/data/runs/2026-09-02/_exports/ingest-status.json /srv/ar-local/data/runs/2026-09-02/_exports/local-cdr.sqlite; do
  test -f "$p"
  stat -c '%n %s' "$p"
  sha256sum "$p"
done
find /srv/ar-local/data/state/export-contracts-v2/2026-09-02 -maxdepth 1 -type f -print0 | sort -z | xargs -0 -r sha256sum
journalctl -u ar-local-daily.service --since '2026-09-02 00:55:00' --until '2026-09-02 02:00:00' --output=json --no-pager
'@
$remote | & $ssh -F NUL -o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes `
  -o "IdentityFile=$env:USERPROFILE\.ssh\pi5" -o StrictHostKeyChecking=yes `
  -o UserKnownHostsFile=NUL -o GlobalKnownHostsFile=NUL `
  -o HostKeyAlgorithms=ssh-ed25519 -o $knownOption "pi@$hostName" bash -s
if ($LASTEXITCODE -ne 0) { throw "read-only Pi evidence failed: $LASTEXITCODE" }
```

Acceptance is a successful pinned session whose output proves clean production
at the expected protected SHA and supplies exact immutable `2026-09-02`
capture, finalization, ledger, pointer, contract and SQLite identities. The next
operator must preserve and hash that output, validate it against public bytes,
then append a new documentation-only authority through review. If the session
again requests additional authentication, any file is missing, any hash/state
differs, or another natural date intervenes, stop `BLOCKED` without mutation.

Preservation action is to leave the old task, catalog, accepted observation,
Pi, payloads and all evidence unchanged. There is no rollback because this entry
authorizes no mutation. No package, preflight or UAC command exists while this
pointer is `BLOCKED`.

## Entry `HANDOFF-20260902T133826+1000-A3-PINNED-LAN-FINAL-AUTHORITY`

### Control and route correction

This append-only entry supersedes only the continuation authority of
`HANDOFF-20260902T113247+1000-A3-LEAN-AUTHORITY-QUARANTINE`. All older bytes,
failures and completed evidence remain immutable. The old Tailscale endpoint,
`ssh-keyscan` and web-auth wording is quarantined and must not be used. The sole
code candidate remains `8b158d74ddd51a3523ecb6367b6ef99ca994df61`.

The authenticated transport is `pi@ar.local:22`: the protected resolver in that
candidate returned exactly one canonical RFC1918 IPv4 endpoint,
`192.168.20.19`, at `2026-09-02T13:12:00+10:00`. OpenSSH connected directly to
that address with `-F NUL`, `HostKeyAlias=ar-local-pi5`, no agent, config,
password, interaction, TOFU or key scan, and the existing pinned Ed25519 key.
The logical host is exactly `ar-local-pi5`; the discovery name and selected IP
are routing inputs, not trust identities. Required key representations remain
raw-blob SHA-256
`84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e`
and OpenSSH fingerprint
`SHA256:hFaXQcJhid3wB2tMMn6EuMnfPZxgzGaI9DIZAHip6n4`.

The documentation source was exact clean `origin/main`
`8b158d74ddd51a3523ecb6367b6ef99ca994df61`; the pre-append working file was
473774 bytes, SHA-256
`a0f03c9631b1ea2fd8ac5534b88a027b01d9e62d15d22372d0efa9d4799275db`,
and its Git blob was 467053 bytes, SHA-256
`4f5b3ee4821b3fcbb59d069ad1da30e6b1df651e75e7a46eeedd901a654040c5`.
Under D-012, this entry becomes usable only after its documentation-only squash
merge is current canonical `origin/main` and the complete merged handoff raw
SHA-256 is independently calculated. Those two post-merge values are not
invented here.

### Authenticated current state

The direct pinned LAN session proved protected production clean at
`9302890fcc752cbf90da97d597e972c157d913e3`. Service invocation
`f0a99bd3558344798741b0ca4db84752` ran 01:00:03–01:17:19 AEST with
`Result=success`, `ExecMainStatus=0`, no restart; the timer is enabled and
active, the ingest lock is absent, and the local dashboard is healthy. The
dashboard response is 373 bytes, SHA-256
`bbca1b65b96b06aed4702b551a507b7475739dc31c7ec9bbbcbadb7c312180b4`,
generation time `2026-09-02T01:11:18+10:00`, with 3009 products and 17050 rates.

`NATURAL-20260902` procedure remains `BLOCKED` because the mandatory D-006
create-once evidence run did not occur; authenticated operational ingest is
separately `PASS`. Raw capture has 3837 attempts, head
`98cd40ca4177dc3fa82c61611bae5bb4cfc3d2aa15fccc9edb5e18d96fbd5240`,
42643954 bytes in 10970 files, tree
`f0081508f4364b0082d103dc215ce6f91a4db3edc37c23cf883d4c3401f0a1ae`,
and promotion manifest 1782131 bytes, SHA-256
`0fd30f32657bca1e42794acdf30353010405c0ec9ac54ebee4224aed2de0ff2d`.
Finalization is observation `obs-2026-09-02-724fc227e6776842`, state `partial`,
119 providers attempted, 112 complete, seven partial, 17 attributable failures,
zero corrupt/unattributed, 3009 products, 17050 rates. Its marker is 1510 bytes,
SHA-256 `bcde983cdab8790fe436d0f977e64cee4ae53ea74701820df2cab9e9d21704f1`;
pointer 300 bytes, SHA-256
`f2945b67890138827dcd1b74be69ae4e6727b740cd1a5414a2da01e0cea35745`;
contract 2742722 bytes, SHA-256
`a1f6cd2369e872704530616b3b435fac8a115e13001645eef6b86fffc2454d44`,
contract digest
`4891d0e01206316e277db1541ee89707ef4cb9c4bdf5f08475cbbb1c260bd2c8`;
and ingest status 38175 bytes, SHA-256
`4f45841840f1b2a256120bd269dd5557f277653d8a7c6667c4cf717564897d25`.

Ledger verification is `PASS`, 22/22 with no finding or warning, at head/event
`c6d2f0b3569e2f54371e62dd31740fa2f8860482a2edd5482dab54f127259fae`;
the head file is 321 bytes, SHA-256
`cf98d96b46a18bdb5f128b439555429f7a648516ee9650aafa304ddca55fa425`.
SQLite is 1099124736 bytes, SHA-256
`9be89c33d89bef07e49c452340f2c2265880d7dd1b035dd6108ce57126d5e7af`;
read-only `quick_check` and full `integrity_check` both returned `ok`; WAL is
zero bytes. Counts are banks 61877, product changes 2178, facts 661383,
products 3009, rates 17050, runs 1 and schema metadata 2.

Publication is independently authenticated: dated v1 manifest 1211 bytes,
SHA-256 `367d2fa065511929943fcb3f154a354939474388c116e28b7d4b04f252075f47`;
rolling v1 manifest 2881 bytes, SHA-256
`a97087c046f864d5df6c8aa6205ad7b703a4feaa46e05f47e072ef2853b54236`;
core 362452 bytes, SHA-256
`d1683a44c258450b2bba233d4b70e95446dad437a023f1bbb0b7dbe6f0a55f11`;
details 757500 bytes, SHA-256
`0bd1ae7c5ecd556983ccecfb7747ca50cb81651e3bd05571c314a23bc2b41e46`;
search 597950 bytes, SHA-256
`6db1e8a078ccc4b05a5b68cd1271508e5452b93e65b459a87554e3dc97637f09`;
dates index 2116 bytes, SHA-256
`9426f208084a501be82504187a82954fbb2b160ec730adab3fa18f0d6a68c56e`,
latest `2026-09-02`. V2 independently remains `FAIL`/stale at `2026-08-21`:
manifest 1217 bytes, SHA-256
`02e14f71b604dbfd652fef7c1a3c46932ad9b32beef7cc90e99ddc14a1ca4acb`.

The prior `NATURAL-20260901` identities and split result in the predecessor are
retained exactly: procedure `BLOCKED`; operational capture/finalization/v1/index
`PASS`; v2 and laptop backup `FAIL`; controlling evidence 49120 bytes,
SHA-256 `83cee70609b0dc0193be1386d9eee5361fd9144f5c59fa175853ad6f4f123484`.
The 2026-09-02 laptop task also `FAIL`ed naturally at 05:00:01 with result 1;
execution 698 bytes, SHA-256
`271bf6621708f13aa55a70dbfa4e315937e53b2ba5717ff5cf9c021db5e00102`.

Laptop state is unchanged: catalog 236234 bytes, SHA-256
`7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511`,
sequence 336, final entry
`368ed91d6957d60eda5d76f06175e3ff00e20fb5cf5d6d2d94a478d164112420`;
latest-verified 316 bytes, SHA-256
`737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389`;
accepted catalog entry
`6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68`;
receipt 3392 bytes, SHA-256
`7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea`;
observation `obs-2026-08-30-69a34aa4c745bb2e`; archive 237101208 bytes,
SHA-256 `abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b`.
The task remains enabled/Ready, S4U/`Limited`, result 1; XML is 4774 bytes,
SHA-256 `aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2`,
raw SDDL SHA-256
`6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b`
and semantic SDDL SHA-256
`d0e0ac6dbbbe519444e70161be2a447fa7b6b718a710160e578bd9f4e4bf7965`.
Active dispatcher pointer is 170 bytes, SHA-256
`fd66311c66aad9a8f16643171fdb3de54f6582361d41ce3255c7da09a086e923`,
sequence 1, manifest
`af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092`.
No helper, receiver lock, transition lease or partial exists; free space was
155318718464 bytes. D-014 journal remains exactly two matching records,
SHA-256 `2d3345aee82b2b453d1aaf627b9c9d29146b12d1030f805b53463f782d8e2fb3`.

### Candidate and local build inputs

| Path | Bytes | Git-blob SHA-256 |
|---|---:|---|
| `install_laptop_backup_trusted_dispatcher.ps1` | 69130 | `20f2581e46b2d525c180ff962ddfadd42e852b8d6fff1511b3f0b3c73969b96d` |
| `install_laptop_backup_trusted_dispatcher_core.ps1` | 58171 | `de958229fe2a8220cae93083e9f1ad0bec031e6b4164d130782f163fc9f49a18` |
| `install_laptop_backup_trusted_dispatcher_ssh.ps1` | 18243 | `7e387696d22a789f9ede481c48b820f52623e610e96a9f170cb6641b84757625` |
| `laptop_backup_trusted_package.py` | 13684 | `6c2e722c16bb875ce3c07a4a56ee868001fdfff6973371ec84014594a7b55d43` |
| `native/laptop_backup_trusted_launcher.cpp` | 24190 | `f31431ddb6ae9e6d7f7db5992dc74872303113761a01462264f50e173e7b7774` |
| `run_laptop_backup_task.ps1` | 919 | `50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860` |
| `run_laptop_backup_trusted_child.ps1` | 20797 | `295271485c79907b7ee87463b53f6cc2258d146e07d771860ae4534b743c772a` |
| `laptop_backup_dispatcher.py` | 38525 | `36595c9155c0b7514c428ecd1a259b1922d810c498f398da41ea72e5a759b2bc` |
| `laptop_backup_dispatcher_security.py` | 20490 | `c52229848b75931cb576855db3093830073be48695e97610f5e82ab8e403b36b` |
| `laptop_backup_atomic.py` | 3324 | `d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c` |
| `laptop_backup_scheduled.py` | 39800 | `25e400780554e82f690822bfbaaf41f8d8e93c85106d4501e561e7558d8c44cb` |
| `laptop_backup_transport.py` | 15588 | `59cd046e7fae1eab543bb70dd0aca91bf346d6f1b554407a5eab76b3097ddfc1` |
| `laptop_pull_backup.py` | 46804 | `ce3c80b492d04ef923aca2701169be76c35ee6d7cc45a517e2c535c7d2232d47` |
| `laptop_backup_ssh_endpoint.py` | 2127 | `4b425d82301c749f3a1f6f2e36a070c169ea8a6e961d8d1ffd52fddbb4347f93` |

Runtime source is
`C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-20260901\20260901T083436+1000\runtime`:
3067 files, 64118158 bytes, canonical sorted path-to-SHA JSON SHA-256
`d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7`;
`python.exe` SHA-256
`53e910971cbb20c3223cc44c696254ccfba9595dc4be8e16f56f6c954fff831f`.
Fixed local inputs are SSH identity
`C:\Users\jkoka\.ssh\pi5`, 387 bytes, SHA-256
`faf1d747eece5be5315b2172bf6ebff4bdb817eb04b49a35a8e9f2748b16ef1e`;
OpenSSH `ssh.exe` SHA-256
`6250fd52163fe99a0dc49403ed1b4bbef9b764bdb7bada017a93d057d9376a42`,
`scp.exe` SHA-256
`63b7118d8e1a8a84398cf4ce1584dc6b146606092fe9c68bbaf110bbdcfb480a`,
Git SHA-256 `c470d205517c7a53ceca321df16a6e4549fcd52b576ab4d09536d36f26fda5a9`
and `whoami.exe` SHA-256
`23240ef9f8b0a9a324110b1c2331de31dc1b0e08f5359cb707e51a939af56cd3`.

### Canonical resume pointer

```json
{"schema":"ARL-A3-RESUME-POINTER-V1","version":1,"sequence":3,"predecessor":"HANDOFF-20260902T113247+1000-A3-LEAN-AUTHORITY-QUARANTINE","entry_id":"HANDOFF-20260902T133826+1000-A3-PINNED-LAN-FINAL-AUTHORITY","created_local":"2026-09-02T13:38:26+10:00","created_utc":"2026-09-02T03:38:26Z","result":"PASS_D012_POST_MERGE_BINDING_REQUIRED","authority_merge_sha":"D012_CURRENT_MAIN_MERGE_CONTAINING_THIS_ENTRY","complete_handoff_raw_sha256":"D012_SHA256_OF_THAT_MERGE_GIT_BLOB","candidate_sha":"8b158d74ddd51a3523ecb6367b6ef99ca994df61","operator":{"name":"jkoka","sid":"S-1-5-21-689213601-40760280-3596424081-1001"},"plan":{"id":"ARL-OPS-001","version":"1.5","commit":"9094a8e115958fcaf2cb36525736bd5e297e6b04","controlled_sha256":"a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada","raw_sha256":"d7be2c8a437baba8babc4f777cd3022c004a5e1a08b8c41edba6d3e8e0a226a4","lf_sha256":"f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684"},"legacy_plan":{"version":"1.4","commit":"14dd066099bba393cccf61a280243e43162eedc9","controlled_sha256":"78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713","raw_sha256":"a5a679297167c37845fbacf0cdf895cad4fb2900c09c1e94e310319d3ae9118d","installed_candidate":"f214e3249c7968d574e3449edb14792904e1cc1f"},"protected":{"sha":"9302890fcc752cbf90da97d597e972c157d913e3","clean":true},"phase":{"A3":"RUNNING_ACTIVATION_AUTHORIZED_NOT_STARTED","A4":"BLOCKED"},"natural":{"2026-09-01":{"procedure":"BLOCKED","capture":"PASS","finalization":"PASS","dated_v1":"PASS","rolling_v1":"PASS","index":"PASS","v2":"FAIL_STALE","dashboard":"PASS","backup":"FAIL","evidence_sha256":"83cee70609b0dc0193be1386d9eee5361fd9144f5c59fa175853ad6f4f123484"},"2026-09-02":{"procedure":"BLOCKED","capture":"PASS_AUTHENTICATED_LAN","finalization":"PASS_AUTHENTICATED_LAN","dated_v1":"PASS","rolling_v1":"PASS","index":"PASS","v2":"FAIL_STALE","dashboard":"PASS","backup":"FAIL","observation":"obs-2026-09-02-724fc227e6776842","marker_sha256":"bcde983cdab8790fe436d0f977e64cee4ae53ea74701820df2cab9e9d21704f1","ledger_head":"c6d2f0b3569e2f54371e62dd31740fa2f8860482a2edd5482dab54f127259fae","sqlite_sha256":"9be89c33d89bef07e49c452340f2c2265880d7dd1b035dd6108ce57126d5e7af"}},"catalog":{"sha256":"7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511","bytes":236234,"sequence":336,"final_entry_sha256":"368ed91d6957d60eda5d76f06175e3ff00e20fb5cf5d6d2d94a478d164112420","latest_sha256":"737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389","latest_bytes":316,"accepted_entry_sha256":"6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68","receipt_path":"observations/2026-08-30/f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d/receipt.json","receipt_sha256":"7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea","receipt_bytes":3392,"observation":"obs-2026-08-30-69a34aa4c745bb2e","archive_sha256":"abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b","archive_bytes":237101208},"route":{"discovery":"ar.local","selected":"192.168.20.19","logical":"ar-local-pi5","user":"pi","port":22,"key_blob_sha256":"84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e","key_fingerprint":"SHA256:hFaXQcJhid3wB2tMMn6EuMnfPZxgzGaI9DIZAHip6n4"},"next_command":"& 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe' -NoProfile -ExecutionPolicy Bypass -File 'C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012\\prepare-and-preflight.ps1'","next_command_utf8_lf_sha256":"0744a9448ae7cc87feaaae63d5c0589a36576bf30a100309c2bba37eb3d1c4d5","earliest":"POST_MERGE_AND_AFTER_03:30_AUSTRALIA_HOBART","latest":"2026-09-02T22:00:00+10:00","freshness":"45_MINUTES_FROM_GENERATED_PREFLIGHT","package_sha256":"D012_DETERMINISTIC_DUAL_BUILD_OUTPUT","dispatcher_manifest_sha256":"D012_GENERATED_AFTER_FRESH_CHECK_ONLY","preexecution_manifest_sha256":"D012_GENERATED_LAST_AND_BOUND_BY_OUTER_COMMAND","acceptance":"installer terminal PASS; then natural trusted 05:00 backup plus full validation; later append-only terminal PASS","stop":["origin/main or handoff drift","resolver not exactly one RFC1918 IPv4","host key or auth drift","source/tool/task/catalog/Pi/evidence drift","timeout or web-auth","process/lock/lease/partial","under 50GiB","D-006 window or expired preflight","any build mismatch"],"preservation":"stop before mutation; installer authenticated rollback only after mutation begins; preserve task/catalog/Pi/payload/evidence","risks":["D-006 procedure misses remain BLOCKED","v2 stale","natural trusted backup not yet accepted"],"findings":["old Tailscale route wording quarantined","Sep2 operational ingest authenticated"],"deviations":["D-006","D-011","D-012","D-013","D-014"],"authorization":"one exact UAC installer invocation only; no manual backup/ingest/deploy/publication or other elevation","terminal_status":"USABLE_ONLY_AFTER_D012_BIND_AND_FRESH_PREFLIGHT"}
```

### Deterministic build, fresh preflight and sole elevation

Save the following UTF-8/LF block at the exact `next_command` path. It is a
generator, not precomputed authority: it must resolve the current post-merge
authority, require this entry, calculate the complete handoff hash, use separate
clean detached checkouts, validate every fixed source/tool/runtime hash, resolve
`ar.local` through `laptop_backup_ssh_endpoint.py`, authenticate the existing
pinned key without `ssh-keyscan`, run the candidate `--check-only` through a
disposable schema-6 trusted-child contract, and record its exact resulting
catalog pointer. It must then create a fresh activation gate and dispatcher
manifest, compile the launcher twice with `/Brepro`, build the package twice,
require byte equality, and create the schema-exact pre-execution manifest only
after rechecking task XML/SDDL, the full catalog chain and archive, D-014, free
space, residue, current Pi SHA/cleanliness/service/timer/lock/dashboard,
Sep-2 marker/pointer/contract/ledger/SQLite hashes and `quick_check=ok`.

The two launcher commands are exactly:

```powershell
& cl.exe /nologo /std:c++17 /O2 /MT /W4 /WX /EHsc /GS /guard:cf /Brepro /DUNICODE /D_UNICODE "$candidate\native\laptop_backup_trusted_launcher.cpp" "/Fe:$root\launcher-1.exe" /link advapi32.lib /DYNAMICBASE /NXCOMPAT /guard:cf
& cl.exe /nologo /std:c++17 /O2 /MT /W4 /WX /EHsc /GS /guard:cf /Brepro /DUNICODE /D_UNICODE "$candidate\native\laptop_backup_trusted_launcher.cpp" "/Fe:$root\launcher-2.exe" /link advapi32.lib /DYNAMICBASE /NXCOMPAT /guard:cf
if ((Get-FileHash "$root\launcher-1.exe" -Algorithm SHA256).Hash -cne (Get-FileHash "$root\launcher-2.exe" -Algorithm SHA256).Hash) { throw 'launcher builds differ' }
```

The two package commands, after the generator has produced the exact bound
`$manifest`, are exactly:

```powershell
$packageArgs=@('--candidate-repo',$candidate,'--candidate-sha',$candidateSha,'--authority-repo',$authority,'--authority-sha',$authoritySha,'--python-root',$runtime,'--launcher',"$root\launcher-1.exe",'--dispatcher-manifest',$manifest,'--install-root',$installRoot,'--control-root',$control,'--operator-sid',$operatorSid,'--git',$git,'--ssh',$ssh,'--scp',$scp,'--ssh-host','ar.local','--ssh-user','pi','--ssh-port','22','--ssh-identity',$identity,'--ssh-known-hosts',$knownHostsSource,'--whoami',$whoami)
& $python -I -B "$candidate\laptop_backup_trusted_package.py" @packageArgs --output "$root\trusted-package-1.zip"
if ($LASTEXITCODE) { throw 'package build 1 failed' }
& $python -I -B "$candidate\laptop_backup_trusted_package.py" @packageArgs --output "$root\trusted-package-2.zip"
if ($LASTEXITCODE) { throw 'package build 2 failed' }
if ((Get-FileHash "$root\trusted-package-1.zip" -Algorithm SHA256).Hash -cne (Get-FileHash "$root\trusted-package-2.zip" -Algorithm SHA256).Hash) { throw 'package builds differ' }
```

The complete non-administrator generator must fail closed unless its emitted
`build-result.json`, `check-only.json`, `activation-gate.json`,
`dispatcher-manifest.json`, `pi-preflight.txt`, `pre-execution-manifest.json`
and `preflight-summary.json` contain exact absolute paths, sizes and SHA-256 for
all fixed and generated inputs above. Its final output is one encoded command
whose typed parameters are exactly those accepted by
`install_laptop_backup_trusted_dispatcher.ps1`, including candidate, actual
authority/handoff, protected/plan, package, installer/core/SSH-boundary,
identity/SSH executable, task, catalog/receipt/archive and pre-execution hashes,
`PiHost=ar.local`, `PiUser=pi`, `PiPort=22`. The manifest expires after 45
minutes and never after 22:00 Hobart.

After that generator returns terminal `PASS`, this is the only authorized UAC
installer command; `$encoded` is its freshly emitted exact bound command:

```powershell
$process = Start-Process -Verb RunAs -WindowStyle Hidden -Wait -PassThru -FilePath 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -ArgumentList @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded); if ($process.ExitCode -ne 0) { throw "trusted bootstrap failed: $($process.ExitCode)" }
```

Do not execute either block from this documentation turn. No other elevation,
manual task trigger, backup, ingest, deployment or publication is authorized.
Installer `PASS` leaves A3 `RUNNING`; only natural backup acceptance and a later
append-only terminal entry can close it or release A4.

### Executable generator correction `C-20260902T140000+1000`

The rolling search-index digest above is corrected to
`6db1e8a078ccc133839a8fa79488bc8ae7e6d6e84db515729cefe0d5cf4dd12a`;
the earlier value is quarantined. The abbreviated generator description is not
an executable by itself. The exact complete generator is the block below.

<!-- BEGIN ARL-D012-PREPARE-AND-PREFLIGHT-PS1 -->
```powershell
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$entry='HANDOFF-20260902T133826+1000-A3-PINNED-LAN-FINAL-AUTHORITY'
$root=[IO.Path]::GetFullPath((Split-Path -Parent $PSCommandPath))
$requiredRoot='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012'
if($root-cne$requiredRoot){throw 'generator path is not the authorized evidence root'}
$candidateSha='8b158d74ddd51a3523ecb6367b6ef99ca994df61'
$protectedSha='9302890fcc752cbf90da97d597e972c157d913e3'
$planCommit='9094a8e115958fcaf2cb36525736bd5e297e6b04'
$planSha='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada'
$target='C:\code\backups\AR-local-pi5'
$control=Join-Path $target 'dispatcher-control'
$recovery='C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21'
$runtime='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-20260901\20260901T083436+1000\runtime'
$python=Join-Path $runtime 'python.exe'
$identity='C:\Users\jkoka\.ssh\pi5'
$git='C:\Program Files\Git\cmd\git.exe'
$ssh='C:\Windows\System32\OpenSSH\ssh.exe'
$scp='C:\Windows\System32\OpenSSH\scp.exe'
$whoami='C:\Windows\System32\whoami.exe'
$operator='jkoka'
$operatorSid='S-1-5-21-689213601-40760280-3596424081-1001'
$principal='yanniedog\jkoka'
$repo='https://github.com/yanniedog/AR-local.git'
$candidate=Join-Path $root 'candidate'
$authority=Join-Path $root 'authority'
$knownHostsSource=Join-Path $root 'known-hosts-source'
$knownHostsAlias=Join-Path $root 'known-hosts-alias'
$manifest=Join-Path $root 'dispatcher-manifest.json'

function Sha([string]$Path){(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function WriteUtf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,($Text-replace "`r",''),[Text.UTF8Encoding]::new($false))}
function WriteJson([string]$Path,[object]$Value){WriteUtf8 $Path (($Value|ConvertTo-Json -Depth 12 -Compress)+"`n")}
function RequireHash([string]$Path,[string]$Expected){if((Sha $Path)-cne$Expected){throw "hash drift: $Path"}}

$now=[DateTimeOffset]::Now
if($now.TimeOfDay-lt[TimeSpan]::FromHours(3.5)-or$now.TimeOfDay-ge[TimeSpan]::FromHours(22)){throw 'outside D-006 daylight window'}
foreach($path in @($candidate,$authority,$knownHostsSource,$knownHostsAlias,$manifest,(Join-Path $root 'trusted-child.json'),(Join-Path $root 'trusted-package-1.zip'),(Join-Path $root 'trusted-package-2.zip'),(Join-Path $root 'pre-execution-manifest.json'))){if(Test-Path -LiteralPath $path){throw "non-reusable output exists: $path"}}

$authoritySha=(((& $git ls-remote $repo refs/heads/main)-split"`t")[0]).ToLowerInvariant()
if($authoritySha-notmatch'^[0-9a-f]{40}$'-or$authoritySha-ceq$candidateSha){throw 'post-merge authority is absent'}
& $git -c core.autocrlf=false clone --quiet --no-checkout $repo $candidate
if($LASTEXITCODE){throw 'candidate clone failed'}
& $git -C $candidate -c core.autocrlf=false checkout --quiet --detach $candidateSha
if($LASTEXITCODE){throw 'candidate checkout failed'}
& $git -c core.autocrlf=false clone --quiet --no-checkout $repo $authority
if($LASTEXITCODE){throw 'authority clone failed'}
& $git -C $authority -c core.autocrlf=false checkout --quiet --detach $authoritySha
if($LASTEXITCODE){throw 'authority checkout failed'}
foreach($pair in @(@($candidate,$candidateSha),@($authority,$authoritySha))){if((& $git -C $pair[0] rev-parse HEAD).Trim()-cne$pair[1]-or(& $git -C $pair[0] status --porcelain=v1)){throw 'checkout identity/cleanliness failed'}}
$handoff=Join-Path $authority 'docs\PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'
if(-not(Select-String -LiteralPath $handoff -SimpleMatch $entry -Quiet)){throw 'authority lacks this entry'}
$handoffSha=Sha $handoff

$sources=[ordered]@{
'install_laptop_backup_trusted_dispatcher.ps1'='20f2581e46b2d525c180ff962ddfadd42e852b8d6fff1511b3f0b3c73969b96d'
'install_laptop_backup_trusted_dispatcher_core.ps1'='de958229fe2a8220cae93083e9f1ad0bec031e6b4164d130782f163fc9f49a18'
'install_laptop_backup_trusted_dispatcher_ssh.ps1'='7e387696d22a789f9ede481c48b820f52623e610e96a9f170cb6641b84757625'
'laptop_backup_trusted_package.py'='6c2e722c16bb875ce3c07a4a56ee868001fdfff6973371ec84014594a7b55d43'
'native\laptop_backup_trusted_launcher.cpp'='f31431ddb6ae9e6d7f7db5992dc74872303113761a01462264f50e173e7b7774'
'run_laptop_backup_task.ps1'='50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860'
'run_laptop_backup_trusted_child.ps1'='295271485c79907b7ee87463b53f6cc2258d146e07d771860ae4534b743c772a'
'laptop_backup_dispatcher.py'='36595c9155c0b7514c428ecd1a259b1922d810c498f398da41ea72e5a759b2bc'
'laptop_backup_dispatcher_security.py'='c52229848b75931cb576855db3093830073be48695e97610f5e82ab8e403b36b'
'laptop_backup_atomic.py'='d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c'
'laptop_backup_scheduled.py'='25e400780554e82f690822bfbaaf41f8d8e93c85106d4501e561e7558d8c44cb'
'laptop_backup_transport.py'='59cd046e7fae1eab543bb70dd0aca91bf346d6f1b554407a5eab76b3097ddfc1'
'laptop_pull_backup.py'='ce3c80b492d04ef923aca2701169be76c35ee6d7cc45a517e2c535c7d2232d47'
'laptop_backup_ssh_endpoint.py'='4b425d82301c749f3a1f6f2e36a070c169ea8a6e961d8d1ffd52fddbb4347f93'
}
foreach($item in $sources.GetEnumerator()){RequireHash (Join-Path $candidate $item.Key) $item.Value}
RequireHash $python '53e910971cbb20c3223cc44c696254ccfba9595dc4be8e16f56f6c954fff831f'
RequireHash $identity 'faf1d747eece5be5315b2172bf6ebff4bdb817eb04b49a35a8e9f2748b16ef1e'
RequireHash $git 'c470d205517c7a53ceca321df16a6e4549fcd52b576ab4d09536d36f26fda5a9'
RequireHash $ssh '6250fd52163fe99a0dc49403ed1b4bbef9b764bdb7bada017a93d057d9376a42'
RequireHash $scp '63b7118d8e1a8a84398cf4ce1584dc6b146606092fe9c68bbaf110bbdcfb480a'
RequireHash $whoami '23240ef9f8b0a9a324110b1c2331de31dc1b0e08f5359cb707e51a939af56cd3'
$inventoryCode='from pathlib import Path;import hashlib,json,sys;r=Path(sys.argv[1]);d={p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob("*")) if p.is_file()};b=(json.dumps(d,sort_keys=True,separators=(",",":"))+"\n").encode();print(len(d),sum(p.stat().st_size for p in r.rglob("*") if p.is_file()),hashlib.sha256(b).hexdigest())'
$inventory=(& $python -I -c $inventoryCode $runtime).Trim()
if($LASTEXITCODE-or$inventory-cne'3067 64118158 d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7'){throw 'runtime inventory drift'}

. (Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_core.ps1')
. (Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_ssh.ps1')
$endpoint=Resolve-ArTrustedSshEndpoint -PythonPath $python -ModulePath (Join-Path $candidate 'laptop_backup_ssh_endpoint.py') -DiscoveryName 'ar.local' -TimeoutSeconds 10
$keyLines=@(Get-Content -LiteralPath 'C:\Users\jkoka\.ssh\known_hosts'|Where-Object{($_-split'\s+')[0].Split(',')-contains$endpoint-and($_-split'\s+')[1]-ceq'ssh-ed25519'})
if($keyLines.Count-ne1){throw 'pinned key source is not unique'}
$keyFields=$keyLines[0]-split'\s+'
$blob=[Convert]::FromBase64String($keyFields[2]);$hash=[Security.Cryptography.SHA256]::Create();try{$digest=$hash.ComputeHash($blob)}finally{$hash.Dispose()}
$blobHex=($digest|ForEach-Object{$_.ToString('x2')})-join'';$fingerprint='SHA256:'+([Convert]::ToBase64String($digest).TrimEnd('='))
if($blobHex-cne'84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e'-or$fingerprint-cne'SHA256:hFaXQcJhid3wB2tMMn6EuMnfPZxgzGaI9DIZAHip6n4'){throw 'pinned key drift'}
WriteUtf8 $knownHostsSource ("ar.local ssh-ed25519 $($keyFields[2])`n")
WriteUtf8 $knownHostsAlias ("ar-local-pi5 ssh-ed25519 $($keyFields[2])`n")

$catalog=Assert-ArTrustedCatalogBaseline -Target $target -ExpectedCatalogSha256 '7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511' -ExpectedCatalogSize 236234 -ExpectedCatalogFinalSequence 336 -ExpectedCatalogFinalEntrySha256 '368ed91d6957d60eda5d76f06175e3ff00e20fb5cf5d6d2d94a478d164112420' -ExpectedLatestVerifiedSha256 '737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389' -ExpectedLatestVerifiedSize 316 -ExpectedAcceptedCatalogEntrySha256 '6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68' -ExpectedAcceptedReceiptRelativePath 'observations/2026-08-30/f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d/receipt.json' -ExpectedAcceptedReceiptSha256 '7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea' -ExpectedAcceptedReceiptSize 3392 -ExpectedAcceptedObservationId 'obs-2026-08-30-69a34aa4c745bb2e' -ExpectedAcceptedArchiveSha256 'abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b' -ExpectedAcceptedArchiveSize 237101208
$trusted=[ordered]@{schema_version=6;authority_path=$authority;atomic_path=(Join-Path $candidate 'laptop_backup_atomic.py');atomic_sha256=$sources['laptop_backup_atomic.py'];control_root=$control;dispatcher_path=(Join-Path $candidate 'laptop_backup_dispatcher.py');dispatcher_sha256=$sources['laptop_backup_dispatcher.py'];dispatcher_security_path=(Join-Path $candidate 'laptop_backup_dispatcher_security.py');dispatcher_security_sha256=$sources['laptop_backup_dispatcher_security.py'];git_path=$git;git_sha256=(Sha $git);python_path=$python;python_sha256=(Sha $python);receiver_path=$candidate;scp_path=$scp;scp_sha256=(Sha $scp);ssh_discovery_timeout_seconds=10;ssh_endpoint_path=(Join-Path $candidate 'laptop_backup_ssh_endpoint.py');ssh_endpoint_sha256=$sources['laptop_backup_ssh_endpoint.py'];ssh_host='ar.local';ssh_logical_host='ar-local-pi5';ssh_identity_path=$identity;ssh_identity_sha256=(Sha $identity);ssh_known_hosts_path=$knownHostsAlias;ssh_known_hosts_sha256=(Sha $knownHostsAlias);ssh_path=$ssh;ssh_sha256=(Sha $ssh);ssh_port=22;ssh_user='pi';whoami_path=$whoami;whoami_sha256=(Sha $whoami)}
WriteJson (Join-Path $root 'trusted-child.json') $trusted
$checkArgs=@('-B','-s','-E',(Join-Path $candidate 'laptop_backup_scheduled.py'),'--target',$target,'--host','ar.local','--ssh-user','pi','--ssh-port','22','--ssh-path',$ssh,'--ssh-sha256',(Sha $ssh),'--scp-path',$scp,'--scp-sha256',(Sha $scp),'--ssh-identity',$identity,'--ssh-known-hosts',$knownHostsAlias,'--recovery-image',$recovery,'--candidate-code-sha',$candidateSha,'--protected-code-sha',$protectedSha,'--plan-git-commit',$planCommit,'--operator',$operator,'--check-only')
$wrapper='import subprocess,sys;r=subprocess.run(sys.argv[1:],capture_output=True,text=True,timeout=120);print(r.stdout,end="");print(r.stderr,end="",file=sys.stderr);raise SystemExit(r.returncode)'
$checkText=(& $python -I -c $wrapper $python @checkArgs 2>&1|Out-String)
if($LASTEXITCODE){throw "fresh check-only failed: $checkText"}
$check=$checkText|ConvertFrom-Json
if($check.ok-ne$true-or$check.result-cne'PASS'-or$check.action-cne'NO_BACKUP_DATA_WRITE'){throw 'fresh check-only was not PASS/NO_BACKUP_DATA_WRITE'}
WriteUtf8 (Join-Path $root 'check-only.json') (($check|ConvertTo-Json -Depth 12 -Compress)+"`n")

$pointerPath=Join-Path $control 'active-runner.json'
RequireHash $pointerPath 'fd66311c66aad9a8f16643171fdb3de54f6582361d41ce3255c7da09a086e923'
$prior=Get-Content -LiteralPath $pointerPath -Raw|ConvertFrom-Json
if($prior.sequence-ne1-or$prior.manifest_sha256-cne'af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092'){throw 'dispatcher predecessor drift'}
$activationId=[guid]::NewGuid().ToString('N')
$gate=[ordered]@{schema_version=1;result='PASS';activation_id=$activationId;candidate_code_sha=$candidateSha;protected_code_sha=$protectedSha;plan_git_commit=$planCommit;plan_sha256=$planSha;authority_commit=$authoritySha;handoff_sha256=$handoffSha;operator_sid=$operatorSid;foreground_result='PASS';check_only_result='PASS'}
$gatePath=Join-Path $root 'activation-gate.json';WriteJson $gatePath $gate
$installRoot="C:\Program Files\AR-local-backup-trusted-$candidateSha-$authoritySha"
$evidenceRoot="C:\Program Files\AR-local-backup-evidence-$candidateSha-$authoritySha"
$created=[DateTimeOffset]::UtcNow
$dispatcher=[ordered]@{schema_version=1;sequence=2;activation_id=$activationId;created_at=$created.ToString('o').Replace('+00:00','Z');activation_expires_at=$created.AddMinutes(45).ToString('o').Replace('+00:00','Z');previous_manifest_sha256=$prior.manifest_sha256;plan_document_id='ARL-OPS-001';plan_version='1.5';plan_git_commit=$planCommit;plan_sha256=$planSha;authority_commit=$authoritySha;handoff_sha256=$handoffSha;authority_repo=(Join-Path $installRoot 'authority');authority_handoff_path='docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md';candidate_code_sha=$candidateSha;protected_code_sha=$protectedSha;operator=$operator;operator_sid=$operatorSid;receiver=(Join-Path $installRoot 'receiver');allowed_receiver_root=$installRoot;entrypoint='run_laptop_backup_task.ps1';entrypoint_sha256=$sources['run_laptop_backup_task.ps1'];python_path=(Join-Path $installRoot 'python\python.exe');python_sha256=(Sha $python);scheduled_plan_git_commit=$planCommit;target=$target;allowed_target_root=$target;recovery_image=$recovery;allowed_recovery_root=[IO.Path]::GetDirectoryName($recovery);gate_evidence_path=$gatePath;gate_evidence_sha256=(Sha $gatePath)}
WriteJson $manifest $dispatcher

$launcher1=Join-Path $root 'launcher-1.exe';$launcher2=Join-Path $root 'launcher-2.exe';$source=Join-Path $candidate 'native\laptop_backup_trusted_launcher.cpp'
Push-Location $root
try{
& cl.exe /nologo /std:c++17 /O2 /MT /W4 /WX /EHsc /GS /guard:cf /Brepro /DUNICODE /D_UNICODE $source "/Fe:$launcher1" /link advapi32.lib /DYNAMICBASE /NXCOMPAT /guard:cf|Out-Null
if($LASTEXITCODE){throw 'launcher build 1 failed'}
& cl.exe /nologo /std:c++17 /O2 /MT /W4 /WX /EHsc /GS /guard:cf /Brepro /DUNICODE /D_UNICODE $source "/Fe:$launcher2" /link advapi32.lib /DYNAMICBASE /NXCOMPAT /guard:cf|Out-Null
if($LASTEXITCODE){throw 'launcher build 2 failed'}
}finally{Pop-Location}
if((Sha $launcher1)-cne(Sha $launcher2)){throw 'launcher builds differ'}
$package1=Join-Path $root 'trusted-package-1.zip';$package2=Join-Path $root 'trusted-package-2.zip'
$packageArgs=@('--candidate-repo',$candidate,'--candidate-sha',$candidateSha,'--authority-repo',$authority,'--authority-sha',$authoritySha,'--python-root',$runtime,'--launcher',$launcher1,'--dispatcher-manifest',$manifest,'--install-root',$installRoot,'--control-root',$control,'--operator-sid',$operatorSid,'--git',$git,'--ssh',$ssh,'--scp',$scp,'--ssh-host','ar.local','--ssh-user','pi','--ssh-port','22','--ssh-identity',$identity,'--ssh-known-hosts',$knownHostsSource,'--whoami',$whoami)
& $python -I -B (Join-Path $candidate 'laptop_backup_trusted_package.py') @packageArgs --output $package1|Out-Null
if($LASTEXITCODE){throw 'package build 1 failed'}
& $python -I -B (Join-Path $candidate 'laptop_backup_trusted_package.py') @packageArgs --output $package2|Out-Null
if($LASTEXITCODE){throw 'package build 2 failed'}
if((Sha $package1)-cne(Sha $package2)){throw 'package builds differ'}

$taskName='AR-local laptop backup';$task=Get-ScheduledTask -TaskName $taskName;$taskInfo=Get-ScheduledTaskInfo -TaskName $taskName
if($task.State.ToString()-cne'Ready'-or-not$task.Settings.Enabled-or$taskInfo.LastTaskResult-ne1){throw 'task state drift'}
$taskXml=Join-Path $root 'observed-task.xml';[IO.File]::WriteAllBytes($taskXml,(Get-ArTrustedTaskXmlBytes $taskName));RequireHash $taskXml 'aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2'
$sddl=Get-ArTrustedTaskSddl $taskName
if((Get-ArTrustedTextSha256 $sddl)-cne'6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b'-or(Get-ArTrustedSddlSemanticSha256 $sddl)-cne'd0e0ac6dbbbe519444e70161be2a447fa7b6b718a710160e578bd9f4e4bf7965'){throw 'task SDDL drift'}
$active=@(Get-CimInstance Win32_Process|Where-Object{$_.ProcessId-ne$PID-and$_.CommandLine-and$_.CommandLine-match'laptop_backup_(scheduled|dispatcher|trusted_child)|laptop_pull_backup|run_laptop_backup|AR-local-backup-trusted-.*launcher\.exe'})
$residue=@((Join-Path $target 'catalog\.receiver.lock'),(Join-Path $control 'transition.lease'))|Where-Object{Test-Path -LiteralPath $_}
$residue+=@(Get-ChildItem -LiteralPath $target -Recurse -Force|Where-Object{$_.Name-like'*.partial'-or$_.Name-like'.partial-*'-or$_.Name-like'*.partial-*'})
if($active.Count-or$residue.Count-or[long](Get-PSDrive C).Free-lt50GB){throw 'process/residue/free-space gate failed'}
$journal='C:\Program Files\AR-local-backup-evidence-0a444caab7624499bca7ffdbbc56189e152e53e9-dc78b85368c020dcbcbb357b932e56110999f105\20260831T090802Z-5b12a8455b9b4c14b36071bc498eb8eb\mutation-journal.jsonl'
RequireHash $journal '2d3345aee82b2b453d1aaf627b9c9d29146b12d1030f805b53463f782d8e2fb3'
$journalLines=@([IO.File]::ReadAllLines($journal,[Text.UTF8Encoding]::new($false)));if($journalLines.Count-ne2){throw 'D-014 line count drift'}

$remote=@'
set -eu
cd /srv/ar-local/AR-local
test "$(git rev-parse HEAD)" = '9302890fcc752cbf90da97d597e972c157d913e3'
test -z "$(git status --porcelain=v1)"
test "$(systemctl show ar-local-daily.service -p Result --value)" = success
test "$(systemctl show ar-local-daily.service -p ExecMainStatus --value)" = 0
test "$(systemctl is-enabled ar-local-daily.timer)" = enabled
test "$(systemctl is-active ar-local-daily.timer)" = active
test ! -e /srv/ar-local/data/state/daily-ingest.lock
printf '%s  %s\n' bcde983cdab8790fe436d0f977e64cee4ae53ea74701820df2cab9e9d21704f1 /srv/ar-local/data/state/2026-09-02.done.json | sha256sum -c -
printf '%s  %s\n' f2945b67890138827dcd1b74be69ae4e6727b740cd1a5414a2da01e0cea35745 /srv/ar-local/data/state/observation-pointers-v2/latest-observation.json | sha256sum -c -
printf '%s  %s\n' cf98d96b46a18bdb5f128b439555429f7a648516ee9650aafa304ddca55fa425 /srv/ar-local/data/state/ledger-v2/head.json | sha256sum -c -
printf '%s  %s\n' 4f45841840f1b2a256120bd269dd5557f277653d8a7c6667c4cf717564897d25 /srv/ar-local/data/runs/2026-09-02/_exports/ingest-status.json | sha256sum -c -
printf '%s  %s\n' a1f6cd2369e872704530616b3b435fac8a115e13001645eef6b86fffc2454d44 /srv/ar-local/data/state/export-contracts-v2/2026-09-02/obs-2026-09-02-724fc227e6776842.json | sha256sum -c -
printf '%s  %s\n' 9be89c33d89bef07e49c452340f2c2265880d7dd1b035dd6108ce57126d5e7af /srv/ar-local/data/runs/2026-09-02/_exports/local-cdr.sqlite | sha256sum -c -
test "$(curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest | sha256sum | cut -d' ' -f1)" = bbca1b65b96b06aed4702b551a507b7475739dc31c7ec9bbbcbadb7c312180b4
python3 - <<'PY'
import sqlite3
p='/srv/ar-local/data/runs/2026-09-02/_exports/local-cdr.sqlite'
c=sqlite3.connect(f'file:{p}?mode=ro',uri=True);c.execute('pragma query_only=on')
assert c.execute('pragma quick_check').fetchall()==[('ok',)]
PY
echo AR_PI_PREFLIGHT_PASS
'@
$pi=Invoke-ArTrustedSshScript -SshPath $ssh -HostName $endpoint -LogicalHost 'ar-local-pi5' -UserName 'pi' -Port 22 -IdentityPath $identity -KnownHostsPath $knownHostsAlias -Script (($remote-replace"`r",'')+"`n") -TimeoutMilliseconds 120000
if($pi.ExitCode-ne0-or$pi.Stderr-or@($pi.Stdout.TrimEnd()-split"`n")[-1]-cne'AR_PI_PREFLIGHT_PASS'){throw "Pi preflight failed: $($pi.Stderr)"}
WriteUtf8 (Join-Path $root 'pi-preflight.txt') $pi.Stdout

$web=[Net.Http.HttpClient]::new();$web.Timeout=[TimeSpan]::FromSeconds(20)
try{foreach($pair in @(@('https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/manifest.json','367d2fa065511929943fcb3f154a354939474388c116e28b7d4b04f252075f47'),@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json','a97087c046f864d5df6c8aa6205ad7b703a4feaa46e05f47e072ef2853b54236'),@('https://github.com/yanniedog/AR-local/releases/download/app-payload-dates/dates-index.json','9426f208084a501be82504187a82954fbb2b160ec730adab3fa18f0d6a68c56e'),@('https://github.com/yanniedog/AR-local/releases/download/app-payload-v2-latest/manifest-v2.json','02e14f71b604dbfd652fef7c1a3c46932ad9b32beef7cc90e99ddc14a1ca4acb'))){$bytes=$web.GetByteArrayAsync($pair[0]).GetAwaiter().GetResult();$h=[Security.Cryptography.SHA256]::Create();try{$actual=($h.ComputeHash($bytes)|ForEach-Object{$_.ToString('x2')})-join''}finally{$h.Dispose()};if($actual-cne$pair[1]){throw "publication drift: $($pair[0])"}}}finally{$web.Dispose()}
if(((& $git ls-remote $repo refs/heads/main)-split"`t")[0]-cne$authoritySha-or(Sha $handoff)-cne$handoffSha){throw 'authority advanced during preparation'}

$installer=Join-Path $candidate 'install_laptop_backup_trusted_dispatcher.ps1';$core=Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_core.ps1';$sshBoundary=Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_ssh.ps1';$hostPath='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe';$preexec=Join-Path $root 'pre-execution-manifest.json'
$invoke=[ordered]@{task_name=$taskName;package_path=$package1;package_sha256=(Sha $package1);install_root=$installRoot;target=$target;control_root=$control;recovery_image=$recovery;evidence_root=$evidenceRoot;principal=$principal;operator=$operator;operator_sid=$operatorSid;candidate_code_sha=$candidateSha;authority_commit=$authoritySha;protected_code_sha=$protectedSha;plan_git_commit=$planCommit;plan_sha256=$planSha;handoff_sha256=$handoffSha;expected_old_task_xml_sha256='aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2';expected_old_task_sddl_sha256='6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b';expected_old_task_sddl_semantic_sha256='d0e0ac6dbbbe519444e70161be2a447fa7b6b718a710160e578bd9f4e4bf7965';expected_old_task_last_result=1;expected_catalog_sha256='7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511';expected_catalog_size=236234L;expected_catalog_final_sequence=336;expected_catalog_final_entry_sha256='368ed91d6957d60eda5d76f06175e3ff00e20fb5cf5d6d2d94a478d164112420';expected_latest_verified_sha256='737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389';expected_latest_verified_size=316L;expected_accepted_catalog_entry_sha256='6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68';expected_accepted_receipt_relative_path='observations/2026-08-30/f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d/receipt.json';expected_accepted_receipt_sha256='7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea';expected_accepted_receipt_size=3392L;expected_accepted_observation_id='obs-2026-08-30-69a34aa4c745bb2e';expected_accepted_archive_sha256='abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b';expected_accepted_archive_size=237101208L;installer_sha256=(Sha $installer);core_sha256=(Sha $core);ssh_boundary_sha256=(Sha $sshBoundary);pre_execution_manifest_path=$preexec;pre_execution_manifest_sha256='<SELF_SHA256>';pi_host='ar.local';pi_user='pi';pi_port=22;ssh_identity_path=$identity;ssh_identity_sha256=(Sha $identity);ssh_executable_sha256=(Sha $ssh)}
$contract=Get-ArTrustedInvocationContractSha256 $invoke
$fresh=[DateTimeOffset]::UtcNow
if([DateTimeOffset]::Now.AddMinutes(45).DateTime.Date-ne[DateTimeOffset]::Now.Date-or[DateTimeOffset]::Now.AddMinutes(45).TimeOfDay-gt[TimeSpan]::FromHours(22)){throw 'preflight would cross safe stop'}
$pre=[ordered]@{schema_version=1;plan_document_id='ARL-OPS-001';plan_version='1.5';task_name=$taskName;package_path=$package1;package_sha256=(Sha $package1);install_root=$installRoot;target=$target;control_root=$control;recovery_image=$recovery;evidence_root=$evidenceRoot;principal=$principal;operator=$operator;operator_sid=$operatorSid;candidate_code_sha=$candidateSha;authority_commit=$authoritySha;protected_code_sha=$protectedSha;plan_git_commit=$planCommit;plan_sha256=$planSha;handoff_sha256=$handoffSha;expected_old_task_xml_sha256=$invoke.expected_old_task_xml_sha256;expected_old_task_sddl_sha256=$invoke.expected_old_task_sddl_sha256;expected_old_task_sddl_semantic_sha256=$invoke.expected_old_task_sddl_semantic_sha256;expected_old_task_last_result=1;installer_sha256=(Sha $installer);core_sha256=(Sha $core);ssh_boundary_sha256=(Sha $sshBoundary);expected_catalog_sha256=$invoke.expected_catalog_sha256;expected_catalog_size=236234L;expected_catalog_final_sequence=336;expected_catalog_final_entry_sha256=$invoke.expected_catalog_final_entry_sha256;expected_latest_verified_sha256=$invoke.expected_latest_verified_sha256;expected_latest_verified_size=316L;expected_accepted_catalog_entry_sha256=$invoke.expected_accepted_catalog_entry_sha256;expected_accepted_receipt_relative_path=$invoke.expected_accepted_receipt_relative_path;expected_accepted_receipt_sha256=$invoke.expected_accepted_receipt_sha256;expected_accepted_receipt_size=3392L;expected_accepted_observation_id=$invoke.expected_accepted_observation_id;expected_accepted_archive_sha256=$invoke.expected_accepted_archive_sha256;expected_accepted_archive_size=237101208L;invocation_contract_schema=1;invocation_host_path=$hostPath;invocation_script_path=$installer;invocation_contract_sha256=$contract;rollback_procedure='RESTORE_TASK_CONTROL_AND_QUARANTINE_V1';preflight_min_free_bytes=53687091200L;preflight_expected_active_process_count=0;preflight_expected_residue_count=0;preflight_expected_pi_status='AR_PI_PREFLIGHT_PASS';pi_host='ar.local';pi_user='pi';pi_port=22;ssh_identity_path=$identity;ssh_identity_sha256=(Sha $identity);ssh_executable_sha256=(Sha $ssh);created_at=$fresh.ToString('o');expires_at=$fresh.AddMinutes(45).ToString('o')}
WriteJson $preexec $pre

function Quote([string]$Value){"'"+$Value.Replace("'","''")+"'"}
$args=[ordered]@{TaskName=$taskName;PackagePath=$package1;PackageSha256=(Sha $package1);InstallRoot=$installRoot;Target=$target;ControlRoot=$control;RecoveryImage=$recovery;EvidenceRoot=$evidenceRoot;Principal=$principal;Operator=$operator;OperatorSid=$operatorSid;CandidateCodeSha=$candidateSha;AuthorityCommit=$authoritySha;ProtectedCodeSha=$protectedSha;PlanGitCommit=$planCommit;PlanSha256=$planSha;HandoffSha256=$handoffSha;ExpectedOldTaskXmlSha256=$invoke.expected_old_task_xml_sha256;ExpectedOldTaskSddlSha256=$invoke.expected_old_task_sddl_sha256;ExpectedOldTaskSddlSemanticSha256=$invoke.expected_old_task_sddl_semantic_sha256;ExpectedOldTaskLastResult='1';ExpectedCatalogSha256=$invoke.expected_catalog_sha256;ExpectedCatalogSize='236234';ExpectedCatalogFinalSequence='336';ExpectedCatalogFinalEntrySha256=$invoke.expected_catalog_final_entry_sha256;ExpectedLatestVerifiedSha256=$invoke.expected_latest_verified_sha256;ExpectedLatestVerifiedSize='316';ExpectedAcceptedCatalogEntrySha256=$invoke.expected_accepted_catalog_entry_sha256;ExpectedAcceptedReceiptRelativePath=$invoke.expected_accepted_receipt_relative_path;ExpectedAcceptedReceiptSha256=$invoke.expected_accepted_receipt_sha256;ExpectedAcceptedReceiptSize='3392';ExpectedAcceptedObservationId=$invoke.expected_accepted_observation_id;ExpectedAcceptedArchiveSha256=$invoke.expected_accepted_archive_sha256;ExpectedAcceptedArchiveSize='237101208';InstallerSha256=(Sha $installer);CoreSha256=(Sha $core);SshBoundarySha256=(Sha $sshBoundary);PreExecutionManifestPath=$preexec;PreExecutionManifestSha256=(Sha $preexec);SshIdentityPath=$identity;SshIdentitySha256=(Sha $identity);SshExecutableSha256=(Sha $ssh);PiHost='ar.local';PiUser='pi';PiPort='22'}
$inner='$ErrorActionPreference=''Stop'';& '+(Quote $installer);foreach($item in $args.GetEnumerator()){$inner+=' -'+$item.Key+' '+(Quote ([string]$item.Value))}
$encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
[IO.File]::WriteAllText((Join-Path $root 'uac-encoded.txt'),$encoded,[Text.Encoding]::ASCII)
$summary=[ordered]@{result='PASS';authority_commit=$authoritySha;handoff_sha256=$handoffSha;candidate_code_sha=$candidateSha;endpoint=$endpoint;logical_host='ar-local-pi5';launcher_sha256=(Sha $launcher1);package_sha256=(Sha $package1);activation_gate_sha256=(Sha $gatePath);dispatcher_manifest_sha256=(Sha $manifest);pre_execution_manifest_sha256=(Sha $preexec);invocation_contract_sha256=$contract;check_only_execution_record=$check.execution_record;catalog_sha256=$invoke.expected_catalog_sha256;expires_at=$pre.expires_at;uac_encoded_sha256=(Sha (Join-Path $root 'uac-encoded.txt'))}
WriteJson (Join-Path $root 'preflight-summary.json') $summary
[Console]::Out.Write($encoded)
```
<!-- END ARL-D012-PREPARE-AND-PREFLIGHT-PS1 -->

Materialize only from the current merged authority checkout: read the bytes
strictly between the markers, remove the Markdown fence lines, normalize LF,
write create-once to the exact path, and require the bound generator SHA-256 in
the correction immediately below. The materializer and generator are ordinary
non-administrator commands; neither is authorized in this documentation turn.

### Generator binding correction `C-20260902T140500+1000`

The exact generator block is 27954 UTF-8/LF bytes, 198 lines, SHA-256
`5471eef99980b1b9970284ccf716ce99aba928fa96bbbf510860e203fdb49de6`.
PowerShell's parser reports zero syntax errors. This binding supersedes the
earlier dangling generator reference and earlier `next_command` hash.

Run this complete materializer only after the authority merge. It obtains the
current immutable handoff directly at canonical `origin/main`, records the
actual D-012 authority and complete handoff hashes, extracts only the marked
block, verifies the hash above, and uses create-once output:

```powershell
$ErrorActionPreference='Stop'
$repo='https://github.com/yanniedog/AR-local.git'
$authoritySha=(((& 'C:\Program Files\Git\cmd\git.exe' ls-remote $repo refs/heads/main)-split"`t")[0]).ToLowerInvariant()
if($authoritySha-notmatch'^[0-9a-f]{40}$'){throw 'canonical main is invalid'}
$client=[Net.Http.HttpClient]::new();$client.Timeout=[TimeSpan]::FromSeconds(20)
try{$bytes=$client.GetByteArrayAsync("https://raw.githubusercontent.com/yanniedog/AR-local/$authoritySha/docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md").GetAwaiter().GetResult()}finally{$client.Dispose()}
$alg=[Security.Cryptography.SHA256]::Create();try{$handoffSha=($alg.ComputeHash($bytes)|ForEach-Object{$_.ToString('x2')})-join''}finally{$alg.Dispose()}
$text=[Text.Encoding]::UTF8.GetString($bytes)
if($text-notmatch'HANDOFF-20260902T133826\+1000-A3-PINNED-LAN-FINAL-AUTHORITY'){throw 'current main lacks authority entry'}
$match=[regex]::Match($text,'(?s)<!-- BEGIN ARL-D012-PREPARE-AND-PREFLIGHT-PS1 -->\r?\n```powershell\r?\n(.*?)\r?\n```\r?\n<!-- END ARL-D012-PREPARE-AND-PREFLIGHT-PS1 -->')
if(-not$match.Success){throw 'bound generator block is absent'}
$script=$match.Groups[1].Value-replace"`r",'';$scriptBytes=[Text.UTF8Encoding]::new($false).GetBytes($script)
$alg=[Security.Cryptography.SHA256]::Create();try{$scriptSha=($alg.ComputeHash($scriptBytes)|ForEach-Object{$_.ToString('x2')})-join''}finally{$alg.Dispose()}
if($scriptBytes.Length-ne27954-or$scriptSha-cne'5471eef99980b1b9970284ccf716ce99aba928fa96bbbf510860e203fdb49de6'){throw 'generator binding mismatch'}
$root='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012';if(Test-Path -LiteralPath $root){throw 'evidence root is not create-once'}
[void](New-Item -ItemType Directory -Path $root)
$path=Join-Path $root 'prepare-and-preflight.ps1';$stream=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$stream.Write($scriptBytes,0,$scriptBytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
$record=[ordered]@{schema_version=1;authority_commit=$authoritySha;complete_handoff_raw_sha256=$handoffSha;generator_path=$path;generator_bytes=$scriptBytes.Length;generator_sha256=$scriptSha;materialized_at=[DateTimeOffset]::UtcNow.ToString('o')}
[IO.File]::WriteAllText((Join-Path $root 'materialization.json'),(($record|ConvertTo-Json -Compress)+"`n"),[Text.UTF8Encoding]::new($false))
if((((& 'C:\Program Files\Git\cmd\git.exe' ls-remote $repo refs/heads/main)-split"`t")[0])-cne$authoritySha){throw 'main advanced during materialization'}
$record|ConvertTo-Json -Compress
```

The corrected exact next command is 205 UTF-8 bytes with no trailing LF,
SHA-256 `45ebfe833dfcf9126e05a2608725fb6e949611f5c3af3a6f3f24d5f0cc0b4184`:

```powershell
$encoded = & 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -ExecutionPolicy Bypass -File 'C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012\prepare-and-preflight.ps1'
```

`$encoded` must be one non-empty base64 line and the generator's terminal
`preflight-summary.json` must be `PASS`, current and unexpired before using the
single UAC command already bound above. The corrected pointer delta is:

```json
{"schema":"ARL-A3-RESUME-POINTER-V1","version":1,"sequence":4,"predecessor":"HANDOFF-20260902T133826+1000-A3-PINNED-LAN-FINAL-AUTHORITY","correction":"C-20260902T140500+1000","generator":{"path":"C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012\\prepare-and-preflight.ps1","bytes":27954,"sha256":"5471eef99980b1b9970284ccf716ce99aba928fa96bbbf510860e203fdb49de6"},"authority_merge_sha":"D012_MATERIALIZATION_RECORD","complete_handoff_raw_sha256":"D012_MATERIALIZATION_RECORD","package_sha256":"D012_PREFLIGHT_SUMMARY","dispatcher_manifest_sha256":"D012_PREFLIGHT_SUMMARY","preexecution_manifest_sha256":"D012_PREFLIGHT_SUMMARY","next_command":"$encoded = & 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe' -NoProfile -ExecutionPolicy Bypass -File 'C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012\\prepare-and-preflight.ps1'","next_command_utf8_lf_sha256":"45ebfe833dfcf9126e05a2608725fb6e949611f5c3af3a6f3f24d5f0cc0b4184","terminal_status":"USABLE_ONLY_AFTER_MATERIALIZER_AND_FRESH_PREFLIGHT_PASS"}
```

### Terminal generator correction `C-20260902T143500+1000`

This correction supersedes and quarantines the unmodified generator and the
sequence-4 materializer. Neither may be used. Read-only fetches on 2026-09-02
authenticated the canonical rolling routes: `app-payload-latest/dates-index.json`
is 2116 bytes, SHA-256
`9426f208084a501be82504187a82954fbb2b160ec730adab3fa18f0d6a68c56e`, and
`app-payload-latest/manifest-v2.json` is 1217 bytes, SHA-256
`02e14f71b604dbfd652fef7c1a3c46932ad9b32beef7cc90e99ddc14a1ca4acb`.
The obsolete `app-payload-dates` and `app-payload-v2-latest` routes are
quarantined. The dated and rolling core/details assets and rolling search asset
were also fetched independently at the exact sizes and hashes in the authority.

The corrected generator requires the create-once evidence root to contain only
`prepare-and-preflight.ps1` and `materialization.json` at entry. It gives both
launcher objects explicit paths, emits `build-result.json`, records every fixed
source/tool and generated file by absolute path, size and SHA-256, and rejects
any missing or unexpected top-level output before terminal `PASS`. The final
UTF-8/LF generator is 31582 bytes, 220 lines, SHA-256
`19bbfa484945d48dd782e52ce16673b7653de2748feb5aad8109dc15c300a2ae`;
PowerShell's parser reports zero errors.

The corrected exact dual launcher commands are:

```powershell
& cl.exe /nologo /std:c++17 /O2 /MT /W4 /WX /EHsc /GS /guard:cf /Brepro /DUNICODE /D_UNICODE $source "/Fo$launcherObj1" "/Fe:$launcher1" /link advapi32.lib /DYNAMICBASE /NXCOMPAT /guard:cf
& cl.exe /nologo /std:c++17 /O2 /MT /W4 /WX /EHsc /GS /guard:cf /Brepro /DUNICODE /D_UNICODE $source "/Fo$launcherObj2" "/Fe:$launcher2" /link advapi32.lib /DYNAMICBASE /NXCOMPAT /guard:cf
if ((Get-FileHash -LiteralPath $launcher1 -Algorithm SHA256).Hash -cne (Get-FileHash -LiteralPath $launcher2 -Algorithm SHA256).Hash) { throw 'launcher builds differ' }
```

The corrected generator retains these exact deterministic dual package commands:

```powershell
$packageArgs=@('--candidate-repo',$candidate,'--candidate-sha',$candidateSha,'--authority-repo',$authority,'--authority-sha',$authoritySha,'--python-root',$runtime,'--launcher',$launcher1,'--dispatcher-manifest',$manifest,'--install-root',$installRoot,'--control-root',$control,'--operator-sid',$operatorSid,'--git',$git,'--ssh',$ssh,'--scp',$scp,'--ssh-host','ar.local','--ssh-user','pi','--ssh-port','22','--ssh-identity',$identity,'--ssh-known-hosts',$knownHostsSource,'--whoami',$whoami)
& $python -I -B (Join-Path $candidate 'laptop_backup_trusted_package.py') @packageArgs --output $package1
if ($LASTEXITCODE) { throw 'package build 1 failed' }
& $python -I -B (Join-Path $candidate 'laptop_backup_trusted_package.py') @packageArgs --output $package2
if ($LASTEXITCODE) { throw 'package build 2 failed' }
if ((Get-FileHash -LiteralPath $package1 -Algorithm SHA256).Hash -cne (Get-FileHash -LiteralPath $package2 -Algorithm SHA256).Hash) { throw 'package builds differ' }
```

After this correction is merged, run the following complete non-administrator
materializer from any clean PowerShell session. It resolves canonical current
`main`, hashes the complete raw handoff, verifies the original marked block,
applies only the eight unique fail-closed replacements below, verifies the exact
corrected generator binding and parser result, and writes create-once. It does
not build, preflight, elevate, trigger, back up, ingest, deploy or publish.

```powershell
$ErrorActionPreference='Stop'
$repo='https://github.com/yanniedog/AR-local.git'
$git='C:\Program Files\Git\cmd\git.exe'
$authoritySha=(((& $git ls-remote $repo refs/heads/main)-split"`t")[0]).ToLowerInvariant()
if($authoritySha-notmatch'^[0-9a-f]{40}$'-or$authoritySha-ceq'8b158d74ddd51a3523ecb6367b6ef99ca994df61'){throw 'post-merge canonical main is invalid'}
$client=[Net.Http.HttpClient]::new();$client.Timeout=[TimeSpan]::FromSeconds(20)
try{$handoffBytes=$client.GetByteArrayAsync("https://raw.githubusercontent.com/yanniedog/AR-local/$authoritySha/docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md").GetAwaiter().GetResult()}finally{$client.Dispose()}
function BytesSha([byte[]]$Bytes){$h=[Security.Cryptography.SHA256]::Create();try{($h.ComputeHash($Bytes)|ForEach-Object{$_.ToString('x2')})-join''}finally{$h.Dispose()}}
$handoffSha=BytesSha $handoffBytes
$text=[Text.Encoding]::UTF8.GetString($handoffBytes)
if(-not$text.Contains('C-20260902T143500+1000')){throw 'current main lacks terminal correction'}
$match=[regex]::Match($text,'(?s)<!-- BEGIN ARL-D012-PREPARE-AND-PREFLIGHT-PS1 -->\r?\n```powershell\r?\n(.*?)\r?\n```\r?\n<!-- END ARL-D012-PREPARE-AND-PREFLIGHT-PS1 -->')
if(-not$match.Success){throw 'marked generator is absent'}
$script=$match.Groups[1].Value-replace"`r",''
$originalBytes=[Text.UTF8Encoding]::new($false).GetBytes($script)
if($originalBytes.Length-ne27954-or(BytesSha $originalBytes)-cne'5471eef99980b1b9970284ccf716ce99aba928fa96bbbf510860e203fdb49de6'){throw 'original generator binding mismatch'}
function ReplaceLineOnce([string]$Text,[string]$Needle,[string]$New){$lines=[Collections.Generic.List[string]]::new();foreach($line in ($Text-split"`n")){$lines.Add($line)};$indexes=@(for($i=0;$i-lt$lines.Count;$i++){if($lines[$i].Contains($Needle)){$i}});if($indexes.Count-ne1){throw "line match count $($indexes.Count): $Needle"};$lines[$indexes[0]]=$New;[string]::Join("`n",$lines)}
$replacement=@'
$allowedInitial=@('prepare-and-preflight.ps1','materialization.json')
$initial=@(Get-ChildItem -LiteralPath $root -Force)
if($initial.Count-ne2-or@($initial|Where-Object{$allowedInitial-notcontains$_.Name}).Count-or@($allowedInitial|Where-Object{-not(Test-Path -LiteralPath (Join-Path $root $_) -PathType Leaf)}).Count){throw 'evidence root contains prior or unbound output'}
'@.Trim()
$script=ReplaceLineOnce $script 'non-reusable output exists' $replacement
$replacement=@'
$launcher1=Join-Path $root 'launcher-1.exe';$launcher2=Join-Path $root 'launcher-2.exe';$launcherObj1=Join-Path $root 'launcher-1.obj';$launcherObj2=Join-Path $root 'launcher-2.obj';$source=Join-Path $candidate 'native\laptop_backup_trusted_launcher.cpp'
'@.Trim()
$script=ReplaceLineOnce $script '$launcher1=Join-Path' $replacement
$script=ReplaceLineOnce $script '"/Fe:$launcher1"' '& cl.exe /nologo /std:c++17 /O2 /MT /W4 /WX /EHsc /GS /guard:cf /Brepro /DUNICODE /D_UNICODE $source "/Fo$launcherObj1" "/Fe:$launcher1" /link advapi32.lib /DYNAMICBASE /NXCOMPAT /guard:cf|Out-Null'
$script=ReplaceLineOnce $script '"/Fe:$launcher2"' '& cl.exe /nologo /std:c++17 /O2 /MT /W4 /WX /EHsc /GS /guard:cf /Brepro /DUNICODE /D_UNICODE $source "/Fo$launcherObj2" "/Fe:$launcher2" /link advapi32.lib /DYNAMICBASE /NXCOMPAT /guard:cf|Out-Null'
$replacement=@'
if((Sha $package1)-cne(Sha $package2)){throw 'package builds differ'}

function Record([string]$Path){[ordered]@{path=[IO.Path]::GetFullPath($Path);bytes=[long](Get-Item -LiteralPath $Path).Length;sha256=(Sha $Path)}}
$sourceRecords=[ordered]@{};foreach($item in $sources.GetEnumerator()){$path=Join-Path $candidate $item.Key;$sourceRecords[$item.Key]=Record $path}
$build=[ordered]@{schema_version=1;authority_commit=$authoritySha;candidate_commit=$candidateSha;protected_commit=$protectedSha;complete_handoff=(Record $handoff);plan=[ordered]@{commit=$planCommit;sha256=$planSha};runtime=[ordered]@{path=$runtime;files=3067;bytes=64118158L;inventory_sha256='d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7';python=(Record $python)};tools=[ordered]@{git=(Record $git);ssh=(Record $ssh);scp=(Record $scp);whoami=(Record $whoami);identity=(Record $identity)};sources=$sourceRecords;route=[ordered]@{discovery='ar.local';selected=$endpoint;logical='ar-local-pi5';user='pi';port=22;key_blob_sha256=$blobHex;fingerprint=$fingerprint};known_hosts_source=(Record $knownHostsSource);known_hosts_alias=(Record $knownHostsAlias);trusted_child=(Record (Join-Path $root 'trusted-child.json'));check_only=(Record (Join-Path $root 'check-only.json'));active_pointer=(Record $pointerPath);activation_gate=(Record $gatePath);dispatcher_manifest=(Record $manifest);launcher_1=(Record $launcher1);launcher_2=(Record $launcher2);launcher_object_1=(Record $launcherObj1);launcher_object_2=(Record $launcherObj2);package_1=(Record $package1);package_2=(Record $package2)}
WriteJson (Join-Path $root 'build-result.json') $build
'@.Trim()
$script=ReplaceLineOnce $script 'if((Sha $package1)-cne' $replacement
$replacement=@'
$publication=@(
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/manifest.json',1211L,'367d2fa065511929943fcb3f154a354939474388c116e28b7d4b04f252075f47'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json',2881L,'a97087c046f864d5df6c8aa6205ad7b703a4feaa46e05f47e072ef2853b54236'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/dates-index.json',2116L,'9426f208084a501be82504187a82954fbb2b160ec730adab3fa18f0d6a68c56e'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest-v2.json',1217L,'02e14f71b604dbfd652fef7c1a3c46932ad9b32beef7cc90e99ddc14a1ca4acb'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/core-2026-09-02-d1683a44c258.json.gz',362452L,'d1683a44c258450b2bba233d4b70e95446dad437a023f1bbb0b7dbe6f0a55f11'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/details-2026-09-02-0bd1ae7c5ecd.json.gz',757500L,'0bd1ae7c5ecd556983ccecfb7747ca50cb81651e3bd05571c314a23bc2b41e46'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/core-2026-09-02-d1683a44c258.json.gz',362452L,'d1683a44c258450b2bba233d4b70e95446dad437a023f1bbb0b7dbe6f0a55f11'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/details-2026-09-02-0bd1ae7c5ecd.json.gz',757500L,'0bd1ae7c5ecd556983ccecfb7747ca50cb81651e3bd05571c314a23bc2b41e46'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/search-index-2026-09-02-6db1e8a078cc.json.gz',597950L,'6db1e8a078ccc133839a8fa79488bc8ae7e6d6e84db515729cefe0d5cf4dd12a'))
$web=[Net.Http.HttpClient]::new();$web.Timeout=[TimeSpan]::FromSeconds(20)
'@.Trim()
$script=ReplaceLineOnce $script '$web=[Net.Http.HttpClient]::new()' $replacement
$script=ReplaceLineOnce $script 'try{foreach($pair in @(@(' 'try{foreach($pair in $publication){$bytes=$web.GetByteArrayAsync($pair[0]).GetAwaiter().GetResult();$h=[Security.Cryptography.SHA256]::Create();try{$actual=($h.ComputeHash($bytes)|ForEach-Object{$_.ToString(''x2'')})-join''''}finally{$h.Dispose()};if($bytes.Length-ne[long]$pair[1]-or$actual-cne$pair[2]){throw "publication drift: $($pair[0])"}}}finally{$web.Dispose()}'
$replacement=@'
$expected=@('prepare-and-preflight.ps1','materialization.json','candidate','authority','known-hosts-source','known-hosts-alias','dispatcher-manifest.json','trusted-child.json','check-only.json','activation-gate.json','launcher-1.exe','launcher-2.exe','launcher-1.obj','launcher-2.obj','trusted-package-1.zip','trusted-package-2.zip','build-result.json','observed-task.xml','pi-preflight.txt','pre-execution-manifest.json','uac-encoded.txt')
$present=@(Get-ChildItem -LiteralPath $root -Force|ForEach-Object{$_.Name})
if(@($expected|Where-Object{$present-notcontains$_}).Count-or@($present|Where-Object{$expected-notcontains$_}).Count){throw 'generated output set is incomplete or unbound'}
$outputs=[ordered]@{};foreach($name in $expected){$path=Join-Path $root $name;if(Test-Path -LiteralPath $path -PathType Leaf){$outputs[$name]=Record $path}}
$outputs['active-runner.json']=Record $pointerPath
$summary=[ordered]@{schema_version=1;result='PASS';authority_commit=$authoritySha;complete_handoff_sha256=$handoffSha;candidate_code_sha=$candidateSha;protected_code_sha=$protectedSha;plan_commit=$planCommit;plan_sha256=$planSha;endpoint=$endpoint;logical_host='ar-local-pi5';host_key_blob_sha256=$blobHex;host_key_fingerprint=$fingerprint;outputs=$outputs;invocation_contract_sha256=$contract;check_only_execution_record=$check.execution_record;catalog_sha256=$invoke.expected_catalog_sha256;expires_at=$pre.expires_at}
'@.Trim()
$script=ReplaceLineOnce $script '$summary=[ordered]@{result=' $replacement
$scriptBytes=[Text.UTF8Encoding]::new($false).GetBytes($script)
$scriptSha=BytesSha $scriptBytes
if($scriptBytes.Length-ne31582-or$scriptSha-cne'19bbfa484945d48dd782e52ce16673b7653de2748feb5aad8109dc15c300a2ae'){throw 'corrected generator binding mismatch'}
$tokens=$null;$parseErrors=$null;[Management.Automation.Language.Parser]::ParseInput($script,[ref]$tokens,[ref]$parseErrors)|Out-Null
if(@($parseErrors).Count){throw 'corrected generator has parse errors'}
if((((& $git ls-remote $repo refs/heads/main)-split"`t")[0]).ToLowerInvariant()-cne$authoritySha){throw 'main advanced during materialization'}
$root='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012'
if(Test-Path -LiteralPath $root){throw 'evidence root is not create-once'}
[void](New-Item -ItemType Directory -Path $root)
function WriteNew([string]$Path,[byte[]]$Bytes){$stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$stream.Write($Bytes,0,$Bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}}
$generatorPath=Join-Path $root 'prepare-and-preflight.ps1'
WriteNew $generatorPath $scriptBytes
$record=[ordered]@{schema_version=1;correction='C-20260902T143500+1000';authority_commit=$authoritySha;complete_handoff_raw_sha256=$handoffSha;original_generator_sha256='5471eef99980b1b9970284ccf716ce99aba928fa96bbbf510860e203fdb49de6';generator_path=$generatorPath;generator_bytes=$scriptBytes.Length;generator_lines=220;generator_sha256=$scriptSha;materialized_at=[DateTimeOffset]::UtcNow.ToString('o')}
$recordBytes=[Text.UTF8Encoding]::new($false).GetBytes((($record|ConvertTo-Json -Compress)+"`n"))
WriteNew (Join-Path $root 'materialization.json') $recordBytes
$record|ConvertTo-Json -Compress
```

Materializer output binding: `prepare-and-preflight.ps1` must be exactly 31582
UTF-8/LF bytes with SHA-256
`19bbfa484945d48dd782e52ce16673b7653de2748feb5aad8109dc15c300a2ae`.
The actual authority commit and complete handoff raw SHA-256 are recorded in
`materialization.json`; generated launcher/package/manifest/pointer and every
preflight output identity are recorded in `build-result.json` and
`preflight-summary.json`. Do not reuse the evidence root after any failure.

The exact next command remains 205 UTF-8 bytes with no trailing LF, SHA-256
`45ebfe833dfcf9126e05a2608725fb6e949611f5c3af3a6f3f24d5f0cc0b4184`:

```powershell
$encoded = & 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -ExecutionPolicy Bypass -File 'C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012\prepare-and-preflight.ps1'
```

Only a non-empty one-line base64 result plus current, unexpired terminal
`preflight-summary.json` `PASS` permits the single UAC command already recorded
in the sequence-3 authority. No other elevation, manual task trigger, backup,
ingest, deployment or publication is authorized. Natural backup acceptance is
still mandatory; A3 remains running and A4 remains blocked.

```json
{"schema":"ARL-A3-RESUME-POINTER-V1","version":1,"sequence":5,"predecessor":"HANDOFF-20260902T133826+1000-A3-PINNED-LAN-FINAL-AUTHORITY","correction":"C-20260902T143500+1000","quarantines":["unmodified-generator-5471eef99980b1b9970284ccf716ce99aba928fa96bbbf510860e203fdb49de6","sequence-4-materializer","app-payload-dates","app-payload-v2-latest"],"candidate_sha":"8b158d74ddd51a3523ecb6367b6ef99ca994df61","authority_merge_sha":"D012_MATERIALIZATION_RECORD","complete_handoff_raw_sha256":"D012_MATERIALIZATION_RECORD","generator":{"path":"C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012\\prepare-and-preflight.ps1","bytes":31582,"lines":220,"sha256":"19bbfa484945d48dd782e52ce16673b7653de2748feb5aad8109dc15c300a2ae"},"build_result":"D012_BUILD_RESULT","package_sha256":"D012_PREFLIGHT_SUMMARY","dispatcher_manifest_sha256":"D012_PREFLIGHT_SUMMARY","active_pointer_sha256":"D012_PREFLIGHT_SUMMARY","preexecution_manifest_sha256":"D012_PREFLIGHT_SUMMARY","publication":{"dates_index_url":"https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/dates-index.json","dates_index_sha256":"9426f208084a501be82504187a82954fbb2b160ec730adab3fa18f0d6a68c56e","v2_url":"https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest-v2.json","v2_sha256":"02e14f71b604dbfd652fef7c1a3c46932ad9b32beef7cc90e99ddc14a1ca4acb","v2_state":"FAIL_STALE_2026-08-21"},"next_action":"materialize corrected generator; run exact next command non-admin; require current terminal PASS; then and only then use the sole sequence-3 UAC command","next_command":"$encoded = & 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe' -NoProfile -ExecutionPolicy Bypass -File 'C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012\\prepare-and-preflight.ps1'","next_command_utf8_lf_sha256":"45ebfe833dfcf9126e05a2608725fb6e949611f5c3af3a6f3f24d5f0cc0b4184","expiry":"fresh preflight 45 minutes; never after 22:00 Australia/Hobart","stop":["main/handoff/generator drift","non-create-once root or unexpected output","resolver/key/auth drift","source/tool/runtime/task/catalog/Pi/evidence/publication drift","timeout/web-auth","process/lock/lease/partial","under 50GiB","D-006 window or expired preflight","launcher/package mismatch"],"terminal_status":"USABLE_ONLY_AFTER_MATERIALIZER_AND_FRESH_PREFLIGHT_PASS"}
```

### Terminal toolchain correction `C-20260902T144000+1000`

The sequence-5 generator and materializer are quarantined and MUST NOT be
materialized or run. They are fail-closed operationally, because the materializer
can inject an evidence-root check before `$root` is assigned and the generator
discovers `cl.exe` through ambient `PATH` without establishing or binding the
compiler/linker environment. This terminal correction supersedes both defects.

<!-- BEGIN ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T144000 -->
```powershell
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$entry='HANDOFF-20260902T133826+1000-A3-PINNED-LAN-FINAL-AUTHORITY'
$root=[IO.Path]::GetFullPath((Split-Path -Parent $PSCommandPath))
$requiredRoot='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012'
if($root-cne$requiredRoot){throw 'generator path is not the authorized evidence root'}
$candidateSha='8b158d74ddd51a3523ecb6367b6ef99ca994df61'
$protectedSha='9302890fcc752cbf90da97d597e972c157d913e3'
$planCommit='9094a8e115958fcaf2cb36525736bd5e297e6b04'
$planSha='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada'
$target='C:\code\backups\AR-local-pi5'
$control=Join-Path $target 'dispatcher-control'
$recovery='C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21'
$runtime='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-20260901\20260901T083436+1000\runtime'
$python=Join-Path $runtime 'python.exe'
$identity='C:\Users\jkoka\.ssh\pi5'
$git='C:\Program Files\Git\cmd\git.exe'
$ssh='C:\Windows\System32\OpenSSH\ssh.exe'
$scp='C:\Windows\System32\OpenSSH\scp.exe'
$whoami='C:\Windows\System32\whoami.exe'
$operator='jkoka'
$operatorSid='S-1-5-21-689213601-40760280-3596424081-1001'
$principal='yanniedog\jkoka'
$repo='https://github.com/yanniedog/AR-local.git'
$candidate=Join-Path $root 'candidate'
$authority=Join-Path $root 'authority'
$knownHostsSource=Join-Path $root 'known-hosts-source'
$knownHostsAlias=Join-Path $root 'known-hosts-alias'
$manifest=Join-Path $root 'dispatcher-manifest.json'

function Sha([string]$Path){(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function WriteUtf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,($Text-replace "`r",''),[Text.UTF8Encoding]::new($false))}
function WriteJson([string]$Path,[object]$Value){WriteUtf8 $Path (($Value|ConvertTo-Json -Depth 12 -Compress)+"`n")}
function RequireHash([string]$Path,[string]$Expected){if((Sha $Path)-cne$Expected){throw "hash drift: $Path"}}

$now=[DateTimeOffset]::Now
if($now.TimeOfDay-lt[TimeSpan]::FromHours(3.5)-or$now.TimeOfDay-ge[TimeSpan]::FromHours(22)){throw 'outside D-006 daylight window'}
$root=[IO.Path]::GetFullPath((Split-Path -Parent $PSCommandPath))
$requiredRoot='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012'
if($root-cne$requiredRoot){throw 'generator path is not the authorized evidence root'}
$allowedInitial=@('prepare-and-preflight.ps1','materialization.json')
$initial=@(Get-ChildItem -LiteralPath $root -Force)
if($initial.Count-ne2-or@($initial|Where-Object{$allowedInitial-notcontains$_.Name}).Count-or@($allowedInitial|Where-Object{-not(Test-Path -LiteralPath (Join-Path $root $_) -PathType Leaf)}).Count){throw 'evidence root contains prior or unbound output'}

$authoritySha=(((& $git ls-remote $repo refs/heads/main)-split"`t")[0]).ToLowerInvariant()
if($authoritySha-notmatch'^[0-9a-f]{40}$'-or$authoritySha-ceq$candidateSha){throw 'post-merge authority is absent'}
& $git -c core.autocrlf=false clone --quiet --no-checkout $repo $candidate
if($LASTEXITCODE){throw 'candidate clone failed'}
& $git -C $candidate -c core.autocrlf=false checkout --quiet --detach $candidateSha
if($LASTEXITCODE){throw 'candidate checkout failed'}
& $git -c core.autocrlf=false clone --quiet --no-checkout $repo $authority
if($LASTEXITCODE){throw 'authority clone failed'}
& $git -C $authority -c core.autocrlf=false checkout --quiet --detach $authoritySha
if($LASTEXITCODE){throw 'authority checkout failed'}
foreach($pair in @(@($candidate,$candidateSha),@($authority,$authoritySha))){if((& $git -C $pair[0] rev-parse HEAD).Trim()-cne$pair[1]-or(& $git -C $pair[0] status --porcelain=v1)){throw 'checkout identity/cleanliness failed'}}
$handoff=Join-Path $authority 'docs\PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'
if(-not(Select-String -LiteralPath $handoff -SimpleMatch $entry -Quiet)){throw 'authority lacks this entry'}
$handoffSha=Sha $handoff

$sources=[ordered]@{
'install_laptop_backup_trusted_dispatcher.ps1'='20f2581e46b2d525c180ff962ddfadd42e852b8d6fff1511b3f0b3c73969b96d'
'install_laptop_backup_trusted_dispatcher_core.ps1'='de958229fe2a8220cae93083e9f1ad0bec031e6b4164d130782f163fc9f49a18'
'install_laptop_backup_trusted_dispatcher_ssh.ps1'='7e387696d22a789f9ede481c48b820f52623e610e96a9f170cb6641b84757625'
'laptop_backup_trusted_package.py'='6c2e722c16bb875ce3c07a4a56ee868001fdfff6973371ec84014594a7b55d43'
'native\laptop_backup_trusted_launcher.cpp'='f31431ddb6ae9e6d7f7db5992dc74872303113761a01462264f50e173e7b7774'
'run_laptop_backup_task.ps1'='50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860'
'run_laptop_backup_trusted_child.ps1'='295271485c79907b7ee87463b53f6cc2258d146e07d771860ae4534b743c772a'
'laptop_backup_dispatcher.py'='36595c9155c0b7514c428ecd1a259b1922d810c498f398da41ea72e5a759b2bc'
'laptop_backup_dispatcher_security.py'='c52229848b75931cb576855db3093830073be48695e97610f5e82ab8e403b36b'
'laptop_backup_atomic.py'='d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c'
'laptop_backup_scheduled.py'='25e400780554e82f690822bfbaaf41f8d8e93c85106d4501e561e7558d8c44cb'
'laptop_backup_transport.py'='59cd046e7fae1eab543bb70dd0aca91bf346d6f1b554407a5eab76b3097ddfc1'
'laptop_pull_backup.py'='ce3c80b492d04ef923aca2701169be76c35ee6d7cc45a517e2c535c7d2232d47'
'laptop_backup_ssh_endpoint.py'='4b425d82301c749f3a1f6f2e36a070c169ea8a6e961d8d1ffd52fddbb4347f93'
}
foreach($item in $sources.GetEnumerator()){RequireHash (Join-Path $candidate $item.Key) $item.Value}
RequireHash $python '53e910971cbb20c3223cc44c696254ccfba9595dc4be8e16f56f6c954fff831f'
RequireHash $identity 'faf1d747eece5be5315b2172bf6ebff4bdb817eb04b49a35a8e9f2748b16ef1e'
RequireHash $git 'c470d205517c7a53ceca321df16a6e4549fcd52b576ab4d09536d36f26fda5a9'
RequireHash $ssh '6250fd52163fe99a0dc49403ed1b4bbef9b764bdb7bada017a93d057d9376a42'
RequireHash $scp '63b7118d8e1a8a84398cf4ce1584dc6b146606092fe9c68bbaf110bbdcfb480a'
RequireHash $whoami '23240ef9f8b0a9a324110b1c2331de31dc1b0e08f5359cb707e51a939af56cd3'
$inventoryCode='from pathlib import Path;import hashlib,json,sys;r=Path(sys.argv[1]);d={p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob("*")) if p.is_file()};b=(json.dumps(d,sort_keys=True,separators=(",",":"))+"\n").encode();print(len(d),sum(p.stat().st_size for p in r.rglob("*") if p.is_file()),hashlib.sha256(b).hexdigest())'
$inventory=(& $python -I -c $inventoryCode $runtime).Trim()
if($LASTEXITCODE-or$inventory-cne'3067 64118158 d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7'){throw 'runtime inventory drift'}

. (Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_core.ps1')
. (Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_ssh.ps1')
$endpoint=Resolve-ArTrustedSshEndpoint -PythonPath $python -ModulePath (Join-Path $candidate 'laptop_backup_ssh_endpoint.py') -DiscoveryName 'ar.local' -TimeoutSeconds 10
$keyLines=@(Get-Content -LiteralPath 'C:\Users\jkoka\.ssh\known_hosts'|Where-Object{($_-split'\s+')[0].Split(',')-contains$endpoint-and($_-split'\s+')[1]-ceq'ssh-ed25519'})
if($keyLines.Count-ne1){throw 'pinned key source is not unique'}
$keyFields=$keyLines[0]-split'\s+'
$blob=[Convert]::FromBase64String($keyFields[2]);$hash=[Security.Cryptography.SHA256]::Create();try{$digest=$hash.ComputeHash($blob)}finally{$hash.Dispose()}
$blobHex=($digest|ForEach-Object{$_.ToString('x2')})-join'';$fingerprint='SHA256:'+([Convert]::ToBase64String($digest).TrimEnd('='))
if($blobHex-cne'84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e'-or$fingerprint-cne'SHA256:hFaXQcJhid3wB2tMMn6EuMnfPZxgzGaI9DIZAHip6n4'){throw 'pinned key drift'}
WriteUtf8 $knownHostsSource ("ar.local ssh-ed25519 $($keyFields[2])`n")
WriteUtf8 $knownHostsAlias ("ar-local-pi5 ssh-ed25519 $($keyFields[2])`n")

$catalog=Assert-ArTrustedCatalogBaseline -Target $target -ExpectedCatalogSha256 '7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511' -ExpectedCatalogSize 236234 -ExpectedCatalogFinalSequence 336 -ExpectedCatalogFinalEntrySha256 '368ed91d6957d60eda5d76f06175e3ff00e20fb5cf5d6d2d94a478d164112420' -ExpectedLatestVerifiedSha256 '737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389' -ExpectedLatestVerifiedSize 316 -ExpectedAcceptedCatalogEntrySha256 '6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68' -ExpectedAcceptedReceiptRelativePath 'observations/2026-08-30/f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d/receipt.json' -ExpectedAcceptedReceiptSha256 '7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea' -ExpectedAcceptedReceiptSize 3392 -ExpectedAcceptedObservationId 'obs-2026-08-30-69a34aa4c745bb2e' -ExpectedAcceptedArchiveSha256 'abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b' -ExpectedAcceptedArchiveSize 237101208
$trusted=[ordered]@{schema_version=6;authority_path=$authority;atomic_path=(Join-Path $candidate 'laptop_backup_atomic.py');atomic_sha256=$sources['laptop_backup_atomic.py'];control_root=$control;dispatcher_path=(Join-Path $candidate 'laptop_backup_dispatcher.py');dispatcher_sha256=$sources['laptop_backup_dispatcher.py'];dispatcher_security_path=(Join-Path $candidate 'laptop_backup_dispatcher_security.py');dispatcher_security_sha256=$sources['laptop_backup_dispatcher_security.py'];git_path=$git;git_sha256=(Sha $git);python_path=$python;python_sha256=(Sha $python);receiver_path=$candidate;scp_path=$scp;scp_sha256=(Sha $scp);ssh_discovery_timeout_seconds=10;ssh_endpoint_path=(Join-Path $candidate 'laptop_backup_ssh_endpoint.py');ssh_endpoint_sha256=$sources['laptop_backup_ssh_endpoint.py'];ssh_host='ar.local';ssh_logical_host='ar-local-pi5';ssh_identity_path=$identity;ssh_identity_sha256=(Sha $identity);ssh_known_hosts_path=$knownHostsAlias;ssh_known_hosts_sha256=(Sha $knownHostsAlias);ssh_path=$ssh;ssh_sha256=(Sha $ssh);ssh_port=22;ssh_user='pi';whoami_path=$whoami;whoami_sha256=(Sha $whoami)}
WriteJson (Join-Path $root 'trusted-child.json') $trusted
$checkArgs=@('-B','-s','-E',(Join-Path $candidate 'laptop_backup_scheduled.py'),'--target',$target,'--host','ar.local','--ssh-user','pi','--ssh-port','22','--ssh-path',$ssh,'--ssh-sha256',(Sha $ssh),'--scp-path',$scp,'--scp-sha256',(Sha $scp),'--ssh-identity',$identity,'--ssh-known-hosts',$knownHostsAlias,'--recovery-image',$recovery,'--candidate-code-sha',$candidateSha,'--protected-code-sha',$protectedSha,'--plan-git-commit',$planCommit,'--operator',$operator,'--check-only')
$wrapper='import subprocess,sys;r=subprocess.run(sys.argv[1:],capture_output=True,text=True,timeout=120);print(r.stdout,end="");print(r.stderr,end="",file=sys.stderr);raise SystemExit(r.returncode)'
$checkText=(& $python -I -c $wrapper $python @checkArgs 2>&1|Out-String)
if($LASTEXITCODE){throw "fresh check-only failed: $checkText"}
$check=$checkText|ConvertFrom-Json
if($check.ok-ne$true-or$check.result-cne'PASS'-or$check.action-cne'NO_BACKUP_DATA_WRITE'){throw 'fresh check-only was not PASS/NO_BACKUP_DATA_WRITE'}
WriteUtf8 (Join-Path $root 'check-only.json') (($check|ConvertTo-Json -Depth 12 -Compress)+"`n")

$pointerPath=Join-Path $control 'active-runner.json'
RequireHash $pointerPath 'fd66311c66aad9a8f16643171fdb3de54f6582361d41ce3255c7da09a086e923'
$prior=Get-Content -LiteralPath $pointerPath -Raw|ConvertFrom-Json
if($prior.sequence-ne1-or$prior.manifest_sha256-cne'af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092'){throw 'dispatcher predecessor drift'}
$activationId=[guid]::NewGuid().ToString('N')
$gate=[ordered]@{schema_version=1;result='PASS';activation_id=$activationId;candidate_code_sha=$candidateSha;protected_code_sha=$protectedSha;plan_git_commit=$planCommit;plan_sha256=$planSha;authority_commit=$authoritySha;handoff_sha256=$handoffSha;operator_sid=$operatorSid;foreground_result='PASS';check_only_result='PASS'}
$gatePath=Join-Path $root 'activation-gate.json';WriteJson $gatePath $gate
$installRoot="C:\Program Files\AR-local-backup-trusted-$candidateSha-$authoritySha"
$evidenceRoot="C:\Program Files\AR-local-backup-evidence-$candidateSha-$authoritySha"
$created=[DateTimeOffset]::UtcNow
$dispatcher=[ordered]@{schema_version=1;sequence=2;activation_id=$activationId;created_at=$created.ToString('o').Replace('+00:00','Z');activation_expires_at=$created.AddMinutes(45).ToString('o').Replace('+00:00','Z');previous_manifest_sha256=$prior.manifest_sha256;plan_document_id='ARL-OPS-001';plan_version='1.5';plan_git_commit=$planCommit;plan_sha256=$planSha;authority_commit=$authoritySha;handoff_sha256=$handoffSha;authority_repo=(Join-Path $installRoot 'authority');authority_handoff_path='docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md';candidate_code_sha=$candidateSha;protected_code_sha=$protectedSha;operator=$operator;operator_sid=$operatorSid;receiver=(Join-Path $installRoot 'receiver');allowed_receiver_root=$installRoot;entrypoint='run_laptop_backup_task.ps1';entrypoint_sha256=$sources['run_laptop_backup_task.ps1'];python_path=(Join-Path $installRoot 'python\python.exe');python_sha256=(Sha $python);scheduled_plan_git_commit=$planCommit;target=$target;allowed_target_root=$target;recovery_image=$recovery;allowed_recovery_root=[IO.Path]::GetDirectoryName($recovery);gate_evidence_path=$gatePath;gate_evidence_sha256=(Sha $gatePath)}
WriteJson $manifest $dispatcher

$launcher1=Join-Path $root 'launcher-1.exe';$launcher2=Join-Path $root 'launcher-2.exe';$launcherObj1=Join-Path $root 'launcher-1.obj';$launcherObj2=Join-Path $root 'launcher-2.obj';$source=Join-Path $candidate 'native\laptop_backup_trusted_launcher.cpp'
$vcRoot='C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207'
$toolBin=Join-Path $vcRoot 'bin\Hostx64\x64';$vcInclude=Join-Path $vcRoot 'include';$vcLib=Join-Path $vcRoot 'lib\x64'
$sdkRoot='C:\Program Files (x86)\Windows Kits\10';$sdkVersion='10.0.26100.0';$sdkInclude=Join-Path $sdkRoot "Include\$sdkVersion";$sdkLib=Join-Path $sdkRoot "Lib\$sdkVersion";$sdkBin=Join-Path $sdkRoot "bin\$sdkVersion\x64"
$compiler=Join-Path $toolBin 'cl.exe';$linker=Join-Path $toolBin 'link.exe';$powershell='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
RequireHash $compiler '88c8344236a27a6e727e0a8edc49aaa2690bdc7a9464b9d18cc7abe70a9f1c0d'
RequireHash $linker 'ca11e6c45debd34bf652dfe984c5360a531a005ed78bf72852330c9c2590cf0d'
RequireHash $powershell '7600ffe12da441fe89d035b13801e8e91d064bc544a27b19a5cf49f6ab8b18f5'
$toolchainExpected=@(
[ordered]@{name='vc_bin';path=$toolBin;files=91;bytes=98923198L;inventory_sha256='08a7daf3ce8c103d678ce97b205b01ba11a02b8ff28762488de3ae5039cd8d3b'},
[ordered]@{name='vc_include';path=$vcInclude;files=361;bytes=16200441L;inventory_sha256='abd6e13dfca5e979931dd28369c7634cb7c2c51d1f759f9154a4cc00096bc99e'},
[ordered]@{name='vc_lib';path=$vcLib;files=149;bytes=525209873L;inventory_sha256='2c5faa81c6d3971c70385a6dcc1c66c3c84d36ec6539f2816b5c1170fbab08dc'},
[ordered]@{name='sdk_include';path=$sdkInclude;files=4771;bytes=361474762L;inventory_sha256='0d9498d38f6fb55cfe34aa43632ee061ac70c9c5edc9b0e9d805d3a7dfa6bb7d'},
[ordered]@{name='sdk_lib';path=$sdkLib;files=1454;bytes=804592816L;inventory_sha256='24f68321d165143550e01a803fd6e669a8d70f4b5e668a1d43a0702a8dfa4f7f'},
[ordered]@{name='sdk_bin';path=$sdkBin;files=220;bytes=73884717L;inventory_sha256='aed80b9dc3b039f42178e9456f33c5e2cc60ba87b6c66ed0ab239e1c2a3ee3a3'})
$toolInventoryCode='from pathlib import Path;import hashlib,json,sys;r=Path(sys.argv[1]);nodes=sorted(r.rglob("*"));bad=(not r.is_dir()) or bool(getattr(r.lstat(),"st_file_attributes",0)&0x400) or any(bool(getattr(p.lstat(),"st_file_attributes",0)&0x400) for p in nodes);bad and (_ for _ in ()).throw(RuntimeError("reparse or missing toolchain root"));files=[p for p in nodes if p.is_file()];d={p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files};b=(json.dumps(d,sort_keys=True,separators=(",",":"))+"\n").encode();print(json.dumps({"path":str(r),"files":len(files),"bytes":sum(p.stat().st_size for p in files),"inventory_sha256":hashlib.sha256(b).hexdigest()},separators=(",",":")))'
$toolchainObserved=[ordered]@{}
foreach($expected in $toolchainExpected){$raw=(& $python -I -B -c $toolInventoryCode $expected.path 2>&1|Out-String).Trim();if($LASTEXITCODE){throw "toolchain inventory failed: $($expected.name): $raw"};$actual=$raw|ConvertFrom-Json;if($actual.path-cne$expected.path-or[long]$actual.files-ne[long]$expected.files-or[long]$actual.bytes-ne[long]$expected.bytes-or$actual.inventory_sha256-cne$expected.inventory_sha256){throw "toolchain inventory drift: $($expected.name)"};$toolchainObserved[$expected.name]=[ordered]@{path=$actual.path;files=[long]$actual.files;bytes=[long]$actual.bytes;inventory_sha256=$actual.inventory_sha256}}
if(-not[Environment]::Is64BitProcess){throw 'x64 PowerShell is required'}
$toolchainEnvironment=[ordered]@{Path=([string]::Join(';',@($toolBin,$sdkBin,'C:\Windows\System32','C:\Windows')));INCLUDE=([string]::Join(';',@($vcInclude,(Join-Path $sdkInclude 'ucrt'),(Join-Path $sdkInclude 'shared'),(Join-Path $sdkInclude 'um'),(Join-Path $sdkInclude 'winrt'),(Join-Path $sdkInclude 'cppwinrt'))));LIB=([string]::Join(';',@($vcLib,(Join-Path $sdkLib 'ucrt\x64'),(Join-Path $sdkLib 'um\x64'))));LIBPATH=([string]::Join(';',@($vcLib,(Join-Path $sdkLib 'ucrt\x64'),(Join-Path $sdkLib 'um\x64'))));VCToolsInstallDir=($vcRoot+'\');WindowsSdkDir=($sdkRoot+'\');WindowsSDKVersion=($sdkVersion+'\');UCRTVersion=$sdkVersion;Platform='x64';VSCMD_ARG_HOST_ARCH='x64';VSCMD_ARG_TGT_ARCH='x64';TEMP=$root;TMP=$root}
foreach($name in @('CL','_CL_','LINK','_LINK_')){[Environment]::SetEnvironmentVariable($name,$null,'Process')}
foreach($item in $toolchainEnvironment.GetEnumerator()){[Environment]::SetEnvironmentVariable($item.Key,[string]$item.Value,'Process')}
if(@($toolchainEnvironment.GetEnumerator()|Where-Object{[Environment]::GetEnvironmentVariable($_.Key,'Process')-cne[string]$_.Value}).Count){throw 'toolchain environment failed to bind'}
$toolWrapper='import subprocess,sys;r=subprocess.run(sys.argv[1:],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=300);print(r.stdout,end="");print(r.stderr,end="",file=sys.stderr);raise SystemExit(r.returncode)'
Push-Location $root
try{
$compileArgs=@('/nologo','/std:c++17','/O2','/MT','/W4','/WX','/EHsc','/GS','/guard:cf','/Brepro','/DUNICODE','/D_UNICODE','/c',$source,"/Fo$launcherObj1")
$toolText=(& $python -I -B -c $toolWrapper $compiler @compileArgs 2>&1|Out-String);if($LASTEXITCODE){throw "launcher compile 1 failed: $toolText"}
$linkArgs=@('/nologo',"/OUT:$launcher1",'/MACHINE:X64','/SUBSYSTEM:CONSOLE','/DYNAMICBASE','/NXCOMPAT','/guard:cf','/Brepro',$launcherObj1,'advapi32.lib')
$toolText=(& $python -I -B -c $toolWrapper $linker @linkArgs 2>&1|Out-String);if($LASTEXITCODE){throw "launcher link 1 failed: $toolText"}
if($LASTEXITCODE){throw 'launcher build 1 failed'}
$compileArgs=@('/nologo','/std:c++17','/O2','/MT','/W4','/WX','/EHsc','/GS','/guard:cf','/Brepro','/DUNICODE','/D_UNICODE','/c',$source,"/Fo$launcherObj2")
$toolText=(& $python -I -B -c $toolWrapper $compiler @compileArgs 2>&1|Out-String);if($LASTEXITCODE){throw "launcher compile 2 failed: $toolText"}
$linkArgs=@('/nologo',"/OUT:$launcher2",'/MACHINE:X64','/SUBSYSTEM:CONSOLE','/DYNAMICBASE','/NXCOMPAT','/guard:cf','/Brepro',$launcherObj2,'advapi32.lib')
$toolText=(& $python -I -B -c $toolWrapper $linker @linkArgs 2>&1|Out-String);if($LASTEXITCODE){throw "launcher link 2 failed: $toolText"}
if($LASTEXITCODE){throw 'launcher build 2 failed'}
}finally{Pop-Location}
if((Sha $launcherObj1)-cne(Sha $launcherObj2)-or(Sha $launcher1)-cne(Sha $launcher2)){throw 'launcher object or executable builds differ'}
$package1=Join-Path $root 'trusted-package-1.zip';$package2=Join-Path $root 'trusted-package-2.zip'
$packageArgs=@('--candidate-repo',$candidate,'--candidate-sha',$candidateSha,'--authority-repo',$authority,'--authority-sha',$authoritySha,'--python-root',$runtime,'--launcher',$launcher1,'--dispatcher-manifest',$manifest,'--install-root',$installRoot,'--control-root',$control,'--operator-sid',$operatorSid,'--git',$git,'--ssh',$ssh,'--scp',$scp,'--ssh-host','ar.local','--ssh-user','pi','--ssh-port','22','--ssh-identity',$identity,'--ssh-known-hosts',$knownHostsSource,'--whoami',$whoami)
& $python -I -B (Join-Path $candidate 'laptop_backup_trusted_package.py') @packageArgs --output $package1|Out-Null
if($LASTEXITCODE){throw 'package build 1 failed'}
& $python -I -B (Join-Path $candidate 'laptop_backup_trusted_package.py') @packageArgs --output $package2|Out-Null
if($LASTEXITCODE){throw 'package build 2 failed'}
if((Sha $package1)-cne(Sha $package2)){throw 'package builds differ'}

function Record([string]$Path){[ordered]@{path=[IO.Path]::GetFullPath($Path);bytes=[long](Get-Item -LiteralPath $Path).Length;sha256=(Sha $Path)}}
$sourceRecords=[ordered]@{};foreach($item in $sources.GetEnumerator()){$path=Join-Path $candidate $item.Key;$sourceRecords[$item.Key]=Record $path}
$build=[ordered]@{schema_version=1;authority_commit=$authoritySha;candidate_commit=$candidateSha;protected_commit=$protectedSha;complete_handoff=(Record $handoff);plan=[ordered]@{commit=$planCommit;sha256=$planSha};runtime=[ordered]@{path=$runtime;files=3067;bytes=64118158L;inventory_sha256='d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7';python=(Record $python)};tools=[ordered]@{git=(Record $git);ssh=(Record $ssh);scp=(Record $scp);whoami=(Record $whoami);identity=(Record $identity)};toolchain=[ordered]@{compiler=(Record $compiler);linker=(Record $linker);powershell=(Record $powershell);inventories=$toolchainObserved;environment=$toolchainEnvironment};sources=$sourceRecords;route=[ordered]@{discovery='ar.local';selected=$endpoint;logical='ar-local-pi5';user='pi';port=22;key_blob_sha256=$blobHex;fingerprint=$fingerprint};known_hosts_source=(Record $knownHostsSource);known_hosts_alias=(Record $knownHostsAlias);trusted_child=(Record (Join-Path $root 'trusted-child.json'));check_only=(Record (Join-Path $root 'check-only.json'));active_pointer=(Record $pointerPath);activation_gate=(Record $gatePath);dispatcher_manifest=(Record $manifest);launcher_1=(Record $launcher1);launcher_2=(Record $launcher2);launcher_object_1=(Record $launcherObj1);launcher_object_2=(Record $launcherObj2);package_1=(Record $package1);package_2=(Record $package2)}
WriteJson (Join-Path $root 'build-result.json') $build

$taskName='AR-local laptop backup';$task=Get-ScheduledTask -TaskName $taskName;$taskInfo=Get-ScheduledTaskInfo -TaskName $taskName
if($task.State.ToString()-cne'Ready'-or-not$task.Settings.Enabled-or$taskInfo.LastTaskResult-ne1){throw 'task state drift'}
$taskXml=Join-Path $root 'observed-task.xml';[IO.File]::WriteAllBytes($taskXml,(Get-ArTrustedTaskXmlBytes $taskName));RequireHash $taskXml 'aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2'
$sddl=Get-ArTrustedTaskSddl $taskName
if((Get-ArTrustedTextSha256 $sddl)-cne'6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b'-or(Get-ArTrustedSddlSemanticSha256 $sddl)-cne'd0e0ac6dbbbe519444e70161be2a447fa7b6b718a710160e578bd9f4e4bf7965'){throw 'task SDDL drift'}
$active=@(Get-CimInstance Win32_Process|Where-Object{$_.ProcessId-ne$PID-and$_.CommandLine-and$_.CommandLine-match'laptop_backup_(scheduled|dispatcher|trusted_child)|laptop_pull_backup|run_laptop_backup|AR-local-backup-trusted-.*launcher\.exe'})
$residue=@((Join-Path $target 'catalog\.receiver.lock'),(Join-Path $control 'transition.lease'))|Where-Object{Test-Path -LiteralPath $_}
$residue+=@(Get-ChildItem -LiteralPath $target -Recurse -Force|Where-Object{$_.Name-like'*.partial'-or$_.Name-like'.partial-*'-or$_.Name-like'*.partial-*'})
if($active.Count-or$residue.Count-or[long](Get-PSDrive C).Free-lt50GB){throw 'process/residue/free-space gate failed'}
$journal='C:\Program Files\AR-local-backup-evidence-0a444caab7624499bca7ffdbbc56189e152e53e9-dc78b85368c020dcbcbb357b932e56110999f105\20260831T090802Z-5b12a8455b9b4c14b36071bc498eb8eb\mutation-journal.jsonl'
RequireHash $journal '2d3345aee82b2b453d1aaf627b9c9d29146b12d1030f805b53463f782d8e2fb3'
$journalLines=@([IO.File]::ReadAllLines($journal,[Text.UTF8Encoding]::new($false)));if($journalLines.Count-ne2){throw 'D-014 line count drift'}

$remote=@'
set -eu
cd /srv/ar-local/AR-local
test "$(git rev-parse HEAD)" = '9302890fcc752cbf90da97d597e972c157d913e3'
test -z "$(git status --porcelain=v1)"
test "$(systemctl show ar-local-daily.service -p Result --value)" = success
test "$(systemctl show ar-local-daily.service -p ExecMainStatus --value)" = 0
test "$(systemctl is-enabled ar-local-daily.timer)" = enabled
test "$(systemctl is-active ar-local-daily.timer)" = active
test ! -e /srv/ar-local/data/state/daily-ingest.lock
printf '%s  %s\n' bcde983cdab8790fe436d0f977e64cee4ae53ea74701820df2cab9e9d21704f1 /srv/ar-local/data/state/2026-09-02.done.json | sha256sum -c -
printf '%s  %s\n' f2945b67890138827dcd1b74be69ae4e6727b740cd1a5414a2da01e0cea35745 /srv/ar-local/data/state/observation-pointers-v2/latest-observation.json | sha256sum -c -
printf '%s  %s\n' cf98d96b46a18bdb5f128b439555429f7a648516ee9650aafa304ddca55fa425 /srv/ar-local/data/state/ledger-v2/head.json | sha256sum -c -
printf '%s  %s\n' 4f45841840f1b2a256120bd269dd5557f277653d8a7c6667c4cf717564897d25 /srv/ar-local/data/runs/2026-09-02/_exports/ingest-status.json | sha256sum -c -
printf '%s  %s\n' a1f6cd2369e872704530616b3b435fac8a115e13001645eef6b86fffc2454d44 /srv/ar-local/data/state/export-contracts-v2/2026-09-02/obs-2026-09-02-724fc227e6776842.json | sha256sum -c -
printf '%s  %s\n' 9be89c33d89bef07e49c452340f2c2265880d7dd1b035dd6108ce57126d5e7af /srv/ar-local/data/runs/2026-09-02/_exports/local-cdr.sqlite | sha256sum -c -
test "$(curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest | sha256sum | cut -d' ' -f1)" = bbca1b65b96b06aed4702b551a507b7475739dc31c7ec9bbbcbadb7c312180b4
python3 - <<'PY'
import sqlite3
p='/srv/ar-local/data/runs/2026-09-02/_exports/local-cdr.sqlite'
c=sqlite3.connect(f'file:{p}?mode=ro',uri=True);c.execute('pragma query_only=on')
assert c.execute('pragma quick_check').fetchall()==[('ok',)]
PY
echo AR_PI_PREFLIGHT_PASS
'@
$pi=Invoke-ArTrustedSshScript -SshPath $ssh -HostName $endpoint -LogicalHost 'ar-local-pi5' -UserName 'pi' -Port 22 -IdentityPath $identity -KnownHostsPath $knownHostsAlias -Script (($remote-replace"`r",'')+"`n") -TimeoutMilliseconds 120000
if($pi.ExitCode-ne0-or$pi.Stderr-or@($pi.Stdout.TrimEnd()-split"`n")[-1]-cne'AR_PI_PREFLIGHT_PASS'){throw "Pi preflight failed: $($pi.Stderr)"}
WriteUtf8 (Join-Path $root 'pi-preflight.txt') $pi.Stdout

$publication=@(
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/manifest.json',1211L,'367d2fa065511929943fcb3f154a354939474388c116e28b7d4b04f252075f47'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json',2881L,'a97087c046f864d5df6c8aa6205ad7b703a4feaa46e05f47e072ef2853b54236'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/dates-index.json',2116L,'9426f208084a501be82504187a82954fbb2b160ec730adab3fa18f0d6a68c56e'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest-v2.json',1217L,'02e14f71b604dbfd652fef7c1a3c46932ad9b32beef7cc90e99ddc14a1ca4acb'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/core-2026-09-02-d1683a44c258.json.gz',362452L,'d1683a44c258450b2bba233d4b70e95446dad437a023f1bbb0b7dbe6f0a55f11'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/details-2026-09-02-0bd1ae7c5ecd.json.gz',757500L,'0bd1ae7c5ecd556983ccecfb7747ca50cb81651e3bd05571c314a23bc2b41e46'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/core-2026-09-02-d1683a44c258.json.gz',362452L,'d1683a44c258450b2bba233d4b70e95446dad437a023f1bbb0b7dbe6f0a55f11'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/details-2026-09-02-0bd1ae7c5ecd.json.gz',757500L,'0bd1ae7c5ecd556983ccecfb7747ca50cb81651e3bd05571c314a23bc2b41e46'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/search-index-2026-09-02-6db1e8a078cc.json.gz',597950L,'6db1e8a078ccc133839a8fa79488bc8ae7e6d6e84db515729cefe0d5cf4dd12a'))
$web=[Net.Http.HttpClient]::new();$web.Timeout=[TimeSpan]::FromSeconds(20)
try{foreach($pair in $publication){$bytes=$web.GetByteArrayAsync($pair[0]).GetAwaiter().GetResult();$h=[Security.Cryptography.SHA256]::Create();try{$actual=($h.ComputeHash($bytes)|ForEach-Object{$_.ToString('x2')})-join''}finally{$h.Dispose()};if($bytes.Length-ne[long]$pair[1]-or$actual-cne$pair[2]){throw "publication drift: $($pair[0])"}}}finally{$web.Dispose()}
if(((& $git ls-remote $repo refs/heads/main)-split"`t")[0]-cne$authoritySha-or(Sha $handoff)-cne$handoffSha){throw 'authority advanced during preparation'}

$installer=Join-Path $candidate 'install_laptop_backup_trusted_dispatcher.ps1';$core=Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_core.ps1';$sshBoundary=Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_ssh.ps1';$hostPath='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe';$preexec=Join-Path $root 'pre-execution-manifest.json'
$invoke=[ordered]@{task_name=$taskName;package_path=$package1;package_sha256=(Sha $package1);install_root=$installRoot;target=$target;control_root=$control;recovery_image=$recovery;evidence_root=$evidenceRoot;principal=$principal;operator=$operator;operator_sid=$operatorSid;candidate_code_sha=$candidateSha;authority_commit=$authoritySha;protected_code_sha=$protectedSha;plan_git_commit=$planCommit;plan_sha256=$planSha;handoff_sha256=$handoffSha;expected_old_task_xml_sha256='aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2';expected_old_task_sddl_sha256='6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b';expected_old_task_sddl_semantic_sha256='d0e0ac6dbbbe519444e70161be2a447fa7b6b718a710160e578bd9f4e4bf7965';expected_old_task_last_result=1;expected_catalog_sha256='7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511';expected_catalog_size=236234L;expected_catalog_final_sequence=336;expected_catalog_final_entry_sha256='368ed91d6957d60eda5d76f06175e3ff00e20fb5cf5d6d2d94a478d164112420';expected_latest_verified_sha256='737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389';expected_latest_verified_size=316L;expected_accepted_catalog_entry_sha256='6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68';expected_accepted_receipt_relative_path='observations/2026-08-30/f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d/receipt.json';expected_accepted_receipt_sha256='7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea';expected_accepted_receipt_size=3392L;expected_accepted_observation_id='obs-2026-08-30-69a34aa4c745bb2e';expected_accepted_archive_sha256='abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b';expected_accepted_archive_size=237101208L;installer_sha256=(Sha $installer);core_sha256=(Sha $core);ssh_boundary_sha256=(Sha $sshBoundary);pre_execution_manifest_path=$preexec;pre_execution_manifest_sha256='<SELF_SHA256>';pi_host='ar.local';pi_user='pi';pi_port=22;ssh_identity_path=$identity;ssh_identity_sha256=(Sha $identity);ssh_executable_sha256=(Sha $ssh)}
$contract=Get-ArTrustedInvocationContractSha256 $invoke
$fresh=[DateTimeOffset]::UtcNow
if([DateTimeOffset]::Now.AddMinutes(45).DateTime.Date-ne[DateTimeOffset]::Now.Date-or[DateTimeOffset]::Now.AddMinutes(45).TimeOfDay-gt[TimeSpan]::FromHours(22)){throw 'preflight would cross safe stop'}
$pre=[ordered]@{schema_version=1;plan_document_id='ARL-OPS-001';plan_version='1.5';task_name=$taskName;package_path=$package1;package_sha256=(Sha $package1);install_root=$installRoot;target=$target;control_root=$control;recovery_image=$recovery;evidence_root=$evidenceRoot;principal=$principal;operator=$operator;operator_sid=$operatorSid;candidate_code_sha=$candidateSha;authority_commit=$authoritySha;protected_code_sha=$protectedSha;plan_git_commit=$planCommit;plan_sha256=$planSha;handoff_sha256=$handoffSha;expected_old_task_xml_sha256=$invoke.expected_old_task_xml_sha256;expected_old_task_sddl_sha256=$invoke.expected_old_task_sddl_sha256;expected_old_task_sddl_semantic_sha256=$invoke.expected_old_task_sddl_semantic_sha256;expected_old_task_last_result=1;installer_sha256=(Sha $installer);core_sha256=(Sha $core);ssh_boundary_sha256=(Sha $sshBoundary);expected_catalog_sha256=$invoke.expected_catalog_sha256;expected_catalog_size=236234L;expected_catalog_final_sequence=336;expected_catalog_final_entry_sha256=$invoke.expected_catalog_final_entry_sha256;expected_latest_verified_sha256=$invoke.expected_latest_verified_sha256;expected_latest_verified_size=316L;expected_accepted_catalog_entry_sha256=$invoke.expected_accepted_catalog_entry_sha256;expected_accepted_receipt_relative_path=$invoke.expected_accepted_receipt_relative_path;expected_accepted_receipt_sha256=$invoke.expected_accepted_receipt_sha256;expected_accepted_receipt_size=3392L;expected_accepted_observation_id=$invoke.expected_accepted_observation_id;expected_accepted_archive_sha256=$invoke.expected_accepted_archive_sha256;expected_accepted_archive_size=237101208L;invocation_contract_schema=1;invocation_host_path=$hostPath;invocation_script_path=$installer;invocation_contract_sha256=$contract;rollback_procedure='RESTORE_TASK_CONTROL_AND_QUARANTINE_V1';preflight_min_free_bytes=53687091200L;preflight_expected_active_process_count=0;preflight_expected_residue_count=0;preflight_expected_pi_status='AR_PI_PREFLIGHT_PASS';pi_host='ar.local';pi_user='pi';pi_port=22;ssh_identity_path=$identity;ssh_identity_sha256=(Sha $identity);ssh_executable_sha256=(Sha $ssh);created_at=$fresh.ToString('o');expires_at=$fresh.AddMinutes(45).ToString('o')}
WriteJson $preexec $pre

function Quote([string]$Value){"'"+$Value.Replace("'","''")+"'"}
$args=[ordered]@{TaskName=$taskName;PackagePath=$package1;PackageSha256=(Sha $package1);InstallRoot=$installRoot;Target=$target;ControlRoot=$control;RecoveryImage=$recovery;EvidenceRoot=$evidenceRoot;Principal=$principal;Operator=$operator;OperatorSid=$operatorSid;CandidateCodeSha=$candidateSha;AuthorityCommit=$authoritySha;ProtectedCodeSha=$protectedSha;PlanGitCommit=$planCommit;PlanSha256=$planSha;HandoffSha256=$handoffSha;ExpectedOldTaskXmlSha256=$invoke.expected_old_task_xml_sha256;ExpectedOldTaskSddlSha256=$invoke.expected_old_task_sddl_sha256;ExpectedOldTaskSddlSemanticSha256=$invoke.expected_old_task_sddl_semantic_sha256;ExpectedOldTaskLastResult='1';ExpectedCatalogSha256=$invoke.expected_catalog_sha256;ExpectedCatalogSize='236234';ExpectedCatalogFinalSequence='336';ExpectedCatalogFinalEntrySha256=$invoke.expected_catalog_final_entry_sha256;ExpectedLatestVerifiedSha256=$invoke.expected_latest_verified_sha256;ExpectedLatestVerifiedSize='316';ExpectedAcceptedCatalogEntrySha256=$invoke.expected_accepted_catalog_entry_sha256;ExpectedAcceptedReceiptRelativePath=$invoke.expected_accepted_receipt_relative_path;ExpectedAcceptedReceiptSha256=$invoke.expected_accepted_receipt_sha256;ExpectedAcceptedReceiptSize='3392';ExpectedAcceptedObservationId=$invoke.expected_accepted_observation_id;ExpectedAcceptedArchiveSha256=$invoke.expected_accepted_archive_sha256;ExpectedAcceptedArchiveSize='237101208';InstallerSha256=(Sha $installer);CoreSha256=(Sha $core);SshBoundarySha256=(Sha $sshBoundary);PreExecutionManifestPath=$preexec;PreExecutionManifestSha256=(Sha $preexec);SshIdentityPath=$identity;SshIdentitySha256=(Sha $identity);SshExecutableSha256=(Sha $ssh);PiHost='ar.local';PiUser='pi';PiPort='22'}
$inner='$ErrorActionPreference=''Stop'';& '+(Quote $installer);foreach($item in $args.GetEnumerator()){$inner+=' -'+$item.Key+' '+(Quote ([string]$item.Value))}
$encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
[IO.File]::WriteAllText((Join-Path $root 'uac-encoded.txt'),$encoded,[Text.Encoding]::ASCII)
$expected=@('prepare-and-preflight.ps1','materialization.json','candidate','authority','known-hosts-source','known-hosts-alias','dispatcher-manifest.json','trusted-child.json','check-only.json','activation-gate.json','launcher-1.exe','launcher-2.exe','launcher-1.obj','launcher-2.obj','trusted-package-1.zip','trusted-package-2.zip','build-result.json','observed-task.xml','pi-preflight.txt','pre-execution-manifest.json','uac-encoded.txt')
$present=@(Get-ChildItem -LiteralPath $root -Force|ForEach-Object{$_.Name})
if(@($expected|Where-Object{$present-notcontains$_}).Count-or@($present|Where-Object{$expected-notcontains$_}).Count){throw 'generated output set is incomplete or unbound'}
$outputs=[ordered]@{};foreach($name in $expected){$path=Join-Path $root $name;if(Test-Path -LiteralPath $path -PathType Leaf){$outputs[$name]=Record $path}}
$outputs['active-runner.json']=Record $pointerPath
$summary=[ordered]@{schema_version=1;result='PASS';authority_commit=$authoritySha;complete_handoff_sha256=$handoffSha;candidate_code_sha=$candidateSha;protected_code_sha=$protectedSha;plan_commit=$planCommit;plan_sha256=$planSha;endpoint=$endpoint;logical_host='ar-local-pi5';host_key_blob_sha256=$blobHex;host_key_fingerprint=$fingerprint;outputs=$outputs;invocation_contract_sha256=$contract;check_only_execution_record=$check.execution_record;catalog_sha256=$invoke.expected_catalog_sha256;expires_at=$pre.expires_at}
WriteJson (Join-Path $root 'preflight-summary.json') $summary
[Console]::Out.Write($encoded)
```
<!-- END ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T144000 -->


The corrected generator is exactly 37487 UTF-8/LF bytes, 252 lines,
SHA-256 `917f41dd538b3cc56ef031de6f0fb6f68d79dd06027a4939bbb2083e5e7a31b2`.
It assigns and validates the exact evidence root before the initial directory
enumeration. It never invokes a compiler or linker by command lookup.

Its immutable x64 build boundary is:

| Item | Exact binding |
|---|---|
| PowerShell | `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`; SHA-256 `7600ffe12da441fe89d035b13801e8e91d064bc544a27b19a5cf49f6ab8b18f5` |
| Compiler | `C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe`; SHA-256 `88c8344236a27a6e727e0a8edc49aaa2690bdc7a9464b9d18cc7abe70a9f1c0d` |
| Linker | `C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\link.exe`; SHA-256 `ca11e6c45debd34bf652dfe984c5360a531a005ed78bf72852330c9c2590cf0d` |
| VC bin inventory | 91 files; 98923198 bytes; SHA-256 `08a7daf3ce8c103d678ce97b205b01ba11a02b8ff28762488de3ae5039cd8d3b` |
| VC include inventory | 361 files; 16200441 bytes; SHA-256 `abd6e13dfca5e979931dd28369c7634cb7c2c51d1f759f9154a4cc00096bc99e` |
| VC x64 lib inventory | 149 files; 525209873 bytes; SHA-256 `2c5faa81c6d3971c70385a6dcc1c66c3c84d36ec6539f2816b5c1170fbab08dc` |
| SDK 10.0.26100.0 include inventory | 4771 files; 361474762 bytes; SHA-256 `0d9498d38f6fb55cfe34aa43632ee061ac70c9c5edc9b0e9d805d3a7dfa6bb7d` |
| SDK 10.0.26100.0 lib inventory | 1454 files; 804592816 bytes; SHA-256 `24f68321d165143550e01a803fd6e669a8d70f4b5e668a1d43a0702a8dfa4f7f` |
| SDK 10.0.26100.0 x64 bin inventory | 220 files; 73884717 bytes; SHA-256 `aed80b9dc3b039f42178e9456f33c5e2cc60ba87b6c66ed0ab239e1c2a3ee3a3` |

Each canonical inventory is the SHA-256 of compact, key-sorted JSON mapping
every relative POSIX path to its file SHA-256, followed by LF. Missing or
reparse-point roots/nodes fail closed. The generator clears `CL`, `_CL_`,
`LINK` and `_LINK_`; then sets and re-reads exact `PATH`, `INCLUDE`,
`LIB`, `LIBPATH`, `VCToolsInstallDir`, `WindowsSdkDir`,
`WindowsSDKVersion`, `UCRTVersion`, `Platform`,
`VSCMD_ARG_HOST_ARCH`, `VSCMD_ARG_TGT_ARCH`, `TEMP` and `TMP`.
Compiler and linker are invoked only by the absolute paths above through the
pinned Python runtime with closed stdin, captured output and a 300-second hard
timeout. Both object and executable identities must match across the dual build.

After this correction is merged, use only a normal x64 System32 Windows
PowerShell session to paste the following non-administrator materializer. It
extracts this complete terminal block directly; it does not evaluate a prior
materializer and does not build, preflight, elevate, trigger, back up, ingest,
deploy or publish.

```powershell
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012'
$repo='https://github.com/yanniedog/AR-local.git'
$git='C:\Program Files\Git\cmd\git.exe'
$hostPath='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
function ShaBytes([byte[]]$Bytes){$h=[Security.Cryptography.SHA256]::Create();try{($h.ComputeHash($Bytes)|ForEach-Object{$_.ToString('x2')})-join''}finally{$h.Dispose()}}
function ShaFile([string]$Path){ShaBytes ([IO.File]::ReadAllBytes($Path))}
if(-not[Environment]::Is64BitProcess-or[IO.Path]::GetFullPath([Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)-cne$hostPath-or(ShaFile $hostPath)-cne'7600ffe12da441fe89d035b13801e8e91d064bc544a27b19a5cf49f6ab8b18f5'){throw 'normal x64 System32 Windows PowerShell is required'}
if((ShaFile $git)-cne'c470d205517c7a53ceca321df16a6e4549fcd52b576ab4d09536d36f26fda5a9'){throw 'git executable drift'}
$env:GIT_TERMINAL_PROMPT='0'
function ResolveMain {
  $out=(& $git -c credential.interactive=never -c http.lowSpeedLimit=1 -c http.lowSpeedTime=20 ls-remote $repo refs/heads/main 2>&1|Out-String).Trim()
  if($LASTEXITCODE){throw "canonical main lookup failed: $out"}
  $sha=($out-split"\s+")[0].ToLowerInvariant()
  if($sha-notmatch'^[0-9a-f]{40}$'){throw 'canonical main is invalid'}
  $sha
}
$authoritySha=ResolveMain
if($authoritySha-ceq'fd091e817cfc45453ce2c31651c7626b4ecadbd6'){throw 'terminal correction is not merged'}
$client=[Net.Http.HttpClient]::new();$client.Timeout=[TimeSpan]::FromSeconds(20)
try{$handoffBytes=$client.GetByteArrayAsync("https://raw.githubusercontent.com/yanniedog/AR-local/$authoritySha/docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md").GetAwaiter().GetResult()}finally{$client.Dispose()}
$handoffSha=ShaBytes $handoffBytes
$text=[Text.UTF8Encoding]::new($false,$true).GetString($handoffBytes)
if(-not$text.Contains('C-20260902T144000+1000')){throw 'current main lacks terminal toolchain correction'}
$pattern='(?s)<!-- BEGIN ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T144000 -->\r?\n```powershell\r?\n(.*?)\r?\n```\r?\n<!-- END ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T144000 -->'
$match=[regex]::Match($text,$pattern)
if(-not$match.Success){throw 'terminal generator block is absent'}
$script=$match.Groups[1].Value-replace"`r",''
$scriptBytes=[Text.UTF8Encoding]::new($false).GetBytes($script)
$scriptSha=ShaBytes $scriptBytes
if($scriptBytes.Length-ne37487-or($script-split"`n").Count-ne252-or$scriptSha-cne'917f41dd538b3cc56ef031de6f0fb6f68d79dd06027a4939bbb2083e5e7a31b2'){throw 'terminal generator binding mismatch'}
$tokens=$null;$parseErrors=$null
[Management.Automation.Language.Parser]::ParseInput($script,[ref]$tokens,[ref]$parseErrors)|Out-Null
if(@($parseErrors).Count-or$script-match'(?m)&\s+cl\.exe\b'){throw 'terminal generator parser or compiler-path gate failed'}
if((ResolveMain)-cne$authoritySha){throw 'main advanced during validation'}
if(Test-Path -LiteralPath $root){throw 'evidence root is not create-once'}
[void](New-Item -ItemType Directory -Path $root)
function WriteNew([string]$Path,[byte[]]$Bytes){$stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$stream.Write($Bytes,0,$Bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}}
$generatorPath=Join-Path $root 'prepare-and-preflight.ps1'
WriteNew $generatorPath $scriptBytes
$record=[ordered]@{schema_version=1;correction='C-20260902T144000+1000';authority_commit=$authoritySha;complete_handoff_raw_sha256=$handoffSha;quarantined_generator_sha256='19bbfa484945d48dd782e52ce16673b7653de2748feb5aad8109dc15c300a2ae';generator_path=$generatorPath;generator_bytes=37487;generator_lines=252;generator_sha256=$scriptSha;powershell=[ordered]@{path=$hostPath;sha256='7600ffe12da441fe89d035b13801e8e91d064bc544a27b19a5cf49f6ab8b18f5'};compiler=[ordered]@{path='C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe';sha256='88c8344236a27a6e727e0a8edc49aaa2690bdc7a9464b9d18cc7abe70a9f1c0d'};linker=[ordered]@{path='C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\link.exe';sha256='ca11e6c45debd34bf652dfe984c5360a531a005ed78bf72852330c9c2590cf0d'};materialized_at=[DateTimeOffset]::UtcNow.ToString('o')}
$recordBytes=[Text.UTF8Encoding]::new($false).GetBytes((($record|ConvertTo-Json -Compress)+"`n"))
WriteNew (Join-Path $root 'materialization.json') $recordBytes
if((ResolveMain)-cne$authoritySha){throw 'main advanced during materialization; discard evidence root'}
$record|ConvertTo-Json -Compress
```

The ordinary post-materialization entrypoint is exactly 221 UTF-8 bytes with no
trailing LF, SHA-256
`f715cc5d2b5b50bed541174bc91c15c979d3ba3c990c27f18ff398f308065349`:

```powershell
$encoded = & 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -NonInteractive -ExecutionPolicy Bypass -File 'C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012\prepare-and-preflight.ps1'
```

Only its non-empty one-line base64 result plus current, unexpired terminal
`preflight-summary.json` `PASS` permits the single UAC command already
recorded in sequence 3. No new elevation is authorized. Natural backup
acceptance remains mandatory; A3 remains running and A4 remains blocked.

```json
{"schema":"ARL-A3-RESUME-POINTER-V1","version":1,"sequence":6,"predecessor":"C-20260902T143500+1000","authority":"HANDOFF-20260902T133826+1000-A3-PINNED-LAN-FINAL-AUTHORITY","correction":"C-20260902T144000+1000","base_main_sha":"fd091e817cfc45453ce2c31651c7626b4ecadbd6","candidate_sha":"8b158d74ddd51a3523ecb6367b6ef99ca994df61","quarantines":["sequence-5-materializer-ec02a021cc01732d66d7f000cb3fbbb862443931553d99817c210f1969a92dae","generator-19bbfa484945d48dd782e52ce16673b7653de2748feb5aad8109dc15c300a2ae"],"authority_merge_sha":"D012_MATERIALIZATION_RECORD","complete_handoff_raw_sha256":"D012_MATERIALIZATION_RECORD","generator":{"path":"C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012\\prepare-and-preflight.ps1","bytes":37487,"lines":252,"sha256":"917f41dd538b3cc56ef031de6f0fb6f68d79dd06027a4939bbb2083e5e7a31b2"},"toolchain":{"powershell_sha256":"7600ffe12da441fe89d035b13801e8e91d064bc544a27b19a5cf49f6ab8b18f5","compiler_sha256":"88c8344236a27a6e727e0a8edc49aaa2690bdc7a9464b9d18cc7abe70a9f1c0d","linker_sha256":"ca11e6c45debd34bf652dfe984c5360a531a005ed78bf72852330c9c2590cf0d","vc_bin_inventory_sha256":"08a7daf3ce8c103d678ce97b205b01ba11a02b8ff28762488de3ae5039cd8d3b","vc_include_inventory_sha256":"abd6e13dfca5e979931dd28369c7634cb7c2c51d1f759f9154a4cc00096bc99e","vc_lib_inventory_sha256":"2c5faa81c6d3971c70385a6dcc1c66c3c84d36ec6539f2816b5c1170fbab08dc","sdk_include_inventory_sha256":"0d9498d38f6fb55cfe34aa43632ee061ac70c9c5edc9b0e9d805d3a7dfa6bb7d","sdk_lib_inventory_sha256":"24f68321d165143550e01a803fd6e669a8d70f4b5e668a1d43a0702a8dfa4f7f","sdk_bin_inventory_sha256":"aed80b9dc3b039f42178e9456f33c5e2cc60ba87b6c66ed0ab239e1c2a3ee3a3"},"a3":"RUNNING","a4":"BLOCKED_UNTIL_NATURAL_ACCEPTANCE","build_result":"D012_BUILD_RESULT","package_sha256":"D012_PREFLIGHT_SUMMARY","dispatcher_manifest_sha256":"D012_PREFLIGHT_SUMMARY","active_pointer_sha256":"D012_PREFLIGHT_SUMMARY","preexecution_manifest_sha256":"D012_PREFLIGHT_SUMMARY","next_action":"materialize sequence-6 generator; invoke the exact normal non-admin PowerShell entrypoint; require current terminal PASS; then and only then use the sole sequence-3 UAC command","next_command":"$encoded = & 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe' -NoProfile -NonInteractive -ExecutionPolicy Bypass -File 'C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012\\prepare-and-preflight.ps1'","next_command_utf8_sha256":"f715cc5d2b5b50bed541174bc91c15c979d3ba3c990c27f18ff398f308065349","expiry":"fresh preflight 45 minutes; never after 22:00 Australia/Hobart","stop":["main/handoff/generator/materializer/toolchain drift","non-create-once root or unexpected output","resolver/key/auth drift","source/runtime/task/catalog/Pi/evidence/publication drift","timeout/web-auth","process/lock/lease/partial","under 50GiB","D-006 window or expired preflight","launcher object/executable or package mismatch"],"terminal_status":"USABLE_ONLY_AFTER_SEQUENCE6_MATERIALIZER_AND_FRESH_PREFLIGHT_PASS"}
```

The sequence-6 materializer block is exactly 4615 UTF-8/LF bytes, 46 lines,
SHA-256 `7dd1fd5fba125205616e15912cce0c5da836e08ba2ce9316cf81a32295ff4383`.
Its local parser and extraction-equivalence checks passed without executing it.


### Terminal runtime correction `C-20260902T160000+1000` (sequence 7)

Sequence 6 is unusable and is superseded by this append-only correction. The
first Windows PowerShell 5.1 materializer attempt stopped because
`System.Net.Http` was not loaded. A rerun with that assembly preloaded created
the root, then the generator stopped before preflight: the direct native
`python -c` boundary changed its program to forms including `r.rglob(*)`,
`separators=(,:)` and `+\n`; Python exited 1 and the following `.Trim()`
received null. No UAC, task trigger, backup, ingest, deployment, publication or
Pi mutation is authorized from sequence 6.

The stopped root is create-once evidence, not reusable workspace:

| Evidence | Authenticated identity |
|---|---|
| Failed root | `C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012`; 1048 files, 128 directories, 22404909 bytes, 1176 nodes; `ARL-D012-TREE-TSV-V1` SHA-256 `79903ee221ae225490bf0a9280b2adfb6ec6cd07badaf83ef9568573836f4abf` |
| Materialization record | 1210 bytes; SHA-256 `557bff5f40394df7f2e6c319f926bea8d508fac1910ff0003f42e3dc9e3a6c41`; authority `c4a32fb77d4ffa8e545ac16d8a4a22308388d5fe`; handoff `f1706ed815819388dbf0edd0be39e2e774dca8d77c5fc9efac95d66790aa068d` |
| Failed generator | 37487 bytes; SHA-256 `917f41dd538b3cc56ef031de6f0fb6f68d79dd06027a4939bbb2083e5e7a31b2` |
| Source runtime after failure | 3081 files, 207 directories, 64290614 bytes; tree SHA-256 `7f3e77e272acf9601fc10228cea49cf08e051f43ea64f3f444f2fd631f9d0f86`; file-map SHA-256 `8ec5cd13af4c229550c453625d564e6b9e151f5f1ee1634e89481c9fb8b37517` |
| Failure-created runtime residue | exactly 14 `.pyc` files, 172456 bytes, fully path/size/hash-bound in the materializer |
| Reconstructed clean runtime | 3067 files, 205 directories, 64118158 bytes; tree SHA-256 `4edd841372c7463bd53b711b0ba236152fa3ed1ef01f00bad8c7af991b99043c`; file-map SHA-256 `d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7` |

The only allowed recovery is an exact, same-volume move of that authenticated
failed root to
`C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012-QUARANTINED-S6-20260902T054429Z-79903ee221ae`,
followed by creation of a new root. The materializer records the complete
1176-node pre-move inventory, verifies the moved tree unchanged, excludes only
the 14 exact failure-created files, copies every retained file with
`CreateNew`, and re-verifies source and destination. Any mismatch stops.

The replacement generator loads and hash-binds `System.Net.Http`. Every
dynamic Python program is UTF-8 encoded as base64 and passed as an opaque argv
value to one fixed single-quoted bootstrap under `-I -B`; arguments remain
separate argv elements, output is always string-normalized, stdin is closed for
child tools, and every native exit code is explicit.

<!-- BEGIN ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T160000 -->
```powershell
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
$httpProbe=[Net.Http.HttpClient]::new()
$httpAssembly=$httpProbe.GetType().Assembly
$httpClientAssembly=$httpAssembly.FullName
$httpClientAssemblyPath=$httpAssembly.Location
$httpProbe.Dispose()
$httpClientAssemblySha=(Get-FileHash -LiteralPath $httpClientAssemblyPath -Algorithm SHA256).Hash.ToLowerInvariant()
if($httpClientAssembly-cne'System.Net.Http, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a'-or$httpClientAssemblySha-cne'd7ce24424f16bd410179bd202b3e375b2b731a6bd57d5d03a8d38cf9062a14db'){throw 'PS5.1 System.Net.Http binding drift'}

$entry='HANDOFF-20260902T133826+1000-A3-PINNED-LAN-FINAL-AUTHORITY'
$root=[IO.Path]::GetFullPath((Split-Path -Parent $PSCommandPath))
$requiredRoot='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012'
$quarantine='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012-QUARANTINED-S6-20260902T054429Z-79903ee221ae'
if($root-cne$requiredRoot){throw 'generator path is not the authorized evidence root'}
$candidateSha='ac4e0acc563e6ac721cad326c5f54995258ac3c9'
$protectedSha='9302890fcc752cbf90da97d597e972c157d913e3'
$planCommit='9094a8e115958fcaf2cb36525736bd5e297e6b04'
$planSha='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada'
$target='C:\code\backups\AR-local-pi5'
$control=Join-Path $target 'dispatcher-control'
$recovery='C:\code\AR-local-pi-image-2026-05-21\AR-local-pi-image-2026-05-21'
$runtime=Join-Path $root 'runtime'
$python=Join-Path $runtime 'python.exe'
$identity='C:\Users\jkoka\.ssh\pi5'
$git='C:\Program Files\Git\cmd\git.exe'
$ssh='C:\Windows\System32\OpenSSH\ssh.exe'
$scp='C:\Windows\System32\OpenSSH\scp.exe'
$whoami='C:\Windows\System32\whoami.exe'
$operator='jkoka'
$operatorSid='S-1-5-21-689213601-40760280-3596424081-1001'
$principal='yanniedog\jkoka'
$repo='https://github.com/yanniedog/AR-local.git'
$candidate=Join-Path $root 'candidate'
$authority=Join-Path $root 'authority'
$knownHostsSource=Join-Path $root 'known-hosts-source'
$knownHostsAlias=Join-Path $root 'known-hosts-alias'
$manifest=Join-Path $root 'dispatcher-manifest.json'

function Sha([string]$Path){(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function WriteUtf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,($Text-replace "`r",''),[Text.UTF8Encoding]::new($false))}
function WriteJson([string]$Path,[object]$Value){WriteUtf8 $Path (($Value|ConvertTo-Json -Depth 12 -Compress)+"`n")}
function RequireHash([string]$Path,[string]$Expected){if((Sha $Path)-cne$Expected){throw "hash drift: $Path"}}
function TextSha([string]$Text){$h=[Security.Cryptography.SHA256]::Create();try{(($h.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($Text)))|ForEach-Object{$_.ToString('x2')})-join''}finally{$h.Dispose()}}
$pythonBootstrap="import base64,sys;code=base64.b64decode(sys.argv.pop(1));exec(compile(code,'<ARL-D012>','exec'))"
function Invoke-PythonCode([string]$Code,[string[]]$Arguments=@()){$payload=[Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes($Code));$output=@(& $python -I -B -c $pythonBootstrap $payload @Arguments 2>&1);[pscustomobject]@{ExitCode=[int]$LASTEXITCODE;Output=($output|Out-String)}}

$now=[DateTimeOffset]::Now
if($now.TimeOfDay-lt[TimeSpan]::FromHours(3.5)-or$now.TimeOfDay-ge[TimeSpan]::FromHours(22)){throw 'outside D-006 daylight window'}
$root=[IO.Path]::GetFullPath((Split-Path -Parent $PSCommandPath))
$requiredRoot='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012'
if($root-cne$requiredRoot){throw 'generator path is not the authorized evidence root'}
$allowedInitial=@('prepare-and-preflight.ps1','materialization.json','runtime')
$initial=@(Get-ChildItem -LiteralPath $root -Force)
if($initial.Count-ne3-or@($initial|Where-Object{$allowedInitial-notcontains$_.Name}).Count-or-not(Test-Path -LiteralPath (Join-Path $root 'prepare-and-preflight.ps1') -PathType Leaf)-or-not(Test-Path -LiteralPath (Join-Path $root 'materialization.json') -PathType Leaf)-or-not(Test-Path -LiteralPath $runtime -PathType Container)){throw 'evidence root contains prior or unbound output'}
$materializationPath=Join-Path $root 'materialization.json'
$materialization=Get-Content -LiteralPath $materializationPath -Raw|ConvertFrom-Json
if($materialization.schema_version-ne2-or$materialization.correction-cne'C-20260902T160000+1000'-or$materialization.plan_document_id-cne'ARL-OPS-001'-or$materialization.plan_version-cne'1.5'-or$materialization.document_commit-cne$planCommit-or$materialization.plan_git_commit-cne$planCommit-or$materialization.plan_sha256-cne$planSha-or$materialization.plan_raw_sha256-cne'f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684'-or$materialization.candidate_code_sha-cne$candidateSha-or$materialization.protected_code_sha-cne$protectedSha-or$materialization.operator-cne'yanniedog\jkoka'-or$materialization.result-cne'PASS'-or@($materialization.deviations).Count-ne0-or$materialization.exact_commands.Count-ne1-or$materialization.exact_commands[0]-cne'MARKED_ARL_D012_RECOVERY_MATERIALIZER_PS1_C20260902T160000'-or$materialization.evidence_paths.Count-ne3-or$materialization.evidence_paths[0]-cne$quarantine-or$materialization.evidence_paths[1]-cne$runtime-or$materialization.evidence_paths[2]-cne$PSCommandPath-or$materialization.prior_partial_root.quarantine_path-cne$quarantine-or$materialization.prior_partial_root.inventory_sha256-cne'79903ee221ae225490bf0a9280b2adfb6ec6cd07badaf83ef9568573836f4abf'-or$materialization.clean_runtime.tree_inventory_sha256-cne'4edd841372c7463bd53b711b0ba236152fa3ed1ef01f00bad8c7af991b99043c'-or$materialization.clean_runtime.file_map_sha256-cne'd664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7'-or$materialization.http_client.sha256-cne'd7ce24424f16bd410179bd202b3e375b2b731a6bd57d5d03a8d38cf9062a14db'-or(Sha $PSCommandPath)-cne$materialization.generator.sha256){throw 'materialization/quarantine binding drift'}
$materializedStarted=[DateTimeOffset]::Parse($materialization.timestamps.started_at,[Globalization.CultureInfo]::InvariantCulture)
$materializedCompleted=[DateTimeOffset]::Parse($materialization.timestamps.completed_at,[Globalization.CultureInfo]::InvariantCulture)
if($materializedCompleted-lt$materializedStarted){throw 'materialization timestamps are inverted'}
$inventoryCode='from pathlib import Path;import hashlib,json,sys;r=Path(sys.argv[1]);nodes=sorted(r.rglob("*"),key=lambda p:p.relative_to(r).as_posix());bad=(not r.is_dir()) or bool(getattr(r.lstat(),"st_file_attributes",0)&0x400) or any(bool(getattr(p.lstat(),"st_file_attributes",0)&0x400) for p in nodes);bad and (_ for _ in ()).throw(RuntimeError("reparse or missing runtime root"));files=[p for p in nodes if p.is_file()];dirs=[p for p in nodes if p.is_dir()];d={p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files};b=(json.dumps(d,sort_keys=True,separators=(",",":"))+"\n").encode();t=("".join(("D\t"+p.relative_to(r).as_posix()+"\n") if p.is_dir() else ("F\t"+p.relative_to(r).as_posix()+"\t"+str(p.stat().st_size)+"\t"+d[p.relative_to(r).as_posix()]+"\n") for p in nodes)).encode();print(len(files),len(dirs),sum(p.stat().st_size for p in files),hashlib.sha256(b).hexdigest(),hashlib.sha256(t).hexdigest())'
$quarantineRun=Invoke-PythonCode -Code $inventoryCode -Arguments @($quarantine)
$quarantineFields=@($quarantineRun.Output.Trim()-split' ')
if($quarantineRun.ExitCode-ne0-or$quarantineFields.Count-ne5-or$quarantineFields[0]-cne'1048'-or$quarantineFields[1]-cne'128'-or$quarantineFields[2]-cne'22404909'-or$quarantineFields[4]-cne'79903ee221ae225490bf0a9280b2adfb6ec6cd07badaf83ef9568573836f4abf'){throw "quarantined sequence-6 tree drift: $($quarantineRun.Output)"}

$earlyEndpoints=@([Net.Dns]::GetHostAddresses('ar.local')|Where-Object{$_.AddressFamily-eq[Net.Sockets.AddressFamily]::InterNetwork}|ForEach-Object{$_.IPAddressToString}|Select-Object -Unique)
if($earlyEndpoints.Count-ne1){throw 'initial Pi endpoint resolution is not unique'}
$earlyEndpoint=$earlyEndpoints[0]
$earlyKeyLines=@(Get-Content -LiteralPath 'C:\Users\jkoka\.ssh\known_hosts'|Where-Object{($_-split'\s+')[0].Split(',')-contains$earlyEndpoint-and($_-split'\s+')[1]-ceq'ssh-ed25519'})
if($earlyKeyLines.Count-ne1){throw 'initial Pi key source is not unique'}
$earlyBlob=[Convert]::FromBase64String(($earlyKeyLines[0]-split'\s+')[2]);$earlyHash=[Security.Cryptography.SHA256]::Create();try{$earlyKeySha=($earlyHash.ComputeHash($earlyBlob)|ForEach-Object{$_.ToString('x2')})-join''}finally{$earlyHash.Dispose()}
if($earlyKeySha-cne'84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e'){throw 'initial Pi key drift'}
RequireHash $ssh '6250fd52163fe99a0dc49403ed1b4bbef9b764bdb7bada017a93d057d9376a42'
RequireHash $identity 'faf1d747eece5be5315b2172bf6ebff4bdb817eb04b49a35a8e9f2748b16ef1e'
$earlyScript=@'
set -eu
state=$(systemctl is-active ar-local-daily.service 2>/dev/null || true)
case "$state" in inactive|failed) ;; *) exit 41;; esac
test ! -e /srv/ar-local/data/state/daily-ingest.lock
! pgrep -f '[c]dr_daily.py' >/dev/null
'@
$earlyArgs=@('-T','-F','NUL','-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10','-o','UserKnownHostsFile=C:\Users\jkoka\.ssh\known_hosts','-i',$identity,"pi@$earlyEndpoint",'bash','-s','--')
$earlyOutput=($earlyScript|& $ssh @earlyArgs 2>&1|Out-String)
if($LASTEXITCODE-ne0){throw "Pi ingest is active or initial idle proof failed: $earlyOutput"}

$authoritySha=(((& $git ls-remote $repo refs/heads/main)-split"`t")[0]).ToLowerInvariant()
if($materialization.authority_commit-cne$authoritySha-or$materialization.document_commit-cne$planCommit){throw 'materialized authority is stale'}
if($authoritySha-notmatch'^[0-9a-f]{40}$'-or$authoritySha-ceq$candidateSha){throw 'post-merge authority is absent'}
& $git -c core.autocrlf=false clone --quiet --no-checkout $repo $candidate
if($LASTEXITCODE){throw 'candidate clone failed'}
& $git -C $candidate -c core.autocrlf=false checkout --quiet --detach $candidateSha
if($LASTEXITCODE){throw 'candidate checkout failed'}
& $git -c core.autocrlf=false clone --quiet --no-checkout $repo $authority
if($LASTEXITCODE){throw 'authority clone failed'}
& $git -C $authority -c core.autocrlf=false checkout --quiet --detach $authoritySha
if($LASTEXITCODE){throw 'authority checkout failed'}
foreach($pair in @(@($candidate,$candidateSha),@($authority,$authoritySha))){if((& $git -C $pair[0] rev-parse HEAD).Trim()-cne$pair[1]-or(& $git -C $pair[0] status --porcelain=v1)){throw 'checkout identity/cleanliness failed'}}
$handoff=Join-Path $authority 'docs\PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'
if(-not(Select-String -LiteralPath $handoff -SimpleMatch $entry -Quiet)){throw 'authority lacks this entry'}
$handoffSha=Sha $handoff
if($materialization.complete_handoff_raw_sha256-cne$handoffSha){throw 'materialized handoff identity is stale'}

$sources=[ordered]@{
'install_laptop_backup_trusted_dispatcher.ps1'='20f2581e46b2d525c180ff962ddfadd42e852b8d6fff1511b3f0b3c73969b96d'
'install_laptop_backup_trusted_dispatcher_core.ps1'='de958229fe2a8220cae93083e9f1ad0bec031e6b4164d130782f163fc9f49a18'
'install_laptop_backup_trusted_dispatcher_ssh.ps1'='7e387696d22a789f9ede481c48b820f52623e610e96a9f170cb6641b84757625'
'laptop_backup_trusted_package.py'='6c2e722c16bb875ce3c07a4a56ee868001fdfff6973371ec84014594a7b55d43'
'native\laptop_backup_trusted_launcher.cpp'='f31431ddb6ae9e6d7f7db5992dc74872303113761a01462264f50e173e7b7774'
'run_laptop_backup_task.ps1'='50180aa0684b51b9c86bc6cfee8e1a3b54b9ef9c7a6cefb2468767e2bbb0c860'
'run_laptop_backup_trusted_child.ps1'='295271485c79907b7ee87463b53f6cc2258d146e07d771860ae4534b743c772a'
'laptop_backup_dispatcher.py'='36595c9155c0b7514c428ecd1a259b1922d810c498f398da41ea72e5a759b2bc'
'laptop_backup_dispatcher_security.py'='c52229848b75931cb576855db3093830073be48695e97610f5e82ab8e403b36b'
'laptop_backup_atomic.py'='d4874016249e28d74d23e30183356ff15a89eb91a2129f8cd968f7d5a903b93c'
'laptop_backup_scheduled.py'='0fc1b475822ec8ff43b0bd0ce95839f229aa9ca2d85b43dbf02994a27b19126e'
'laptop_backup_transport.py'='59cd046e7fae1eab543bb70dd0aca91bf346d6f1b554407a5eab76b3097ddfc1'
'laptop_pull_backup.py'='952fae2d5e7e6a1952c81c387d9c426bf038f394bf739b43a05c5f2cacaf6a00'
'laptop_backup_ssh_endpoint.py'='4b425d82301c749f3a1f6f2e36a070c169ea8a6e961d8d1ffd52fddbb4347f93'
}
foreach($item in $sources.GetEnumerator()){RequireHash (Join-Path $candidate $item.Key) $item.Value}
RequireHash $python '53e910971cbb20c3223cc44c696254ccfba9595dc4be8e16f56f6c954fff831f'
RequireHash $identity 'faf1d747eece5be5315b2172bf6ebff4bdb817eb04b49a35a8e9f2748b16ef1e'
RequireHash $git 'c470d205517c7a53ceca321df16a6e4549fcd52b576ab4d09536d36f26fda5a9'
RequireHash $ssh '6250fd52163fe99a0dc49403ed1b4bbef9b764bdb7bada017a93d057d9376a42'
RequireHash $scp '63b7118d8e1a8a84398cf4ce1584dc6b146606092fe9c68bbaf110bbdcfb480a'
RequireHash $whoami '23240ef9f8b0a9a324110b1c2331de31dc1b0e08f5359cb707e51a939af56cd3'
$argvProbeCode='import json,sys;print(json.dumps(sys.argv[1:],separators=(",",":")))'
$argvProbeArgs=@('space value','C:\path with space\leaf','star*','comma,:')
$argvProbeExpected='["space value","C:\\path with space\\leaf","star*","comma,:"]'
$argvProbeRun=Invoke-PythonCode -Code $argvProbeCode -Arguments $argvProbeArgs
$argvProbeActual=$argvProbeRun.Output.Trim()
if($argvProbeRun.ExitCode-ne0-or$argvProbeActual-cne$argvProbeExpected){throw "PS5.1 Python argv boundary failed: $($argvProbeRun.Output)"}
$pythonBoundary=[ordered]@{bootstrap_sha256=(TextSha $pythonBootstrap);probe_code_sha256=(TextSha $argvProbeCode);probe_result_sha256=(TextSha $argvProbeActual)}
$inventoryRun=Invoke-PythonCode -Code $inventoryCode -Arguments @($runtime)
$inventory=$inventoryRun.Output.Trim()
if($inventoryRun.ExitCode-ne0-or$inventory-cne'3067 205 64118158 d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7 4edd841372c7463bd53b711b0ba236152fa3ed1ef01f00bad8c7af991b99043c'){throw "runtime inventory drift: $($inventoryRun.Output)"}

. (Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_core.ps1')
. (Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_ssh.ps1')
$endpoint=Resolve-ArTrustedSshEndpoint -PythonPath $python -ModulePath (Join-Path $candidate 'laptop_backup_ssh_endpoint.py') -DiscoveryName 'ar.local' -TimeoutSeconds 10
$keyLines=@(Get-Content -LiteralPath 'C:\Users\jkoka\.ssh\known_hosts'|Where-Object{($_-split'\s+')[0].Split(',')-contains$endpoint-and($_-split'\s+')[1]-ceq'ssh-ed25519'})
if($keyLines.Count-ne1){throw 'pinned key source is not unique'}
$keyFields=$keyLines[0]-split'\s+'
$blob=[Convert]::FromBase64String($keyFields[2]);$hash=[Security.Cryptography.SHA256]::Create();try{$digest=$hash.ComputeHash($blob)}finally{$hash.Dispose()}
$blobHex=($digest|ForEach-Object{$_.ToString('x2')})-join'';$fingerprint='SHA256:'+([Convert]::ToBase64String($digest).TrimEnd('='))
if($blobHex-cne'84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e'-or$fingerprint-cne'SHA256:hFaXQcJhid3wB2tMMn6EuMnfPZxgzGaI9DIZAHip6n4'){throw 'pinned key drift'}
WriteUtf8 $knownHostsSource ("ar.local ssh-ed25519 $($keyFields[2])`n")
WriteUtf8 $knownHostsAlias ("ar-local-pi5 ssh-ed25519 $($keyFields[2])`n")

$catalog=Assert-ArTrustedCatalogBaseline -Target $target -ExpectedCatalogSha256 '7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511' -ExpectedCatalogSize 236234 -ExpectedCatalogFinalSequence 336 -ExpectedCatalogFinalEntrySha256 '368ed91d6957d60eda5d76f06175e3ff00e20fb5cf5d6d2d94a478d164112420' -ExpectedLatestVerifiedSha256 '737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389' -ExpectedLatestVerifiedSize 316 -ExpectedAcceptedCatalogEntrySha256 '6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68' -ExpectedAcceptedReceiptRelativePath 'observations/2026-08-30/f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d/receipt.json' -ExpectedAcceptedReceiptSha256 '7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea' -ExpectedAcceptedReceiptSize 3392 -ExpectedAcceptedObservationId 'obs-2026-08-30-69a34aa4c745bb2e' -ExpectedAcceptedArchiveSha256 'abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b' -ExpectedAcceptedArchiveSize 237101208
$trusted=[ordered]@{schema_version=6;authority_path=$authority;atomic_path=(Join-Path $candidate 'laptop_backup_atomic.py');atomic_sha256=$sources['laptop_backup_atomic.py'];control_root=$control;dispatcher_path=(Join-Path $candidate 'laptop_backup_dispatcher.py');dispatcher_sha256=$sources['laptop_backup_dispatcher.py'];dispatcher_security_path=(Join-Path $candidate 'laptop_backup_dispatcher_security.py');dispatcher_security_sha256=$sources['laptop_backup_dispatcher_security.py'];git_path=$git;git_sha256=(Sha $git);python_path=$python;python_sha256=(Sha $python);receiver_path=$candidate;scp_path=$scp;scp_sha256=(Sha $scp);ssh_discovery_timeout_seconds=10;ssh_endpoint_path=(Join-Path $candidate 'laptop_backup_ssh_endpoint.py');ssh_endpoint_sha256=$sources['laptop_backup_ssh_endpoint.py'];ssh_host='ar.local';ssh_logical_host='ar-local-pi5';ssh_identity_path=$identity;ssh_identity_sha256=(Sha $identity);ssh_known_hosts_path=$knownHostsAlias;ssh_known_hosts_sha256=(Sha $knownHostsAlias);ssh_path=$ssh;ssh_sha256=(Sha $ssh);ssh_port=22;ssh_user='pi';whoami_path=$whoami;whoami_sha256=(Sha $whoami)}
WriteJson (Join-Path $root 'trusted-child.json') $trusted
$checkArgs=@('-B','-s','-E',(Join-Path $candidate 'laptop_backup_scheduled.py'),'--target',$target,'--host',$endpoint,'--ssh-user','pi','--ssh-port','22','--ssh-path',$ssh,'--ssh-sha256',(Sha $ssh),'--scp-path',$scp,'--scp-sha256',(Sha $scp),'--ssh-identity',$identity,'--ssh-known-hosts',$knownHostsAlias,'--recovery-image',$recovery,'--candidate-code-sha',$candidateSha,'--protected-code-sha',$protectedSha,'--plan-git-commit',$planCommit,'--operator',$operator,'--check-only')
$wrapper='import subprocess,sys;r=subprocess.run(sys.argv[1:],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=120);print(r.stdout,end="");print(r.stderr,end="",file=sys.stderr);raise SystemExit(r.returncode)'
$checkRun=Invoke-PythonCode -Code $wrapper -Arguments (@($python)+$checkArgs)
$checkText=$checkRun.Output
if($checkRun.ExitCode-ne0){throw "fresh check-only failed: $checkText"}
$check=$checkText|ConvertFrom-Json
if($check.ok-ne$true-or$check.result-cne'PASS'-or$check.action-cne'NO_BACKUP_DATA_WRITE'){throw 'fresh check-only was not PASS/NO_BACKUP_DATA_WRITE'}
WriteUtf8 (Join-Path $root 'check-only.json') (($check|ConvertTo-Json -Depth 12 -Compress)+"`n")

$pointerPath=Join-Path $control 'active-runner.json'
RequireHash $pointerPath 'fd66311c66aad9a8f16643171fdb3de54f6582361d41ce3255c7da09a086e923'
$prior=Get-Content -LiteralPath $pointerPath -Raw|ConvertFrom-Json
if($prior.sequence-ne1-or$prior.manifest_sha256-cne'af5d7880a114aa8ab0d73d0b13ff68d91625545d3990d6352cf219567e661092'){throw 'dispatcher predecessor drift'}
$activationId=[guid]::NewGuid().ToString('N')
$gate=[ordered]@{schema_version=1;result='PASS';activation_id=$activationId;candidate_code_sha=$candidateSha;protected_code_sha=$protectedSha;plan_git_commit=$planCommit;plan_sha256=$planSha;authority_commit=$authoritySha;handoff_sha256=$handoffSha;operator_sid=$operatorSid;foreground_result='PASS';check_only_result='PASS'}
$gatePath=Join-Path $root 'activation-gate.json';WriteJson $gatePath $gate
$installRoot="C:\Program Files\AR-local-backup-trusted-$candidateSha-$authoritySha"
$evidenceRoot="C:\Program Files\AR-local-backup-evidence-$candidateSha-$authoritySha"

$launcher1=Join-Path $root 'launcher-1.exe';$launcher2=Join-Path $root 'launcher-2.exe';$launcherObj1=Join-Path $root 'launcher-1.obj';$launcherObj2=Join-Path $root 'launcher-2.obj';$source=Join-Path $candidate 'native\laptop_backup_trusted_launcher.cpp'
$vcRoot='C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207'
$toolBin=Join-Path $vcRoot 'bin\Hostx64\x64';$vcInclude=Join-Path $vcRoot 'include';$vcLib=Join-Path $vcRoot 'lib\x64'
$sdkRoot='C:\Program Files (x86)\Windows Kits\10';$sdkVersion='10.0.26100.0';$sdkInclude=Join-Path $sdkRoot "Include\$sdkVersion";$sdkLib=Join-Path $sdkRoot "Lib\$sdkVersion";$sdkBin=Join-Path $sdkRoot "bin\$sdkVersion\x64"
$compiler=Join-Path $toolBin 'cl.exe';$linker=Join-Path $toolBin 'link.exe';$powershell='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
RequireHash $compiler '88c8344236a27a6e727e0a8edc49aaa2690bdc7a9464b9d18cc7abe70a9f1c0d'
RequireHash $linker 'ca11e6c45debd34bf652dfe984c5360a531a005ed78bf72852330c9c2590cf0d'
RequireHash $powershell '7600ffe12da441fe89d035b13801e8e91d064bc544a27b19a5cf49f6ab8b18f5'
$toolchainExpected=@(
[ordered]@{name='vc_bin';path=$toolBin;files=91;bytes=98923198L;inventory_sha256='08a7daf3ce8c103d678ce97b205b01ba11a02b8ff28762488de3ae5039cd8d3b'},
[ordered]@{name='vc_include';path=$vcInclude;files=361;bytes=16200441L;inventory_sha256='abd6e13dfca5e979931dd28369c7634cb7c2c51d1f759f9154a4cc00096bc99e'},
[ordered]@{name='vc_lib';path=$vcLib;files=149;bytes=525209873L;inventory_sha256='2c5faa81c6d3971c70385a6dcc1c66c3c84d36ec6539f2816b5c1170fbab08dc'},
[ordered]@{name='sdk_include';path=$sdkInclude;files=4771;bytes=361474762L;inventory_sha256='0d9498d38f6fb55cfe34aa43632ee061ac70c9c5edc9b0e9d805d3a7dfa6bb7d'},
[ordered]@{name='sdk_lib';path=$sdkLib;files=1454;bytes=804592816L;inventory_sha256='24f68321d165143550e01a803fd6e669a8d70f4b5e668a1d43a0702a8dfa4f7f'},
[ordered]@{name='sdk_bin';path=$sdkBin;files=220;bytes=73884717L;inventory_sha256='aed80b9dc3b039f42178e9456f33c5e2cc60ba87b6c66ed0ab239e1c2a3ee3a3'})
$toolInventoryCode='from pathlib import Path;import hashlib,json,sys;r=Path(sys.argv[1]);nodes=sorted(r.rglob("*"));bad=(not r.is_dir()) or bool(getattr(r.lstat(),"st_file_attributes",0)&0x400) or any(bool(getattr(p.lstat(),"st_file_attributes",0)&0x400) for p in nodes);bad and (_ for _ in ()).throw(RuntimeError("reparse or missing toolchain root"));files=[p for p in nodes if p.is_file()];d={p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files};b=(json.dumps(d,sort_keys=True,separators=(",",":"))+"\n").encode();print(json.dumps({"path":str(r),"files":len(files),"bytes":sum(p.stat().st_size for p in files),"inventory_sha256":hashlib.sha256(b).hexdigest()},separators=(",",":")))'
$toolchainObserved=[ordered]@{}
foreach($expected in $toolchainExpected){$toolInventoryRun=Invoke-PythonCode -Code $toolInventoryCode -Arguments @($expected.path);$raw=$toolInventoryRun.Output.Trim();if($toolInventoryRun.ExitCode-ne0){throw "toolchain inventory failed: $($expected.name): $($toolInventoryRun.Output)"};$actual=$raw|ConvertFrom-Json;if($actual.path-cne$expected.path-or[long]$actual.files-ne[long]$expected.files-or[long]$actual.bytes-ne[long]$expected.bytes-or$actual.inventory_sha256-cne$expected.inventory_sha256){throw "toolchain inventory drift: $($expected.name)"};$toolchainObserved[$expected.name]=[ordered]@{path=$actual.path;files=[long]$actual.files;bytes=[long]$actual.bytes;inventory_sha256=$actual.inventory_sha256}}
if(-not[Environment]::Is64BitProcess){throw 'x64 PowerShell is required'}
$toolchainEnvironment=[ordered]@{Path=([string]::Join(';',@($toolBin,$sdkBin,'C:\Windows\System32','C:\Windows')));INCLUDE=([string]::Join(';',@($vcInclude,(Join-Path $sdkInclude 'ucrt'),(Join-Path $sdkInclude 'shared'),(Join-Path $sdkInclude 'um'),(Join-Path $sdkInclude 'winrt'),(Join-Path $sdkInclude 'cppwinrt'))));LIB=([string]::Join(';',@($vcLib,(Join-Path $sdkLib 'ucrt\x64'),(Join-Path $sdkLib 'um\x64'))));LIBPATH=([string]::Join(';',@($vcLib,(Join-Path $sdkLib 'ucrt\x64'),(Join-Path $sdkLib 'um\x64'))));VCToolsInstallDir=($vcRoot+'\');WindowsSdkDir=($sdkRoot+'\');WindowsSDKVersion=($sdkVersion+'\');UCRTVersion=$sdkVersion;Platform='x64';VSCMD_ARG_HOST_ARCH='x64';VSCMD_ARG_TGT_ARCH='x64';TEMP=$root;TMP=$root}
foreach($name in @('CL','_CL_','LINK','_LINK_')){[Environment]::SetEnvironmentVariable($name,$null,'Process')}
foreach($item in $toolchainEnvironment.GetEnumerator()){[Environment]::SetEnvironmentVariable($item.Key,[string]$item.Value,'Process')}
if(@($toolchainEnvironment.GetEnumerator()|Where-Object{[Environment]::GetEnvironmentVariable($_.Key,'Process')-cne[string]$_.Value}).Count){throw 'toolchain environment failed to bind'}
$toolWrapper='import subprocess,sys;r=subprocess.run(sys.argv[1:],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=300);print(r.stdout,end="");print(r.stderr,end="",file=sys.stderr);raise SystemExit(r.returncode)'
Push-Location $root
try{
$compileArgs=@('/nologo','/std:c++17','/O2','/MT','/W4','/WX','/EHsc','/GS','/guard:cf','/Brepro','/DUNICODE','/D_UNICODE','/c',$source,"/Fo$launcherObj1")
$toolRun=Invoke-PythonCode -Code $toolWrapper -Arguments (@($compiler)+$compileArgs);$toolText=$toolRun.Output;if($toolRun.ExitCode-ne0){throw "launcher compile 1 failed: $toolText"}
$linkArgs=@('/nologo',"/OUT:$launcher1",'/MACHINE:X64','/SUBSYSTEM:CONSOLE','/DYNAMICBASE','/NXCOMPAT','/guard:cf','/Brepro',$launcherObj1,'advapi32.lib')
$toolRun=Invoke-PythonCode -Code $toolWrapper -Arguments (@($linker)+$linkArgs);$toolText=$toolRun.Output;if($toolRun.ExitCode-ne0){throw "launcher link 1 failed: $toolText"}
if(-not(Test-Path -LiteralPath $launcherObj1 -PathType Leaf)-or-not(Test-Path -LiteralPath $launcher1 -PathType Leaf)){throw 'launcher build 1 output missing'}
$compileArgs=@('/nologo','/std:c++17','/O2','/MT','/W4','/WX','/EHsc','/GS','/guard:cf','/Brepro','/DUNICODE','/D_UNICODE','/c',$source,"/Fo$launcherObj2")
$toolRun=Invoke-PythonCode -Code $toolWrapper -Arguments (@($compiler)+$compileArgs);$toolText=$toolRun.Output;if($toolRun.ExitCode-ne0){throw "launcher compile 2 failed: $toolText"}
$linkArgs=@('/nologo',"/OUT:$launcher2",'/MACHINE:X64','/SUBSYSTEM:CONSOLE','/DYNAMICBASE','/NXCOMPAT','/guard:cf','/Brepro',$launcherObj2,'advapi32.lib')
$toolRun=Invoke-PythonCode -Code $toolWrapper -Arguments (@($linker)+$linkArgs);$toolText=$toolRun.Output;if($toolRun.ExitCode-ne0){throw "launcher link 2 failed: $toolText"}
if(-not(Test-Path -LiteralPath $launcherObj2 -PathType Leaf)-or-not(Test-Path -LiteralPath $launcher2 -PathType Leaf)){throw 'launcher build 2 output missing'}
}finally{Pop-Location}
if((Sha $launcherObj1)-cne(Sha $launcherObj2)-or(Sha $launcher1)-cne(Sha $launcher2)){throw 'launcher object or executable builds differ'}
$taskName='AR-local laptop backup';$task=Get-ScheduledTask -TaskName $taskName;$taskInfo=Get-ScheduledTaskInfo -TaskName $taskName
if($task.State.ToString()-cne'Ready'-or-not$task.Settings.Enabled-or$taskInfo.LastTaskResult-ne1){throw 'task state drift'}
$taskXml=Join-Path $root 'observed-task.xml';[IO.File]::WriteAllBytes($taskXml,(Get-ArTrustedTaskXmlBytes $taskName));RequireHash $taskXml 'aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2'
$sddl=Get-ArTrustedTaskSddl $taskName
if((Get-ArTrustedTextSha256 $sddl)-cne'6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b'-or(Get-ArTrustedSddlSemanticSha256 $sddl)-cne'd0e0ac6dbbbe519444e70161be2a447fa7b6b718a710160e578bd9f4e4bf7965'){throw 'task SDDL drift'}
$active=@(Get-CimInstance Win32_Process|Where-Object{$_.ProcessId-ne$PID-and$_.CommandLine-and$_.CommandLine-match'laptop_backup_(scheduled|dispatcher|trusted_child)|laptop_pull_backup|run_laptop_backup|AR-local-backup-trusted-.*launcher\.exe'})
$residue=@((Join-Path $target 'catalog\.receiver.lock'),(Join-Path $control 'transition.lease'))|Where-Object{Test-Path -LiteralPath $_}
$residue+=@(Get-ChildItem -LiteralPath $target -Recurse -Force|Where-Object{$_.Name-like'*.partial'-or$_.Name-like'.partial-*'-or$_.Name-like'*.partial-*'})
if($active.Count-or$residue.Count-or[long](Get-PSDrive C).Free-lt50GB){throw 'process/residue/free-space gate failed'}
$journal='C:\Program Files\AR-local-backup-evidence-0a444caab7624499bca7ffdbbc56189e152e53e9-dc78b85368c020dcbcbb357b932e56110999f105\20260831T090802Z-5b12a8455b9b4c14b36071bc498eb8eb\mutation-journal.jsonl'
RequireHash $journal '2d3345aee82b2b453d1aaf627b9c9d29146b12d1030f805b53463f782d8e2fb3'
$journalLines=@([IO.File]::ReadAllLines($journal,[Text.UTF8Encoding]::new($false)));if($journalLines.Count-ne2){throw 'D-014 line count drift'}

$remote=@'
set -eu
cd /srv/ar-local/AR-local
test "$(git rev-parse HEAD)" = '9302890fcc752cbf90da97d597e972c157d913e3'
test -z "$(git status --porcelain=v1)"
test "$(systemctl show ar-local-daily.service -p Result --value)" = success
test "$(systemctl show ar-local-daily.service -p ExecMainStatus --value)" = 0
test "$(systemctl is-enabled ar-local-daily.timer)" = enabled
test "$(systemctl is-active ar-local-daily.timer)" = active
test ! -e /srv/ar-local/data/state/daily-ingest.lock
printf '%s  %s\n' bcde983cdab8790fe436d0f977e64cee4ae53ea74701820df2cab9e9d21704f1 /srv/ar-local/data/state/2026-09-02.done.json | sha256sum -c -
printf '%s  %s\n' f2945b67890138827dcd1b74be69ae4e6727b740cd1a5414a2da01e0cea35745 /srv/ar-local/data/state/observation-pointers-v2/latest-observation.json | sha256sum -c -
printf '%s  %s\n' cf98d96b46a18bdb5f128b439555429f7a648516ee9650aafa304ddca55fa425 /srv/ar-local/data/state/ledger-v2/head.json | sha256sum -c -
printf '%s  %s\n' 4f45841840f1b2a256120bd269dd5557f277653d8a7c6667c4cf717564897d25 /srv/ar-local/data/runs/2026-09-02/_exports/ingest-status.json | sha256sum -c -
printf '%s  %s\n' a1f6cd2369e872704530616b3b435fac8a115e13001645eef6b86fffc2454d44 /srv/ar-local/data/state/export-contracts-v2/2026-09-02/obs-2026-09-02-724fc227e6776842.json | sha256sum -c -
printf '%s  %s\n' 9be89c33d89bef07e49c452340f2c2265880d7dd1b035dd6108ce57126d5e7af /srv/ar-local/data/runs/2026-09-02/_exports/local-cdr.sqlite | sha256sum -c -
test "$(curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest | sha256sum | cut -d' ' -f1)" = bbca1b65b96b06aed4702b551a507b7475739dc31c7ec9bbbcbadb7c312180b4
python3 - <<'PY'
import sqlite3
p='/srv/ar-local/data/runs/2026-09-02/_exports/local-cdr.sqlite'
c=sqlite3.connect(f'file:{p}?mode=ro',uri=True);c.execute('pragma query_only=on')
assert c.execute('pragma quick_check').fetchall()==[('ok',)]
PY
echo AR_PI_PREFLIGHT_PASS
'@
$pi=Invoke-ArTrustedSshScript -SshPath $ssh -HostName $endpoint -LogicalHost 'ar-local-pi5' -UserName 'pi' -Port 22 -IdentityPath $identity -KnownHostsPath $knownHostsAlias -Script (($remote-replace"`r",'')+"`n") -TimeoutMilliseconds 120000
if($pi.ExitCode-ne0-or$pi.Stderr-or@($pi.Stdout.TrimEnd()-split"`n")[-1]-cne'AR_PI_PREFLIGHT_PASS'){throw "Pi preflight failed: $($pi.Stderr)"}
WriteUtf8 (Join-Path $root 'pi-preflight.txt') $pi.Stdout

$publication=@(
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/manifest.json',1211L,'367d2fa065511929943fcb3f154a354939474388c116e28b7d4b04f252075f47'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json',2881L,'a97087c046f864d5df6c8aa6205ad7b703a4feaa46e05f47e072ef2853b54236'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/dates-index.json',2116L,'9426f208084a501be82504187a82954fbb2b160ec730adab3fa18f0d6a68c56e'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest-v2.json',1217L,'02e14f71b604dbfd652fef7c1a3c46932ad9b32beef7cc90e99ddc14a1ca4acb'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/core-2026-09-02-d1683a44c258.json.gz',362452L,'d1683a44c258450b2bba233d4b70e95446dad437a023f1bbb0b7dbe6f0a55f11'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-2026-09-02/details-2026-09-02-0bd1ae7c5ecd.json.gz',757500L,'0bd1ae7c5ecd556983ccecfb7747ca50cb81651e3bd05571c314a23bc2b41e46'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/core-2026-09-02-d1683a44c258.json.gz',362452L,'d1683a44c258450b2bba233d4b70e95446dad437a023f1bbb0b7dbe6f0a55f11'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/details-2026-09-02-0bd1ae7c5ecd.json.gz',757500L,'0bd1ae7c5ecd556983ccecfb7747ca50cb81651e3bd05571c314a23bc2b41e46'),
@('https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/search-index-2026-09-02-6db1e8a078cc.json.gz',597950L,'6db1e8a078ccc133839a8fa79488bc8ae7e6d6e84db515729cefe0d5cf4dd12a'))
$web=[Net.Http.HttpClient]::new();$web.Timeout=[TimeSpan]::FromSeconds(20)
try{foreach($pair in $publication){$bytes=$web.GetByteArrayAsync($pair[0]).GetAwaiter().GetResult();$h=[Security.Cryptography.SHA256]::Create();try{$actual=($h.ComputeHash($bytes)|ForEach-Object{$_.ToString('x2')})-join''}finally{$h.Dispose()};if($bytes.Length-ne[long]$pair[1]-or$actual-cne$pair[2]){throw "publication drift: $($pair[0])"}}}finally{$web.Dispose()}
if(((& $git ls-remote $repo refs/heads/main)-split"`t")[0]-cne$authoritySha-or(Sha $handoff)-cne$handoffSha){throw 'authority advanced during preparation'}

$created=[DateTimeOffset]::UtcNow
$dispatcher=[ordered]@{schema_version=1;sequence=2;activation_id=$activationId;created_at=$created.ToString('o').Replace('+00:00','Z');activation_expires_at=$created.AddMinutes(45).ToString('o').Replace('+00:00','Z');previous_manifest_sha256=$prior.manifest_sha256;plan_document_id='ARL-OPS-001';plan_version='1.5';plan_git_commit=$planCommit;plan_sha256=$planSha;authority_commit=$authoritySha;handoff_sha256=$handoffSha;authority_repo=(Join-Path $installRoot 'authority');authority_handoff_path='docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md';candidate_code_sha=$candidateSha;protected_code_sha=$protectedSha;operator=$operator;operator_sid=$operatorSid;receiver=(Join-Path $installRoot 'receiver');allowed_receiver_root=$installRoot;entrypoint='run_laptop_backup_task.ps1';entrypoint_sha256=$sources['run_laptop_backup_task.ps1'];python_path=(Join-Path $installRoot 'python\python.exe');python_sha256=(Sha $python);scheduled_plan_git_commit=$planCommit;target=$target;allowed_target_root=$target;recovery_image=$recovery;allowed_recovery_root=[IO.Path]::GetDirectoryName($recovery);gate_evidence_path=$gatePath;gate_evidence_sha256=(Sha $gatePath)}
WriteJson $manifest $dispatcher
$package1=Join-Path $root 'trusted-package-1.zip';$package2=Join-Path $root 'trusted-package-2.zip'
$packageArgs=@('--candidate-repo',$candidate,'--candidate-sha',$candidateSha,'--authority-repo',$authority,'--authority-sha',$authoritySha,'--python-root',$runtime,'--launcher',$launcher1,'--dispatcher-manifest',$manifest,'--install-root',$installRoot,'--control-root',$control,'--operator-sid',$operatorSid,'--git',$git,'--ssh',$ssh,'--scp',$scp,'--ssh-host','ar.local','--ssh-user','pi','--ssh-port','22','--ssh-identity',$identity,'--ssh-known-hosts',$knownHostsSource,'--whoami',$whoami)
& $python -I -B (Join-Path $candidate 'laptop_backup_trusted_package.py') @packageArgs --output $package1|Out-Null
if($LASTEXITCODE){throw 'package build 1 failed'}
& $python -I -B (Join-Path $candidate 'laptop_backup_trusted_package.py') @packageArgs --output $package2|Out-Null
if($LASTEXITCODE){throw 'package build 2 failed'}
if((Sha $package1)-cne(Sha $package2)){throw 'package builds differ'}
if($created.AddMinutes(45)-lt[DateTimeOffset]::UtcNow.AddMinutes(30)){throw 'dispatcher activation window has less than 30 minutes remaining'}

function Record([string]$Path){[ordered]@{path=[IO.Path]::GetFullPath($Path);bytes=[long](Get-Item -LiteralPath $Path).Length;sha256=(Sha $Path)}}
$sourceRecords=[ordered]@{};foreach($item in $sources.GetEnumerator()){$path=Join-Path $candidate $item.Key;$sourceRecords[$item.Key]=Record $path}
$build=[ordered]@{schema_version=1;authority_commit=$authoritySha;candidate_commit=$candidateSha;protected_commit=$protectedSha;complete_handoff=(Record $handoff);plan=[ordered]@{commit=$planCommit;sha256=$planSha};runtime=[ordered]@{path=$runtime;files=3067;directories=205;bytes=64118158L;inventory_sha256='d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7';tree_inventory_sha256='4edd841372c7463bd53b711b0ba236152fa3ed1ef01f00bad8c7af991b99043c';python=(Record $python);python_boundary=$pythonBoundary;http_client=[ordered]@{assembly=$httpClientAssembly;path=$httpClientAssemblyPath;sha256=$httpClientAssemblySha}};materialization=(Record $materializationPath);tools=[ordered]@{git=(Record $git);ssh=(Record $ssh);scp=(Record $scp);whoami=(Record $whoami);identity=(Record $identity)};toolchain=[ordered]@{compiler=(Record $compiler);linker=(Record $linker);powershell=(Record $powershell);inventories=$toolchainObserved;environment=$toolchainEnvironment};sources=$sourceRecords;route=[ordered]@{discovery='ar.local';selected=$endpoint;logical='ar-local-pi5';user='pi';port=22;key_blob_sha256=$blobHex;fingerprint=$fingerprint};known_hosts_source=(Record $knownHostsSource);known_hosts_alias=(Record $knownHostsAlias);trusted_child=(Record (Join-Path $root 'trusted-child.json'));check_only=(Record (Join-Path $root 'check-only.json'));active_pointer=(Record $pointerPath);activation_gate=(Record $gatePath);dispatcher_manifest=(Record $manifest);launcher_1=(Record $launcher1);launcher_2=(Record $launcher2);launcher_object_1=(Record $launcherObj1);launcher_object_2=(Record $launcherObj2);package_1=(Record $package1);package_2=(Record $package2)}
WriteJson (Join-Path $root 'build-result.json') $build

$installer=Join-Path $candidate 'install_laptop_backup_trusted_dispatcher.ps1';$core=Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_core.ps1';$sshBoundary=Join-Path $candidate 'install_laptop_backup_trusted_dispatcher_ssh.ps1';$hostPath='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe';$preexec=Join-Path $root 'pre-execution-manifest.json'
$invoke=[ordered]@{task_name=$taskName;package_path=$package1;package_sha256=(Sha $package1);install_root=$installRoot;target=$target;control_root=$control;recovery_image=$recovery;evidence_root=$evidenceRoot;principal=$principal;operator=$operator;operator_sid=$operatorSid;candidate_code_sha=$candidateSha;authority_commit=$authoritySha;protected_code_sha=$protectedSha;plan_git_commit=$planCommit;plan_sha256=$planSha;handoff_sha256=$handoffSha;expected_old_task_xml_sha256='aa539fb4bb2f1768b2ea57539e7d5201a930e88eecf9192f4f94518b08e9d9e2';expected_old_task_sddl_sha256='6d56e1b8b4e14f3354aee7644012e0084fd64dd6a58468fe87c181560e19eb7b';expected_old_task_sddl_semantic_sha256='d0e0ac6dbbbe519444e70161be2a447fa7b6b718a710160e578bd9f4e4bf7965';expected_old_task_last_result=1;expected_catalog_sha256='7c498eb639a5f90595f4252767507599f2fd65e8655d82b4b55df347d981f511';expected_catalog_size=236234L;expected_catalog_final_sequence=336;expected_catalog_final_entry_sha256='368ed91d6957d60eda5d76f06175e3ff00e20fb5cf5d6d2d94a478d164112420';expected_latest_verified_sha256='737890501caf8c2054b1f0b30fd17bba077327a4469bd14f1d176bee75e9a389';expected_latest_verified_size=316L;expected_accepted_catalog_entry_sha256='6f9cd2729a8e2c5278b5dd46801ab7deac699de7ddc6dd070e4b0b4228a34d68';expected_accepted_receipt_relative_path='observations/2026-08-30/f37721927e2f3f1272986fe0b8f1c454e29c42d854a301cb7460e6516aef118d/receipt.json';expected_accepted_receipt_sha256='7c50fc6f1dbf8b333cdb9b725d0a5190e9418454fcb1260a79754eab0dbad1ea';expected_accepted_receipt_size=3392L;expected_accepted_observation_id='obs-2026-08-30-69a34aa4c745bb2e';expected_accepted_archive_sha256='abd6bd284ae9dc35b367b463c9e6c885866aba27fb1c385e914d4ba7aa68991b';expected_accepted_archive_size=237101208L;installer_sha256=(Sha $installer);core_sha256=(Sha $core);ssh_boundary_sha256=(Sha $sshBoundary);pre_execution_manifest_path=$preexec;pre_execution_manifest_sha256='<SELF_SHA256>';pi_host='ar.local';pi_user='pi';pi_port=22;ssh_identity_path=$identity;ssh_identity_sha256=(Sha $identity);ssh_executable_sha256=(Sha $ssh)}
$contract=Get-ArTrustedInvocationContractSha256 $invoke
$fresh=[DateTimeOffset]::UtcNow
if([DateTimeOffset]::Now.AddMinutes(45).DateTime.Date-ne[DateTimeOffset]::Now.Date-or[DateTimeOffset]::Now.AddMinutes(45).TimeOfDay-gt[TimeSpan]::FromHours(22)){throw 'preflight would cross safe stop'}
$pre=[ordered]@{schema_version=1;plan_document_id='ARL-OPS-001';plan_version='1.5';task_name=$taskName;package_path=$package1;package_sha256=(Sha $package1);install_root=$installRoot;target=$target;control_root=$control;recovery_image=$recovery;evidence_root=$evidenceRoot;principal=$principal;operator=$operator;operator_sid=$operatorSid;candidate_code_sha=$candidateSha;authority_commit=$authoritySha;protected_code_sha=$protectedSha;plan_git_commit=$planCommit;plan_sha256=$planSha;handoff_sha256=$handoffSha;expected_old_task_xml_sha256=$invoke.expected_old_task_xml_sha256;expected_old_task_sddl_sha256=$invoke.expected_old_task_sddl_sha256;expected_old_task_sddl_semantic_sha256=$invoke.expected_old_task_sddl_semantic_sha256;expected_old_task_last_result=1;installer_sha256=(Sha $installer);core_sha256=(Sha $core);ssh_boundary_sha256=(Sha $sshBoundary);expected_catalog_sha256=$invoke.expected_catalog_sha256;expected_catalog_size=236234L;expected_catalog_final_sequence=336;expected_catalog_final_entry_sha256=$invoke.expected_catalog_final_entry_sha256;expected_latest_verified_sha256=$invoke.expected_latest_verified_sha256;expected_latest_verified_size=316L;expected_accepted_catalog_entry_sha256=$invoke.expected_accepted_catalog_entry_sha256;expected_accepted_receipt_relative_path=$invoke.expected_accepted_receipt_relative_path;expected_accepted_receipt_sha256=$invoke.expected_accepted_receipt_sha256;expected_accepted_receipt_size=3392L;expected_accepted_observation_id=$invoke.expected_accepted_observation_id;expected_accepted_archive_sha256=$invoke.expected_accepted_archive_sha256;expected_accepted_archive_size=237101208L;invocation_contract_schema=1;invocation_host_path=$hostPath;invocation_script_path=$installer;invocation_contract_sha256=$contract;rollback_procedure='RESTORE_TASK_CONTROL_AND_QUARANTINE_V1';preflight_min_free_bytes=53687091200L;preflight_expected_active_process_count=0;preflight_expected_residue_count=0;preflight_expected_pi_status='AR_PI_PREFLIGHT_PASS';pi_host='ar.local';pi_user='pi';pi_port=22;ssh_identity_path=$identity;ssh_identity_sha256=(Sha $identity);ssh_executable_sha256=(Sha $ssh);created_at=$fresh.ToString('o');expires_at=$fresh.AddMinutes(45).ToString('o')}
WriteJson $preexec $pre

function Quote([string]$Value){"'"+$Value.Replace("'","''")+"'"}
$args=[ordered]@{TaskName=$taskName;PackagePath=$package1;PackageSha256=(Sha $package1);InstallRoot=$installRoot;Target=$target;ControlRoot=$control;RecoveryImage=$recovery;EvidenceRoot=$evidenceRoot;Principal=$principal;Operator=$operator;OperatorSid=$operatorSid;CandidateCodeSha=$candidateSha;AuthorityCommit=$authoritySha;ProtectedCodeSha=$protectedSha;PlanGitCommit=$planCommit;PlanSha256=$planSha;HandoffSha256=$handoffSha;ExpectedOldTaskXmlSha256=$invoke.expected_old_task_xml_sha256;ExpectedOldTaskSddlSha256=$invoke.expected_old_task_sddl_sha256;ExpectedOldTaskSddlSemanticSha256=$invoke.expected_old_task_sddl_semantic_sha256;ExpectedOldTaskLastResult='1';ExpectedCatalogSha256=$invoke.expected_catalog_sha256;ExpectedCatalogSize='236234';ExpectedCatalogFinalSequence='336';ExpectedCatalogFinalEntrySha256=$invoke.expected_catalog_final_entry_sha256;ExpectedLatestVerifiedSha256=$invoke.expected_latest_verified_sha256;ExpectedLatestVerifiedSize='316';ExpectedAcceptedCatalogEntrySha256=$invoke.expected_accepted_catalog_entry_sha256;ExpectedAcceptedReceiptRelativePath=$invoke.expected_accepted_receipt_relative_path;ExpectedAcceptedReceiptSha256=$invoke.expected_accepted_receipt_sha256;ExpectedAcceptedReceiptSize='3392';ExpectedAcceptedObservationId=$invoke.expected_accepted_observation_id;ExpectedAcceptedArchiveSha256=$invoke.expected_accepted_archive_sha256;ExpectedAcceptedArchiveSize='237101208';InstallerSha256=(Sha $installer);CoreSha256=(Sha $core);SshBoundarySha256=(Sha $sshBoundary);PreExecutionManifestPath=$preexec;PreExecutionManifestSha256=(Sha $preexec);SshIdentityPath=$identity;SshIdentitySha256=(Sha $identity);SshExecutableSha256=(Sha $ssh);PiHost='ar.local';PiUser='pi';PiPort='22'}
$inner='$ErrorActionPreference=''Stop'';& '+(Quote $installer);foreach($item in $args.GetEnumerator()){$inner+=' -'+$item.Key+' '+(Quote ([string]$item.Value))}
$encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
[IO.File]::WriteAllText((Join-Path $root 'uac-encoded.txt'),$encoded,[Text.Encoding]::ASCII)
$expected=@('prepare-and-preflight.ps1','materialization.json','runtime','candidate','authority','known-hosts-source','known-hosts-alias','dispatcher-manifest.json','trusted-child.json','check-only.json','activation-gate.json','launcher-1.exe','launcher-2.exe','launcher-1.obj','launcher-2.obj','trusted-package-1.zip','trusted-package-2.zip','build-result.json','observed-task.xml','pi-preflight.txt','pre-execution-manifest.json','uac-encoded.txt')
$present=@(Get-ChildItem -LiteralPath $root -Force|ForEach-Object{$_.Name})
if(@($expected|Where-Object{$present-notcontains$_}).Count-or@($present|Where-Object{$expected-notcontains$_}).Count){throw 'generated output set is incomplete or unbound'}
$outputs=[ordered]@{};foreach($name in $expected){$path=Join-Path $root $name;if(Test-Path -LiteralPath $path -PathType Leaf){$outputs[$name]=Record $path}}
$outputs['active-runner.json']=Record $pointerPath
$summary=[ordered]@{schema_version=1;result='PASS';authority_commit=$authoritySha;complete_handoff_sha256=$handoffSha;candidate_code_sha=$candidateSha;protected_code_sha=$protectedSha;plan_commit=$planCommit;plan_sha256=$planSha;endpoint=$endpoint;logical_host='ar-local-pi5';host_key_blob_sha256=$blobHex;host_key_fingerprint=$fingerprint;outputs=$outputs;invocation_contract_sha256=$contract;check_only_execution_record=$check.execution_record;catalog_sha256=$invoke.expected_catalog_sha256;expires_at=$pre.expires_at}
WriteJson (Join-Path $root 'preflight-summary.json') $summary
[Console]::Out.Write($encoded)
```
<!-- END ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T160000 -->

The generator above is exactly 45965 UTF-8/LF bytes, 305 lines, SHA-256
`4a70b8580e4848eaa8c6cc2b4d6f7bb9ce0987e4db849ec2f1f53b1c670cf2bf`.
Its PowerShell parser has zero errors. Its only native `python -c` site is the
base64 bootstrap helper.

After this correction is merged, paste only the complete block below into a
normal, non-administrator, x64 System32 Windows PowerShell 5.1 session. Do not
run it from this PR. It binds current main and the complete raw handoff, validates
all failed artifacts before mutation, preserves them by exact move, and creates
the new generator/runtime/materialization record. It does not preflight, build,
elevate, trigger, back up, ingest, deploy, publish or touch the Pi.

<!-- BEGIN ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260902T160000 -->
```powershell
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
function ShaBytes([byte[]]$Bytes){$h=[Security.Cryptography.SHA256]::Create();try{($h.ComputeHash($Bytes)|ForEach-Object{$_.ToString('x2')})-join''}finally{$h.Dispose()}}
function ShaFile([string]$Path){ShaBytes ([IO.File]::ReadAllBytes($Path))}
Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
$httpProbe=[Net.Http.HttpClient]::new()
try{$httpAssembly=$httpProbe.GetType().Assembly;$httpClientAssembly=$httpAssembly.FullName;$httpAssemblyPath=$httpAssembly.Location;$httpAssemblySha=ShaFile $httpAssemblyPath}finally{$httpProbe.Dispose()}
if($httpClientAssembly-cne'System.Net.Http, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a'-or$httpAssemblySha-cne'd7ce24424f16bd410179bd202b3e375b2b731a6bd57d5d03a8d38cf9062a14db'){throw 'PS5.1 System.Net.Http binding drift'}
$root='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012'
$quarantine='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012-QUARANTINED-S6-20260902T054429Z-79903ee221ae'
$runtimeSource='C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-20260901\20260901T083436+1000\runtime'
$repo='https://github.com/yanniedog/AR-local.git'
$candidateSha='ac4e0acc563e6ac721cad326c5f54995258ac3c9'
$protectedSha='9302890fcc752cbf90da97d597e972c157d913e3'
$planCommit='9094a8e115958fcaf2cb36525736bd5e297e6b04'
$planSha='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada'
$planRawShaExpected='f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684'
$git='C:\Program Files\Git\cmd\git.exe'
$hostPath='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$startedAt=[DateTimeOffset]::UtcNow
$windowsIdentity=[Security.Principal.WindowsIdentity]::GetCurrent()
$operator=$windowsIdentity.Name
$principal=[Security.Principal.WindowsPrincipal]::new($windowsIdentity)
if($operator-cne'yanniedog\jkoka'-or$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'normal non-administrator operator is required'}
if(-not[Environment]::Is64BitProcess-or[IO.Path]::GetFullPath([Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)-cne$hostPath-or(ShaFile $hostPath)-cne'7600ffe12da441fe89d035b13801e8e91d064bc544a27b19a5cf49f6ab8b18f5'){throw 'normal x64 System32 Windows PowerShell is required'}
if((ShaFile $git)-cne'c470d205517c7a53ceca321df16a6e4549fcd52b576ab4d09536d36f26fda5a9'){throw 'git executable drift'}
$hobartZone=[TimeZoneInfo]::FindSystemTimeZoneById('Tasmania Standard Time')
$hobartNow=[TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow,$hobartZone)
if($hobartNow.TimeOfDay-lt[TimeSpan]::FromHours(3.5)-or$hobartNow.TimeOfDay-ge[TimeSpan]::FromHours(22)){throw 'outside D-006 daylight window'}
$env:GIT_TERMINAL_PROMPT='0'
function ResolveMain {
  $out=(& $git -c credential.interactive=never -c http.lowSpeedLimit=1 -c http.lowSpeedTime=20 ls-remote $repo refs/heads/main 2>&1|Out-String).Trim()
  if($LASTEXITCODE){throw "canonical main lookup failed: $out"}
  $sha=($out-split'\s+')[0].ToLowerInvariant()
  if($sha-notmatch'^[0-9a-f]{40}$'){throw 'canonical main is invalid'}
  $sha
}
function Get-TreeInventory([string]$Path){
  $base=[IO.Path]::GetFullPath($Path).TrimEnd('\')
  if(-not(Test-Path -LiteralPath $base -PathType Container)){throw "inventory root absent: $base"}
  $rootItem=Get-Item -LiteralPath $base -Force
  if(($rootItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw "inventory root is reparse: $base"}
  $recordsByPath=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
  $pending=[Collections.Generic.Stack[string]]::new();$pending.Push($base)
  while($pending.Count){
    $dir=$pending.Pop()
    foreach($item in @(Get-ChildItem -LiteralPath $dir -Force)){
      if(($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw "inventory node is reparse: $($item.FullName)"}
      $full=[IO.Path]::GetFullPath($item.FullName)
      if(-not$full.StartsWith($base+'\',[StringComparison]::OrdinalIgnoreCase)){throw "inventory node escapes root: $full"}
      $relative=$full.Substring($base.Length+1).Replace('\','/')
      if($item.PSIsContainer){$recordsByPath.Add($relative,[ordered]@{type='directory';path=$relative});$pending.Push($full)}
      else{$recordsByPath.Add($relative,[ordered]@{type='file';path=$relative;bytes=[long]$item.Length;sha256=(ShaFile $full)})}
    }
  }
  $paths=[string[]]$recordsByPath.Keys;[Array]::Sort($paths,[StringComparer]::Ordinal)
  $builder=[Text.StringBuilder]::new();$records=[Collections.Generic.List[object]]::new()
  [long]$files=0;[long]$directories=0;[long]$bytes=0
  foreach($relative in $paths){
    $record=$recordsByPath[$relative];[void]$records.Add($record)
    if($record.type-ceq'directory'){$directories++;[void]$builder.Append('D'+[char]9+$relative+[char]10)}
    else{$files++;$bytes+=[long]$record.bytes;[void]$builder.Append('F'+[char]9+$relative+[char]9+$record.bytes+[char]9+$record.sha256+[char]10)}
  }
  $manifestBytes=[Text.UTF8Encoding]::new($false).GetBytes($builder.ToString())
  [pscustomobject][ordered]@{path=$base;format='ARL-D012-TREE-TSV-V1';files=$files;directories=$directories;bytes=$bytes;nodes=($files+$directories);inventory_sha256=(ShaBytes $manifestBytes);records=$records}
}
function AssertInventory([object]$Actual,[long]$Files,[long]$Directories,[long]$Bytes,[string]$Sha,[string]$Name){
  if($Actual.format-cne'ARL-D012-TREE-TSV-V1'-or[long]$Actual.files-ne$Files-or[long]$Actual.directories-ne$Directories-or[long]$Actual.bytes-ne$Bytes-or$Actual.inventory_sha256-cne$Sha){throw "$Name inventory drift"}
}
$authoritySha=ResolveMain
if($authoritySha-ceq'c4a32fb77d4ffa8e545ac16d8a4a22308388d5fe'){throw 'sequence-7 correction is not merged'}
$client=[Net.Http.HttpClient]::new();$client.Timeout=[TimeSpan]::FromSeconds(20)
try{$handoffBytes=$client.GetByteArrayAsync("https://raw.githubusercontent.com/yanniedog/AR-local/$authoritySha/docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md").GetAwaiter().GetResult();$planBytes=$client.GetByteArrayAsync("https://raw.githubusercontent.com/yanniedog/AR-local/$authoritySha/docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md").GetAwaiter().GetResult()}finally{$client.Dispose()}
$handoffSha=ShaBytes $handoffBytes
$planRawSha=ShaBytes $planBytes
if($planRawSha-cne$planRawShaExpected){throw 'controlled plan raw hash drift'}
$text=[Text.UTF8Encoding]::new($false,$true).GetString($handoffBytes)
$resumeMatches=[regex]::Matches($text,'(?m)^\{"schema":"ARL-A3-RESUME-POINTER-V1".*\}$')
if($resumeMatches.Count-lt1){throw 'current handoff lacks a resume pointer'}
$latestResume=$resumeMatches[$resumeMatches.Count-1]
$resumeTail=$text.Substring($latestResume.Index+$latestResume.Length)
$resume=$latestResume.Value|ConvertFrom-Json
if($resumeTail-notmatch'^\r?\n\x60\x60\x60\r?\n\s*$'-or$resume.schema-cne'ARL-A3-RESUME-POINTER-V1'-or$resume.version-ne1-or$resume.sequence-ne7-or$resume.predecessor-cne'C-20260902T144000+1000'-or$resume.authority-cne'HANDOFF-20260902T133826+1000-A3-PINNED-LAN-FINAL-AUTHORITY'-or$resume.correction-cne'C-20260902T160000+1000'-or$resume.candidate_sha-cne$candidateSha-or$resume.terminal_status-cne'BLOCKED_UNTIL_SEQUENCE7_MATERIALIZER_AND_FRESH_PREFLIGHT_PASS'){throw 'sequence-7 correction is not the final exact resume pointer'}
$pattern='(?s)<!-- BEGIN ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T160000 -->\r?\n\x60\x60\x60powershell\r?\n(.*?)\r?\n\x60\x60\x60\r?\n<!-- END ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T160000 -->'
$match=[regex]::Match($text,$pattern)
if(-not$match.Success){throw 'sequence-7 generator block is absent'}
$script=$match.Groups[1].Value.Replace([string][char]13,'')
$scriptBytes=[Text.UTF8Encoding]::new($false).GetBytes($script);$scriptSha=ShaBytes $scriptBytes
if($scriptBytes.Length-ne45965-or$script.Split([char]10).Count-ne305-or$scriptSha-cne'4a70b8580e4848eaa8c6cc2b4d6f7bb9ce0987e4db849ec2f1f53b1c670cf2bf'){throw 'sequence-7 generator binding mismatch'}
$tokens=$null;$parseErrors=$null;[Management.Automation.Language.Parser]::ParseInput($script,[ref]$tokens,[ref]$parseErrors)|Out-Null
$nativePython=@($script.Split([char]10)|Where-Object{$_-match'& \$python .* -c '})
if(@($parseErrors).Count-or$nativePython.Count-ne1-or-not$nativePython[0].Contains('& $python -I -B -c $pythonBootstrap $payload @Arguments')-or-not$script.Contains('Add-Type -AssemblyName System.Net.Http -ErrorAction Stop')){throw 'sequence-7 parser or runtime-boundary gate failed'}
$partial=Get-TreeInventory $root
AssertInventory $partial 1048 128 22404909 '79903ee221ae225490bf0a9280b2adfb6ec6cd07badaf83ef9568573836f4abf' 'failed sequence-6 root'
if(Test-Path -LiteralPath $quarantine){throw 'fixed quarantine destination already exists'}
if([IO.Path]::GetPathRoot($root)-cne[IO.Path]::GetPathRoot($quarantine)){throw 'quarantine is not on the evidence volume'}
$runtimeSourceInventory=Get-TreeInventory $runtimeSource
AssertInventory $runtimeSourceInventory 3081 207 64290614 '7f3e77e272acf9601fc10228cea49cf08e051f43ea64f3f444f2fd631f9d0f86' 'source runtime'
$excluded=@(
[ordered]@{path='Lib/__pycache__/_collections_abc.cpython-310.pyc';bytes=33006L;sha256='425fbd5ac12907adef92c584a2190e075cf415ca688980a5ca41964f84283ea3'},
[ordered]@{path='Lib/__pycache__/_sitebuiltins.cpython-310.pyc';bytes=3628L;sha256='04fdae26c503f1b6889024c18070ee6d6a7de4b82322db0c42d003f6f5aa62f8'},
[ordered]@{path='Lib/__pycache__/abc.cpython-310.pyc';bytes=6832L;sha256='ff33f4bc62aaa37b094d8adc47226448cfce32d76792325e5ac6683b0d591d82'},
[ordered]@{path='Lib/__pycache__/codecs.cpython-310.pyc';bytes=33300L;sha256='23870e73fb0601c6788135e40f11d8b45ac8cbe09ff977533f46bb68c8d805af'},
[ordered]@{path='Lib/__pycache__/genericpath.cpython-310.pyc';bytes=3988L;sha256='fb23d82c091a4b96fa969c246135fa82fb97464263a0e85fdcbb3b3202bcfded'},
[ordered]@{path='Lib/__pycache__/io.cpython-310.pyc';bytes=3744L;sha256='4c6f92991fea91fdca1f80d30cad265eccd8ad39a773790ed22b6e4a73df16cb'},
[ordered]@{path='Lib/__pycache__/ntpath.cpython-310.pyc';bytes=15369L;sha256='d05dddeda13116d7cfae8e4fba2176ddf1d8efd39fd34c3def8f4552ae46d917'},
[ordered]@{path='Lib/__pycache__/os.cpython-310.pyc';bytes=31680L;sha256='5bb45fad1ba945c890eafad69e51f08dd58be168c17c40c3594fe1d1eb05ff16'},
[ordered]@{path='Lib/__pycache__/site.cpython-310.pyc';bytes=17461L;sha256='b873702652354c18a983f05b2297036411db888970145cccbf6e9eb7eca08db1'},
[ordered]@{path='Lib/__pycache__/stat.cpython-310.pyc';bytes=4354L;sha256='83b5087c77a45cbfe09526a711abef7bf9424647d4eb83b8988a028f13bead4e'},
[ordered]@{path='Lib/encodings/__pycache__/__init__.cpython-310.pyc';bytes=3956L;sha256='784f6e2d0691dc55aef592941ba1aa724bd37053d1a315128faa49a4e98bcdba'},
[ordered]@{path='Lib/encodings/__pycache__/aliases.cpython-310.pyc';bytes=11002L;sha256='a5241cfb46f3e1bdd31e6f2f1208afd821351c672ba11519f14b6eb88ca3d459'},
[ordered]@{path='Lib/encodings/__pycache__/cp1252.cpython-310.pyc';bytes=2458L;sha256='498aff31a1d2f086b44c68f38665e040ace7af18937c161fd3008af92f5a7b6e'},
[ordered]@{path='Lib/encodings/__pycache__/utf_8.cpython-310.pyc';bytes=1678L;sha256='7891dbd77cb81f7626d14daeaf2a099f31f949608c54aaa93027eec94288d345'}
)
$excludedByPath=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
foreach($expected in $excluded){
  $actual=@($runtimeSourceInventory.records|Where-Object{$_.type-ceq'file'-and$_.path-ceq$expected.path})
  if($actual.Count-ne1-or[long]$actual[0].bytes-ne[long]$expected.bytes-or$actual[0].sha256-cne$expected.sha256){throw "excluded runtime file drift: $($expected.path)"}
  $excludedByPath.Add($expected.path,$expected)
}
if((ResolveMain)-cne$authoritySha){throw 'main advanced before quarantine'}
$partialFinal=Get-TreeInventory $root;AssertInventory $partialFinal 1048 128 22404909 '79903ee221ae225490bf0a9280b2adfb6ec6cd07badaf83ef9568573836f4abf' 'failed sequence-6 root'
$runtimeSourceFinal=Get-TreeInventory $runtimeSource;AssertInventory $runtimeSourceFinal 3081 207 64290614 '7f3e77e272acf9601fc10228cea49cf08e051f43ea64f3f444f2fd631f9d0f86' 'source runtime'
Move-Item -LiteralPath $root -Destination $quarantine
if(Test-Path -LiteralPath $root){throw 'failed root remained after quarantine move'}
$quarantineInventory=Get-TreeInventory $quarantine
AssertInventory $quarantineInventory 1048 128 22404909 '79903ee221ae225490bf0a9280b2adfb6ec6cd07badaf83ef9568573836f4abf' 'quarantined sequence-6 root'
[void](New-Item -ItemType Directory -Path $root)
$runtime=Join-Path $root 'runtime';[void](New-Item -ItemType Directory -Path $runtime)
foreach($record in $runtimeSourceInventory.records){
  if($record.type-cne'file'-or$excludedByPath.ContainsKey([string]$record.path)){continue}
  $sourcePath=Join-Path $runtimeSource ([string]$record.path).Replace('/','\')
  $destinationPath=Join-Path $runtime ([string]$record.path).Replace('/','\')
  $parent=Split-Path -Parent $destinationPath
  if(-not(Test-Path -LiteralPath $parent -PathType Container)){[void](New-Item -ItemType Directory -Path $parent -Force)}
  $input=$null;$output=$null
  try{
    $input=[IO.File]::Open($sourcePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $output=[IO.File]::Open($destinationPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $input.CopyTo($output);$output.Flush($true)
  }finally{
    if($null-ne$output){$output.Dispose()}
    if($null-ne$input){$input.Dispose()}
  }
}
$python=Join-Path $runtime 'python.exe'
if((ShaFile $python)-cne'53e910971cbb20c3223cc44c696254ccfba9595dc4be8e16f56f6c954fff831f'){throw 'copied Python drift'}
$pythonBootstrap="import base64,sys;code=base64.b64decode(sys.argv.pop(1));exec(compile(code,'<ARL-D012>','exec'))"
function TextSha([string]$Text){ShaBytes ([Text.UTF8Encoding]::new($false).GetBytes($Text))}
function Invoke-PythonCode([string]$Code,[string[]]$Arguments=@()){
  $payload=[Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes($Code))
  $output=@(& $python -I -B -c $pythonBootstrap $payload @Arguments 2>&1)
  [pscustomobject]@{ExitCode=[int]$LASTEXITCODE;Output=($output|Out-String)}
}
$argvProbeCode='import json,sys;print(json.dumps(sys.argv[1:],separators=(",",":")))'
$argvProbeArgs=@('space value','C:\path with space\leaf','star*','comma,:')
$argvProbeExpected='["space value","C:\\path with space\\leaf","star*","comma,:"]'
$argvProbeRun=Invoke-PythonCode -Code $argvProbeCode -Arguments $argvProbeArgs
$argvProbeActual=$argvProbeRun.Output.Trim()
if($argvProbeRun.ExitCode-ne0-or$argvProbeActual-cne$argvProbeExpected){throw "PS5.1 Python argv boundary failed: $($argvProbeRun.Output)"}
$inventoryCode='from pathlib import Path;import hashlib,json,sys;r=Path(sys.argv[1]);nodes=sorted(r.rglob("*"),key=lambda p:p.relative_to(r).as_posix());bad=(not r.is_dir()) or bool(getattr(r.lstat(),"st_file_attributes",0)&0x400) or any(bool(getattr(p.lstat(),"st_file_attributes",0)&0x400) for p in nodes);bad and (_ for _ in ()).throw(RuntimeError("reparse or missing runtime root"));files=[p for p in nodes if p.is_file()];dirs=[p for p in nodes if p.is_dir()];d={p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files};b=(json.dumps(d,sort_keys=True,separators=(",",":"))+"\n").encode();t=("".join(("D\t"+p.relative_to(r).as_posix()+"\n") if p.is_dir() else ("F\t"+p.relative_to(r).as_posix()+"\t"+str(p.stat().st_size)+"\t"+d[p.relative_to(r).as_posix()]+"\n") for p in nodes)).encode();print(len(files),len(dirs),sum(p.stat().st_size for p in files),hashlib.sha256(b).hexdigest(),hashlib.sha256(t).hexdigest())'
$inventoryRun=Invoke-PythonCode -Code $inventoryCode -Arguments @($runtime)
$inventoryActual=$inventoryRun.Output.Trim()
if($inventoryRun.ExitCode-ne0-or$inventoryActual-cne'3067 205 64118158 d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7 4edd841372c7463bd53b711b0ba236152fa3ed1ef01f00bad8c7af991b99043c'){throw "copied runtime Python inventory drift: $($inventoryRun.Output)"}
$cleanRuntime=Get-TreeInventory $runtime
AssertInventory $cleanRuntime 3067 205 64118158 '4edd841372c7463bd53b711b0ba236152fa3ed1ef01f00bad8c7af991b99043c' 'clean copied runtime'
$runtimeSourceAfter=Get-TreeInventory $runtimeSource
AssertInventory $runtimeSourceAfter 3081 207 64290614 '7f3e77e272acf9601fc10228cea49cf08e051f43ea64f3f444f2fd631f9d0f86' 'source runtime after copy'
function WriteNew([string]$Path,[byte[]]$Bytes){$stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$stream.Write($Bytes,0,$Bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}}
$generatorPath=Join-Path $root 'prepare-and-preflight.ps1';WriteNew $generatorPath $scriptBytes
$completedAt=[DateTimeOffset]::UtcNow
$record=[ordered]@{
  schema_version=2
  correction='C-20260902T160000+1000'
  plan_document_id='ARL-OPS-001'
  plan_version='1.5'
  document_commit=$planCommit
  plan_git_commit=$planCommit
  plan_sha256=$planSha
  plan_raw_sha256=$planRawSha
  candidate_code_sha=$candidateSha
  protected_code_sha=$protectedSha
  operator=$operator
  timestamps=[ordered]@{started_at=$startedAt.ToString('o');completed_at=$completedAt.ToString('o')}
  exact_commands=@('MARKED_ARL_D012_RECOVERY_MATERIALIZER_PS1_C20260902T160000')
  evidence_paths=@($quarantine,$runtime,$generatorPath)
  result='PASS'
  deviations=@()
  authority_commit=$authoritySha
  complete_handoff_raw_sha256=$handoffSha
  prior_partial_root=[ordered]@{path=$partial.path;quarantine_path=$quarantine;format=$partial.format;files=[long]$partial.files;directories=[long]$partial.directories;bytes=[long]$partial.bytes;nodes=[long]$partial.nodes;inventory_sha256=$partial.inventory_sha256;records=$partial.records}
  source_runtime=[ordered]@{path=$runtimeSource;format=$runtimeSourceInventory.format;files=[long]$runtimeSourceInventory.files;directories=[long]$runtimeSourceInventory.directories;bytes=[long]$runtimeSourceInventory.bytes;nodes=[long]$runtimeSourceInventory.nodes;inventory_sha256=$runtimeSourceInventory.inventory_sha256;excluded=$excluded}
  clean_runtime=[ordered]@{path=$runtime;format=$cleanRuntime.format;files=[long]$cleanRuntime.files;directories=[long]$cleanRuntime.directories;bytes=[long]$cleanRuntime.bytes;nodes=[long]$cleanRuntime.nodes;tree_inventory_sha256=$cleanRuntime.inventory_sha256;file_map_sha256='d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7'}
  generator=[ordered]@{path=$generatorPath;bytes=$scriptBytes.Length;lines=$script.Split([char]10).Count;sha256=$scriptSha}
  powershell=[ordered]@{path=$hostPath;sha256=(ShaFile $hostPath)}
  http_client=[ordered]@{assembly=$httpClientAssembly;path=$httpAssemblyPath;sha256=$httpAssemblySha}
  python_boundary=[ordered]@{bootstrap_sha256=(TextSha $pythonBootstrap);probe_code_sha256=(TextSha $argvProbeCode);probe_result_sha256=(TextSha $argvProbeActual);inventory_code_sha256=(TextSha $inventoryCode);inventory_result_sha256=(TextSha $inventoryActual)}
  materialized_at=[DateTimeOffset]::UtcNow.ToString('o')
}
$authorityBeforeRecord=ResolveMain
if($authorityBeforeRecord-cne$authoritySha){throw 'main advanced before terminal materialization record'}
$recordBytes=[Text.UTF8Encoding]::new($false).GetBytes((($record|ConvertTo-Json -Depth 20 -Compress)+[char]10))
WriteNew (Join-Path $root 'materialization.json') $recordBytes
$record|ConvertTo-Json -Depth 4 -Compress
```
<!-- END ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260902T160000 -->

The materializer above is exactly 19314 UTF-8/LF bytes, 204 lines, SHA-256
`9a6079f22337d435f4e2cd69bffdb12bb7d96478009ea003121d8a8f0c45ab52`.
It is the exact next safe command after merge; any different bytes are
unauthorized.

Current non-mutating Windows PowerShell 5.1 runtime tests:

- Without `Add-Type -AssemblyName System.Net.Http`,
  `[Net.Http.HttpClient]::new()` fails with “Unable to find type”.
- With the explicit load, construction/disposal passes as
  `System.Net.Http, Version=4.0.0.0`; assembly SHA-256 is
  `d7ce24424f16bd410179bd202b3e375b2b731a6bd57d5d03a8d38cf9062a14db`.
- The exact sequence-6 native call reproduces Python exit 1 and the corrupted
  source. The replacement bootstrap preserves
  `["space value","C:\\path with space\\leaf","star*","comma,:"]`
  exactly and exits 0.
- The same replacement boundary inventories the current source runtime as
  `3081 207 64290614 8ec5cd13af4c229550c453625d564e6b9e151f5f1ee1634e89481c9fb8b37517 7f3e77e272acf9601fc10228cea49cf08e051f43ea64f3f444f2fd631f9d0f86`.
- The materializer's exact pre-mutation path, with current branch bytes used
  for the not-yet-merged raw URL and the tail cut before `Move-Item`, executes
  under Windows PowerShell 5.1 and returns the two inventory hashes above plus
  `excluded=14`.
- Both marked scripts parse under stock Windows PowerShell 5.1; extraction,
  UTF-8/LF byte count and SHA-256 equivalence pass. Neither marked script was
  executed.

After a successful materializer terminal record, the ordinary non-admin
generator command remains:

```powershell
$encoded = & 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -NonInteractive -ExecutionPolicy Bypass -File 'C:\code\backups\AR-local-pi5\evidence\A3-TRUSTED-BOOTSTRAP-D012\prepare-and-preflight.ps1'
```

Only its non-empty one-line base64 result and a current, unexpired terminal
`preflight-summary.json` `PASS` permit the sole sequence-3 UAC command.
Natural backup acceptance remains mandatory; A3 remains running and A4 remains
blocked.

```json
{"schema":"ARL-A3-RESUME-POINTER-V1","version":1,"sequence":7,"predecessor":"C-20260902T144000+1000","authority":"HANDOFF-20260902T133826+1000-A3-PINNED-LAN-FINAL-AUTHORITY","correction":"C-20260902T160000+1000","base_main_sha":"c4a32fb77d4ffa8e545ac16d8a4a22308388d5fe","candidate_sha":"ac4e0acc563e6ac721cad326c5f54995258ac3c9","quarantines":["sequence-6-materializer-7dd1fd5fba125205616e15912cce0c5da836e08ba2ce9316cf81a32295ff4383","sequence-6-generator-917f41dd538b3cc56ef031de6f0fb6f68d79dd06027a4939bbb2083e5e7a31b2","partial-sequence-6-root-79903ee221ae225490bf0a9280b2adfb6ec6cd07badaf83ef9568573836f4abf"],"failed_root":{"path":"C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012","files":1048,"directories":128,"bytes":22404909,"nodes":1176,"tree_inventory_sha256":"79903ee221ae225490bf0a9280b2adfb6ec6cd07badaf83ef9568573836f4abf","materialization_sha256":"557bff5f40394df7f2e6c319f926bea8d508fac1910ff0003f42e3dc9e3a6c41","generator_sha256":"917f41dd538b3cc56ef031de6f0fb6f68d79dd06027a4939bbb2083e5e7a31b2"},"quarantine_path":"C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012-QUARANTINED-S6-20260902T054429Z-79903ee221ae","source_runtime":{"path":"C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-20260901\\20260901T083436+1000\\runtime","files":3081,"directories":207,"bytes":64290614,"tree_inventory_sha256":"7f3e77e272acf9601fc10228cea49cf08e051f43ea64f3f444f2fd631f9d0f86","file_map_sha256":"8ec5cd13af4c229550c453625d564e6b9e151f5f1ee1634e89481c9fb8b37517","excluded_pyc":{"files":14,"bytes":172456}},"clean_runtime":{"files":3067,"directories":205,"bytes":64118158,"tree_inventory_sha256":"4edd841372c7463bd53b711b0ba236152fa3ed1ef01f00bad8c7af991b99043c","file_map_sha256":"d664070cb4ef57b349809a499086fa977516d5b1d66d9c70dfdd5a7420f5c7b7"},"authority_merge_sha":"D012_SEQUENCE7_MATERIALIZATION_RECORD","complete_handoff_raw_sha256":"D012_SEQUENCE7_MATERIALIZATION_RECORD","generator":{"path":"C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012\\prepare-and-preflight.ps1","bytes":45965,"lines":305,"sha256":"4a70b8580e4848eaa8c6cc2b4d6f7bb9ce0987e4db849ec2f1f53b1c670cf2bf"},"materializer":{"encoding":"UTF8_LF_NO_TRAILING_LF","bytes":19314,"lines":204,"sha256":"9a6079f22337d435f4e2cd69bffdb12bb7d96478009ea003121d8a8f0c45ab52"},"boundaries":{"powershell_sha256":"7600ffe12da441fe89d035b13801e8e91d064bc544a27b19a5cf49f6ab8b18f5","system_net_http_sha256":"d7ce24424f16bd410179bd202b3e375b2b731a6bd57d5d03a8d38cf9062a14db","python_sha256":"53e910971cbb20c3223cc44c696254ccfba9595dc4be8e16f56f6c954fff831f","python_mode":"-I -B BASE64_ARGV_BOOTSTRAP"},"a3":"RUNNING","a4":"BLOCKED_UNTIL_NATURAL_ACCEPTANCE","next_action":"after this correction is merged, paste exactly the marked sequence-7 materializer in a normal x64 System32 Windows PowerShell 5.1 session; require its terminal record; then run the ordinary non-admin generator entrypoint","next_command":"MARKED_ARL_D012_RECOVERY_MATERIALIZER_PS1_C20260902T160000","next_command_utf8_lf_sha256":"9a6079f22337d435f4e2cd69bffdb12bb7d96478009ea003121d8a8f0c45ab52","preflight_command":"$encoded = & 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe' -NoProfile -NonInteractive -ExecutionPolicy Bypass -File 'C:\\code\\backups\\AR-local-pi5\\evidence\\A3-TRUSTED-BOOTSTRAP-D012\\prepare-and-preflight.ps1'","preflight_command_utf8_sha256":"f715cc5d2b5b50bed541174bc91c15c979d3ba3c990c27f18ff398f308065349","stop":["main/handoff/generator/materializer/root/runtime/toolchain drift","quarantine already exists","resolver/key/auth drift","source/task/catalog/Pi/evidence/publication drift","timeout/web-auth","process/lock/lease/partial","under 50GiB","D-006 window or expired preflight","launcher object/executable or package mismatch"],"authorization":"non-admin sequence-7 quarantine/materialization and preflight only after merge; sole sequence-3 UAC command only after terminal PASS; no manual backup/ingest/deploy/publication","terminal_status":"BLOCKED_UNTIL_SEQUENCE7_MATERIALIZER_AND_FRESH_PREFLIGHT_PASS"}
```
