"""Shape checks for canary gate-evidence example fixtures (not live evidence)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

FIX_DIR = Path(__file__).resolve().parent / "fixtures" / "canary-gate-evidence"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "canary-gate-evidence-v1.schema.json"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FILENAME_RE = re.compile(
    r"^example-(pass|fail|unknown)-([a-z0-9_]+)\.json$"
)
GATES = {
    "preservation_restore",
    "historical_integrity",
    "shadow_ingest",
    "producer_contracts",
    "stable_app_compatibility",
    "candidate_emulator_matrix",
    "candidate_device_matrix",
    "public_candidate_bytes",
}
RESULTS = {"PASS", "FAIL", "UNKNOWN"}
RESULT_BY_TOKEN = {"pass": "PASS", "fail": "FAIL", "unknown": "UNKNOWN"}
ASSEMBLE_BINDINGS = ("candidate_generation", "preservation_snapshot_sha256")


def _example_paths() -> list[Path]:
    return sorted(FIX_DIR.glob("example-*.json"))


def _schema_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize("path", _example_paths(), ids=lambda p: p.name)
def test_example_gate_evidence_shape(path: Path) -> None:
    match = FILENAME_RE.fullmatch(path.name)
    assert match, f"fixture filename must be example-<result>-<gate>.json: {path.name}"
    expected_result = RESULT_BY_TOKEN[match.group(1)]
    expected_gate = match.group(2)
    assert expected_gate in GATES

    data = json.loads(path.read_text(encoding="utf-8"))
    _schema_validator().validate(data)

    assert data["schema_version"] == 1
    assert isinstance(data["schema_version"], int)
    assert data["gate"] == expected_gate
    assert isinstance(data["gate"], str)
    assert data["result"] == expected_result
    assert isinstance(data["result"], str)
    assert data["gate"] in GATES
    assert data["result"] in RESULTS

    target_commit = data["target_commit"]
    assert isinstance(target_commit, str)
    assert COMMIT_RE.fullmatch(target_commit)

    completed_at = data["completed_at"]
    assert isinstance(completed_at, str) and completed_at
    parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, "completed_at must be timezone-aware ISO-8601"

    evidence = data["evidence"]
    assert isinstance(evidence, list) and evidence
    for item in evidence:
        assert isinstance(item, dict)
        item_path = item["path"]
        digest = item["sha256"]
        assert isinstance(item_path, str) and item_path
        assert isinstance(digest, str)
        assert SHA_RE.fullmatch(digest)

    notes = data.get("notes", "")
    assert isinstance(notes, str)
    assert "FIXTURE ONLY" in notes

    # Example PASS fixtures must stay non-assemble-ready: no generation/snapshot
    # bindings that could authorize canary-acceptance assembly.
    for field in ASSEMBLE_BINDINGS:
        assert field not in data, f"{path.name} must omit assemble binding {field}"


def test_examples_cover_pass_fail_unknown() -> None:
    results = {
        json.loads(p.read_text(encoding="utf-8"))["result"] for p in _example_paths()
    }
    assert results == {"PASS", "FAIL", "UNKNOWN"}


def test_pass_fixture_rejected_when_assembler_requires_bindings() -> None:
    """Regression: PASS example alone cannot satisfy assemble binding checks."""
    from pi_canary_acceptance_assemble import evaluate_gate_evidence

    pass_paths = [p for p in _example_paths() if p.name.startswith("example-pass-")]
    assert pass_paths, "expected at least one PASS fixture"
    path = pass_paths[0]
    data = json.loads(path.read_text(encoding="utf-8"))
    ok, reason = evaluate_gate_evidence(
        path,
        expected_gate=data["gate"],
        expected_commit=data["target_commit"],
        expected_candidate_generation="fixture-must-not-match",
        expected_preservation_snapshot_sha256="0" * 64,
    )
    assert ok is False
    assert "candidate_generation mismatch" in reason
