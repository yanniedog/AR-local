"""Shape checks for canary gate-evidence example fixtures (not live evidence)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FIX_DIR = Path(__file__).resolve().parent / "fixtures" / "canary-gate-evidence"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
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


def _example_paths() -> list[Path]:
    return sorted(FIX_DIR.glob("example-*.json"))


@pytest.mark.parametrize("path", _example_paths(), ids=lambda p: p.name)
def test_example_gate_evidence_shape(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("schema_version") == 1
    assert data.get("gate") in GATES
    assert data.get("result") in RESULTS
    assert COMMIT_RE.fullmatch(str(data.get("target_commit") or ""))
    assert isinstance(data.get("completed_at"), str) and data["completed_at"]
    evidence = data.get("evidence")
    assert isinstance(evidence, list) and evidence
    for item in evidence:
        assert isinstance(item.get("path"), str) and item["path"]
        assert SHA_RE.fullmatch(str(item.get("sha256") or ""))
    notes = data.get("notes", "")
    assert "FIXTURE ONLY" in notes


def test_examples_cover_pass_fail_unknown() -> None:
    results = {
        json.loads(p.read_text(encoding="utf-8"))["result"] for p in _example_paths()
    }
    assert results == {"PASS", "FAIL", "UNKNOWN"}
