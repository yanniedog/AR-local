"""Tests for canary gate emit/bind helpers (no fabricated live acceptance)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_canary_acceptance as canary  # noqa: E402
import pi_canary_gate_bind as bind  # noqa: E402
import pi_canary_gate_emit as emit  # noqa: E402

COMMIT = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, encoding="utf-8"
).strip()
FAKE_COMMIT = "a" * 40
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
            target_commit=FAKE_COMMIT,
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
        target_commit=FAKE_COMMIT,
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


def test_historical_integrity_scoped_flag_never_authorizes(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dates_checked": 2,
                "dates_passed": 2,
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
        allow_scoped_index=True,
    )
    assert payload["result"] == "FAIL"


def test_write_json_atomic_publishes_via_replace(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    digest = emit.write_json_atomic(path, {"ok": True})
    assert path.is_file()
    assert digest == emit.sha256_file(path)
    with pytest.raises(emit.GateEmitError, match="overwrite"):
        emit.write_json_atomic(path, {"ok": False})


def test_receipt_gate_rejects_missing_explicit_pass(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps({"target_commit": COMMIT, "status": "FAIL"}) + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_receipt_gate(
        gate_dir,
        gate="shadow_ingest",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "FAIL"
    assert (gate_dir / "receipts" / "shadow_ingest-source.json").is_file()


def test_receipt_gate_rejects_generation_relabel(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "target_commit": COMMIT,
                "result": "PASS",
                "candidate_generation": "prep-old",
                "preservation_snapshot_sha256": SNAPSHOT,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_receipt_gate(
        gate_dir,
        gate="shadow_ingest",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "FAIL"


def test_producer_contracts_reject_mismatched_target(tmp_path: Path) -> None:
    payload = bind.bind_producer_contracts(
        tmp_path,
        target_commit=FAKE_COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"


def test_harness_isolates_malformed_receipt(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    status = bind.run_harness(
        tmp_path / "gates",
        target_commit=COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        shadow_receipt=bad,
        skip_ssh=True,
    )
    assert status["assemble_ready"] is False
    assert (tmp_path / "gates" / "status.json").is_file()
    assert status["gates"]["shadow_ingest"]["result"] == "FAIL"
    assert status["gates"]["producer_contracts"]["result"] == "PASS"


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
