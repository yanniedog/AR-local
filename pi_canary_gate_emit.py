#!/usr/bin/env python3
"""Emit one canary-gate-evidence-v1 JSON file from hashed receipt artifacts.

Never invents PASS. Callers decide result after validating real receipts.
Referenced evidence paths must be relative to the gate file directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pi_canary_acceptance as canary

GATE_EVIDENCE_SCHEMA_VERSION = 1
ALLOWED_RESULTS = frozenset({"PASS", "FAIL", "UNKNOWN"})
MAX_NOTES_CHARS = 2048


class GateEmitError(ValueError):
    """Gate evidence file cannot be written honestly."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode_gate_payload(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def build_gate_payload(
    *,
    gate: str,
    result: str,
    target_commit: str,
    evidence_items: Sequence[Mapping[str, str]],
    completed_at: Optional[str] = None,
    notes: Optional[str] = None,
    candidate_generation: Optional[str] = None,
    preservation_snapshot_sha256: Optional[str] = None,
) -> dict[str, Any]:
    if gate not in canary.REQUIRED_ACCEPTANCE_GATES:
        raise GateEmitError(f"unknown gate: {gate}")
    if result not in ALLOWED_RESULTS:
        raise GateEmitError(f"result must be one of {sorted(ALLOWED_RESULTS)}")
    if not canary.COMMIT_RE.fullmatch(target_commit):
        raise GateEmitError("target_commit must be 40 lowercase hex")
    if not evidence_items:
        raise GateEmitError("evidence must be a non-empty list")

    payload: dict[str, Any] = {
        "schema_version": GATE_EVIDENCE_SCHEMA_VERSION,
        "gate": gate,
        "result": result,
        "target_commit": target_commit,
        "completed_at": completed_at or utc_now_iso(),
        "evidence": [
            {"path": str(item["path"]).strip(), "sha256": str(item["sha256"]).strip()}
            for item in evidence_items
        ],
    }
    if notes is not None:
        if not isinstance(notes, str) or len(notes) > MAX_NOTES_CHARS:
            raise GateEmitError(f"notes must be a string ≤ {MAX_NOTES_CHARS} chars")
        payload["notes"] = notes
    if result == "PASS":
        if candidate_generation is None or preservation_snapshot_sha256 is None:
            raise GateEmitError(
                "PASS requires candidate_generation and preservation_snapshot_sha256"
            )
        if not canary.CANDIDATE_GENERATION_RE.fullmatch(candidate_generation):
            raise GateEmitError("candidate_generation charset/length invalid")
        if not canary.SHA256_RE.fullmatch(preservation_snapshot_sha256):
            raise GateEmitError("preservation_snapshot_sha256 must be 64 lowercase hex")
        payload["candidate_generation"] = candidate_generation
        payload["preservation_snapshot_sha256"] = preservation_snapshot_sha256
    else:
        if candidate_generation is not None:
            payload["candidate_generation"] = candidate_generation
        if preservation_snapshot_sha256 is not None:
            payload["preservation_snapshot_sha256"] = preservation_snapshot_sha256
    for index, item in enumerate(payload["evidence"]):
        if not item["path"] or Path(item["path"]).is_absolute():
            raise GateEmitError(f"evidence[{index}].path must be relative non-empty")
        if not canary.SHA256_RE.fullmatch(item["sha256"]):
            raise GateEmitError(f"evidence[{index}].sha256 must be 64 lowercase hex")
    return payload


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    """Write JSON object atomically; refuse overwrite. Return SHA-256 of bytes.

    Bytes are fully written + fsynced to a unique temp sibling, then published
    with ``os.replace`` so readers never observe a partial destination. The
    destination must not already exist (no silent overwrite).
    """

    raw = (json.dumps(dict(payload), sort_keys=True, indent=2) + "\n").encode("utf-8")
    digest = sha256_bytes(raw)
    if path.exists() or path.is_symlink():
        raise GateEmitError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        fd = os.open(str(tmp), flags)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        # Race-safe refuse-overwrite: exclusive create of destination, then
        # replace that empty placeholder with the fsynced temp payload.
        placeholder_fd = os.open(str(path), flags)
        os.close(placeholder_fd)
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return digest


def materialize_receipt(
    gate_dir: Path,
    *,
    relative_path: str,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    """Write a receipt under gate_dir and return {path, sha256} for evidence[]."""

    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise GateEmitError(f"receipt path must be relative without ..: {relative_path}")
    path = gate_dir / relative_path
    digest = write_json_atomic(path, payload)
    return {"path": relative_path.replace("\\", "/"), "sha256": digest}


def materialize_bytes(
    gate_dir: Path,
    *,
    relative_path: str,
    raw: bytes,
) -> dict[str, str]:
    """Copy opaque bytes under gate_dir atomically; return evidence item."""

    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise GateEmitError(f"receipt path must be relative without ..: {relative_path}")
    path = gate_dir / relative_path
    digest = sha256_bytes(raw)
    if path.exists() or path.is_symlink():
        raise GateEmitError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        fd = os.open(str(tmp), flags)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        placeholder_fd = os.open(str(path), flags)
        os.close(placeholder_fd)
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return {"path": relative_path.replace("\\", "/"), "sha256": digest}


def emit_gate_evidence(
    gate_dir: Path,
    *,
    gate: str,
    result: str,
    target_commit: str,
    evidence_items: Sequence[Mapping[str, str]],
    completed_at: Optional[str] = None,
    notes: Optional[str] = None,
    candidate_generation: Optional[str] = None,
    preservation_snapshot_sha256: Optional[str] = None,
) -> tuple[Path, dict[str, Any]]:
    """Write <gate>.json under gate_dir after verifying referenced receipt bytes."""

    payload = build_gate_payload(
        gate=gate,
        result=result,
        target_commit=target_commit,
        evidence_items=evidence_items,
        completed_at=completed_at,
        notes=notes,
        candidate_generation=candidate_generation,
        preservation_snapshot_sha256=preservation_snapshot_sha256,
    )
    base = gate_dir.resolve()
    for index, item in enumerate(payload["evidence"]):
        resolved = (base / item["path"]).resolve()
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise GateEmitError(f"evidence[{index}] escapes gate dir") from exc
        if resolved.is_symlink() or not resolved.is_file():
            raise GateEmitError(f"evidence[{index}] missing regular file: {item['path']}")
        actual = sha256_file(resolved)
        if actual != item["sha256"]:
            raise GateEmitError(
                f"evidence[{index}] sha256 mismatch for {item['path']} "
                f"(got {actual}, expected {item['sha256']})"
            )
    out = gate_dir / f"{gate}.json"
    write_json_atomic(out, payload)
    return out, payload
