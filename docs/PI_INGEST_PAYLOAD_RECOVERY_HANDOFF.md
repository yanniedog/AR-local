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

This merge is code availability only. The installed Windows task remains at
receiver `c87cdd0...` and plan v1.3. No instruction in this entry permits
installing `f214e32...`, changing the task, running the receiver against the Pi,
or changing Pi production.

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
| Authorization | This append-only decision is made within the operator-authorized bounded slice and does not broaden authority to installation, deployment, A4 execution, or later phases. |
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
