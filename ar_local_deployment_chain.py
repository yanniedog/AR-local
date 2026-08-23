"""Validate and recover the append-only Pi deployment acceptance chain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator, FormatChecker

from ar_local_backup_policy import (
    BackupPolicy,
    COMMIT_RE,
    SHA256_RE,
    atomic_replace_json,
    sha256_file,
    validate_plan_identity,
)

DEPLOYMENT_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "contracts/pi-deployment-acceptance-v1.schema.json"
)


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _validate_record(path: Path, record: Mapping[str, object], policy: BackupPolicy) -> None:
    schema = _json(DEPLOYMENT_SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ValueError(f"deployment record schema is invalid: {path}: {errors[0].message}")
    backup_root = policy.backup_dir.resolve()
    for entry in record["evidence"]:
        if not isinstance(entry, Mapping):
            raise ValueError(f"deployment record evidence is invalid: {path}")
        evidence_path = Path(str(entry["path"]))
        if not evidence_path.is_absolute() or evidence_path.is_symlink():
            raise ValueError(f"deployment evidence path is unsafe: {evidence_path}")
        resolved = evidence_path.resolve(strict=True)
        if resolved != evidence_path or not resolved.is_relative_to(backup_root):
            raise ValueError(f"deployment evidence escapes backup storage: {evidence_path}")
        if not resolved.is_file() or resolved.stat().st_nlink != 1:
            raise ValueError(f"deployment evidence is not an immutable regular file: {evidence_path}")
        if sha256_file(resolved) != entry["sha256"]:
            raise ValueError(f"deployment evidence digest mismatch: {evidence_path}")


def reconcile_deployment_chain(records_root: Path, policy: BackupPolicy) -> tuple[int, str | None]:
    """Return the next sequence and predecessor digest, repairing only a valid head lag."""

    records: list[tuple[int, Path, dict[str, object], str]] = []
    for path in records_root.glob("*.record.json"):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"deployment record is not a regular file: {path}")
        record = _json(path)
        _validate_record(path, record, policy)
        sequence = record.get("sequence")
        if not isinstance(sequence, int) or sequence < 1:
            raise ValueError(f"deployment record sequence is invalid: {path}")
        records.append((sequence, path.resolve(), record, sha256_file(path)))
    records.sort(key=lambda item: item[0])
    previous_digest: str | None = None
    for expected_sequence, (sequence, _path, record, digest) in enumerate(records, 1):
        if sequence != expected_sequence or record.get("previous_record_sha256") != previous_digest:
            raise ValueError("deployment record chain is not contiguous")
        if (
            record.get("result") != "PASS"
            or not validate_plan_identity(record, policy)
            or not COMMIT_RE.fullmatch(str(record.get("candidate_code_sha") or ""))
        ):
            raise ValueError("deployment record chain contains an invalid record")
        previous_digest = digest
    head_path = records_root / "head.json"
    if head_path.is_symlink():
        raise ValueError("deployment chain head is a symlink")
    if not records:
        if head_path.exists():
            raise ValueError("deployment chain head exists without records")
        return 1, None
    sequence, record_path, _record, digest = records[-1]
    expected_head = {
        "schema_version": 1,
        "sequence": sequence,
        "record_path": record_path.relative_to(records_root.resolve()).as_posix(),
        "record_sha256": digest,
    }
    if head_path.is_file():
        head = _json(head_path)
        head_sequence = head.get("sequence")
        if not isinstance(head_sequence, int) or head_sequence < 1 or head_sequence > sequence:
            raise ValueError("deployment chain head sequence is invalid")
        prefix = records[head_sequence - 1]
        prefix_expected = {
            "schema_version": 1,
            "sequence": prefix[0],
            "record_path": prefix[1].relative_to(records_root.resolve()).as_posix(),
            "record_sha256": prefix[3],
        }
        if head != prefix_expected:
            raise ValueError("deployment chain head does not identify a valid prefix")
    atomic_replace_json(head_path, expected_head)
    if not SHA256_RE.fullmatch(digest):
        raise ValueError("deployment predecessor digest is invalid")
    return sequence + 1, digest
