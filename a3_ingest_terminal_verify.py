"""Verify one natural Pi ingest and its public v1 bytes without mutating production."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import time as clock
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from a3_verifier_common import (
    EvidenceWriter,
    VerificationError,
    add_identity_arguments,
    contained_file,
    fail_closed_main,
    is_link_or_reparse,
    load_json,
    load_json_bytes,
    require_mapping,
    require_sha256,
    run_capture,
    sha256_bytes,
    sha256_file,
    verify_runtime_source,
)


HOBART_OFFSET = timezone(timedelta(hours=10))
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_date(value: str) -> date:
    if not DATE_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD")
    return date.fromisoformat(value)


def parse_key_values(payload: bytes, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in payload.decode("utf-8", "strict").splitlines():
        if not raw or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key in result:
            raise VerificationError(f"duplicate {label} key: {key}")
        result[key] = value
    return result


def require_keys(value: Mapping[str, Any], keys: Sequence[str], label: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise VerificationError(f"{label} lacks required keys: {missing}")


def verify_execution_record(path: Path, args: argparse.Namespace, phase: str) -> Mapping[str, Any]:
    record = require_mapping(load_json(path), str(path))
    expected = {
        "schema_version": 1,
        "plan_document_id": args.plan_document_id,
        "plan_version": args.plan_version,
        "plan_git_commit": args.plan_git_commit,
        "plan_sha256": args.plan_sha256,
        "plan_normalized_sha256": args.plan_normalized_sha256,
        "authority_commit": args.authority_commit,
        "authority_handoff_sha256": args.authority_handoff_sha256,
        "candidate_code_sha": args.candidate_code_sha,
        "protected_code_sha": args.protected_code_sha,
        "operator": args.operator,
        "phase": phase,
        "result": "PASS",
        "deviations": [],
        "deviation_authorization": None,
    }
    if record.get("wrapper_sha256") != args.preflight_wrapper_sha256:
        raise VerificationError(f"{phase} preflight wrapper digest is invalid")
    if record.get("preflight_script_sha256") != args.preflight_script_sha256:
        raise VerificationError(f"{phase} timed preflight digest is invalid")
    if any(record.get(key) != item for key, item in expected.items()):
        raise VerificationError(f"{phase} execution identity is invalid")
    timestamps = record.get("timestamps")
    commands = record.get("exact_commands")
    evidence = record.get("evidence")
    if (
        not isinstance(timestamps, Mapping)
        or not timestamps.get("started_at")
        or not timestamps.get("completed_at")
        or not isinstance(commands, list)
        or not commands
        or not isinstance(evidence, list)
        or not evidence
    ):
        raise VerificationError(f"{phase} execution envelope is incomplete")
    expected_paths = {
        f"{phase}-stdout.txt",
        f"{phase}-stderr.txt",
        f"{phase}-local.json",
        f"{phase}-pi.txt",
        f"{phase}-values.json",
        f"{phase}-hashes.json",
    }
    actual_paths: set[str] = set()
    for raw in evidence:
        item = require_mapping(raw, f"{phase} execution evidence")
        relative = str(item.get("path") or "")
        if relative in actual_paths:
            raise VerificationError(f"{phase} execution evidence repeats {relative}")
        evidence_path = contained_file(path.parent, relative)
        digest = require_sha256(item.get("sha256"), f"{phase} {relative} digest")
        if sha256_file(evidence_path) != digest or evidence_path.stat().st_size != int(item.get("bytes", -1)):
            raise VerificationError(f"{phase} execution evidence changed: {relative}")
        actual_paths.add(relative)
    if actual_paths != expected_paths:
        raise VerificationError(f"{phase} execution evidence set is incomplete")
    return record


def verify_preflight(root: Path, args: argparse.Namespace, writer: EvidenceWriter) -> dict[str, Any]:
    configured_root = root.absolute()
    if is_link_or_reparse(configured_root):
        raise VerificationError("active evidence root is a link or reparse point")
    root = configured_root.resolve(strict=True)
    parent = root.parent.resolve(strict=True)
    expected_generation = re.compile(rf"^{args.date.strftime('%Y%m%d')}T\d{{6}}\+1000-[0-9a-f]{{32}}$")
    if not expected_generation.fullmatch(root.name):
        raise VerificationError("active evidence generation identity is invalid")
    matching = [
        item.resolve(strict=True)
        for item in parent.iterdir()
        if item.is_dir() and not is_link_or_reparse(item) and (item / "0025-hashes.json").is_file()
    ]
    if matching != [root]:
        raise VerificationError("active evidence generation is not uniquely bound")
    pointer_source = parent / "ACTIVE_EVIDENCE_PATH.txt"
    initialization_path = parent / "INITIALIZATION.json"
    if is_link_or_reparse(pointer_source) or is_link_or_reparse(initialization_path):
        raise VerificationError("initialization control traverses a link or reparse point")
    pointer = pointer_source.resolve(strict=True)
    if Path(pointer.read_text(encoding="utf-8").strip()).resolve(strict=True) != root:
        raise VerificationError("active evidence pointer does not bind this generation")
    initialization = require_mapping(load_json(initialization_path), "initialization")
    initialization_keys = {
        "schema_version", "plan_document_id", "plan_version", "plan_git_commit",
        "plan_sha256", "candidate_code_sha", "protected_code_sha", "operator",
        "created_at", "evidence_root", "result", "deviations", "deviation_authorization",
    }
    initialization_expected = {
        "schema_version": 1,
        "plan_document_id": args.plan_document_id,
        "plan_version": args.plan_version,
        "plan_git_commit": args.plan_git_commit,
        "plan_sha256": args.plan_sha256,
        "candidate_code_sha": args.candidate_code_sha,
        "protected_code_sha": args.protected_code_sha,
        "operator": args.operator,
        "evidence_root": str(root),
        "result": "RUNNING",
        "deviations": [],
        "deviation_authorization": None,
    }
    try:
        initialized_at = datetime.fromisoformat(str(initialization["created_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise VerificationError("initialization timestamp is invalid") from exc
    initialization_minimum = datetime.combine(args.date, time(0, 20), HOBART_OFFSET)
    initialization_maximum = datetime.combine(args.date, time(0, 30), HOBART_OFFSET)
    if (
        set(initialization) != initialization_keys
        or any(initialization.get(key) != item for key, item in initialization_expected.items())
        or initialized_at.tzinfo is None
        or not initialization_minimum <= initialized_at.astimezone(HOBART_OFFSET) < initialization_maximum
    ):
        raise VerificationError("initialization record identity is invalid")
    script_path = contained_file(root, "timed-preflight.ps1")
    if sha256_file(script_path) != args.preflight_script_sha256:
        raise VerificationError("timed preflight source digest is invalid")
    wrapper_path = contained_file(root, args.preflight_wrapper_path)
    if sha256_file(wrapper_path) != args.preflight_wrapper_sha256:
        raise VerificationError("timed preflight wrapper source digest is invalid")

    phases: dict[str, Any] = {}
    run_day = args.date
    windows = {
        "0025": (
            datetime.combine(run_day, time(0, 20), HOBART_OFFSET),
            datetime.combine(run_day, time(0, 30), HOBART_OFFSET),
        ),
        "0055": (
            datetime.combine(run_day, time(0, 55), HOBART_OFFSET),
            datetime.combine(run_day + timedelta(days=0), time(1, 0), HOBART_OFFSET),
        ),
    }
    for phase, (minimum, maximum) in windows.items():
        manifest_path = contained_file(root, f"{phase}-hashes.json")
        manifest = require_mapping(load_json(manifest_path), str(manifest_path))
        if manifest.get("result") != "PASS" or manifest.get("script_sha256") != args.preflight_script_sha256:
            raise VerificationError(f"{phase} preflight manifest identity is invalid")
        try:
            completed = datetime.fromisoformat(str(manifest["completed_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise VerificationError(f"{phase} completion timestamp is invalid") from exc
        if completed.tzinfo is None or not minimum <= completed.astimezone(HOBART_OFFSET) < maximum:
            raise VerificationError(f"{phase} completed outside its authorized window")
        artifact_hashes: dict[str, str] = {}
        for role in ("local", "pi", "values"):
            name = f"{phase}-{role}.json" if role != "pi" else f"{phase}-pi.txt"
            digest = require_sha256(manifest.get(f"{role}_sha256"), f"{phase} {role} hash")
            artifact = contained_file(root, name)
            if sha256_file(artifact) != digest:
                raise VerificationError(f"{phase} {role} evidence digest changed")
            artifact_hashes[name] = digest
        execution_path = contained_file(root, f"{phase}-execution.json")
        execution = verify_execution_record(execution_path, args, phase)
        execution_timestamps = require_mapping(execution.get("timestamps"), f"{phase} execution timestamps")
        try:
            started = datetime.fromisoformat(str(execution_timestamps["started_at"]).replace("Z", "+00:00"))
            execution_completed = datetime.fromisoformat(str(execution_timestamps["completed_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise VerificationError(f"{phase} execution timestamps are invalid") from exc
        if (
            started.tzinfo is None
            or execution_completed.tzinfo is None
            or not minimum <= started.astimezone(HOBART_OFFSET)
            or not started <= completed <= execution_completed
            or not execution_completed.astimezone(HOBART_OFFSET) < maximum
        ):
            raise VerificationError(f"{phase} wrapper execution escaped its authorized window")
        for name in (*artifact_hashes, f"{phase}-hashes.json", f"{phase}-execution.json", f"{phase}-stdout.txt", f"{phase}-stderr.txt"):
            writer.reference(contained_file(root, name))
        phases[phase] = {
            "manifest_sha256": sha256_file(manifest_path),
            "execution_sha256": sha256_file(execution_path),
            "artifacts": artifact_hashes,
        }
    baseline_path = contained_file(root, "0055-baseline-authentication.json")
    baseline = require_mapping(load_json(baseline_path), str(baseline_path))
    baseline_expected = {
        "schema_version": 1,
        "plan_document_id": args.plan_document_id,
        "plan_version": args.plan_version,
        "plan_git_commit": args.plan_git_commit,
        "plan_sha256": args.plan_sha256,
        "plan_normalized_sha256": args.plan_normalized_sha256,
        "candidate_code_sha": args.candidate_code_sha,
        "protected_code_sha": args.protected_code_sha,
        "operator": args.operator,
        "result": "PASS",
        "deviations": [],
        "deviation_authorization": None,
    }
    if any(baseline.get(key) != value for key, value in baseline_expected.items()):
        raise VerificationError("00:55 baseline authentication did not pass")
    if not isinstance(baseline.get("exact_commands"), list) or not baseline["exact_commands"]:
        raise VerificationError("00:55 baseline authentication lacks exact commands")
    baseline_paths = baseline.get("evidence_paths")
    required_baseline_paths = {
        script_path.resolve(),
        contained_file(root, "0025-hashes.json").resolve(),
        contained_file(root, "0025-local.json").resolve(),
        contained_file(root, "0025-pi.txt").resolve(),
        contained_file(root, "0025-values.json").resolve(),
    }
    if not isinstance(baseline_paths, list):
        raise VerificationError("00:55 baseline authentication lacks evidence paths")
    try:
        actual_baseline_paths = {Path(str(item)).resolve(strict=True) for item in baseline_paths}
    except OSError as exc:
        raise VerificationError("00:55 baseline authentication references missing evidence") from exc
    if actual_baseline_paths != required_baseline_paths:
        raise VerificationError("00:55 baseline authentication evidence set is invalid")
    writer.reference(script_path)
    writer.reference(wrapper_path)
    writer.reference(baseline_path)
    return {
        "initialization_sha256": sha256_file(initialization_path),
        "pointer_sha256": sha256_file(pointer),
        "script_sha256": sha256_file(script_path),
        "baseline_authentication_sha256": sha256_file(baseline_path),
        "phases": phases,
    }


def remote_terminal_script(run_day: date) -> bytes:
    next_day = run_day + timedelta(days=1)
    script = f"""set -eu
cd /srv/ar-local/AR-local
echo observed_at=$(date --iso-8601=seconds)
echo head=$(git rev-parse HEAD)
if test -z "$(git status --porcelain=v1)"; then echo checkout_clean=true; else echo checkout_clean=false; fi
echo active=$(systemctl is-active ar-local-daily.service || true)
echo invocation=$(systemctl show ar-local-daily.service -p InvocationID --value)
start_timestamp=$(systemctl show ar-local-daily.service -p ExecMainStartTimestamp --value); echo start_timestamp=$start_timestamp
echo start_iso=$(date --date="$start_timestamp" --iso-8601=seconds)
exit_timestamp=$(systemctl show ar-local-daily.service -p ExecMainExitTimestamp --value); echo exit_timestamp=$exit_timestamp
echo exit_iso=$(date --date="$exit_timestamp" --iso-8601=seconds)
echo status=$(systemctl show ar-local-daily.service -p ExecMainStatus --value)
echo code=$(systemctl show ar-local-daily.service -p ExecMainCode --value)
echo result=$(systemctl show ar-local-daily.service -p Result --value)
echo restarts=$(systemctl show ar-local-daily.service -p NRestarts --value)
echo timer_enabled=$(systemctl is-enabled ar-local-daily.timer)
echo timer_active=$(systemctl is-active ar-local-daily.timer)
echo timer_last=$(systemctl show ar-local-daily.timer -p LastTriggerUSec --value)
echo timer_next=$(systemctl show ar-local-daily.timer -p NextElapseUSecRealtime --value)
if test -e /srv/ar-local/data/state/daily-ingest.lock; then echo lock=PRESENT; exit 42; else echo lock=ABSENT; fi
if pgrep -f '[p]i_daily_sync.py|[c]dr_daily.py' >/dev/null; then echo competing_process=PRESENT; exit 43; else echo competing_process=ABSENT; fi
curl -fsS --max-time 10 http://127.0.0.1:8808/api/status | python3 -c "import json,sys;v=json.load(sys.stdin);o=v.get('observation')or{{}};assert v.get('service')=='ar-local';assert v.get('status') in ('ok','degraded');assert o.get('date')=='{run_day.isoformat()}';assert o.get('accounting_id')"
echo status_api=HEALTHY
case "$(systemctl show ar-local-daily.timer -p NextElapseUSecRealtime --value)" in *"{next_day.isoformat()} 01:00:00 AEST") ;; *) exit 46 ;; esac
"""
    return script.encode()


def remote_start_script() -> bytes:
    return b"""set -eu
echo observed_at=$(date --iso-8601=seconds)
echo active=$(systemctl is-active ar-local-daily.service || true)
echo invocation=$(systemctl show ar-local-daily.service -p InvocationID --value)
echo start_timestamp=$(systemctl show ar-local-daily.service -p ExecMainStartTimestamp --value)
echo restarts=$(systemctl show ar-local-daily.service -p NRestarts --value)
echo timer_last=$(systemctl show ar-local-daily.timer -p LastTriggerUSec --value)
echo timer_next=$(systemctl show ar-local-daily.timer -p NextElapseUSecRealtime --value)
if test -e /srv/ar-local/data/state/daily-ingest.lock;then echo lock=PRESENT;else echo lock=ABSENT;fi
service_cgroup=$(systemctl show ar-local-daily.service -p ControlGroup --value);echo service_cgroup=$service_cgroup
count=0;bad=0
for pid in $(pgrep -f '[p]i_daily_sync.py|[c]dr_daily.py'||true);do count=$((count+1));process_cgroup=$(cut -d: -f3 /proc/$pid/cgroup|tail -1);echo ingest_pid_$count=$pid:$process_cgroup;case "$process_cgroup" in "$service_cgroup"|"$service_cgroup"/*);;*)bad=1;;esac;done
echo ingest_process_count=$count
if test "$bad" -eq 0;then echo competing_process=ABSENT;else echo competing_process=PRESENT;fi
"""


def remote_observation_script(run_day: date) -> bytes:
    template = r'''import hashlib,json,sqlite3
from pathlib import Path
from cdr_finalization import verify_completion_marker
D=__DATE__;data=Path('/srv/ar-local/data').resolve();state=(data/'state').resolve()
def h(path):
 digest=hashlib.sha256()
 with path.open('rb') as stream:
  for block in iter(lambda:stream.read(1048576),b''):digest.update(block)
 return digest.hexdigest()
p=json.loads((state/'observation-pointers-v2/latest-observation.json').read_text())
assert p['observation_date']==D
m_path=(state/p['marker_path']).resolve();m_path.relative_to(state);m=json.loads(m_path.read_text());assert verify_completion_marker(m,state,D)
c_path=(state/m['export_contract_path']).resolve();c_path.relative_to(state);c=json.loads(c_path.read_text())
assert p['generation_id']==m['generation_id']==c['generation_id'];assert p['ledger_event_digest']==m['ledger_event_digest']
a=m.get('attempt_evidence') or {};assert a.get('verified') is True and int(a.get('attempts') or 0)>0
v=c.get('coverage') or {};reg=int(v.get('providers_registered') or 0);att=int(v.get('providers_attempted') or 0)
complete=int(v.get('providers_complete') or 0);partial=int(v.get('providers_partial') or 0);failed=int(v.get('providers_failed') or 0)
failures=int(v.get('failure_records') or 0);corrupt=int(v.get('corrupt_failure_records') or 0);unattributed=int(v.get('unattributed_failure_records') or 0)
discovered=int(v.get('products_discovered') or 0);register_attempted=int(v.get('register_sources_attempted') or 0);register_complete=int(v.get('register_sources_complete') or 0)
states=c.get('provider_states') or [];state_counts={k:sum(1 for x in states if x.get('state')==k) for k in ('complete','partial','failed')}
assert reg>0 and att==reg and len(states)==reg and complete+partial+failed==reg and state_counts=={'complete':complete,'partial':partial,'failed':failed}
assert c.get('observation_state') in {'complete','partial'} and v.get('failure_provenance_complete') is True and v.get('register_provenance_complete') is True
assert register_attempted>0 and register_complete==register_attempted and corrupt==0 and unattributed==0 and discovered>0
if c.get('observation_state')=='partial':assert failures>0 or partial>0 or failed>0
else:assert failures==0 and partial==0 and failed==0
for x in states:
 assert x.get('state') in {'complete','partial','failed'}
 assert int(x.get('failure_records') or 0)>=0
 if x.get('state')=='failed':assert int(x.get('failure_records') or 0)>0
assert int((m.get('banks') or {}).get('products') or 0)==discovered and int((m.get('banks') or {}).get('failures') or 0)==failures
assert not(c.get('quarantines') or [])
unavailable=set(v.get('unavailable_populations') or []);assert {'consumer_eligible_products','priced_products','rate_tiers_by_classification'}<=unavailable
source=(data/c['source_path']).resolve();source.relative_to(data);dbs=[x for x in c['artifacts'] if x['path'].endswith('.sqlite')];assert len(dbs)==1
meta=dbs[0];db=(source/meta['path']).resolve();db.relative_to(source);digest=h(db);assert db.stat().st_size==int(meta['bytes']) and digest==meta['sha256']
with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as con:
 qc=con.execute('PRAGMA quick_check').fetchone()[0];assert qc=='ok';tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
 required={'runs','schema_meta','bank_products','bank_rates','bank_items','bank_product_facts','bank_product_changes'};assert required<=tables
 counts={t:con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in sorted(required)};assert all(counts[t]>0 for t in ('bank_products','bank_rates','bank_items','bank_product_facts'))
 banks=m.get('banks') or {};assert counts['bank_products']==int(banks.get('products') or 0)==discovered;assert counts['bank_rates']==int(banks.get('rates') or 0);assert counts['bank_product_facts']==int(banks.get('product_facts') or 0);assert counts['bank_product_changes']==int(banks.get('product_changes') or 0);assert counts['bank_items']==sum(int(banks.get(k) or 0) for k in ('fees','features','eligibility','constraints'))
assert sum(int(x.get('failure_records') or 0) for x in states)==failures
local_v1={}
for key,folder,tag,required,allowed in (('dated','v1-dated',f'app-payload-{D}',{'core','details'},{'core','details'}),('rolling','v1-latest','app-payload-latest',{'core','details'},{'bank_history','core','details','history_banks','rba_calendar','search_index'})):
 root=(state/'app-payload/v1'/folder).resolve();root.relative_to(state);manifest_path=(root/'manifest.json').resolve();manifest_path.relative_to(root);payload=json.loads(manifest_path.read_text())
 assert payload.get('schema_version')==1 and payload.get('run_date')==D and payload.get('tag')==tag;roles=set((payload.get('files') or {}).keys());assert required<=roles<=allowed;assets={}
 for role,item in payload['files'].items():
  name=item['name'];assert Path(name).name==name;asset=(root/name).resolve();asset.relative_to(root);asset_sha=h(asset);asset_bytes=asset.stat().st_size;assert asset_sha==item['sha256'] and asset_bytes==int(item['bytes']);assets[role]={'name':name,'sha256':asset_sha,'bytes':asset_bytes}
 local_v1[key]={'tag':tag,'manifest_sha256':h(manifest_path),'assets':assets}
print(json.dumps({'result':'PASS','date':D,'pointer':p,'marker_sha256':h(m_path),'contract_digest':c['contract_digest'],'banks':m.get('banks') or {},'attempt_evidence':a,'coverage':v,'provider_states':states,'quarantines':c.get('quarantines',[]),'sqlite':{'path':str(db),'bytes':db.stat().st_size,'sha256':digest,'quick_check':qc,'populations':counts},'local_v1':local_v1},sort_keys=True))
'''
    return template.replace("__DATE__", repr(run_day.isoformat())).encode()


def ssh(args: argparse.Namespace, *remote: str, input_bytes: bytes | None = None, timeout: int = 600):
    command = [args.ssh_bin, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.pi_host, *remote]
    return run_capture(command, input_bytes=input_bytes, timeout=timeout)


def require_success(result: Any, label: str, writer: EvidenceWriter) -> bytes:
    writer.write(f"{label}-stdout.txt", result.stdout)
    writer.write(f"{label}-stderr.txt", result.stderr)
    if result.returncode != 0:
        raise VerificationError(f"{label} failed with exit {result.returncode}")
    return result.stdout


def observe_natural_start(args: argparse.Namespace, writer: EvidenceWriter) -> Path:
    root = Path(args.evidence_root)
    baseline = require_mapping(load_json(contained_file(root, "0055-values.json")), "00:55 values")
    deadline = datetime.combine(args.date, time(1, 5), HOBART_OFFSET)
    attempts: list[bytes] = []
    selected_raw: bytes | None = None
    selected: dict[str, str] | None = None
    while datetime.now(HOBART_OFFSET) < deadline:
        capture = ssh(args, "bash", "-s", input_bytes=remote_start_script(), timeout=30)
        attempts.append(
            f"--- {datetime.now(timezone.utc).isoformat()} exit={capture.returncode} ---\n".encode()
            + capture.stdout
            + b"\n[stderr]\n"
            + capture.stderr
            + b"\n"
        )
        if capture.returncode == 0:
            candidate = parse_key_values(capture.stdout, "natural start")
            process_count = candidate.get("ingest_process_count", "")
            if candidate.get("active") == "active" and candidate.get("lock") == "PRESENT" and process_count.isdigit() and int(process_count) > 0:
                selected_raw, selected = capture.stdout, candidate
                break
        clock.sleep(2)
    writer.write_root("0100-start-attempts.txt", b"".join(attempts))
    if selected is None or selected_raw is None:
        raise VerificationError("natural service never reached a lock-bound ingest process by 01:05")
    require_keys(selected, ("observed_at", "active", "invocation", "start_timestamp", "restarts", "timer_last", "timer_next", "lock", "service_cgroup", "ingest_process_count", "competing_process"), "natural start")
    observed = datetime.fromisoformat(selected["observed_at"].replace("Z", "+00:00"))
    minimum = datetime.combine(args.date, time(1, 0), HOBART_OFFSET)
    if (
        not minimum <= observed.astimezone(HOBART_OFFSET) < deadline
        or not selected["invocation"]
        or selected["invocation"] == baseline.get("service_invocation")
        or args.date.isoformat() not in selected["start_timestamp"]
        or "01:00:" not in selected["start_timestamp"]
        or int(selected["restarts"]) != 0
        or selected["timer_last"] == baseline.get("timer_last")
        or selected["lock"] != "PRESENT"
        or int(selected["ingest_process_count"]) < 1
        or selected["competing_process"] != "ABSENT"
    ):
        raise VerificationError("natural start identity, timer, cgroup, or lock gate failed")
    writer.write_root("0100-start.txt", selected_raw)
    return writer.write_root_json(args.start_values, selected)


def wait_for_terminal(args: argparse.Namespace, writer: EvidenceWriter) -> None:
    observations: list[str] = []
    while True:
        result = ssh(args, "systemctl show ar-local-daily.service -p ActiveState --value", timeout=30)
        observed = datetime.now(timezone.utc).isoformat()
        state = result.stdout.decode("utf-8", "replace").strip()
        observations.append(f"{observed} exit={result.returncode} state={state} stderr={result.stderr.decode('utf-8','replace').strip()}")
        if result.returncode != 0:
            writer.write("terminal-poll.txt", ("\n".join(observations) + "\n").encode())
            raise VerificationError("terminal service polling failed")
        if state not in {"active", "activating"}:
            writer.write("terminal-poll.txt", ("\n".join(observations) + "\n").encode())
            return
        clock.sleep(30)


def validate_service(args: argparse.Namespace, writer: EvidenceWriter) -> dict[str, Any]:
    start_path = contained_file(Path(args.evidence_root), args.start_values)
    writer.reference(start_path)
    start = require_mapping(load_json(start_path), "natural start values")
    require_keys(start, ("invocation", "start_timestamp", "timer_last", "restarts", "lock", "competing_process"), "start values")
    if (
        not str(start["invocation"]).strip()
        or args.date.isoformat() not in str(start["start_timestamp"])
        or "01:00:" not in str(start["start_timestamp"])
        or int(start["restarts"]) != 0
        or start["lock"] != "PRESENT"
        or start["competing_process"] != "ABSENT"
    ):
        raise VerificationError("natural start identity is invalid")
    terminal_raw = require_success(ssh(args, "bash", "-s", input_bytes=remote_terminal_script(args.date)), "terminal-service", writer)
    terminal = parse_key_values(terminal_raw, "terminal")
    require_keys(terminal, ("head", "checkout_clean", "active", "invocation", "start_timestamp", "start_iso", "exit_iso", "status", "code", "result", "restarts", "timer_enabled", "timer_active", "timer_last", "timer_next", "lock", "competing_process", "status_api"), "terminal values")
    exit_at = datetime.fromisoformat(terminal["exit_iso"].replace("Z", "+00:00"))
    started_at = datetime.fromisoformat(terminal["start_iso"].replace("Z", "+00:00"))
    if (
        terminal["head"] != args.protected_code_sha
        or terminal["checkout_clean"] != "true"
        or terminal["active"] != "inactive"
        or terminal["invocation"] != start["invocation"]
        or terminal["start_timestamp"] != start["start_timestamp"]
        or terminal["timer_last"] != start["timer_last"]
        or exit_at.tzinfo is None
        or started_at.tzinfo is None
        or exit_at < started_at
        or terminal["status"] != "0"
        or terminal["code"] != "exited"
        or terminal["result"] != "success"
        or int(terminal["restarts"]) != 0
        or terminal["timer_enabled"] != "enabled"
        or terminal["timer_active"] != "active"
        or terminal["lock"] != "ABSENT"
        or terminal["competing_process"] != "ABSENT"
        or terminal["status_api"] != "HEALTHY"
    ):
        raise VerificationError("natural terminal service gate failed")
    writer.write_json("terminal-service-values.json", terminal)
    since = f"{args.date.isoformat()} 00:55:00"
    journal_raw = require_success(
        ssh(args, "journalctl", "-u", "ar-local-daily.service", f"--since={since.replace(' ', 'T')}", "--output=json", "--no-pager"),
        "service-journal",
        writer,
    )
    invocations: set[str] = set()
    for line in journal_raw.splitlines():
        if not line.strip():
            continue
        row = require_mapping(load_json_bytes(line, "journal line"), "journal line")
        invocation = row.get("_SYSTEMD_INVOCATION_ID")
        if isinstance(invocation, str) and invocation:
            invocations.add(invocation)
    if invocations != {str(start["invocation"])}:
        raise VerificationError(f"journal does not prove exactly one invocation: {sorted(invocations)}")
    return {"start": dict(start), "terminal": terminal, "invocations": sorted(invocations)}


def validate_observation(args: argparse.Namespace, writer: EvidenceWriter) -> Mapping[str, Any]:
    ledger_raw = require_success(
        ssh(args, "cd /srv/ar-local/AR-local && python3 cdr_ledger_v2.py verify --state /srv/ar-local/data/state"),
        "ledger-verify",
        writer,
    )
    ledger = require_mapping(load_json_bytes(ledger_raw, "ledger verification"), "ledger verification")
    if ledger.get("ok") is not True or ledger.get("findings") or ledger.get("warnings"):
        raise VerificationError("ledger verification has findings or warnings")
    observation_raw = require_success(
        ssh(args, "cd /srv/ar-local/AR-local && python3 -", input_bytes=remote_observation_script(args.date), timeout=1200),
        "observation-verify",
        writer,
    )
    observation = require_mapping(load_json_bytes(observation_raw, "observation verification"), "observation verification")
    if observation.get("result") != "PASS" or observation.get("date") != args.date.isoformat():
        raise VerificationError("observation verification identity failed")
    return observation


def download(url: str, timeout: int, max_bytes: int = 64 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AR-local-A3-verifier/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise VerificationError(f"HTTP {response.status}: {url}")
            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise VerificationError(f"public download exceeds {max_bytes} bytes: {url}")
            return payload
    except (OSError, urllib.error.URLError) as exc:
        raise VerificationError(f"public download failed: {url}: {exc}") from exc


def validate_public(args: argparse.Namespace, writer: EvidenceWriter, observation: Mapping[str, Any]) -> dict[str, Any]:
    repository = args.github_repository.strip("/")
    run_date = args.date.isoformat()
    local_v1 = require_mapping(observation.get("local_v1"), "local v1 staging")
    banks = require_mapping(observation.get("banks"), "bank counts")
    report: dict[str, Any] = {"date": run_date, "manifests": {}}
    decoded_assets: dict[tuple[str, str], object] = {}
    for local_key, tag in (("dated", f"app-payload-{run_date}"), ("rolling", "app-payload-latest")):
        producer = require_mapping(local_v1.get(local_key), f"{local_key} producer manifest")
        manifest_url = f"https://github.com/{repository}/releases/download/{tag}/manifest.json"
        manifest_bytes = download(manifest_url, args.http_timeout)
        writer.write(f"public/{tag}/manifest.json", manifest_bytes)
        manifest = require_mapping(load_json_bytes(manifest_bytes, manifest_url), f"{tag} manifest")
        if manifest.get("schema_version") != 1 or manifest.get("run_date") != run_date or manifest.get("tag") != tag:
            raise VerificationError(f"{tag} manifest identity mismatch")
        if sha256_bytes(manifest_bytes) != producer.get("manifest_sha256"):
            raise VerificationError(f"{tag} public manifest differs from Pi staging")
        files = require_mapping(manifest.get("files"), f"{tag} files")
        producer_assets = require_mapping(producer.get("assets"), f"{tag} producer assets")
        if set(files) != set(producer_assets):
            raise VerificationError(f"{tag} public role set differs from Pi staging")
        counts = require_mapping(manifest.get("counts"), f"{tag} counts")
        for key, value in banks.items():
            if int(counts.get(key, -1)) != int(value):
                raise VerificationError(f"{tag} count mismatch: {key}")
        assets: list[dict[str, Any]] = []
        for role, raw_meta in files.items():
            meta = require_mapping(raw_meta, f"{tag} {role}")
            producer_meta = require_mapping(producer_assets.get(role), f"{tag} producer {role}")
            digest = require_sha256(meta.get("sha256"), f"{tag} {role} digest")
            expected_bytes = int(meta.get("bytes", -1))
            if expected_bytes < 1 or expected_bytes > 64 * 1024 * 1024:
                raise VerificationError(f"{tag} {role} asset size is outside the controlled bound")
            expected_name = f"{role.replace('_', '-')}-{run_date}-{digest[:12]}.json.gz"
            expected_url = f"https://github.com/{repository}/releases/download/{tag}/{expected_name}"
            if (
                meta.get("name") != expected_name
                or meta.get("url") != expected_url
                or producer_meta.get("name") != expected_name
                or producer_meta.get("sha256") != digest
                or int(producer_meta.get("bytes", -1)) != expected_bytes
            ):
                raise VerificationError(f"{tag} {role} manifest/staging identity mismatch")
            payload = download(expected_url, args.http_timeout)
            if sha256_bytes(payload) != digest or len(payload) != expected_bytes:
                raise VerificationError(f"{tag} {role} public bytes differ")
            writer.write(f"public/{tag}/{expected_name}", payload)
            try:
                decoded = load_json_bytes(gzip.decompress(payload), expected_url)
            except (OSError, EOFError) as exc:
                raise VerificationError(f"{tag} {role} gzip is invalid") from exc
            if isinstance(decoded, Mapping) and decoded.get("run_date", run_date) != run_date:
                raise VerificationError(f"{tag} {role} run date mismatch")
            decoded_assets[(tag, role)] = decoded
            assets.append({"role": role, "name": expected_name, "sha256": digest, "bytes": len(payload)})
        report["manifests"][tag] = {"sha256": sha256_bytes(manifest_bytes), "assets": assets}
    for role in ("core", "details"):
        dated = next(item for item in report["manifests"][f"app-payload-{run_date}"]["assets"] if item["role"] == role)
        rolling = next(item for item in report["manifests"]["app-payload-latest"]["assets"] if item["role"] == role)
        if dated["sha256"] != rolling["sha256"]:
            raise VerificationError(f"dated and rolling {role} bytes differ")
    core = require_mapping(decoded_assets[("app-payload-latest", "core")], "rolling core")
    coverage = require_mapping(core.get("coverage"), "public coverage")
    coverage_counts = require_mapping(coverage.get("counts"), "public coverage counts")
    local_coverage = require_mapping(observation.get("coverage"), "local coverage")
    if (
        core.get("schema_version") != 1
        or core.get("run_date") != run_date
        or coverage.get("observed_on") != run_date
        or int(coverage_counts.get("products", -1)) != int(banks.get("products", -2))
        or int(coverage_counts.get("rates", -1)) != int(banks.get("rates", -2))
        or int(coverage_counts.get("failure_records", -1)) != int(banks.get("failures", -2))
        or int(coverage_counts.get("providers_attempted", -1)) != int(local_coverage.get("providers_attempted", -2))
        or coverage.get("failure_provenance_complete") is not True
    ):
        raise VerificationError("public core coverage/date/count binding failed")
    failures = coverage.get("failures")
    provider_failures = coverage.get("provider_failures")
    if not isinstance(failures, list) or failures != provider_failures:
        raise VerificationError("public provider failure disclosure is invalid")
    aggregate: dict[str, int] = {}
    for item in failures:
        entry = require_mapping(item, "provider failure")
        provider = str(entry.get("provider") or "")
        aggregate[provider] = aggregate.get(provider, 0) + int(entry.get("count") or 0)
    expected = {
        str(item["brand_name"]): int(item.get("failure_records") or 0)
        for item in observation.get("provider_states", [])
        if isinstance(item, Mapping) and int(item.get("failure_records") or 0) > 0
    }
    if aggregate != expected or sum(aggregate.values()) != int(banks.get("failures") or 0):
        raise VerificationError("public per-provider gaps do not match the observation")

    index_url = f"https://github.com/{repository}/releases/download/app-payload-latest/dates-index.json"
    index_bytes = download(index_url, args.http_timeout)
    writer.write("public/app-payload-latest/dates-index.json", index_bytes)
    index = require_mapping(load_json_bytes(index_bytes, index_url), "dates index")
    dates = index.get("dates")
    if not isinstance(dates, list) or not dates or not all(isinstance(item, str) for item in dates):
        raise VerificationError("dates index dates must be a non-empty string list")
    try:
        parsed_dates = [date.fromisoformat(item) for item in dates]
        minimum_date = date.fromisoformat(str(index.get("min_date")))
    except ValueError as exc:
        raise VerificationError("dates index contains an invalid date") from exc
    expected_index_keys = {
        "schema_version", "dates", "count", "min_date", "latest_date",
    }
    if (
        set(index) != expected_index_keys
        or index.get("schema_version") != 1
        or dates != sorted(set(dates))
        or any(item < minimum_date for item in parsed_dates)
        or index.get("count") != len(dates)
        or index.get("latest_date") != dates[-1]
        or index.get("latest_date") != run_date
    ):
        raise VerificationError("dates index is not independently current")
    report["dates_index"] = {"sha256": sha256_bytes(index_bytes), "latest_date": run_date}

    v2_url = f"https://github.com/{repository}/releases/download/app-payload-latest/manifest-v2.json"
    try:
        v2_bytes = download(v2_url, args.http_timeout)
        writer.write("public/app-payload-latest/manifest-v2.json", v2_bytes)
        v2 = require_mapping(load_json_bytes(v2_bytes, v2_url), "v2 manifest")
        current = v2.get("run_date") == run_date
        report["v2"] = {
            "result": "PASS" if current else "FAIL",
            "status": "PASS_CURRENT_INDEPENDENT_NOT_A_V1_GATE" if current else "STALE_FAIL_INDEPENDENT_NOT_A_V1_GATE",
            "run_date": v2.get("run_date"),
            "sha256": sha256_bytes(v2_bytes),
        }
    except Exception as exc:
        report["v2"] = {"result": "FAIL", "status": "FAIL_INDEPENDENT_NOT_A_V1_GATE", "error": str(exc)}
    return report


def verify(args: argparse.Namespace, writer: EvidenceWriter) -> Mapping[str, object]:
    runtime = verify_runtime_source(args, Path(__file__))
    preflight = verify_preflight(Path(args.evidence_root), args, writer)
    start_path = contained_file(Path(args.evidence_root), args.start_values, must_exist=False)
    if not start_path.exists():
        if not args.observe_natural_start:
            raise VerificationError("natural start evidence is missing")
        observe_natural_start(args, writer)
        wait_for_terminal(args, writer)
    service = validate_service(args, writer)
    observation = validate_observation(args, writer)
    public = validate_public(args, writer, observation)
    return {"date": args.date.isoformat(), "verifier": runtime, "preflight": preflight, "service": service, "observation": observation, "public": public}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--date", required=True, type=parse_date)
    value.add_argument("--evidence-root", required=True)
    value.add_argument("--start-values", default="0100-start-values.json")
    value.add_argument("--observe-natural-start", action="store_true")
    value.add_argument("--preflight-script-sha256", required=True)
    value.add_argument("--preflight-wrapper-sha256", required=True)
    value.add_argument("--preflight-wrapper-path", default="run_a3_timed_preflight.ps1")
    value.add_argument("--pi-host", default="ar-local-pi5-lan")
    value.add_argument("--ssh-bin", default="ssh")
    value.add_argument("--github-repository", default="yanniedog/AR-local")
    value.add_argument("--http-timeout", type=int, default=120)
    add_identity_arguments(value)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    require_sha256(args.preflight_script_sha256, "preflight script SHA-256")
    require_sha256(args.preflight_wrapper_sha256, "preflight wrapper SHA-256")
    return fail_closed_main(args, "terminal-ingest-verification", verify)


if __name__ == "__main__":
    raise SystemExit(main())
