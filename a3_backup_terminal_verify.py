"""Verify the first natural managed-dispatcher laptop backup for an observation."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import laptop_backup_scheduled as scheduled
import laptop_backup_dispatcher as dispatcher_module
import laptop_backup_transition_contract as contract
import laptop_pull_backup as receiver
from a3_verifier_common import (
    EvidenceWriter,
    VerificationError,
    add_identity_arguments,
    fail_closed_main,
    load_json_bytes,
    require_commit,
    require_mapping,
    require_sha256,
    run_capture,
    sha256_file,
    verify_runtime_source,
)
from a3_ingest_terminal_verify import HOBART_OFFSET, parse_date


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def task_snapshot_script(args: argparse.Namespace) -> str:
    values = {
        "task": args.task_name,
        "runner": str(Path(args.receiver) / "run_laptop_backup_task.ps1"),
        "config": str(Path(args.target) / "dispatcher-control/runner-config.json"),
        "manifest": str(Path(args.target) / "dispatcher-control/manifests" / f"{args.dispatcher_manifest_sha256}.json"),
        "pointer": str(Path(args.target) / "dispatcher-control/active-runner.json"),
        "receipt": args.activation_receipt,
    }
    literal = {key: ps_quote(value) for key, value in values.items()}
    return f"""$ErrorActionPreference='Stop'
$task=Get-ScheduledTask -TaskName {literal['task']};$info=Get-ScheduledTaskInfo -TaskName {literal['task']}
$xml=Export-ScheduledTask -TaskName {literal['task']}
$xmlBytes=[byte[]](0xff,0xfe)+[Text.Encoding]::Unicode.GetBytes($xml)
$algorithm=[Security.Cryptography.SHA256]::Create();try{{$xmlHash=([BitConverter]::ToString($algorithm.ComputeHash($xmlBytes))-replace'-','').ToLowerInvariant()}}finally{{$algorithm.Dispose()}}
$svc=New-Object -ComObject 'Schedule.Service';$svc.Connect();$slash=[string][char]92;$sddl=$svc.GetFolder($slash).GetTask($slash+{literal['task']}).GetSecurityDescriptor(7)
$algorithm=[Security.Cryptography.SHA256]::Create();try{{$sddlHash=([BitConverter]::ToString($algorithm.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($sddl)))-replace'-','').ToLowerInvariant()}}finally{{$algorithm.Dispose()}}
$helpers=@(Get-CimInstance Win32_Process|Where-Object{{$_.ProcessId-ne$PID-and$_.CommandLine-and$_.CommandLine-match'(laptop_backup_(scheduled|dispatcher|atomic)|run_laptop_backup_task)'}}|ForEach-Object{{[ordered]@{{pid=$_.ProcessId;command_line=$_.CommandLine}}}})
$triggers=@($task.Triggers|ForEach-Object{{[ordered]@{{type=$_.CimClass.CimClassName;start_boundary=[string]$_.StartBoundary;delay=[string]$_.Delay}}}})
[ordered]@{{
 observed_at=[DateTimeOffset]::Now.ToString('o');state=[string]$task.State;enabled=[bool]$task.Settings.Enabled;last_task_result=[int]$info.LastTaskResult;last_run_time=$info.LastRunTime.ToString('o');next_run_time=$info.NextRunTime.ToString('o');boot_time=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o');triggers=$triggers;xml_sha256=$xmlHash;sddl_sha256=$sddlHash
 runner_sha256=(Get-FileHash -LiteralPath {literal['runner']} -Algorithm SHA256).Hash.ToLowerInvariant()
 config_sha256=(Get-FileHash -LiteralPath {literal['config']} -Algorithm SHA256).Hash.ToLowerInvariant()
 manifest_sha256=(Get-FileHash -LiteralPath {literal['manifest']} -Algorithm SHA256).Hash.ToLowerInvariant()
 pointer_sha256=(Get-FileHash -LiteralPath {literal['pointer']} -Algorithm SHA256).Hash.ToLowerInvariant()
 receipt_sha256=(Get-FileHash -LiteralPath {literal['receipt']} -Algorithm SHA256).Hash.ToLowerInvariant()
 free_bytes=[int64](Get-PSDrive -Name ([IO.Path]::GetPathRoot({ps_quote(args.target)}).Substring(0,1))).Free
 helpers=$helpers
}}|ConvertTo-Json -Depth 8 -Compress
"""


def collect_task_snapshot(args: argparse.Namespace, writer: EvidenceWriter) -> Mapping[str, Any]:
    result = run_capture(
        [args.powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", task_snapshot_script(args)],
        timeout=180,
    )
    writer.write("task-snapshot-stdout.txt", result.stdout)
    writer.write("task-snapshot-stderr.txt", result.stderr)
    if result.returncode != 0:
        raise VerificationError(f"Task Scheduler snapshot failed with exit {result.returncode}")
    snapshot = require_mapping(load_json_bytes(result.stdout, "task snapshot"), "task snapshot")
    expected = {
        "state": "Ready",
        "enabled": True,
        "last_task_result": 0,
        "xml_sha256": args.task_xml_sha256,
        "sddl_sha256": args.task_sddl_sha256,
        "runner_sha256": args.runner_sha256,
        "config_sha256": args.dispatcher_config_sha256,
        "manifest_sha256": args.dispatcher_manifest_sha256,
        "receipt_sha256": args.activation_receipt_sha256,
    }
    if any(snapshot.get(key) != value for key, value in expected.items()):
        raise VerificationError("live task or dispatcher identity differs from the accepted state")
    last_run = datetime.fromisoformat(str(snapshot.get("last_run_time")))
    boot_time = datetime.fromisoformat(str(snapshot.get("boot_time")))
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=HOBART_OFFSET)
    if boot_time.tzinfo is None:
        boot_time = boot_time.replace(tzinfo=HOBART_OFFSET)
    local_last_run = last_run.astimezone(HOBART_OFFSET)
    daily_minimum = datetime.combine(args.date, time(5, 0), HOBART_OFFSET)
    daily_maximum = datetime.combine(args.date, time(5, 5), HOBART_OFFSET)
    startup_minimum = boot_time + timedelta(minutes=5)
    startup_maximum = startup_minimum + timedelta(minutes=5)
    trigger_rows = snapshot.get("triggers")
    if not isinstance(trigger_rows, list):
        raise VerificationError("Task Scheduler trigger evidence is missing")
    daily_triggers = [item for item in trigger_rows if isinstance(item, Mapping) and item.get("type") == "MSFT_TaskDailyTrigger" and "T05:00:00" in str(item.get("start_boundary"))]
    boot_triggers = [item for item in trigger_rows if isinstance(item, Mapping) and item.get("type") == "MSFT_TaskBootTrigger" and item.get("delay") == "PT5M"]
    if len(daily_triggers) != 1 or len(boot_triggers) != 1:
        raise VerificationError("Task Scheduler daily/startup trigger contract is invalid")
    if daily_minimum <= local_last_run < daily_maximum:
        snapshot["accepted_trigger"] = "DAILY_05_00"
    elif local_last_run.date() == args.date and startup_minimum <= last_run <= startup_maximum:
        snapshot["accepted_trigger"] = "STARTUP_PLUS_5_MINUTES"
    else:
        raise VerificationError("last task execution matches neither authorized natural trigger")
    if int(snapshot.get("free_bytes", 0)) < 50 * 1024**3 or snapshot.get("helpers"):
        raise VerificationError("laptop capacity, helper, or overlap gate failed")
    writer.write_json("task-snapshot.json", snapshot)
    return snapshot


def git_state(path: Path) -> tuple[str, list[str], bool]:
    head = subprocess.run(("git", "-C", str(path), "rev-parse", "HEAD"), text=True, capture_output=True, check=True).stdout.strip()
    dirty = subprocess.run(("git", "-C", str(path), "status", "--porcelain=v1"), text=True, capture_output=True, check=True).stdout.splitlines()
    symbolic = subprocess.run(("git", "-C", str(path), "symbolic-ref", "-q", "HEAD"), text=True, capture_output=True).returncode == 0
    return head, dirty, symbolic


def validate_dispatcher(args: argparse.Namespace) -> dict[str, Any]:
    receiver_root = contract.reject_linked_components(Path(args.receiver), "managed receiver").resolve(strict=True)
    implementation_root = contract.reject_linked_components(Path(args.implementation_root), "dispatcher implementation").resolve(strict=True)
    candidate_root = contract.reject_linked_components(Path(args.candidate_root), "backup candidate").resolve(strict=True)
    receiver_head, receiver_dirty, _receiver_symbolic = git_state(receiver_root)
    implementation_head, implementation_dirty, implementation_symbolic = git_state(implementation_root)
    candidate_head, candidate_dirty, candidate_symbolic = git_state(candidate_root)
    if receiver_head != args.candidate_code_sha or receiver_dirty != [" M run_laptop_backup_task.ps1"]:
        raise VerificationError("managed receiver drifted beyond its accepted runner")
    if implementation_head != args.implementation_commit or implementation_dirty or implementation_symbolic:
        raise VerificationError("dispatcher implementation checkout is not exact, clean, and detached")
    if candidate_head != args.candidate_code_sha or candidate_dirty or candidate_symbolic:
        raise VerificationError("backup candidate checkout is not exact, clean, and detached")
    target = receiver.canonical_target(Path(args.target))
    control = contract.reject_linked_components(target / "dispatcher-control", "dispatcher control").resolve(strict=True)
    config_path = control / "runner-config.json"
    manifest_path = control / "manifests" / f"{args.dispatcher_manifest_sha256}.json"
    pointer_path = control / "active-runner.json"
    receipt_path = Path(args.activation_receipt).resolve(strict=True)
    try:
        receipt_path.relative_to(control)
    except ValueError as exc:
        raise VerificationError("activation receipt escaped dispatcher control") from exc
    config = require_mapping(load_json_bytes(config_path.read_bytes(), str(config_path)), "dispatcher config")
    manifest = require_mapping(load_json_bytes(manifest_path.read_bytes(), str(manifest_path)), "dispatcher manifest")
    pointer = require_mapping(load_json_bytes(pointer_path.read_bytes(), str(pointer_path)), "dispatcher pointer")
    receipt = require_mapping(load_json_bytes(receipt_path.read_bytes(), str(receipt_path)), "activation receipt")
    validated_manifest = dispatcher_module.validate_manifest(manifest, activation=False)
    if (
        sha256_file(config_path) != args.dispatcher_config_sha256
        or sha256_file(manifest_path) != args.dispatcher_manifest_sha256
        or sha256_file(receipt_path) != args.activation_receipt_sha256
        or config.get("implementation_commit") != args.implementation_commit
        or Path(str(config.get("implementation_root"))).resolve(strict=True) != implementation_root
        or config.get("dispatcher_sha256") != args.dispatcher_sha256
        or sha256_file(implementation_root / "laptop_backup_dispatcher.py") != args.dispatcher_sha256
        or manifest.get("candidate_code_sha") != args.candidate_code_sha
        or manifest.get("protected_code_sha") != args.protected_code_sha
        or manifest.get("plan_git_commit") != args.plan_git_commit
        or manifest.get("plan_sha256") != args.plan_sha256
        or pointer.get("manifest_sha256") != args.dispatcher_manifest_sha256
        or pointer.get("sequence") != 1
        or receipt.get("status") != "PASS"
        or receipt.get("manifest_sha256") != args.dispatcher_manifest_sha256
    ):
        raise VerificationError("managed dispatcher activation identity is invalid")
    cutoff = datetime.combine(args.date, time(0, 30), HOBART_OFFSET).astimezone(timezone.utc)
    executions: list[dict[str, Any]] = []
    execution_root = control / "dispatcher-executions"
    for path in sorted(execution_root.glob("*.json")):
        value = require_mapping(load_json_bytes(path.read_bytes(), str(path)), str(path))
        timestamps = require_mapping(value.get("timestamps"), f"{path} timestamps")
        try:
            completed = datetime.fromisoformat(str(timestamps["completed_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise VerificationError(f"dispatcher execution timestamp is invalid: {path}") from exc
        if completed < cutoff:
            continue
        expected_execution = {
            "schema_version": 1,
            "plan_document_id": args.plan_document_id,
            "plan_version": args.plan_version,
            "plan_git_commit": args.plan_git_commit,
            "plan_sha256": args.plan_sha256,
            "candidate_code_sha": args.candidate_code_sha,
            "protected_code_sha": args.protected_code_sha,
            "operator": args.operator,
            "manifest_sha256": args.dispatcher_manifest_sha256,
            "dispatcher_sha256": args.dispatcher_sha256,
            "child_exit_code": 0,
            "result": "PASS",
            "error": None,
            "deviations": [],
            "deviation_authorization": None,
        }
        if any(value.get(key) != item for key, item in expected_execution.items()):
            raise VerificationError(f"dispatcher execution identity is invalid: {path}")
        if not isinstance(value.get("exact_arguments"), list) or not value["exact_arguments"] or not isinstance(value.get("child_arguments"), list) or not value["child_arguments"]:
            raise VerificationError(f"dispatcher execution lacks exact arguments: {path}")
        try:
            started = datetime.fromisoformat(str(timestamps["started_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise VerificationError(f"dispatcher execution start timestamp is invalid: {path}") from exc
        if started.tzinfo is None or completed.tzinfo is None or started > completed:
            raise VerificationError(f"dispatcher execution timestamp envelope is invalid: {path}")
        executions.append({"path": str(path), "sha256": sha256_file(path), "started_at": started.isoformat(), "completed_at": completed.isoformat()})
    if not executions:
        raise VerificationError("no managed-dispatcher execution exists after the ingest baseline")
    if (control / "transition.lease").exists():
        raise VerificationError("dispatcher lease remains after task completion")
    return {
        "receiver": {"path": str(receiver_root), "head": receiver_head, "dirty": receiver_dirty},
        "implementation": {"path": str(implementation_root), "head": implementation_head},
        "candidate": {"path": str(candidate_root), "head": candidate_head},
        "config_sha256": sha256_file(config_path),
        "manifest_sha256": sha256_file(manifest_path),
        "pointer_sha256": sha256_file(pointer_path),
        "receipt_sha256": sha256_file(receipt_path),
        "validated_manifest": validated_manifest,
        "executions": executions,
    }


def scheduled_plan_expected(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "plan_document_id": args.scheduled_plan_document_id,
        "plan_version": args.scheduled_plan_version,
        "plan_git_commit": args.scheduled_plan_git_commit,
        "plan_sha256": args.scheduled_plan_sha256,
        "plan_normalized_raw_sha256": args.scheduled_plan_normalized_sha256,
        "plan_raw_sha256": None,
        "candidate_code_sha": args.candidate_code_sha,
        "protected_code_sha": args.protected_code_sha,
        "operator": args.operator,
        "result": "PASS",
        "deviations": [],
        "deviation_authorization": None,
    }


def validate_component_state(detail: Mapping[str, Any], expected_date: str) -> None:
    observation = require_mapping(detail.get("observation"), "scheduled observation")
    inventory = require_mapping(detail.get("inventory"), "scheduled inventory")
    if observation.get("status") != "UP_TO_DATE" or observation.get("observation_date") != expected_date:
        raise VerificationError("scheduled observation is not current")
    for kind in ("control", "macro"):
        if require_mapping(detail.get(kind), f"scheduled {kind}").get("status") != "UP_TO_DATE":
            raise VerificationError(f"scheduled {kind} is not current")
    if inventory != {"status": "UP_TO_DATE", "missing_completed_dates": [], "stale_diagnostics": []}:
        raise VerificationError("scheduled retained-run inventory is incomplete")
    if detail.get("backfill_required") is not False or detail.get("status") != "UP_TO_DATE":
        raise VerificationError("scheduled aggregate state is not current")


def validate_new_records(args: argparse.Namespace) -> dict[str, Any]:
    target = receiver.canonical_target(Path(args.target))
    records_root = target / "catalog/scheduled-runs"
    cutoff = datetime.combine(args.date, time(0, 30), HOBART_OFFSET).astimezone(timezone.utc)
    records: list[tuple[datetime, Path, Mapping[str, Any]]] = []
    for path in records_root.glob("*.json"):
        value = require_mapping(load_json_bytes(path.read_bytes(), str(path)), str(path))
        timestamps = require_mapping(value.get("timestamps"), f"{path} timestamps")
        try:
            completed = datetime.fromisoformat(str(timestamps["completed_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise VerificationError(f"scheduled record timestamp is invalid: {path}") from exc
        if completed.tzinfo is None:
            raise VerificationError(f"scheduled record timestamp lacks timezone: {path}")
        if completed >= cutoff:
            records.append((completed, path.resolve(), value))
    records.sort(key=lambda item: (item[0], item[1].name))
    if not records:
        raise VerificationError("no scheduled records exist after the natural ingest baseline")
    expected = scheduled_plan_expected(args)
    previous: dict[str, str] | None = None
    evidence: list[dict[str, Any]] = []
    writes = 0
    natural_daily = 0
    for completed, path, record in records:
        actual_expected = dict(expected)
        actual_expected["plan_raw_sha256"] = record.get("plan_raw_sha256")
        if record.get("plan_raw_sha256") not in args.scheduled_plan_raw_sha256:
            raise VerificationError(f"scheduled record raw plan digest is invalid: {path}")
        if record.get("schema_version") != 1 or any(record.get(key) != value for key, value in actual_expected.items()):
            raise VerificationError(f"scheduled record controlled identity is invalid: {path}")
        commands = record.get("exact_commands")
        if not isinstance(commands, list) or not commands or not all(isinstance(item, str) and item.strip() for item in commands):
            raise VerificationError(f"scheduled record command evidence is invalid: {path}")
        action = record.get("action")
        if action not in {"BACKUP-LATEST", "NO_BACKUP_DATA_WRITE"}:
            raise VerificationError(f"unexpected scheduled action after natural ingest: {action}")
        raw_detail = require_mapping(record.get("detail"), f"{path} detail")
        if action == "BACKUP-LATEST":
            before = require_mapping(raw_detail.get("before"), "backup before state")
            detail = require_mapping(raw_detail.get("after"), "backup after state")
            if before.get("status") != "STALE" or before.get("backup_command") != "backup-latest" or before.get("backfill_required") is not False:
                raise VerificationError("BACKUP-LATEST did not advance an authenticated stale observation")
            writes += 1
        else:
            detail = raw_detail
        validate_component_state(detail, args.date.isoformat())
        relative = path.relative_to(target).as_posix()
        digest = sha256_file(path)
        link = record.get("previous_execution")
        if previous is None and link is not None:
            if not isinstance(link, Mapping) or set(link) != {"record_path", "record_sha256"}:
                raise VerificationError("first new scheduled predecessor is malformed")
            predecessor = (target / str(link["record_path"])).resolve(strict=True);predecessor.relative_to(target)
            if sha256_file(predecessor) != link.get("record_sha256"):
                raise VerificationError("first new scheduled predecessor digest changed")
        elif previous is not None and link != previous:
            raise VerificationError("new scheduled execution chain is gapped or branched")
        previous = {"record_path": relative, "record_sha256": digest}
        local_completed = completed.astimezone(HOBART_OFFSET)
        if time(5, 0) <= local_completed.time() < time(5, 30):
            natural_daily += 1
        evidence.append({"path": relative, "sha256": digest, "action": action, "completed_at": completed.isoformat()})
    if writes < 1:
        raise VerificationError("no BACKUP-LATEST PASS exists for the natural observation")
    pointer_path = target / "catalog/latest-scheduled.json"
    pointer = require_mapping(load_json_bytes(pointer_path.read_bytes(), str(pointer_path)), "latest scheduled pointer")
    if pointer != {**previous, "result": "PASS"}:
        raise VerificationError("latest scheduled pointer does not bind the complete append chain")
    return {"cutoff": cutoff.isoformat(), "records": evidence, "write_count": writes, "natural_daily_count": natural_daily, "latest_pointer": pointer}


def source_listing(args: argparse.Namespace, writer: EvidenceWriter) -> Mapping[str, Any]:
    helper = Path(args.source_helper).resolve(strict=True)
    if sha256_file(helper) != args.source_helper_sha256:
        raise VerificationError("Pi source helper digest is invalid")
    command = [
        args.ssh_bin, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.pi_host,
        "python3", "-", "list",
        "--expected-production-sha", args.protected_code_sha,
        "--candidate-code-sha", args.candidate_code_sha,
        "--plan-document-id", args.plan_document_id,
        "--plan-version", args.plan_version,
        "--plan-git-commit", args.plan_git_commit,
        "--plan-sha256", args.plan_sha256,
    ]
    result = run_capture(command, input_bytes=helper.read_bytes(), timeout=1200)
    writer.write("pi-source-listing-stdout.json", result.stdout)
    writer.write("pi-source-listing-stderr.txt", result.stderr)
    if result.returncode != 0:
        raise VerificationError(f"Pi source listing failed with exit {result.returncode}")
    listing = require_mapping(load_json_bytes(result.stdout, "Pi source listing"), "Pi source listing")
    if listing.get("ok") is not True:
        raise VerificationError("Pi source listing did not pass")
    status_args = SimpleNamespace(
        candidate_code_sha=args.candidate_code_sha,
        protected_code_sha=args.protected_code_sha,
        plan_git_commit=args.plan_git_commit,
    )
    status = scheduled.scheduled_status(receiver.canonical_target(Path(args.target)), listing, status_args)
    if status.get("status") != "UP_TO_DATE" or status.get("backfill_required") is not False:
        raise VerificationError(f"laptop backup does not match current Pi identities: {status}")
    return {"source_helper_sha256": sha256_file(helper), "status": status, "listing": listing}


def validate_catalog_and_receipts(args: argparse.Namespace) -> dict[str, Any]:
    target = receiver.canonical_target(Path(args.target))
    hygiene = contract.validate_hygiene(target, [])
    entries = receiver.catalog_entries(target / "catalog/generations.jsonl")
    if not entries or any(item.get("result") != "PASS" for item in entries):
        raise VerificationError("backup catalog is empty or contains a non-PASS entry")
    paths: dict[str, str] = {}
    receipt_evidence: dict[str, Any] = {}
    for kind, pointer_name in (("observation", "latest-verified.json"), ("control", "latest-control.json"), ("macro", "latest-macro.json")):
        receipt, _manifest, _entry, path = scheduled.pointer_generation(
            target,
            pointer_name,
            kind,
            candidate_sha=args.candidate_code_sha,
            protected_sha=args.protected_code_sha,
            plan_commit=args.plan_git_commit,
        )
        if kind == "observation" and receipt.get("observation_date") != args.date.isoformat():
            raise VerificationError("latest observation receipt has the wrong date")
        if not scheduled.has_component_restore_evidence(receipt.get("checks"), kind):
            raise VerificationError(f"{kind} receipt lacks restoration evidence")
        paths[kind] = str(path)
        receipt_evidence[kind] = {"path": str(path), "sha256": sha256_file(path), "checks": receipt.get("checks")}
    return {"entries": len(entries), "latest_sequence": entries[-1].get("sequence"), "receipts": receipt_evidence, "hygiene": hygiene}


def verify(args: argparse.Namespace, writer: EvidenceWriter) -> Mapping[str, object]:
    runtime = verify_runtime_source(args, Path(__file__))
    task = collect_task_snapshot(args, writer)
    dispatcher = validate_dispatcher(args)
    records = validate_new_records(args)
    ordered_dispatcher = sorted(dispatcher["executions"], key=lambda item: (datetime.fromisoformat(str(item["completed_at"])), str(item["path"])))
    ordered_records = sorted(records["records"], key=lambda item: (datetime.fromisoformat(str(item["completed_at"])), str(item["path"])))
    dispatcher_times = [datetime.fromisoformat(str(item["completed_at"])) for item in ordered_dispatcher]
    record_times = [datetime.fromisoformat(str(item["completed_at"])) for item in ordered_records]
    if len(dispatcher_times) != len(record_times) or any(
        dispatch_time < record_time or dispatch_time - record_time > timedelta(minutes=5)
        for dispatch_time, record_time in zip(dispatcher_times, record_times, strict=True)
    ):
        raise VerificationError("dispatcher and scheduled execution records are not one-to-one")
    last_run = datetime.fromisoformat(str(task["last_run_time"]))
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=HOBART_OFFSET)
    paired = list(zip(ordered_dispatcher, ordered_records, strict=True))
    matching_pairs = [
        (dispatch, record)
        for dispatch, record in paired
        if timedelta(0) <= datetime.fromisoformat(str(dispatch["started_at"])) - last_run <= timedelta(minutes=2)
    ]
    if len(matching_pairs) != 1:
        raise VerificationError("dispatcher history does not bind exactly one execution to the accepted Task Scheduler trigger")
    boot_time = datetime.fromisoformat(str(task["boot_time"]))
    if boot_time.tzinfo is None:
        boot_time = boot_time.replace(tzinfo=HOBART_OFFSET)
    daily_minimum = datetime.combine(args.date, time(5, 0), HOBART_OFFSET)
    daily_maximum = datetime.combine(args.date, time(5, 5), HOBART_OFFSET)
    startup_minimum = boot_time + timedelta(minutes=5)
    startup_maximum = startup_minimum + timedelta(minutes=5)
    natural_pairs = [
        (dispatch, record)
        for dispatch, record in paired
        if (
            daily_minimum <= datetime.fromisoformat(str(dispatch["started_at"])).astimezone(HOBART_OFFSET) < daily_maximum
            or (
                datetime.fromisoformat(str(dispatch["started_at"])).astimezone(HOBART_OFFSET).date() == args.date
                and startup_minimum <= datetime.fromisoformat(str(dispatch["started_at"])) <= startup_maximum
            )
        )
    ]
    if sum(1 for _dispatch, record in natural_pairs if record.get("action") == "BACKUP-LATEST") != 1:
        raise VerificationError("no unique BACKUP-LATEST record is bound to an authorized natural task trigger")
    catalog = validate_catalog_and_receipts(args)
    source = source_listing(args, writer)
    return {"date": args.date.isoformat(), "verifier": runtime, "task": task, "dispatcher": dispatcher, "scheduled_records": records, "catalog": catalog, "pi_source_equality": source}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--date", required=True, type=parse_date)
    value.add_argument("--evidence-root", required=True)
    value.add_argument("--target", required=True)
    value.add_argument("--receiver", required=True)
    value.add_argument("--implementation-root", required=True)
    value.add_argument("--implementation-commit", required=True)
    value.add_argument("--candidate-root", required=True)
    value.add_argument("--source-helper", required=True)
    value.add_argument("--source-helper-sha256", required=True)
    value.add_argument("--task-name", default="AR-local laptop backup")
    value.add_argument("--task-xml-sha256", required=True)
    value.add_argument("--task-sddl-sha256", required=True)
    value.add_argument("--runner-sha256", required=True)
    value.add_argument("--dispatcher-config-sha256", required=True)
    value.add_argument("--dispatcher-manifest-sha256", required=True)
    value.add_argument("--dispatcher-sha256", required=True)
    value.add_argument("--activation-receipt", required=True)
    value.add_argument("--activation-receipt-sha256", required=True)
    value.add_argument("--scheduled-plan-document-id", required=True)
    value.add_argument("--scheduled-plan-version", required=True)
    value.add_argument("--scheduled-plan-git-commit", required=True)
    value.add_argument("--scheduled-plan-sha256", required=True)
    value.add_argument("--scheduled-plan-normalized-sha256", required=True)
    value.add_argument("--scheduled-plan-raw-sha256", action="append", required=True)
    value.add_argument("--pi-host", default="ar-local-pi5-lan")
    value.add_argument("--ssh-bin", default="ssh")
    value.add_argument("--powershell", default="powershell.exe")
    add_identity_arguments(value)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    require_commit(args.implementation_commit, "implementation commit")
    require_commit(args.scheduled_plan_git_commit, "scheduled plan commit")
    for name in (
        "source_helper_sha256", "task_xml_sha256", "task_sddl_sha256",
        "runner_sha256", "dispatcher_config_sha256", "dispatcher_manifest_sha256",
        "dispatcher_sha256",
        "activation_receipt_sha256", "scheduled_plan_sha256",
        "scheduled_plan_normalized_sha256",
    ):
        require_sha256(getattr(args, name), name.replace("_", " "))
    for digest in args.scheduled_plan_raw_sha256:
        require_sha256(digest, "scheduled plan raw SHA-256")
    return fail_closed_main(args, "natural-backup-verification", verify)


if __name__ == "__main__":
    raise SystemExit(main())
