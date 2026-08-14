"""Portable contract checks for the off-repository preservation locator."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "docs" / "preservation" / "PRESERVATION_EVIDENCE_V1.json"
SCHEMA_PATH = ROOT / "contracts" / "preservation-evidence-v1.schema.json"


def test_preservation_evidence_is_schema_valid_and_complete() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(evidence)

    manifests = {item["path"]: item for item in evidence["manifests"]}
    assert len(manifests) == len(evidence["manifests"]) == 10
    assert manifests["manifests/preservation-file-inventory.jsonl"] == {
        "path": "manifests/preservation-file-inventory.jsonl",
        "bytes": 744155,
        "sha256": "0482f54a47536a0971d061a13a7549ffe0a22094eb13c6bd961d714354221325",
    }
    assert evidence["verification_summary"]["critical_files"] == 1932
    assert evidence["verification_summary"]["critical_bytes"] == 25586769110


def test_preservation_locator_is_portable_and_fail_closed() -> None:
    raw = EVIDENCE_PATH.read_text(encoding="utf-8")
    evidence = json.loads(raw)
    assert "C:\\" not in raw
    assert "/Users/" not in raw
    assert evidence["retrieval"]["network_required"] is False
    assert evidence["retrieval"]["writes_permitted"] is False
    assert evidence["storage"]["offsite_object_locked_copy_status"] == "pending"
    assert any("Stop the import" in step for step in evidence["retrieval"]["procedure"])
