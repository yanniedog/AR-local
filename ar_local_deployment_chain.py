"""Validate and recover the append-only Pi deployment acceptance chain."""

from __future__ import annotations

import json
from pathlib import Path

from ar_local_backup_policy import (
    BackupPolicy,
    COMMIT_RE,
    SHA256_RE,
    atomic_replace_json,
    sha256_file,
    validate_plan_identity,
)


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def reconcile_deployment_chain(records_root: Path, policy: BackupPolicy) -> tuple[int, str | None]:
    """Return the next sequence and predecessor digest, repairing only a valid head lag."""

    records: list[tuple[int, Path, dict[str, object], str]] = []
    for path in records_root.glob("*.record.json"):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"deployment record is not a regular file: {path}")
        record = _json(path)
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
        if head_path.is_symlink():
            raise ValueError("deployment chain head is a symlink")
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
