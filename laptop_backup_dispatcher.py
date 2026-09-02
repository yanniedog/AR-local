"""Fixed, non-elevated dispatcher for the AR-local laptop backup task.

Task Scheduler points at an administrator-protected copy of this module.  The
ordinary operator changes candidates by atomically activating a strict,
content-addressed manifest; the scheduled-task definition never changes again.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from laptop_backup_atomic import atomic_create, atomic_replace, fsync_directory
from laptop_backup_dispatcher_security import (
    ACTIVATION_ID,
    BOOTSTRAP_GATE_NAME,
    MANIFEST_KEYS,
    PLAN_ID,
    POINTER_KEYS,
    POINTER_SCHEMA_VERSION,
    SCHEMA_VERSION,
    SHA40,
    SHA256,
    canonical_json,
    canonical_unlinked,
    current_sid,
    git_detached,
    git_state,
    is_admin,
    is_reparse,
    latest_authority_commit,
    parse_json,
    parse_time,
    require_hash,
    require_limited_identity,
    require_within,
    sha256_bytes,
    sha256_file,
    strict_object,
    test_override_enabled,
    token_facts,
    validate_lineage_manifest,
    validate_manifest,
)


def layout(control_root: Path, *, create: bool = True) -> dict[str, Path]:
    root = canonical_unlinked(control_root, "control root", file=False)
    result = {
        "root": root, "manifests": root / "manifests", "receipts": root / "activation-receipts",
        "lease_recoveries": root / "lease-recoveries",
        "executions": root / "dispatcher-executions",
        "pointer": root / "active-runner.json", "lease": root / "transition.lease",
    }
    for name in ("manifests", "receipts", "lease_recoveries", "executions"):
        if create:
            result[name].mkdir(exist_ok=True)
        if not result[name].is_dir() or is_reparse(result[name]):
            raise ValueError(f"active control directory is absent or linked: {name}")
    return result


def receipt_path(paths: Mapping[str, Path], manifest: Mapping[str, object], status: str) -> Path:
    return paths["receipts"] / f"{int(manifest['sequence']):08d}-{manifest['activation_id']}-{status.lower()}.json"


def receipt_ledger(paths: Mapping[str, Path]) -> tuple[int, set[str]]:
    maximum = 0
    identities: dict[str, int] = {}
    outcomes: dict[str, list[dict[str, object]]] = {}
    for path in sorted(paths["receipts"].glob("*.json")):
        value = parse_json(path.read_bytes(), "activation receipt")
        if set(value) != {
            "schema_version", "sequence", "activation_id", "manifest_sha256",
            "previous_manifest_sha256", "status",
        } or value.get("schema_version") != 1:
            raise ValueError("activation receipt fields are invalid")
        sequence = value.get("sequence")
        activation_id = value.get("activation_id")
        if not isinstance(sequence, int) or sequence < 1:
            raise ValueError("activation receipt sequence is invalid")
        require_hash(activation_id, ACTIVATION_ID, "receipt activation ID")
        require_hash(value.get("manifest_sha256"), SHA256, "receipt manifest digest")
        previous = value.get("previous_manifest_sha256")
        if previous is not None:
            require_hash(previous, SHA256, "receipt predecessor digest")
        status = value.get("status")
        if status not in {"PENDING", "PASS", "ROLLED_BACK", "ABANDONED"} or path != receipt_path(paths, value, str(status)):
            raise ValueError("activation receipt status or path is invalid")
        prior = identities.setdefault(str(activation_id), sequence)
        if prior != sequence:
            raise ValueError("activation ID was reused at another sequence")
        outcomes.setdefault(str(activation_id), []).append(dict(value))
        maximum = max(maximum, sequence)
    for receipts in outcomes.values():
        pending = [item for item in receipts if item["status"] == "PENDING"]
        terminal = [item for item in receipts if item["status"] != "PENDING"]
        if len(pending) != 1 or len(terminal) > 1:
            raise ValueError("activation must have one PENDING and at most one terminal receipt")
        if terminal:
            expected_terminal = dict(pending[0])
            expected_terminal["status"] = terminal[0]["status"]
            if terminal[0] != expected_terminal:
                raise ValueError("activation terminal receipt differs from its PENDING receipt")
    return maximum, set(identities)


def immutable_write(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"immutable artifact changed: {path}")
        return
    atomic_create(path, payload)


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def recover_expired_lease(paths: Mapping[str, Path]) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if not paths["lease"].exists():
        return
    stale_payload = paths["lease"].read_bytes()
    stale = parse_json(stale_payload, "transition lease")
    if set(stale) != {"schema_version", "pid", "activation_id", "created_at", "expires_at"}:
        raise ValueError("transition lease fields are invalid")
    expires = parse_time(stale.get("expires_at"), "lease expires_at")
    pid = stale.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        raise ValueError("transition lease PID is invalid")
    if expires > now or process_alive(pid):
        raise ValueError("candidate transition lease is active")
    recovery = paths["lease_recoveries"] / f"{sha256_bytes(stale_payload)}.json"
    if recovery.exists():
        if recovery.read_bytes() != stale_payload:
            raise ValueError("lease recovery artifact changed")
        paths["lease"].unlink()
    else:
        paths["lease"].replace(recovery)
    fsync_directory(paths["root"])


def require_activation_window() -> None:
    """Keep the complete transition lease outside the protected ingest window."""
    local = datetime.now().astimezone()
    minutes = local.hour * 60 + local.minute
    # D-006 freezes changes from 00:30 until the natural ingest has been
    # validated.  A transition lease lasts 15 minutes, so stop admitting new
    # activations at 00:15.  The conservative 03:30 end avoids guessing that a
    # slow ingest has completed.
    if 15 <= minutes < 210:
        raise ValueError("candidate activation is inside the protected ingest window")


def acquire_lease(paths: Mapping[str, Path], activation_id: str) -> bytes:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    recover_expired_lease(paths)
    payload = canonical_json({
        "schema_version": 1, "pid": os.getpid(), "activation_id": activation_id,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
    })
    atomic_create(paths["lease"], payload)
    return payload


def acquire_bootstrap_gate() -> int | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, 1, BOOTSTRAP_GATE_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        raise ValueError("trusted bootstrap gate blocks dispatcher activation")
    return int(handle)


def release_bootstrap_gate(handle: int | None) -> None:
    if handle is None:
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
    kernel32.ReleaseMutex.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    released = kernel32.ReleaseMutex(handle)
    release_error = ctypes.get_last_error()
    closed = kernel32.CloseHandle(handle)
    close_error = ctypes.get_last_error()
    if not released:
        raise ctypes.WinError(release_error)
    if not closed:
        raise ctypes.WinError(close_error)


def release_lease(paths: Mapping[str, Path], payload: bytes) -> None:
    if not paths["lease"].exists() or paths["lease"].read_bytes() != payload:
        raise ValueError("transition lease ownership changed")
    paths["lease"].unlink()
    fsync_directory(paths["root"])


def active(paths: Mapping[str, Path]) -> tuple[dict[str, object], dict[str, object], str] | None:
    pointer_path = paths["pointer"]
    if not pointer_path.exists():
        return None
    pointer = parse_json(pointer_path.read_bytes(), "active pointer")
    if set(pointer) != POINTER_KEYS or pointer.get("schema_version") != POINTER_SCHEMA_VERSION:
        raise ValueError("active pointer fields are not exact")
    digest = require_hash(pointer.get("manifest_sha256"), SHA256, "active manifest digest")
    manifest_path = paths["manifests"] / f"{digest}.json"
    payload = manifest_path.read_bytes()
    if sha256_bytes(payload) != digest:
        raise ValueError("active manifest bytes do not match the pointer")
    manifest = validate_manifest(parse_json(payload, "active manifest"), activation=False)
    if pointer != {
        "schema_version": POINTER_SCHEMA_VERSION,
        "sequence": manifest["sequence"],
        "activation_id": manifest["activation_id"],
        "manifest_sha256": digest,
    }:
        raise ValueError("active pointer identity is inconsistent")
    passed = receipt_path(paths, manifest, "PASS")
    if not passed.exists():
        raise ValueError("active manifest lacks terminal PASS receipt")
    receipt = parse_json(passed.read_bytes(), "PASS receipt")
    expected = {
        "schema_version": 1, "sequence": manifest["sequence"],
        "activation_id": manifest["activation_id"], "manifest_sha256": digest,
        "previous_manifest_sha256": manifest["previous_manifest_sha256"], "status": "PASS",
    }
    if receipt != expected:
        raise ValueError("active PASS receipt is invalid")
    return dict(pointer), manifest, digest


def reconcile(paths: Mapping[str, Path]) -> None:
    """Finish or roll back an activation interrupted after pointer replacement."""
    pointer: Mapping[str, object] | None = None
    digest: str | None = None
    if paths["pointer"].exists():
        pointer = parse_json(paths["pointer"].read_bytes(), "recovery pointer")
        if set(pointer) != POINTER_KEYS:
            raise ValueError("recovery pointer fields are invalid")
        digest = require_hash(pointer.get("manifest_sha256"), SHA256, "recovery manifest digest")
    pending_files = sorted(paths["receipts"].glob(f"*-*-pending.json"))
    pending: Mapping[str, object] | None = None
    for path in pending_files:
        candidate = parse_json(path.read_bytes(), "PENDING receipt")
        candidate_digest = require_hash(
            candidate.get("manifest_sha256"), SHA256, "PENDING manifest digest"
        )
        terminal = any(
            receipt_path(paths, candidate, status).exists()
            for status in ("PASS", "ROLLED_BACK", "ABANDONED")
        )
        if terminal:
            continue
        if candidate_digest == digest:
            if pending is not None:
                raise ValueError("activation has duplicate PENDING receipts")
            pending = candidate
        else:
            abandoned = dict(candidate)
            abandoned["status"] = "ABANDONED"
            immutable_write(
                receipt_path(paths, candidate, "ABANDONED"), canonical_json(abandoned)
            )
    if pending is None:
        return
    pass_path = receipt_path(paths, pending, "PASS")
    if pass_path.exists():
        return
    try:
        raw = (paths["manifests"] / f"{digest}.json").read_bytes()
        if sha256_bytes(raw) != digest:
            raise ValueError("interrupted manifest hash mismatch")
        manifest = validate_manifest(parse_json(raw, "interrupted manifest"), activation=False)
        if pointer.get("sequence") != manifest["sequence"] or pointer.get("activation_id") != manifest["activation_id"]:
            raise ValueError("interrupted pointer identity mismatch")
        # A valid interrupted pointer remains PENDING until the exact operator
        # token performs the live check-only proof in finalize_pending().
        return
    except Exception:
        previous = pending.get("previous_manifest_sha256")
        if previous is None:
            paths["pointer"].unlink(missing_ok=True)
            fsync_directory(paths["root"])
        else:
            previous_digest = require_hash(previous, SHA256, "recovery predecessor digest")
            raw = (paths["manifests"] / f"{previous_digest}.json").read_bytes()
            if sha256_bytes(raw) != previous_digest:
                raise ValueError("recovery predecessor hash mismatch")
            prior = validate_manifest(parse_json(raw, "recovery predecessor"), activation=False)
            prior_pointer = {
                "schema_version": POINTER_SCHEMA_VERSION, "sequence": prior["sequence"],
                "activation_id": prior["activation_id"], "manifest_sha256": previous_digest,
            }
            atomic_replace(paths["pointer"], canonical_json(prior_pointer))
            active(paths)
        rolled_back = dict(pending)
        rolled_back["status"] = "ROLLED_BACK"
        immutable_write(receipt_path(paths, pending, "ROLLED_BACK"), canonical_json(rolled_back))


def pending_activation(
    paths: Mapping[str, Path],
) -> tuple[dict[str, object], dict[str, object], str, dict[str, object]] | None:
    reconcile(paths)
    if not paths["pointer"].exists():
        return None
    pointer = parse_json(paths["pointer"].read_bytes(), "pending pointer")
    digest = require_hash(pointer.get("manifest_sha256"), SHA256, "pending manifest digest")
    raw = (paths["manifests"] / f"{digest}.json").read_bytes()
    if sha256_bytes(raw) != digest:
        raise ValueError("pending manifest hash mismatch")
    manifest = validate_manifest(parse_json(raw, "pending manifest"), activation=False)
    pass_path = receipt_path(paths, manifest, "PASS")
    if pass_path.exists():
        return None
    pending_path = receipt_path(paths, manifest, "PENDING")
    pending = parse_json(pending_path.read_bytes(), "PENDING receipt")
    expected = {
        "schema_version": 1, "sequence": manifest["sequence"],
        "activation_id": manifest["activation_id"], "manifest_sha256": digest,
        "previous_manifest_sha256": manifest["previous_manifest_sha256"], "status": "PENDING",
    }
    if pending != expected:
        raise ValueError("PENDING receipt is invalid")
    return dict(pointer), manifest, digest, dict(pending)


def check_only_proof(manifest: Mapping[str, object]) -> None:
    command = [
        str(manifest["python_path"]),
        str(Path(str(manifest["receiver"])) / "laptop_backup_scheduled.py"),
        "--target", str(manifest["target"]),
        "--recovery-image", str(manifest["recovery_image"]),
        "--candidate-code-sha", str(manifest["candidate_code_sha"]),
        "--protected-code-sha", str(manifest["protected_code_sha"]),
        "--plan-git-commit", str(manifest["scheduled_plan_git_commit"]),
        "--operator", str(manifest["operator"]), "--check-only",
    ]
    if os.spawnv(os.P_WAIT, command[0], command) != 0:
        raise ValueError("fresh non-elevated check-only proof failed")


def restore_pending_predecessor(
    paths: Mapping[str, Path], manifest: Mapping[str, object], pending: Mapping[str, object]
) -> None:
    previous = manifest["previous_manifest_sha256"]
    if previous is None:
        paths["pointer"].unlink(missing_ok=True)
        fsync_directory(paths["root"])
    else:
        previous_digest = require_hash(previous, SHA256, "pending predecessor digest")
        raw = (paths["manifests"] / f"{previous_digest}.json").read_bytes()
        if sha256_bytes(raw) != previous_digest:
            raise ValueError("pending predecessor hash mismatch")
        prior = validate_manifest(parse_json(raw, "pending predecessor"), activation=False)
        prior_pointer = {
            "schema_version": 1, "sequence": prior["sequence"],
            "activation_id": prior["activation_id"], "manifest_sha256": previous_digest,
        }
        atomic_replace(paths["pointer"], canonical_json(prior_pointer))
        active(paths)
    rolled_back = dict(pending)
    rolled_back["status"] = "ROLLED_BACK"
    immutable_write(receipt_path(paths, manifest, "ROLLED_BACK"), canonical_json(rolled_back))


def finalize_pending(paths: Mapping[str, Path]) -> dict[str, object]:
    state = pending_activation(paths)
    if state is None:
        current = active(paths)
        if current is None:
            raise ValueError("dispatcher has no activation to finalize")
        pointer, manifest, digest = current
        proof = require_limited_identity(manifest)
        return {
            "ok": True, "result": "PASS", "mode": "ALREADY_FINALIZED",
            **proof, "sequence": pointer["sequence"],
            "candidate_code_sha": manifest["candidate_code_sha"], "manifest_sha256": digest,
        }
    pointer, manifest, digest, pending = state
    proof = require_limited_identity(manifest)
    try:
        check_only_proof(manifest)
        passed = dict(pending)
        passed["status"] = "PASS"
        immutable_write(receipt_path(paths, manifest, "PASS"), canonical_json(passed))
        active(paths)
    except BaseException:
        restore_pending_predecessor(paths, manifest, pending)
        raise
    return {
        "ok": True, "result": "PASS", "mode": "FINALIZE", **proof,
        "sequence": pointer["sequence"], "candidate_code_sha": manifest["candidate_code_sha"],
        "manifest_sha256": digest,
    }


def probe(control_root: Path) -> dict[str, object]:
    paths = layout(control_root)
    reconcile(paths)
    state = active(paths)
    if state is None:
        raise ValueError("dispatcher has no active manifest")
    pointer, manifest, digest = state
    proof = require_limited_identity(manifest)
    return {
        "ok": True, "result": "PASS", "mode": "PROBE", **proof, "sequence": pointer["sequence"],
        "candidate_code_sha": manifest["candidate_code_sha"],
        "manifest_sha256": digest,
    }


def write_dispatcher_execution(
    paths: Mapping[str, Path], payload: Mapping[str, object]
) -> tuple[Path, str]:
    raw = canonical_json(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = paths["executions"] / f"{stamp}-{uuid.uuid4().hex}.json"
    immutable_write(path, raw)
    return path, sha256_bytes(raw)


def run(control_root: Path) -> int:
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    paths = layout(control_root)
    result: dict[str, object] = {"ok": False, "result": "FAIL", "mode": "RUN"}
    child_exit_code = 1
    error: str | None = None
    manifest: Mapping[str, object] | None = None
    digest: str | None = None
    command: list[str] = []
    lease_payload: bytes | None = None
    try:
        lease_payload = acquire_lease(paths, uuid.uuid4().hex)
        if pending_activation(paths) is not None:
            finalize_pending(paths)
        result.update(probe(control_root))
        result["mode"] = "RUN"
        _, manifest, digest = active(paths) or (None, None, None)
        assert manifest is not None and digest is not None
        command = [
            os.environ.get("SystemRoot", r"C:\WINDOWS") + r"\System32\WindowsPowerShell\v1.0\powershell.exe",
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(manifest["entrypoint_path"]),
            "-PythonPath", str(manifest["python_path"]),
            "-ScriptPath", str(Path(str(manifest["receiver"])) / "laptop_backup_scheduled.py"),
            "-Target", str(manifest["target"]), "-RecoveryImage", str(manifest["recovery_image"]),
            "-CandidateCodeSha", str(manifest["candidate_code_sha"]),
            "-ProtectedCodeSha", str(manifest["protected_code_sha"]),
            "-PlanGitCommit", str(manifest["scheduled_plan_git_commit"]),
            "-Operator", str(manifest["operator"]),
        ]
        # spawnv passes an exact argv vector to the fixed executable and never
        # invokes cmd.exe or PowerShell command parsing for manifest values.
        child_exit_code = os.spawnv(os.P_WAIT, command[0], command)
        result.update({"ok": child_exit_code == 0, "result": "PASS" if child_exit_code == 0 else "FAIL"})
    except Exception as exc:
        error = str(exc)
        result.update({"ok": False, "result": "FAIL", "error": error})
    finally:
        if lease_payload is not None:
            try:
                release_lease(paths, lease_payload)
            except Exception as exc:
                error = f"{error}; {exc}" if error else str(exc)
                child_exit_code = 1
                result.update({"ok": False, "result": "FAIL", "error": error})
    completed = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    record = {
        "schema_version": 1,
        "plan_document_id": manifest.get("plan_document_id") if manifest else None,
        "plan_version": manifest.get("plan_version") if manifest else None,
        "plan_git_commit": manifest.get("plan_git_commit") if manifest else None,
        "plan_sha256": manifest.get("plan_sha256") if manifest else None,
        "candidate_code_sha": manifest.get("candidate_code_sha") if manifest else None,
        "protected_code_sha": manifest.get("protected_code_sha") if manifest else None,
        "operator": manifest.get("operator") if manifest else None,
        "manifest_sha256": digest,
        "dispatcher_sha256": sha256_file(Path(__file__).resolve()),
        "timestamps": {"started_at": started, "completed_at": completed},
        "exact_arguments": list(sys.argv), "child_arguments": command,
        "child_exit_code": child_exit_code, "result": result["result"], "error": error,
        "deviations": [], "deviation_authorization": None,
    }
    record_path, record_sha = write_dispatcher_execution(paths, record)
    result.update({"execution_record": str(record_path), "execution_record_sha256": record_sha})
    print(json.dumps(result, sort_keys=True), flush=True)
    return child_exit_code


def proposed_activation(manifest_path: Path) -> tuple[bytes, dict[str, object], str]:
    supplied = manifest_path.read_bytes()
    raw = canonical_json(parse_json(supplied, "proposed manifest"))
    if supplied != raw:
        raise ValueError("proposed manifest bytes are not canonical")
    manifest = validate_manifest(parse_json(raw, "proposed manifest"), activation=True)
    return raw, manifest, sha256_bytes(raw)


def validate_activation_state(paths: Mapping[str, Path], manifest: Mapping[str, object]) -> None:
    # This pre-mutation path is deliberately read-only: do not call reconcile()
    # or pending_activation(), both of which may write terminal receipts.
    receipt_ledger(paths)
    for pending_path in sorted(paths["receipts"].glob("*-*-pending.json")):
        pending = parse_json(pending_path.read_bytes(), "PENDING receipt")
        if not any(
            receipt_path(paths, pending, status).exists()
            for status in ("PASS", "ROLLED_BACK", "ABANDONED")
        ):
            raise ValueError("an earlier activation remains pending limited-token proof")
    current = active(paths)
    ledger_sequence, activation_ids = receipt_ledger(paths)
    previous_digest = current[2] if current else None
    previous_sequence = int(current[0]["sequence"]) if current else 0
    if manifest["previous_manifest_sha256"] != previous_digest:
        raise ValueError("manifest predecessor does not match the active pointer")
    if manifest["sequence"] != ledger_sequence + 1 or previous_sequence > ledger_sequence:
        raise ValueError("manifest sequence is not the next ledger sequence")
    if str(manifest["activation_id"]) in activation_ids:
        raise ValueError("manifest activation ID is a replay")


def verify_active_state(control_root: Path) -> dict[str, object]:
    """Read-only proof that the complete active control lineage is runnable."""
    paths = layout(control_root, create=False)
    if paths["lease"].exists():
        raise ValueError("active control tree retains a transition lease")
    receipt_ledger(paths)
    for pending_path in sorted(paths["receipts"].glob("*-*-pending.json")):
        pending = parse_json(pending_path.read_bytes(), "PENDING receipt")
        if not any(
            receipt_path(paths, pending, status).exists()
            for status in ("PASS", "ROLLED_BACK", "ABANDONED")
        ):
            raise ValueError("active control tree retains an unresolved PENDING receipt")
    current = active(paths)
    if current is None:
        raise ValueError("active control tree has no active manifest")
    pointer, manifest, digest = current
    pass_receipts: dict[str, dict[str, object]] = {}
    maximum_pass_sequence = 0
    for pass_path in sorted(paths["receipts"].glob("*-*-pass.json")):
        receipt = parse_json(pass_path.read_bytes(), "PASS receipt")
        receipt_digest = require_hash(
            receipt.get("manifest_sha256"), SHA256, "PASS receipt manifest digest"
        )
        if receipt_digest in pass_receipts:
            raise ValueError("manifest has duplicate terminal PASS receipts")
        pass_receipts[receipt_digest] = receipt
        maximum_pass_sequence = max(maximum_pass_sequence, int(receipt["sequence"]))
    if int(pointer["sequence"]) != maximum_pass_sequence:
        raise ValueError("active pointer is stale behind a later PASS generation")

    chain_length = 0
    seen_digests: set[str] = set()
    seen_activations: set[str] = set()
    next_sequence = int(manifest["sequence"]) + 1
    chain_digest: str | None = digest
    while chain_digest is not None:
        if chain_digest in seen_digests:
            raise ValueError("active manifest lineage contains a digest cycle")
        manifest_path = paths["manifests"] / f"{chain_digest}.json"
        payload = manifest_path.read_bytes()
        if sha256_bytes(payload) != chain_digest:
            raise ValueError("active lineage manifest bytes do not match their digest")
        parsed_manifest = parse_json(payload, "active lineage manifest")
        chain_manifest = manifest if chain_digest == digest else validate_lineage_manifest(parsed_manifest)
        sequence = int(chain_manifest["sequence"])
        activation_id = str(chain_manifest["activation_id"])
        if sequence >= next_sequence:
            raise ValueError("active manifest lineage sequence is not strictly descending")
        if activation_id in seen_activations:
            raise ValueError("active manifest lineage reuses an activation ID")
        receipt = pass_receipts.pop(chain_digest, None)
        expected_receipt = {
            "schema_version": 1,
            "sequence": sequence,
            "activation_id": activation_id,
            "manifest_sha256": chain_digest,
            "previous_manifest_sha256": chain_manifest["previous_manifest_sha256"],
            "status": "PASS",
        }
        if receipt != expected_receipt:
            raise ValueError("active manifest lineage lacks its exact PASS receipt")
        seen_digests.add(chain_digest)
        seen_activations.add(activation_id)
        chain_length += 1
        next_sequence = sequence
        predecessor = chain_manifest["previous_manifest_sha256"]
        chain_digest = str(predecessor) if predecessor is not None else None
    if pass_receipts:
        raise ValueError("terminal PASS receipt exists outside the active manifest lineage")
    return {
        "ok": True,
        "result": "PASS",
        "mode": "VERIFY_ACTIVE",
        "sequence": pointer["sequence"],
        "activation_id": pointer["activation_id"],
        "manifest_sha256": digest,
        "candidate_code_sha": manifest["candidate_code_sha"],
        "verified_lineage_length": chain_length,
    }


def activate(
    control_root: Path, manifest_path: Path, *, defer_proof: bool = False
) -> dict[str, object]:
    paths = layout(control_root)
    require_activation_window()
    bootstrap_gate = acquire_bootstrap_gate()
    lease_payload: bytes | None = None
    try:
        lease_payload = acquire_lease(paths, uuid.uuid4().hex)
        old_pointer = paths["pointer"].read_bytes() if paths["pointer"].exists() else None
        pointer_replaced = False
        manifest: dict[str, object] | None = None
        digest: str | None = None
        try:
            reconcile(paths)
            if pending_activation(paths) is not None:
                if is_admin():
                    raise ValueError("an earlier activation remains pending limited-token proof")
                finalize_pending(paths)
            raw, manifest, digest = proposed_activation(manifest_path)
            validate_activation_state(paths, manifest)
            immutable_write(paths["manifests"] / f"{digest}.json", raw)
            pending = {
                "schema_version": 1, "sequence": manifest["sequence"],
                "activation_id": manifest["activation_id"], "manifest_sha256": digest,
                "previous_manifest_sha256": manifest["previous_manifest_sha256"], "status": "PENDING",
            }
            immutable_write(receipt_path(paths, manifest, "PENDING"), canonical_json(pending))
            pointer = {
                "schema_version": POINTER_SCHEMA_VERSION, "sequence": manifest["sequence"],
                "activation_id": manifest["activation_id"], "manifest_sha256": digest,
            }
            atomic_replace(paths["pointer"], canonical_json(pointer))
            pointer_replaced = True
            if parse_json(paths["pointer"].read_bytes(), "activated pointer") != pointer:
                raise ValueError("activated pointer readback failed")
            if defer_proof:
                return {"ok": True, "result": "PENDING", **pointer}
            final = finalize_pending(paths)
            if final.get("result") != "PASS":
                raise ValueError("fresh semantic proof did not pass")
            return {"ok": True, "result": "PASS", **pointer}
        except BaseException:
            if pointer_replaced:
                if old_pointer is None:
                    paths["pointer"].unlink(missing_ok=True)
                    fsync_directory(paths["root"])
                else:
                    atomic_replace(paths["pointer"], old_pointer)
            if manifest is not None and digest is not None:
                terminal = {
                    "schema_version": 1, "sequence": manifest["sequence"],
                    "activation_id": manifest["activation_id"], "manifest_sha256": digest,
                    "previous_manifest_sha256": manifest["previous_manifest_sha256"],
                    "status": "ROLLED_BACK" if pointer_replaced else "ABANDONED",
                }
                immutable_write(receipt_path(paths, manifest, str(terminal["status"])), canonical_json(terminal))
            raise
    finally:
        try:
            if lease_payload is not None:
                release_lease(paths, lease_payload)
        finally:
            release_bootstrap_gate(bootstrap_gate)


def prepare_manifest(args: argparse.Namespace) -> dict[str, object]:
    created = datetime.now(timezone.utc).replace(microsecond=0)
    value = {
        "schema_version": SCHEMA_VERSION,
        "sequence": args.sequence,
        "activation_id": args.activation_id,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "activation_expires_at": args.activation_expires_at,
        "previous_manifest_sha256": args.previous_manifest_sha256,
        "plan_document_id": PLAN_ID,
        "plan_version": "1.5",
        "plan_git_commit": args.plan_git_commit,
        "plan_sha256": args.plan_sha256,
        "authority_commit": args.authority_commit,
        "handoff_sha256": args.handoff_sha256,
        "authority_repo": str(args.authority_repo),
        "authority_handoff_path": "docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md",
        "candidate_code_sha": args.candidate_code_sha,
        "protected_code_sha": args.protected_code_sha,
        "operator": args.operator,
        "operator_sid": args.operator_sid,
        "receiver": str(args.receiver),
        "allowed_receiver_root": str(args.allowed_receiver_root),
        "entrypoint": args.entrypoint,
        "entrypoint_sha256": args.entrypoint_sha256,
        "python_path": str(args.python_path),
        "python_sha256": args.python_sha256,
        "scheduled_plan_git_commit": args.scheduled_plan_git_commit,
        "target": str(args.target),
        "allowed_target_root": str(args.allowed_target_root),
        "recovery_image": str(args.recovery_image),
        "allowed_recovery_root": str(args.allowed_recovery_root),
        "gate_evidence_path": str(args.gate_evidence_path),
        "gate_evidence_sha256": args.gate_evidence_sha256,
    }
    validated = validate_manifest(value, activation=True)
    payload = canonical_json({key: value[key] for key in MANIFEST_KEYS})
    atomic_replace(args.output, payload)
    return {
        "ok": True, "result": "PASS", "mode": "PREPARE",
        "manifest_path": str(args.output.resolve(strict=True)),
        "manifest_sha256": sha256_bytes(payload),
        "candidate_code_sha": validated["candidate_code_sha"],
        "sequence": validated["sequence"], "activation_id": validated["activation_id"],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("probe", "run"):
        item = sub.add_parser(name)
        item.add_argument("--control-root", type=Path, required=True)
        item.add_argument("--output", type=Path)
    item = sub.add_parser("activate")
    item.add_argument("--control-root", type=Path, required=True)
    item.add_argument("--manifest", type=Path, required=True)
    item.add_argument("--defer-proof", action="store_true")
    item = sub.add_parser("validate")
    item.add_argument("--control-root", type=Path, required=True)
    item.add_argument("--manifest", type=Path, required=True)
    item = sub.add_parser("verify-active")
    item.add_argument("--control-root", type=Path, required=True)
    item = sub.add_parser("finalize")
    item.add_argument("--control-root", type=Path, required=True)
    item.add_argument("--output", type=Path)
    item = sub.add_parser("prepare")
    item.add_argument("--output", type=Path, required=True)
    item.add_argument("--sequence", type=int, required=True)
    item.add_argument("--activation-id", required=True)
    item.add_argument("--activation-expires-at", required=True)
    item.add_argument("--previous-manifest-sha256")
    item.add_argument("--plan-git-commit", required=True)
    item.add_argument("--plan-sha256", required=True)
    item.add_argument("--authority-commit", required=True)
    item.add_argument("--handoff-sha256", required=True)
    item.add_argument("--authority-repo", type=Path, required=True)
    item.add_argument("--candidate-code-sha", required=True)
    item.add_argument("--protected-code-sha", required=True)
    item.add_argument("--operator", required=True)
    item.add_argument("--operator-sid", required=True)
    item.add_argument("--receiver", type=Path, required=True)
    item.add_argument("--allowed-receiver-root", type=Path, required=True)
    item.add_argument("--entrypoint", default="run_laptop_backup_task.ps1")
    item.add_argument("--entrypoint-sha256", required=True)
    item.add_argument("--python-path", type=Path, required=True)
    item.add_argument("--python-sha256", required=True)
    item.add_argument("--scheduled-plan-git-commit", required=True)
    item.add_argument("--target", type=Path, required=True)
    item.add_argument("--allowed-target-root", type=Path, required=True)
    item.add_argument("--recovery-image", type=Path, required=True)
    item.add_argument("--allowed-recovery-root", type=Path, required=True)
    item.add_argument("--gate-evidence-path", type=Path, required=True)
    item.add_argument("--gate-evidence-sha256", required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "activate":
            value = activate(args.control_root, args.manifest, defer_proof=args.defer_proof)
        elif args.command == "validate":
            raw, validated, _digest = proposed_activation(args.manifest)
            validate_activation_state(layout(args.control_root), validated)
            value = {
                "ok": True, "result": "PASS", "mode": "VALIDATE",
                "candidate_code_sha": validated["candidate_code_sha"],
                "sequence": validated["sequence"],
            }
        elif args.command == "verify-active":
            value = verify_active_state(args.control_root)
        elif args.command == "finalize":
            value = finalize_pending(layout(args.control_root))
        elif args.command == "prepare":
            value = prepare_manifest(args)
        elif args.command == "probe":
            value = probe(args.control_root)
        else:
            return run(args.control_root)
        payload = canonical_json(value)
        if args.command in {"probe", "finalize"} and getattr(args, "output", None):
            atomic_replace(args.output, payload)
        sys.stdout.buffer.write(payload)
        return 0
    except Exception as exc:
        payload = canonical_json({"ok": False, "result": "FAIL", "error": str(exc)})
        if args.command in {"probe", "finalize"} and getattr(args, "output", None):
            atomic_replace(args.output, payload)
        sys.stdout.buffer.write(payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
