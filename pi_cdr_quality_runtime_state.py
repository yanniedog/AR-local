"""Bind publication controls without restoring or rewriting outstanding work."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from pi_cdr_quality_digest import DigestSnapshot, read_digest

PENDING = "app-payload-publication-pending.json"
CONTROL_FILES = (PENDING, "app-payload-continuity.json")
RETRIES = "app-payload-retries"
MAX_FILES = 4096
MAX_BYTES = 64 * 1024 * 1024


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate publication control key")
        result[key] = value
    return result


def control_state(data: Path) -> dict:
    """Hash presence, directory membership and the exact bytes parsed as JSON."""
    state = data / "state"
    snapshot = DigestSnapshot(data)
    snapshot.directory(state)
    result = {"files": {}, "retry_directory_present": False, "pending_has_queue": False}
    paths = [state / name for name in CONTROL_FILES]
    retry = state / RETRIES
    if retry.is_symlink():
        raise ValueError("publication retry directory must not be linked")
    if retry.exists():
        snapshot.directory(retry)
        result["retry_directory_present"] = True
        children = sorted(retry.iterdir())
        if len(children) > MAX_FILES:
            raise ValueError("publication retry inventory exceeds bound")
        paths.extend(children)
    total = 0
    for path in paths:
        name = path.relative_to(state).as_posix()
        try:
            path.lstat()
        except FileNotFoundError:
            result["files"][name] = None
            continue
        entry, body = read_digest(path, root=data, capture=True, max_bytes=MAX_BYTES - total)
        total += entry.size
        value = json.loads(body, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise ValueError("publication control must be a JSON object")
        snapshot.files[path] = entry
        result["files"][name] = {"sha256": entry.sha256, "bytes": entry.size}
        if name == PENDING and "queued_pointers" in value:
            queued = value["queued_pointers"]
            if not isinstance(queued, list) or any(not isinstance(p, dict) or not p for p in queued):
                raise ValueError("malformed queued publication pointers")
            result["pending_has_queue"] = True
    snapshot.finish()
    return result


def _pending_helpers(repo: Path) -> tuple[str, str, bool]:
    entry, body = read_digest(repo / "pi_daily_sync.py", capture=True, max_bytes=MAX_BYTES)
    tree = ast.parse(body.decode("utf-8-sig"))
    names = ("mark_payload_publication_pending", "clear_payload_publication_pending")
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names}
    if set(functions) != set(names):
        raise ValueError("predecessor publication helpers are unavailable")
    capable = all(any(isinstance(node, ast.Constant) and node.value == "queued_pointers"
                      for node in ast.walk(functions[name])) for name in names)
    normalized = "\n".join(ast.dump(functions[name], include_attributes=False) for name in names)
    return entry.sha256, hashlib.sha256(normalized.encode()).hexdigest(), capable


def rollback_contract(source: Path, production: Path) -> dict:
    candidate_file, candidate_helpers, capable = _pending_helpers(source)
    previous_file, previous_helpers, _ = _pending_helpers(production)
    return {"candidate_file_sha256": candidate_file, "previous_file_sha256": previous_file,
            "candidate_helpers_sha256": candidate_helpers, "previous_helpers_sha256": previous_helpers,
            "queue_compatible": capable and candidate_file == previous_file}


def require_controls(data: Path, expected: dict, contract: dict) -> None:
    observed = control_state(data)
    if observed != expected:
        raise ValueError("publication control state changed since canary")
    if observed["pending_has_queue"] and contract.get("queue_compatible") is not True:
        raise ValueError("rollback predecessor cannot preserve queued publication pointers")


def require_predecessor(production: Path, contract: dict) -> None:
    digest, helpers, _ = _pending_helpers(production)
    if digest != contract["previous_file_sha256"] or helpers != contract["previous_helpers_sha256"]:
        raise ValueError("rollback predecessor publication helper changed")
