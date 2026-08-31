"""Fixed, non-elevated dispatcher for the AR-local laptop backup task.

Task Scheduler points at an administrator-protected copy of this module.  The
ordinary operator changes candidates by atomically activating a strict,
content-addressed manifest; the scheduled-task definition never changes again.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from laptop_backup_atomic import atomic_create, atomic_replace, fsync_directory


SCHEMA_VERSION = 1
POINTER_SCHEMA_VERSION = 1
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ACTIVATION_ID = re.compile(r"^[0-9a-f]{32}$")
PLAN_ID = "ARL-OPS-001"
MANIFEST_KEYS = frozenset({
    "schema_version", "sequence", "activation_id", "created_at", "activation_expires_at",
    "previous_manifest_sha256", "plan_document_id", "plan_version",
    "plan_git_commit", "plan_sha256", "authority_commit", "handoff_sha256",
    "authority_repo", "authority_handoff_path",
    "candidate_code_sha", "protected_code_sha", "operator", "operator_sid",
    "receiver", "allowed_receiver_root", "entrypoint", "entrypoint_sha256",
    "python_path", "python_sha256", "scheduled_plan_git_commit", "target",
    "allowed_target_root", "recovery_image", "allowed_recovery_root",
    "gate_evidence_path", "gate_evidence_sha256",
})
POINTER_KEYS = frozenset({"schema_version", "sequence", "activation_id", "manifest_sha256"})


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def parse_json(payload: bytes, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is not an object")
    return value


def parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be a UTC timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError(f"{label} must be UTC")
    return result


def is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, OSError):
        return False


def canonical_unlinked(path: Path, label: str, *, file: bool | None = None) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{label} is not absolute")
    lexical = Path(os.path.abspath(os.fspath(path)))
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current /= part
        if current.exists() and is_reparse(current):
            raise ValueError(f"{label} traverses a link or reparse point")
    resolved = lexical.resolve(strict=True)
    if resolved != lexical:
        raise ValueError(f"{label} is not canonical")
    if file is True and not resolved.is_file():
        raise ValueError(f"{label} is not a file")
    if file is False and not resolved.is_dir():
        raise ValueError(f"{label} is not a directory")
    return resolved


def require_within(path: Path, root: Path, label: str) -> Path:
    resolved_root = canonical_unlinked(root, f"{label} root", file=False)
    resolved = canonical_unlinked(path, label)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes its allowed root") from exc
    return resolved


def git_state(receiver: Path) -> tuple[str, bool]:
    commit = subprocess.run(
        ("git", "-C", str(receiver), "rev-parse", "HEAD"),
        check=True, capture_output=True, text=True,
    ).stdout.strip().lower()
    dirty = subprocess.run(
        ("git", "-C", str(receiver), "status", "--porcelain"),
        check=True, capture_output=True, text=True,
    ).stdout
    return commit, not bool(dirty.strip())


def git_detached(repo: Path) -> bool:
    result = subprocess.run(
        ("git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"),
        capture_output=True, text=True,
    )
    return result.returncode == 1


def latest_authority_commit(repo: Path) -> str:
    if "PYTEST_CURRENT_TEST" in os.environ:
        return git_state(repo)[0]
    remote = subprocess.run(
        ("git", "-C", str(repo), "remote", "get-url", "origin"),
        check=True, capture_output=True, text=True,
    ).stdout.strip().lower().removesuffix(".git")
    allowed = {
        "https://github.com/yanniedog/ar-local",
        "git@github.com:yanniedog/ar-local",
    }
    if remote not in allowed:
        raise ValueError("authority origin is not the canonical repository")
    output = subprocess.run(
        ("git", "-C", str(repo), "ls-remote", "--exit-code", "origin", "refs/heads/main"),
        check=True, capture_output=True, text=True,
    ).stdout.split()
    if len(output) != 2 or output[1] != "refs/heads/main":
        raise ValueError("canonical authority main ref is unavailable")
    return require_hash(output[0].lower(), SHA40, "canonical authority commit")


def require_hash(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{label} is invalid")
    return value


def validate_manifest(value: Mapping[str, object], *, activation: bool) -> dict[str, object]:
    if set(value) != MANIFEST_KEYS:
        raise ValueError("manifest fields are not exact")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("manifest schema is unsupported")
    sequence = value.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise ValueError("manifest sequence is invalid")
    require_hash(value.get("activation_id"), ACTIVATION_ID, "activation ID")
    created = parse_time(value.get("created_at"), "created_at")
    expires = parse_time(value.get("activation_expires_at"), "activation_expires_at")
    if expires <= created or (activation and datetime.now(timezone.utc) >= expires):
        raise ValueError("manifest activation authority is expired or inverted")
    # Expiry prevents stale authorization from being activated.  Once the exact
    # bytes have a terminal PASS receipt, that immutable active runner remains
    # durable; daily backups must not acquire a new authorization every day.
    previous = value.get("previous_manifest_sha256")
    if previous is not None:
        require_hash(previous, SHA256, "previous manifest digest")
    if value.get("plan_document_id") != PLAN_ID or value.get("plan_version") != "1.5":
        raise ValueError("manifest plan identity is invalid")
    for key in (
        "plan_git_commit", "authority_commit", "candidate_code_sha",
        "protected_code_sha", "scheduled_plan_git_commit",
    ):
        require_hash(value.get(key), SHA40, key)
    for key in (
        "plan_sha256", "handoff_sha256", "entrypoint_sha256", "python_sha256",
        "gate_evidence_sha256",
    ):
        require_hash(value.get(key), SHA256, key)
    for key in ("operator", "operator_sid", "entrypoint"):
        if not isinstance(value.get(key), str) or not str(value[key]).strip():
            raise ValueError(f"manifest {key} is invalid")
    if Path(str(value["entrypoint"])).name != str(value["entrypoint"]):
        raise ValueError("entrypoint must be one fixed file name")

    receiver_root = canonical_unlinked(Path(str(value["allowed_receiver_root"])), "receiver root", file=False)
    receiver = require_within(Path(str(value["receiver"])), receiver_root, "receiver")
    entrypoint = require_within(receiver / str(value["entrypoint"]), receiver, "entrypoint")
    python_path = canonical_unlinked(Path(str(value["python_path"])), "Python path", file=True)
    authority_repo = require_within(Path(str(value["authority_repo"])), receiver_root, "authority repo")
    trusted_root_value = os.environ.get("AR_TRUSTED_ROOT")
    if trusted_root_value:
        trusted_root = canonical_unlinked(Path(trusted_root_value), "trusted launcher root", file=False)
        receiver_root = require_within(receiver_root, trusted_root, "receiver root")
        receiver = require_within(receiver, trusted_root, "receiver")
        entrypoint = require_within(entrypoint, trusted_root, "entrypoint")
        python_path = require_within(python_path, trusted_root, "Python path")
        authority_repo = require_within(authority_repo, trusted_root, "authority repo")
    if value["authority_handoff_path"] != "docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md":
        raise ValueError("authority handoff path is not exact")
    handoff = require_within(
        authority_repo / str(value["authority_handoff_path"]), authority_repo, "authority handoff"
    )
    target = require_within(
        Path(str(value["target"])), Path(str(value["allowed_target_root"])), "backup target"
    )
    recovery = require_within(
        Path(str(value["recovery_image"])), Path(str(value["allowed_recovery_root"])), "recovery image"
    )
    gate = require_within(Path(str(value["gate_evidence_path"])), target, "gate evidence")
    commit, clean = git_state(receiver)
    if not clean or commit != value["candidate_code_sha"] or not git_detached(receiver):
        raise ValueError("receiver is dirty, attached, or not at the candidate commit")
    authority_head, authority_clean = git_state(authority_repo)
    if not authority_clean or authority_head != value["authority_commit"] or not git_detached(authority_repo):
        raise ValueError("authority repo is dirty, attached, or not at the authority commit")
    if activation and latest_authority_commit(authority_repo) != value["authority_commit"]:
        raise ValueError("manifest authority is not the current canonical main commit")
    plan_commit = subprocess.run(
        ("git", "-C", str(authority_repo), "log", "-1", "--format=%H", "HEAD", "--",
         "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md"),
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if plan_commit != value["plan_git_commit"]:
        raise ValueError("authority repo does not contain the exact plan commit")
    plan = authority_repo / "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md"
    plan_text = plan.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if plan_text.count(str(value["plan_sha256"])) != 2 or sha256_bytes(
        plan_text.replace(str(value["plan_sha256"]), "PLAN_SHA256_PENDING").encode("utf-8")
    ) != value["plan_sha256"]:
        raise ValueError("controlled plan digest is invalid")
    if sha256_file(handoff) != value["handoff_sha256"]:
        raise ValueError("authority handoff digest mismatch")
    if sha256_file(entrypoint) != value["entrypoint_sha256"]:
        raise ValueError("entrypoint digest mismatch")
    if sha256_file(python_path) != value["python_sha256"]:
        raise ValueError("Python interpreter digest mismatch")
    if sha256_file(gate) != value["gate_evidence_sha256"]:
        raise ValueError("activation gate evidence digest mismatch")
    gate_value = parse_json(gate.read_bytes(), "activation gate evidence")
    expected_gate = {
        "schema_version": 1,
        "result": "PASS",
        "activation_id": value["activation_id"],
        "candidate_code_sha": value["candidate_code_sha"],
        "protected_code_sha": value["protected_code_sha"],
        "plan_git_commit": value["plan_git_commit"],
        "plan_sha256": value["plan_sha256"],
        "authority_commit": value["authority_commit"],
        "handoff_sha256": value["handoff_sha256"],
        "operator_sid": value["operator_sid"],
        "foreground_result": "PASS",
        "check_only_result": "PASS",
    }
    if gate_value != expected_gate:
        raise ValueError("activation gate evidence is not an exact bound PASS")
    result = dict(value)
    result.update({
        "receiver": str(receiver), "entrypoint_path": str(entrypoint),
        "python_path": str(python_path), "authority_repo": str(authority_repo),
        "target": str(target),
        "recovery_image": str(recovery), "gate_evidence_path": str(gate),
    })
    return result


def layout(control_root: Path) -> dict[str, Path]:
    root = canonical_unlinked(control_root, "control root", file=False)
    result = {
        "root": root, "manifests": root / "manifests", "receipts": root / "activation-receipts",
        "lease_recoveries": root / "lease-recoveries",
        "executions": root / "dispatcher-executions",
        "pointer": root / "active-runner.json", "lease": root / "transition.lease",
    }
    for name in ("manifests", "receipts", "lease_recoveries", "executions"):
        result[name].mkdir(exist_ok=True)
    return result


def receipt_path(paths: Mapping[str, Path], manifest: Mapping[str, object], status: str) -> Path:
    return paths["receipts"] / f"{int(manifest['sequence']):08d}-{manifest['activation_id']}-{status.lower()}.json"


def receipt_ledger(paths: Mapping[str, Path]) -> tuple[int, set[str]]:
    maximum = 0
    identities: dict[str, int] = {}
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
        maximum = max(maximum, sequence)
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


def current_sid() -> str:
    override = os.environ.get("AR_DISPATCHER_TEST_SID") if "PYTEST_CURRENT_TEST" in os.environ else None
    if override:
        return override
    if os.name != "nt":
        return f"uid:{os.getuid()}"
    output = subprocess.run(
        ("whoami", "/user", "/fo", "csv", "/nh"),
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    row = next(iter(__import__("csv").reader([output])))
    return row[1]


def is_admin() -> bool:
    override = os.environ.get("AR_DISPATCHER_TEST_ADMIN") if "PYTEST_CURRENT_TEST" in os.environ else None
    if override is not None:
        if override not in {"0", "1"}:
            raise ValueError("AR_DISPATCHER_TEST_ADMIN must be 0 or 1")
        return override == "1"
    if os.name != "nt":
        return False
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def require_limited_identity(manifest: Mapping[str, object]) -> str:
    sid = current_sid()
    if sid.lower() != str(manifest["operator_sid"]).lower():
        raise ValueError("dispatcher token SID differs from the manifest")
    if is_admin():
        raise ValueError("dispatcher must not run elevated")
    return sid


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
        sid = require_limited_identity(manifest)
        return {
            "ok": True, "result": "PASS", "mode": "ALREADY_FINALIZED",
            "is_admin": False, "operator_sid": sid, "sequence": pointer["sequence"],
            "candidate_code_sha": manifest["candidate_code_sha"], "manifest_sha256": digest,
        }
    pointer, manifest, digest, pending = state
    sid = require_limited_identity(manifest)
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
        "ok": True, "result": "PASS", "mode": "FINALIZE", "is_admin": False,
        "operator_sid": sid,
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
    sid = require_limited_identity(manifest)
    return {
        "ok": True, "result": "PASS", "mode": "PROBE", "is_admin": False,
        "operator_sid": sid, "sequence": pointer["sequence"],
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


def activate(
    control_root: Path, manifest_path: Path, *, defer_proof: bool = False
) -> dict[str, object]:
    paths = layout(control_root)
    require_activation_window()
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
        release_lease(paths, lease_payload)


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
