"""Accept backup evidence only after the entire isolated worker has stopped."""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

from ar_local_operation_lock import production_lock
from pi_drive_backup_resources import require_receipt, supervise


def execute_worker(config, command, *, force, full, operation):
    import pi_drive_backup as backup
    request = {"config": {key: str(value) if isinstance(value, Path) else
        [str(item) for item in value] if key == "controls" else value
        for key, value in asdict(config).items()}, "command": command, "force": force, "full": full,
        "supervisor_pid": os.getpid()}
    backup.atomic_json(operation / "request.json", request, immutable=True)
    resources = supervise([sys.executable, str(Path(backup.__file__).resolve()),
        command, "--worker-request", str(operation / "request.json")], operation / "resources.json", guard=backup.guard_window)
    if resources.get("result") == "BLOCKED":
        raise backup.Blocked(str(resources.get("reason", "Drive resource admission blocked")))
    candidate_path = operation / "candidate.json"
    if (resources.get("workload_exit_code") == 2 and resources.get("group_clean") is True
            and resources.get("reason") == "RuntimeError: workload_failed_or_left_descendants"
            and candidate_path.is_file() and not candidate_path.is_symlink() and candidate_path.stat().st_size <= 16 * 1024**2):
        blocked = json.loads(candidate_path.read_text(encoding="utf-8"))
        if isinstance(blocked, dict) and blocked.get("result") == "BLOCKED":
            raise backup.Blocked(str(blocked.get("error", "protected worker blocked")))
    require_receipt(resources)
    if candidate_path.is_symlink() or candidate_path.stat().st_size > 16 * 1024**2:
        raise ValueError("unsafe or oversized worker candidate")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(candidate, dict) or candidate.get("result") != "PASS":
        raise RuntimeError("worker did not produce successful candidate evidence")
    return candidate


def validate_binding(spool, value):
    """Old/forged/failed resource evidence cannot turn same-day NO_WORK green."""
    from pi_drive_backup_source import digest
    binding = value.get("resource_evidence", {})
    if not isinstance(binding, dict) or not re.fullmatch(r"resource-runs/[a-f0-9]{32}", str(binding.get("path", ""))):
        raise ValueError("accepted backup lacks bounded resource evidence")
    directory = spool / binding["path"]
    for name in ("resources", "candidate", "request"):
        path = directory / f"{name}.json"
        if (path.resolve() != path or path.stat().st_size > 16 * 1024**2
                or not re.fullmatch(r"[a-f0-9]{64}", str(binding.get(f"{name}_sha256", "")))
                or digest(path) != binding[f"{name}_sha256"]):
            raise ValueError("accepted resource evidence hash differs")
    require_receipt(json.loads((directory / "resources.json").read_text(encoding="utf-8")))
    candidate = json.loads((directory / "candidate.json").read_text(encoding="utf-8"))
    if candidate != {key: item for key, item in value.items() if key != "resource_evidence"}:
        raise ValueError("accepted backup differs from supervised candidate")


def run_protected(config, command="run", *, force=False, full=False):
    import pi_drive_backup as backup
    ready = backup.readiness(config)
    if ready["result"] != "PASS":
        raise backup.Blocked("; ".join(ready["reasons"]))
    config.spool.mkdir(parents=True, exist_ok=True, mode=0o700)
    with production_lock(config.spool / "backup.lock", "drive-backup"):
        operation = config.spool / "resource-runs" / uuid.uuid4().hex
        operation.mkdir(parents=True, mode=0o700)
        candidate = execute_worker(config, command, force=force, full=full, operation=operation)
        resources = json.loads((operation / "resources.json").read_text(encoding="utf-8"))
        require_receipt(resources)
        backup.guard_window()
        accepted = {**candidate, "resource_evidence": {"path": operation.relative_to(config.spool).as_posix(),
            **{f"{name}_sha256": backup.digest(operation / f"{name}.json") for name in ("request", "candidate", "resources")}}}
        validate_binding(config.spool, accepted)
        if command == "run" and candidate.get("action") != "NO_WORK":
            if not re.fullmatch(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{12}", str(candidate.get("run_id", ""))):
                raise ValueError("worker backup identity is invalid")
            requests = candidate.get("request_ids")
            if not isinstance(requests, list) or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{32}", item) for item in requests):
                raise ValueError("worker queue acknowledgement identity is invalid")
            backup.atomic_json(config.spool / "receipts" / f"{candidate['run_id']}.PASS.json", accepted, immutable=True)
            backup.atomic_json(config.spool / "latest-verified.json", accepted)
            for identifier in requests:
                (config.spool / "requests" / f"{identifier}.json").unlink(missing_ok=True)
        else:
            backup.atomic_json(operation / "accepted.json", accepted, immutable=True)
        return accepted


def worker(request_path):
    """Internal workers can only emit candidates; they never accept/acknowledge."""
    import pi_drive_backup as backup
    if (not request_path.is_absolute() or request_path.resolve() != request_path
            or request_path.name != "request.json" or request_path.stat().st_size > 64 * 1024):
        raise ValueError("worker requires a private canonical request")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    from pi_drive_backup_resources import own_cgroup, members
    group = own_cgroup()
    if request.get("supervisor_pid") != os.getppid() or os.getppid() not in members(group):
        raise RuntimeError("private worker requires its live resource supervisor")
    config_args = request["config"]
    for key in ("data", "spool", "password", "rclone_config"):
        config_args[key] = Path(config_args[key])
    config_args["controls"] = [Path(value) for value in config_args["controls"]]
    config = backup.Config(**config_args)
    if request_path.parent.parent != config.spool / "resource-runs":
        raise ValueError("worker request is outside its operation spool")
    # Readiness is local here; all network commands stay in this supervised child.
    ready = backup.readiness(config)
    if ready["result"] != "PASS":
        raise backup.Blocked("; ".join(ready["reasons"]))
    try:
        from pi_drive_backup_diagnostics import operation_scope
        with operation_scope(request_path.parent):
            result = worker_action(config, request)
    except (OSError, ValueError, RuntimeError) as error:
        result = {"result": "BLOCKED" if isinstance(error, backup.Blocked) else "FAIL", "error": str(error)}
    backup.atomic_json(request_path.parent / "candidate.json", result, immutable=True)
    return result


def worker_action(config, request):
    import pi_drive_backup as backup
    command = request["command"]
    if command == "run":
        result = backup._run_locked(config, force=request["force"])
    elif command == "init":
        backup.Restic(config).run("init", "--repository-version", "2")
        result = {"result": "PASS", "action": "INITIALIZED", "backup": "NOT_RUN"}
    elif command == "restore":
        result = backup.restore_accepted(config, full=request["full"])
    elif command == "readiness":
        backup.Restic(config).run("cat", "config")
        result = {"schema": backup.SCHEMA, "result": "PASS", "remote_checked": True,
                  "reasons": [], "retention": "all snapshots; no pruning"}
    else:
        raise ValueError("unsupported protected worker action")
    return result
