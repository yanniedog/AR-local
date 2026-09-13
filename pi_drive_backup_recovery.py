"""Verify an already uploaded snapshot after a narrowly identified output failure.

Recovery is an explicit, hash-pinned run mode. It never freezes current source,
uploads a replacement, rewrites failed evidence, or acknowledges queue requests.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import tempfile
import uuid

SCHEMA = "ar-local-drive-recovery-input-v1"
OUTPUT_FAILURE = "restic command output exceeded bounded receipt limit"
HEX = re.compile(r"[0-9a-f]{64}")
ID = re.compile(r"[0-9a-f]{32}")
RUN = re.compile(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{12}")
HASHES = {"request", "resources", "candidate", "failure", "running", "diagnostic_started",
          "diagnostic_process", "diagnostic_result", "capture_started", "capture_terminal", "manifest"}


def small(path: Path, maximum=65536):
    if path.resolve() != path or path.is_symlink() or not path.is_file():
        raise ValueError("unsafe recovery evidence")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("oversized recovery evidence")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("invalid recovery evidence JSON") from None
    if not isinstance(value, dict):
        raise ValueError("recovery evidence must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def descriptor(path: Path, expected_sha: str) -> dict:
    value, actual = small(path)
    if not isinstance(expected_sha, str) or not HEX.fullmatch(expected_sha) or actual != expected_sha:
        raise ValueError("recovery descriptor hash differs")
    if (set(value) != {"schema", "source_operation", "source_run_id", "diagnostic_id", "capture_directory", "snapshot_id", "capture_helper_sha256", "hashes"}
            or value.get("schema") != SCHEMA or not ID.fullmatch(str(value.get("source_operation", "")))
            or not RUN.fullmatch(str(value.get("source_run_id", "")))
            or not ID.fullmatch(str(value.get("diagnostic_id", "")))
            or not re.fullmatch(r"stdout-capture-[a-zA-Z0-9-]{1,100}", str(value.get("capture_directory", "")))
            or not HEX.fullmatch(str(value.get("snapshot_id", "")))
            or not HEX.fullmatch(str(value.get("capture_helper_sha256", "")))
            or not isinstance(value.get("hashes"), dict) or set(value["hashes"]) != HASHES
            or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in value["hashes"].values())):
        raise ValueError("invalid recovery descriptor binding")
    return {"descriptor": value, "descriptor_sha256": actual}


def evidence_paths(spool, spec):
    operation = spool / "resource-runs" / spec["source_operation"]
    diagnostic = operation / "diagnostics" / spec["diagnostic_id"]
    capture = spool / spec["capture_directory"]
    return {**{key: operation / (key + ".json") for key in ("request", "resources", "candidate")},
        **{key: diagnostic / (name + ".json") for key, name in
           (("diagnostic_started", "started"), ("diagnostic_process", "process"), ("diagnostic_result", "result"))},
        "failure": spool / "receipts" / (spec["source_run_id"] + ".FAIL.json"),
        "running": spool / "receipts" / (spec["source_run_id"] + ".RUNNING.json"),
        "capture_started": capture / "started.json", "capture_terminal": capture / "terminal.json",
        "manifest": spool / "manifests" / (spec["source_run_id"] + ".json")}


def _same_config(old, config):
    # Controls may now point to the newly tested immutable runtime. Source,
    # repository and credential references must still identify the same backup.
    expected = {"data": str(config.data), "spool": str(config.spool), "repository": config.repository,
                "password": str(config.password), "rclone_config": str(config.rclone_config),
                "restic": config.restic, "rclone": config.rclone, "min_free_bytes": config.min_free_bytes}
    return isinstance(old, dict) and all(old.get(key) == value for key, value in expected.items())


def _source_receipts(spec, rows, config):
    from process_safety import process_alive
    request, resources, failed = (rows[key] for key in ("request", "resources", "failure"))
    owner = request.get("supervisor_pid")
    if (request.get("command") != "run" or request.get("recovery") is not None
            or type(owner) is not int or owner <= 0 or process_alive(owner)
            or not _same_config(request.get("config"), config)):
        raise ValueError("original backup request is not a stopped matching source")
    if (resources.get("schema") != "ar-local-drive-resources-v1" or resources.get("result") != "FAIL"
            or resources.get("group_clean") is not True or type(resources.get("workload_exit_code")) is not int or resources["workload_exit_code"] != 1
            or resources.get("reason") != "RuntimeError: workload_failed_or_left_descendants"
            or resources.get("cgroup") != "/sys/fs/cgroup/system.slice/ar-local-drive-backup.service"
            or "cleanup_error" in resources):
        raise ValueError("original backup did not finish with a clean output-only failure")
    for value in (failed, rows["candidate"]):
        if value.get("result") != "FAIL" or value.get("error") != OUTPUT_FAILURE:
            raise ValueError("original failure is not the supported stdout-limit failure")
    running = rows["running"]
    if (failed.get("run_id") != spec["source_run_id"] or running.get("run_id") != spec["source_run_id"]
            or running.get("result") != "RUNNING" or failed.get("started_at") != running.get("started_at")
            or failed.get("manifest_path") != "manifests/" + spec["source_run_id"] + ".json"
            or failed.get("manifest_sha256") != spec["hashes"]["manifest"]
            or not HEX.fullmatch(str(failed.get("content_sha256", "")))):
        raise ValueError("original run and manifest receipts disagree")
    began, ended = (datetime.fromisoformat(failed[key]) for key in ("started_at", "finished_at"))
    if began.tzinfo is None or ended.tzinfo is None or ended < began:
        raise ValueError("invalid original backup timestamps")
    return owner, began


def _capture_receipts(spec, rows, owner):
    started, done = rows["diagnostic_started"], rows["diagnostic_result"]
    worker, process = started.get("worker_pid"), rows["diagnostic_process"].get("process_pid")
    if any(type(pid) is not int or pid <= 0 for pid in (worker, process)):
        raise ValueError("invalid original diagnostic process")
    for value in (started, done):
        if (value.get("schema") != "ar-local-drive-command-diagnostic-v1" or value.get("command") != "backup"
                or value.get("operation_id") != spec["source_operation"] or value.get("request_sha256") != spec["hashes"]["request"]
                or value.get("supervisor_pid") != owner or value.get("worker_pid") != worker):
            raise ValueError("original diagnostic binding differs")
    if (started.get("result") != "STARTED" or done.get("result") != "EXITED" or type(done.get("exit_code")) is not int or done["exit_code"] != 0
            or done.get("reader_complete") is not True or done.get("reader_error") is not False
            or done.get("category") != "NONE" or done.get("process_pid") != process):
        raise ValueError("original Restic command did not complete successfully")
    capture, terminal = rows["capture_started"], rows["capture_terminal"]
    if any(terminal.get(key) != value for key, value in capture.items()):
        raise ValueError("stdout capture start/terminal binding differs")
    if (capture.get("purpose") != "PRIVATE_STDOUT_EVIDENCE_NOT_BACKUP_ACCEPTANCE"
            or capture.get("operation") != spec["source_operation"] or capture.get("request_sha256") != spec["hashes"]["request"]
            or capture.get("supervisor_pid") != owner or capture.get("worker_pid") != worker
            or capture.get("restic_pid") != process or capture.get("helper_sha256") != spec["capture_helper_sha256"]
            or terminal.get("result") != "CAPTURE_COMPLETE" or type(terminal.get("command_exit_code")) is not int or terminal["command_exit_code"] != 0
            or terminal.get("acceptance_verified") is not False
            or type(terminal.get("captured_bytes")) is not int or not 16 * 1024**2 < terminal["captured_bytes"] <= 256 * 1024**2
            or not HEX.fullmatch(str(terminal.get("stdout_sha256", "")))
            or not isinstance(terminal.get("summaries"), list) or len(terminal["summaries"]) != 1
            or not isinstance(terminal["summaries"][0], dict) or terminal["summaries"][0].get("snapshot_id") != spec["snapshot_id"]):
        raise ValueError("original stdout capture is incomplete or mismatched")


def recovery_admission(config, command, recovery):
    import pi_drive_backup as backup
    from pi_drive_backup_resources import own_cgroup
    backup.guard_window()
    if command != "run" or str(own_cgroup()) != "/sys/fs/cgroup/system.slice/ar-local-drive-backup.service":
        raise ValueError("snapshot recovery requires the fixed backup service")
    # Initial commissioning only: never overwrite an existing accepted backup.
    latest = config.spool / "latest-verified.json"
    if latest.exists() or latest.is_symlink():
        raise backup.Blocked("existing accepted backup prevents initial snapshot recovery")
    if not isinstance(recovery, dict) or set(recovery) != {"descriptor", "descriptor_sha256"}:
        raise ValueError("invalid recovery request")
    return recovery


def recovery_acceptance(config, recovery, accepted):
    import pi_drive_backup as backup
    from pi_drive_backup_resources import own_cgroup
    if str(own_cgroup()) != "/sys/fs/cgroup/system.slice/ar-local-drive-backup.service":
        raise ValueError("recovery acceptance requires the fixed backup service")
    latest = config.spool / "latest-verified.json"
    spec = recovery["descriptor"]
    if latest.exists() or latest.is_symlink():
        raise backup.Blocked("accepted backup appeared during snapshot recovery")
    if (accepted.get("acquisition") != "recovered_snapshot" or accepted.get("recovery") != recovery
            or accepted.get("snapshot_id") != spec["snapshot_id"] or accepted.get("source_run_id") != spec["source_run_id"]
            or accepted.get("manifest_sha256") != spec["hashes"]["manifest"] or accepted.get("request_ids") != []
            or accepted.get("uploaded_bytes") != 0 or accepted.get("repository_check") != "PASS"
            or not isinstance(accepted.get("restore"), dict) or accepted["restore"].get("result") != "PASS"
            or accepted["restore"].get("full") is not True):
        raise ValueError("recovery candidate lacks complete same-snapshot restore evidence")
    backup.guard_window()


def verified_source(config, recovery):
    import pi_drive_backup as backup
    from pi_drive_backup_output import backup_summary
    spec = recovery["descriptor"]
    paths = evidence_paths(config.spool, spec)
    rows = {}
    for key, path in paths.items():
        backup.guard_window()
        if key == "manifest":
            if path.resolve() != path or path.is_symlink() or backup.digest(path, backup.guard_window) != spec["hashes"][key]:
                raise ValueError("recovery manifest hash differs")
        else:
            value, sha = small(path)
            if sha != spec["hashes"][key]:
                raise ValueError("recovery evidence hash differs")
            rows[key] = value
    owner, began = _source_receipts(spec, rows, config)
    _capture_receipts(spec, rows, owner)
    raw = config.spool / spec["capture_directory"] / "stdout.private.jsonl"
    terminal = rows["capture_terminal"]
    if (raw.resolve() != raw or raw.is_symlink() or raw.stat().st_size != terminal["captured_bytes"]
            or backup.digest(raw, backup.guard_window) != terminal["stdout_sha256"]):
        raise ValueError("captured stdout bytes differ")
    with raw.open("rb") as stream:
        summary = json.loads(backup_summary(stream, guard=backup.guard_window))
    if summary["snapshot_id"] != spec["snapshot_id"]:
        raise ValueError("captured final snapshot differs")
    return spec, paths, rows, began, summary


def recover_snapshot(config, recovery):
    import pi_drive_backup as backup
    spec, paths, rows, began, summary = verified_source(config, recovery)
    started = backup.now()
    if began.astimezone(backup.TZ).date() > started.date():
        raise ValueError("source backup date is in the future")
    with tempfile.TemporaryDirectory(prefix="recovery-index-", dir=config.spool) as temporary:
        manifest = backup.load_manifest(paths["manifest"], Path(temporary) / "manifest.sqlite")
        try:
            if manifest.get("content_sha256") != rows["failure"]["content_sha256"]:
                raise ValueError("recovery manifest content identity differs")
            client = backup.Restic(config)
            client.run("check")
            restore = backup.restore_snapshot(config, client, spec["snapshot_id"], manifest,
                                               full=True, manifest_path=paths["manifest"])
            if restore.get("result") != "PASS" or restore.get("full") is not True:
                raise ValueError("full recovery restore verification did not pass")
            stats = json.loads(client.run("stats", "--mode", "raw-data", "--json"))
            # Detect replaced provenance/manifest after the remote operation too.
            verified_source(config, recovery)
            return {"schema": backup.SCHEMA, "result": "PASS", "action": "BACKUP",
                "acquisition": "recovered_snapshot", "run_id": started.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12],
                "started_at": started.isoformat(), "finished_at": backup.now().isoformat(),
                "backup_date": began.astimezone(backup.TZ).date().isoformat(), "source_started_at": began.isoformat(),
                "source_run_id": spec["source_run_id"], "snapshot_id": spec["snapshot_id"],
                "manifest_path": rows["failure"]["manifest_path"], "manifest_sha256": spec["hashes"]["manifest"],
                "content_sha256": manifest["content_sha256"], "repository_check": "PASS", "restore": restore,
                "restore_verified_at": backup.now().isoformat(), "restore_rotation": 1,
                "repository_stored_bytes": stats.get("total_size"), "uploaded_bytes": 0,
                "original_upload_summary": summary, "request_ids": [], "recovery": recovery}
        finally:
            backup.close_manifest(manifest)
