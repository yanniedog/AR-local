"""Crash-safe serialization and repair for scheduled execution lineage."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterator, Mapping

import laptop_pull_backup as receiver


SHA256 = re.compile(r"[0-9a-f]{64}")
VALID_OUTCOMES = {
    "PREFLIGHT_FAILED": {"BLOCKED"},
    "NO_BACKUP_DATA_WRITE": {"PASS"},
    "BACKUP_REQUIRED": {"BLOCKED"},
    "BACKUP-LATEST": {"PASS", "FAIL"},
    "BACKFILL": {"PASS", "FAIL"},
    "POST_BACKUP_VERIFY": {"FAIL"},
}


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, FileNotFoundError):
        return False


def safe_path(target: Path, relative: str, *, must_exist: bool = True) -> Path:
    receiver.validate_relative_path(relative, {})
    root = target.resolve(strict=True)
    candidate = root
    for part in PurePosixPath(relative).parts:
        candidate = candidate / part
        if _is_link(candidate):
            raise ValueError("scheduled lineage path contains a link or reparse point")
    resolved = candidate.resolve(strict=must_exist)
    if resolved != root and root not in resolved.parents:
        raise ValueError("scheduled lineage path escapes the backup target")
    return resolved


@contextmanager
def scheduled_record_mutex(target: Path) -> Iterator[None]:
    """Serialize every new-code writer of the scheduled record pointer."""
    catalog = safe_path(target, "catalog")
    path = catalog / ".scheduled-record.mutex"
    if _is_link(path):
        raise ValueError("scheduled record mutex is a link or reparse point")
    with path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
            os.fsync(stream.fileno())
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _pointer_identity(target: Path, payload: bytes) -> dict[str, str]:
    value = json.loads(payload)
    relative = value.get("record_path") if isinstance(value, Mapping) else None
    digest = value.get("record_sha256") if isinstance(value, Mapping) else None
    result = value.get("result") if isinstance(value, Mapping) else None
    if not isinstance(relative, str) or not relative.startswith("catalog/scheduled-runs/"):
        raise ValueError("scheduled execution pointer path is invalid")
    path = safe_path(target, relative)
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(digest, str)
        or not SHA256.fullmatch(digest)
        or receiver.sha256_file(path) != digest
        or result not in {"PASS", "FAIL", "BLOCKED"}
        or not isinstance(record, Mapping)
        or record.get("result") != result
    ):
        raise ValueError("scheduled execution pointer identity is invalid")
    return {"record_path": relative, "record_sha256": digest, "result": result}


def _validate_owned_record(
    value: Mapping[str, object], expected: Mapping[str, object], *, predecessor: bool = False
) -> None:
    fixed = {
        "schema_version": 1,
        "plan_document_id": receiver.PLAN_DOCUMENT_ID,
        "plan_version": receiver.PLAN_VERSION,
        "plan_git_commit": expected["plan_git_commit"],
        "plan_sha256": receiver.PLAN_SHA256,
        "plan_normalized_raw_sha256": receiver.PLAN_NORMALIZED_RAW_SHA256,
        "protected_code_sha": expected["protected_code_sha"],
        "operator": expected["operator"],
        "deviations": [],
        "deviation_authorization": None,
    }
    if any(value.get(key) != item for key, item in fixed.items()):
        raise ValueError("orphaned scheduled record identity is invalid")
    allowed_candidates = {expected["candidate_code_sha"]}
    if predecessor:
        allowed_candidates.update(expected.get("allowed_predecessor_candidates", ()))
    if value.get("candidate_code_sha") not in allowed_candidates:
        raise ValueError("orphaned scheduled record candidate is invalid")
    timestamp = value.get("timestamps")
    completed = timestamp.get("completed_at") if isinstance(timestamp, Mapping) else None
    commands = value.get("exact_commands")
    action = value.get("action")
    try:
        parsed = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("orphaned scheduled record timestamp is invalid") from exc
    if (
        value.get("plan_raw_sha256") not in receiver.PLAN_VALID_RAW_SHA256S
        or parsed.tzinfo is None
        or not isinstance(commands, list)
        or not commands
        or any(not isinstance(command, str) or not command.strip() for command in commands)
        or action not in VALID_OUTCOMES
        or value.get("result") not in VALID_OUTCOMES.get(action, set())
        or not isinstance(value.get("detail"), Mapping)
    ):
        raise ValueError("orphaned scheduled record envelope is invalid")


def repair_orphaned_suffix(target: Path, expected: Mapping[str, object]) -> dict[str, str] | None:
    """Roll a stale pointer through its one authenticated immutable child chain."""
    pointer_path = safe_path(target, "catalog/latest-scheduled.json", must_exist=False)
    root = safe_path(target, "catalog/scheduled-runs", must_exist=False)
    if not root.exists():
        if pointer_path.exists():
            raise ValueError("scheduled pointer exists without its record directory")
        root.mkdir()
    if not pointer_path.exists():
        roots = sorted(root.glob("*.json"))
        if not roots:
            return None
        if len(roots) != 1:
            raise ValueError("scheduled root recovery is ambiguous")
        path = safe_path(target, roots[0].relative_to(target).as_posix())
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping) or value.get("previous_execution") is not None:
            raise ValueError("orphaned scheduled root is invalid")
        _validate_owned_record(value, expected)
        current = {
            "record_path": path.relative_to(target.resolve(strict=True)).as_posix(),
            "record_sha256": receiver.sha256_file(path),
            "result": str(value["result"]),
        }
        receiver.atomic_replace(pointer_path, receiver.canonical_json_bytes(current))
    else:
        current = _pointer_identity(target, pointer_path.read_bytes())
        pointed = safe_path(target, current["record_path"])
        pointed_value = json.loads(pointed.read_text(encoding="utf-8"))
        if not isinstance(pointed_value, Mapping):
            raise ValueError("pointed scheduled predecessor is invalid")
        _validate_owned_record(pointed_value, expected, predecessor=True)
    seen = {current["record_path"]}
    while True:
        matches: list[tuple[str, str, Mapping[str, object]]] = []
        predecessor = {key: current[key] for key in ("record_path", "record_sha256")}
        for path in sorted(root.glob("*.json")):
            regular = safe_path(target, path.relative_to(target).as_posix())
            value = json.loads(regular.read_text(encoding="utf-8"))
            if isinstance(value, Mapping) and value.get("previous_execution") == predecessor:
                relative = regular.relative_to(target.resolve(strict=True)).as_posix()
                if relative in seen:
                    raise ValueError("scheduled execution lineage contains a cycle")
                _validate_owned_record(value, expected)
                matches.append((relative, receiver.sha256_file(regular), value))
        if len(matches) > 1:
            raise ValueError("scheduled execution lineage is branched")
        if not matches:
            return current
        relative, digest, value = matches[0]
        current = {"record_path": relative, "record_sha256": digest, "result": str(value["result"])}
        receiver.atomic_replace(pointer_path, receiver.canonical_json_bytes(current))
        seen.add(relative)
