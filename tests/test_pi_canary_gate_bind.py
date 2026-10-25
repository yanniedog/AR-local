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


def test_write_json_atomic_preserves_peer_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TOCTOU: peer owns destination after exists-check; do not unlink it."""

    path = tmp_path / "peer.json"
    path.write_text('{"peer": true}\n', encoding="utf-8")
    before = path.read_bytes()
    target = path.resolve()
    orig_exists = Path.exists
    orig_is_symlink = Path.is_symlink

    def fake_exists(self: Path) -> bool:
        try:
            if self.resolve() == target:
                return False
        except OSError:
            pass
        return orig_exists(self)

    def fake_is_symlink(self: Path) -> bool:
        try:
            if self.resolve() == target:
                return False
        except OSError:
            pass
        return orig_is_symlink(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    with pytest.raises(FileExistsError):
        emit.write_json_atomic(path, {"hijack": True})
    assert path.read_bytes() == before


def test_historical_integrity_requires_expected_index_binding(tmp_path: Path) -> None:
    index = {
        "dates": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "revision_heads": {},
    }
    index_raw = (json.dumps(index, sort_keys=True) + "\n").encode("utf-8")
    index_path = tmp_path / "dates-index.json"
    index_path.write_bytes(index_raw)
    index_sha = hashlib.sha256(index_raw).hexdigest()
    # Scoped two-date audit claiming the full-index digest must still FAIL.
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dates_checked": 2,
                "dates_passed": 2,
                "index_sha256": index_sha,
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
        expected_index_path=index_path,
    )
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "historical_integrity-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("population" in f for f in receipt["findings"])


def test_producer_contracts_reject_mismatched_target(tmp_path: Path) -> None:
    payload = bind.bind_producer_contracts(
        tmp_path,
        target_commit=FAKE_COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
    )
    assert payload["result"] == "FAIL"


def test_producer_contracts_reject_invalid_v3_metaschema(tmp_path: Path) -> None:
    """Syntactically valid but metaschema-invalid v3 schema must FAIL (not digest-only PASS)."""
    import shutil

    from cdr_domain import contract_validation

    contracts_root = tmp_path / "contracts"
    contracts_root.mkdir()
    # Top-level schema must be Draft 2020-12 valid so only the v3 defect is exercised.
    (contracts_root / "top.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    v3_src = ROOT / "contracts" / "v3"
    v3_dst = contracts_root / "v3"
    v3_dst.mkdir()
    for name in contract_validation.SCHEMA_FILES:
        shutil.copy2(v3_src / name, v3_dst / name)
    bad = v3_dst / "canonical-core-v3.schema.json"
    schema = json.loads(bad.read_text(encoding="utf-8"))
    schema["type"] = 42  # invalid JSON Schema type keyword
    bad.write_text(json.dumps(schema) + "\n", encoding="utf-8")

    gate_dir = tmp_path / "gates"
    gate_dir.mkdir()
    payload = bind.bind_producer_contracts(
        gate_dir,
        target_commit=COMMIT,
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        contracts_root=contracts_root,
    )
    assert payload["result"] == "FAIL"
    receipt = json.loads(
        (gate_dir / "receipts" / "producer_contracts-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any(
        f.startswith("v3/canonical-core-v3.schema.json:") for f in receipt["findings"]
    )


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
