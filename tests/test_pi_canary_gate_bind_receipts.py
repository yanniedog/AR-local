"""External-receipt binder tests (split from gate bind)."""

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


def test_receipt_gate_validates_preserved_bytes_not_source_reread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the producer rewrites the source after copy, binder must use preserved bytes."""
    import pi_canary_gate_bind_ops as ops

    receipt = tmp_path / "r.json"
    fail_body = {
        "gate": "shadow_ingest",
        "target_commit": COMMIT,
        "result": "FAIL",
        "candidate_generation": GENERATION,
        "preservation_snapshot_sha256": SNAPSHOT,
    }
    pass_body = {
        "gate": "shadow_ingest",
        "target_commit": COMMIT,
        "result": "PASS",
        "candidate_generation": GENERATION,
        "preservation_snapshot_sha256": SNAPSHOT,
    }
    receipt.write_text(json.dumps(fail_body) + "\n", encoding="utf-8")
    original = ops._copy_source_receipt

    def copy_then_rewrite(gate_dir, *, source, relative_path):
        item = original(gate_dir, source=source, relative_path=relative_path)
        source.write_text(json.dumps(pass_body) + "\n", encoding="utf-8")
        return item

    monkeypatch.setattr(ops, "_copy_source_receipt", copy_then_rewrite)
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
    preserved = json.loads(
        (gate_dir / "receipts" / "shadow_ingest-source.json").read_text(encoding="utf-8")
    )
    assert preserved["result"] == "FAIL"


def test_receipt_gate_rejects_missing_explicit_pass(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps({"gate": "shadow_ingest", "target_commit": COMMIT, "status": "FAIL"})
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
    assert (gate_dir / "receipts" / "shadow_ingest-source.json").is_file()


def test_receipt_gate_rejects_generation_relabel(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "gate": "shadow_ingest",
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


def test_receipt_gate_rejects_cross_gate_substitution(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "gate": "shadow_ingest",
                "target_commit": COMMIT,
                "result": "PASS",
                "candidate_generation": GENERATION,
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
        gate="candidate_device_matrix",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "FAIL"
    body = json.loads(
        (gate_dir / "receipts" / "candidate_device_matrix-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("gate:" in f and "shadow_ingest" in f for f in body["findings"])


def test_receipt_gate_rejects_shadow_without_exit_exports(tmp_path: Path) -> None:
    """Labeled PASS without exit_code/exports must not authorize shadow_ingest."""
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "gate": "shadow_ingest",
                "target_commit": COMMIT,
                "result": "PASS",
                "candidate_generation": GENERATION,
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
    body = json.loads(
        (gate_dir / "receipts" / "shadow_ingest-receipt.json").read_text(encoding="utf-8")
    )
    assert any("exit_code" in f for f in body["findings"])
    assert any("exports" in f for f in body["findings"])


def test_receipt_gate_passes_shadow_with_exit_exports(tmp_path: Path) -> None:
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "gate": "shadow_ingest",
                "target_commit": COMMIT,
                "result": "PASS",
                "exit_code": 0,
                "exports_dirs": ["/srv/ar-local/canary/exports/day"],
                "candidate_generation": GENERATION,
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
    assert payload["result"] == "PASS"


def test_receipt_gate_rejects_empty_device_matrix(tmp_path: Path) -> None:
    """Matrix labels alone (empty devices / FAIL rows) must not authorize PASS."""
    receipt = tmp_path / "r.json"
    receipt.write_text(
        json.dumps(
            {
                "gate": "candidate_device_matrix",
                "target_commit": COMMIT,
                "result": "PASS",
                "devices": [{"model": "Pixel", "result": "FAIL"}],
                "candidate_generation": GENERATION,
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
        gate="candidate_device_matrix",
        target_commit=COMMIT,
        receipt_path=receipt,
        required_fields={"target_commit": COMMIT},
        candidate_generation=GENERATION,
        preservation_snapshot_sha256=SNAPSHOT,
        missing_reason="unused",
    )
    assert payload["result"] == "FAIL"
    body = json.loads(
        (gate_dir / "receipts" / "candidate_device_matrix-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("devices[0].result must be PASS" in f for f in body["findings"])

