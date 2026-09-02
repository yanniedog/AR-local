"""Security and manifest contract for the protected laptop backup dispatcher."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = 1
POINTER_SCHEMA_VERSION = 1
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ACTIVATION_ID = re.compile(r"^[0-9a-f]{32}$")
PLAN_ID = "ARL-OPS-001"
BOOTSTRAP_GATE_NAME = "Global\\ARLocalTrustedBootstrapGate"
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
    if test_override_enabled():
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


def validate_lineage_manifest(value: Mapping[str, object]) -> dict[str, object]:
    """Validate immutable predecessor identity without reopening old live paths."""
    if set(value) != MANIFEST_KEYS or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("lineage manifest fields or schema are invalid")
    sequence = value.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise ValueError("lineage manifest sequence is invalid")
    require_hash(value.get("activation_id"), ACTIVATION_ID, "lineage activation ID")
    created = parse_time(value.get("created_at"), "lineage created_at")
    expires = parse_time(value.get("activation_expires_at"), "lineage activation_expires_at")
    if expires <= created:
        raise ValueError("lineage manifest authority interval is inverted")
    previous = value.get("previous_manifest_sha256")
    if previous is not None:
        require_hash(previous, SHA256, "lineage predecessor digest")
    if value.get("plan_document_id") != PLAN_ID or value.get("plan_version") != "1.5":
        raise ValueError("lineage manifest plan identity is invalid")
    for key in (
        "plan_git_commit", "authority_commit", "candidate_code_sha",
        "protected_code_sha", "scheduled_plan_git_commit",
    ):
        require_hash(value.get(key), SHA40, f"lineage {key}")
    for key in (
        "plan_sha256", "handoff_sha256", "entrypoint_sha256", "python_sha256",
        "gate_evidence_sha256",
    ):
        require_hash(value.get(key), SHA256, f"lineage {key}")
    for key in (
        "operator", "operator_sid", "authority_repo", "authority_handoff_path",
        "receiver", "allowed_receiver_root", "entrypoint", "python_path", "target",
        "allowed_target_root", "recovery_image", "allowed_recovery_root", "gate_evidence_path",
    ):
        if not isinstance(value.get(key), str) or not str(value[key]).strip():
            raise ValueError(f"lineage manifest {key} is invalid")
    return dict(value)


def current_sid() -> str:
    override = os.environ.get("AR_DISPATCHER_TEST_SID") if test_override_enabled() else None
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
    override = os.environ.get("AR_DISPATCHER_TEST_ADMIN") if test_override_enabled() else None
    if override is not None:
        if override not in {"0", "1"}:
            raise ValueError("AR_DISPATCHER_TEST_ADMIN must be 0 or 1")
        return override == "1"
    if os.name != "nt":
        return False
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def test_override_enabled() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ and "pytest" in sys.modules


def _token_dword(information_class: int) -> int:
    token = ctypes.c_void_p()
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    ctypes.windll.advapi32.OpenProcessToken.argtypes = (
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)
    )
    if not ctypes.windll.advapi32.OpenProcessToken(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):
        raise ctypes.WinError()
    try:
        value = ctypes.c_ulong()
        returned = ctypes.c_ulong()
        if not ctypes.windll.advapi32.GetTokenInformation(
            token, information_class, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(returned)
        ):
            raise ctypes.WinError()
        return int(value.value)
    finally:
        ctypes.windll.kernel32.CloseHandle(token)


def _token_integrity_rid() -> int:
    token = ctypes.c_void_p()
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    ctypes.windll.advapi32.OpenProcessToken.argtypes = (
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)
    )
    if not ctypes.windll.advapi32.OpenProcessToken(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):
        raise ctypes.WinError()
    try:
        needed = ctypes.c_ulong()
        ctypes.windll.advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        if not ctypes.windll.advapi32.GetTokenInformation(
            token, 25, buffer, needed, ctypes.byref(needed)
        ):
            raise ctypes.WinError()
        sid = ctypes.c_void_p.from_buffer(buffer).value
        ctypes.windll.advapi32.GetSidSubAuthorityCount.argtypes = (ctypes.c_void_p,)
        ctypes.windll.advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        ctypes.windll.advapi32.GetSidSubAuthority.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        ctypes.windll.advapi32.GetSidSubAuthority.restype = ctypes.POINTER(ctypes.c_ulong)
        count = ctypes.windll.advapi32.GetSidSubAuthorityCount(sid)[0]
        return int(ctypes.windll.advapi32.GetSidSubAuthority(sid, count - 1)[0])
    finally:
        ctypes.windll.kernel32.CloseHandle(token)


def token_facts() -> dict[str, object]:
    testing = test_override_enabled()
    if testing:
        elevation = os.environ.get("AR_DISPATCHER_TEST_ELEVATION", "0")
        elevation_type = os.environ.get("AR_DISPATCHER_TEST_ELEVATION_TYPE", "Limited")
        restricted = os.environ.get("AR_DISPATCHER_TEST_RESTRICTED", "1")
        integrity = os.environ.get("AR_DISPATCHER_TEST_INTEGRITY_RID", "8192")
        if elevation not in {"0", "1"} or restricted not in {"0", "1"}:
            raise ValueError("dispatcher token-fact test override is invalid")
        return {
            "is_admin": is_admin(), "token_elevation": elevation == "1",
            "token_elevation_type": elevation_type, "token_has_restrictions": restricted == "1",
            "integrity_rid": int(integrity),
            "ssh_preflight": os.environ.get("AR_BACKUP_SSH_PREFLIGHT", "PASS"),
        }
    elevation_types = {1: "Default", 2: "Full", 3: "Limited"}
    return {
        "is_admin": is_admin(), "token_elevation": bool(_token_dword(20)),
        "token_elevation_type": elevation_types.get(_token_dword(18), "Unknown"),
        "token_has_restrictions": bool(_token_dword(21)),
        "integrity_rid": _token_integrity_rid(),
        "ssh_preflight": os.environ.get("AR_BACKUP_SSH_PREFLIGHT"),
    }


def require_limited_identity(manifest: Mapping[str, object]) -> dict[str, object]:
    sid = current_sid()
    if sid.lower() != str(manifest["operator_sid"]).lower():
        raise ValueError("dispatcher token SID differs from the manifest")
    facts = token_facts()
    if facts["is_admin"]:
        raise ValueError("dispatcher must not run elevated")
    if (facts["token_elevation"] or facts["token_elevation_type"] not in {"Default", "Limited"} or
            not facts["token_has_restrictions"] or int(facts["integrity_rid"]) > 8192):
        raise ValueError("dispatcher token is not a restricted non-elevated Medium token")
    if facts["ssh_preflight"] != "PASS":
        raise ValueError("dispatcher lacks the trusted SSH semantic preflight")
    return {"operator_sid": sid, **facts}
