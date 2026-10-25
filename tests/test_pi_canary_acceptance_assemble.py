"""Tests for assembling canary-acceptance.json from per-gate evidence files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_canary_acceptance as canary  # noqa: E402
import pi_canary_acceptance_assemble as assemble  # noqa: E402

COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40
REPOSITORY = "yanniedog/AR-local"
SNAPSHOT = "c" * 64
COMPLETED = "2026-10-25T10:00:00+11:00"


def gate_payload(gate: str, *, result: str = "PASS", commit: str = COMMIT) -> dict:
    return {
        "schema_version": 1,
        "gate": gate,
        "result": result,
        "target_commit": commit,
        "completed_at": COMPLETED,
        "evidence": [
            {
                "path": f"fixtures/{gate}-receipt.json",
                "sha256": "d" * 64,
            }
        ],
    }


def write_gate(dir_path: Path, gate: str, **kwargs) -> Path:
    path = dir_path / f"{gate}.json"
    path.write_text(json.dumps(gate_payload(gate, **kwargs), indent=2) + "\n", encoding="utf-8")
    return path


def write_all_pass(dir_path: Path) -> None:
    for gate in canary.REQUIRED_ACCEPTANCE_GATES:
        write_gate(dir_path, gate)


def test_gate_evidence_schema_matches_fixture_shape() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "canary-gate-evidence-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for gate in canary.REQUIRED_ACCEPTANCE_GATES:
        validator.validate(gate_payload(gate))
        validator.validate(gate_payload(gate, result="UNKNOWN"))
        validator.validate(gate_payload(gate, result="FAIL"))


def test_assembles_manifest_only_when_all_gates_pass(tmp_path: Path) -> None:
    evidence = tmp_path / "gates"
    evidence.mkdir()
    write_all_pass(evidence)
    output = tmp_path / "canary-acceptance.json"

    payload, digest = assemble.assemble_canary_acceptance(
        repository=REPOSITORY,
        target_commit=COMMIT,
        candidate_generation="prep-2026-10-25-001",
        preservation_snapshot_sha256=SNAPSHOT,
        completed_at=COMPLETED,
        output=output,
        gate_paths={g: evidence / f"{g}.json" for g in canary.REQUIRED_ACCEPTANCE_GATES},
    )

    assert output.is_file()
    assert payload["status"] == "passed"
    assert all(payload["acceptance_gates"][g] is True for g in canary.REQUIRED_ACCEPTANCE_GATES)
    verified = canary.verify_canary_acceptance(
        output,
        expected_sha256=digest,
        expected_commit=COMMIT,
        expected_repository=REPOSITORY,
    )
    assert verified["candidate_generation"] == "prep-2026-10-25-001"


@pytest.mark.parametrize("bad_result", ["UNKNOWN", "FAIL"])
def test_refuses_unknown_or_fail_without_writing(tmp_path: Path, bad_result: str) -> None:
    evidence = tmp_path / "gates"
    evidence.mkdir()
    write_all_pass(evidence)
    write_gate(evidence, "candidate_emulator_matrix", result=bad_result)
    output = tmp_path / "canary-acceptance.json"

    with pytest.raises(assemble.CanaryAssembleError, match="candidate_emulator_matrix"):
        assemble.assemble_canary_acceptance(
            repository=REPOSITORY,
            target_commit=COMMIT,
            candidate_generation="prep-2026-10-25-001",
            preservation_snapshot_sha256=SNAPSHOT,
            completed_at=COMPLETED,
            output=output,
            gate_paths={g: evidence / f"{g}.json" for g in canary.REQUIRED_ACCEPTANCE_GATES},
        )
    assert not output.exists()


def test_refuses_missing_gate_file_never_defaults_true(tmp_path: Path) -> None:
    evidence = tmp_path / "gates"
    evidence.mkdir()
    for gate in canary.REQUIRED_ACCEPTANCE_GATES:
        if gate != "candidate_device_matrix":
            write_gate(evidence, gate)
    paths = {
        g: evidence / f"{g}.json"
        for g in canary.REQUIRED_ACCEPTANCE_GATES
        if g != "candidate_device_matrix"
    }
    output = tmp_path / "canary-acceptance.json"

    with pytest.raises(assemble.CanaryAssembleError, match="candidate_device_matrix"):
        assemble.assemble_canary_acceptance(
            repository=REPOSITORY,
            target_commit=COMMIT,
            candidate_generation="prep-2026-10-25-001",
            preservation_snapshot_sha256=SNAPSHOT,
            completed_at=COMPLETED,
            output=output,
            gate_paths=paths,
        )
    assert not output.exists()


def test_refuses_commit_mismatch_on_gate_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "gates"
    evidence.mkdir()
    write_all_pass(evidence)
    write_gate(evidence, "historical_integrity", commit=OTHER_COMMIT)
    output = tmp_path / "out.json"

    with pytest.raises(assemble.CanaryAssembleError, match="target_commit mismatch"):
        assemble.assemble_canary_acceptance(
            repository=REPOSITORY,
            target_commit=COMMIT,
            candidate_generation="prep-2026-10-25-001",
            preservation_snapshot_sha256=SNAPSHOT,
            completed_at=COMPLETED,
            output=output,
            gate_paths={g: evidence / f"{g}.json" for g in canary.REQUIRED_ACCEPTANCE_GATES},
        )
    assert not output.exists()


def test_cli_lists_missing_gates_and_exits_nonzero(tmp_path: Path) -> None:
    evidence = tmp_path / "gates"
    evidence.mkdir()
    write_gate(evidence, "preservation_restore")
    write_gate(evidence, "historical_integrity", result="UNKNOWN")
    output = tmp_path / "canary-acceptance.json"

    code = assemble.main(
        [
            "--repository",
            REPOSITORY,
            "--target-commit",
            COMMIT,
            "--candidate-generation",
            "prep-2026-10-25-001",
            "--preservation-snapshot-sha256",
            SNAPSHOT,
            "--completed-at",
            COMPLETED,
            "--output",
            str(output),
            "--gate-evidence-dir",
            str(evidence),
        ]
    )
    assert code == 2
    assert not output.exists()


def test_cli_writes_when_directory_has_all_pass(tmp_path: Path) -> None:
    evidence = tmp_path / "gates"
    evidence.mkdir()
    write_all_pass(evidence)
    output = tmp_path / "canary-acceptance.json"

    code = assemble.main(
        [
            "--repository",
            REPOSITORY,
            "--target-commit",
            COMMIT,
            "--candidate-generation",
            "prep-2026-10-25-001",
            "--preservation-snapshot-sha256",
            SNAPSHOT,
            "--completed-at",
            COMPLETED,
            "--output",
            str(output),
            "--gate-evidence-dir",
            str(evidence),
        ]
    )
    assert code == 0
    assert output.is_file()


def test_refuses_overwrite_existing_manifest(tmp_path: Path) -> None:
    evidence = tmp_path / "gates"
    evidence.mkdir()
    write_all_pass(evidence)
    output = tmp_path / "canary-acceptance.json"
    output.write_text("existing\n", encoding="utf-8")

    with pytest.raises(assemble.CanaryAssembleError, match="overwrite"):
        assemble.assemble_canary_acceptance(
            repository=REPOSITORY,
            target_commit=COMMIT,
            candidate_generation="prep-2026-10-25-001",
            preservation_snapshot_sha256=SNAPSHOT,
            completed_at=COMPLETED,
            output=output,
            gate_paths={g: evidence / f"{g}.json" for g in canary.REQUIRED_ACCEPTANCE_GATES},
        )
