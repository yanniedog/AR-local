"""Portable contract checks for the off-repository preservation locator."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from preservation_evidence import load_and_validate, validate_evidence


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "docs" / "preservation" / "PRESERVATION_EVIDENCE_V1.json"
SCHEMA_PATH = ROOT / "contracts" / "preservation-evidence-v1.schema.json"


def test_preservation_evidence_is_schema_valid_and_complete() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert load_and_validate(EVIDENCE_PATH, SCHEMA_PATH) == evidence

    manifests = {item["path"]: item for item in evidence["manifests"]}
    assert len(manifests) == len(evidence["manifests"]) == 10
    assert manifests["manifests/preservation-file-inventory.jsonl"] == {
        "path": "manifests/preservation-file-inventory.jsonl",
        "bytes": 744155,
        "sha256": "0482f54a47536a0971d061a13a7549ffe0a22094eb13c6bd961d714354221325",
    }
    assert evidence["verification_summary"]["critical_files"] == 1932
    assert evidence["verification_summary"]["critical_bytes"] == 25586769110
    assert evidence["retrieval"]["required_root"] == evidence["storage"][
        "root_placeholder"
    ]
    assert evidence["storage"]["snapshot_relative_path"] == evidence[
        "snapshot_id"
    ]


def test_preservation_locator_is_portable_and_fail_closed() -> None:
    raw = EVIDENCE_PATH.read_text(encoding="utf-8")
    evidence = json.loads(raw)
    assert "C:\\" not in raw
    assert "/Users/" not in raw
    assert evidence["retrieval"]["network_required"] is False
    assert evidence["retrieval"]["writes_permitted"] is False
    assert evidence["storage"]["offsite_object_locked_copy_status"] == "pending"
    assert any("Stop the import" in step for step in evidence["retrieval"]["procedure"])


def test_preservation_evidence_rejects_duplicate_manifest_paths() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    invalid = deepcopy(evidence)
    duplicate = deepcopy(invalid["manifests"][0])
    duplicate["sha256"] = "0" * 64
    invalid["manifests"].append(duplicate)

    with pytest.raises(ValueError, match="unique path values"):
        validate_evidence(invalid, schema)
