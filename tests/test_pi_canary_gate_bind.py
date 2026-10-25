"""Tests for canary gate emit/bind helpers (no fabricated live acceptance)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_canary_acceptance as canary  # noqa: E402
import pi_canary_gate_bind as bind  # noqa: E402
import pi_canary_gate_emit as emit  # noqa: E402

COMMIT = "a" * 40
GENERATION = "prep-test-001"
SNAPSHOT = "c" * 64


def test_emit_refuses_pass_without_bindings(tmp_path: Path) -> None:
    receipt = emit.materialize_receipt(
        tmp_path, relative_path="receipts/x.json", payload={"ok": True}
    )
    with pytest.raises(emit.GateEmitError, match="PASS requires"):
        emit.emit_gate_evidence(
            tmp_path,
            gate="producer_contracts",
            result="PASS",
            target_commit=COMMIT,
            evidence_items=[receipt],
        )


def test_emit_unknown_without_pass_bindings(tmp_path: Path) -> None:
    receipt = emit.materialize_receipt(
        tmp_path, relative_path="receipts/x.json", payload={"ok": True}
    )
    path, payload = emit.emit_gate_evidence(
        tmp_path,
        gate="shadow_ingest",
        result="UNKNOWN",
        target_commit=COMMIT,
        evidence_items=[receipt],
        notes="missing receipt",
    )
    assert path.is_file()
    assert payload["result"] == "UNKNOWN"
    assert "candidate_generation" not in payload


def test_producer_contracts_pass_on_real_repo_schemas(tmp_path: Path) -> None:
    payload = bind.bind_producer_contracts(
        tmp_path,
        target_commit=COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "PASS"
    assert payload["target_commit"] == COMMIT
    assert (tmp_path / "producer_contracts.json").is_file()
    assert (tmp_path / "receipts" / "producer_contracts-receipt.json").is_file()


def test_historical_integrity_fail_when_summary_incomplete(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dates_checked": 2,
                "dates_passed": 1,
                "index_sha256": "d" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_historical_integrity(
        gate_dir,
        target_commit=COMMIT,
        summary_path=summary,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"


def test_historical_integrity_refuses_scoped_one_date_by_default(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dates_checked": 1,
                "dates_passed": 1,
                "index_sha256": "d" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_historical_integrity(
        gate_dir,
        target_commit=COMMIT,
        summary_path=summary,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"


def test_harness_fail_closed_without_external_receipts(tmp_path: Path) -> None:
    status = bind.run_harness(
        tmp_path / "gates",
        target_commit=COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        skip_ssh=True,
    )
    assert status["assemble_ready"] is False
    assert status["gates"]["producer_contracts"]["result"] == "PASS"
    for gate in (
        "preservation_restore",
        "historical_integrity",
        "shadow_ingest",
        "stable_app_compatibility",
        "candidate_emulator_matrix",
        "candidate_device_matrix",
        "public_candidate_bytes",
    ):
        assert status["gates"][gate]["result"] in {"UNKNOWN", "FAIL"}
    # Assembler must refuse.
    import pi_canary_acceptance_assemble as assemble

    gate_dir = tmp_path / "gates"
    with pytest.raises(assemble.CanaryAssembleError, match="unresolved gates"):
        assemble.assemble_canary_acceptance(
            repository="yanniedog/AR-local",
            target_commit=COMMIT,
            candidate_generation=GENERATION,
            preservation_snapshot_sha256=SNAPSHOT,
            completed_at="2026-10-26T00:00:00+00:00",
            output=tmp_path / "canary-acceptance.json",
            gate_paths={g: gate_dir / f"{g}.json" for g in canary.REQUIRED_ACCEPTANCE_GATES},
        )
    assert not (tmp_path / "canary-acceptance.json").exists()


def test_sha256_helpers_stable() -> None:
    raw = b"abc"
    assert emit.sha256_bytes(raw) == hashlib.sha256(raw).hexdigest()
