"""Unit tests for shadow-ingest and app-matrix receipt producers (fail-closed)."""

from __future__ import annotations

import json
from pathlib import Path

import pi_canary_app_matrix_receipts as app_matrix
import pi_canary_shadow_ingest as shadow

TARGET = "0d8cd36a478a2e8c35d2372659b42a842a14b220"


def test_shadow_template_is_unknown(tmp_path: Path) -> None:
    out = tmp_path / "shadow-template.json"
    info = shadow.emit_template(
        out, target_commit=TARGET, candidate_generation="prep-test"
    )
    assert info["result"] == "UNKNOWN"
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["result"] == "UNKNOWN"
    assert body["target_commit"] == TARGET
    assert body["operator_steps"]


def test_shadow_canonicalize_rejects_wrong_commit(tmp_path: Path) -> None:
    src = tmp_path / "src.json"
    src.write_text(
        json.dumps(
            {
                "target_commit": "a" * 40,
                "result": "PASS",
                "exit_code": 0,
                "exports_dirs": ["/tmp/x"],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    info = shadow.validate_and_canonicalize(src, out, target_commit=TARGET)
    assert info["result"] == "FAIL"
    assert any("mismatch" in f for f in info["findings"])


def test_shadow_canonicalize_pass(tmp_path: Path) -> None:
    src = tmp_path / "src.json"
    src.write_text(
        json.dumps(
            {
                "target_commit": TARGET,
                "result": "PASS",
                "exit_code": 0,
                "exports_dirs": ["/srv/ar-local/canary/x/data/runs/2026-10-26/_exports"],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    info = shadow.validate_and_canonicalize(src, out, target_commit=TARGET)
    assert info["result"] == "PASS"


def test_app_matrix_templates(tmp_path: Path) -> None:
    infos = []
    for gate in app_matrix.GATES:
        out = tmp_path / f"{gate}.json"
        infos.append(app_matrix.emit_template(gate, out, target_commit=TARGET))
    assert {i["result"] for i in infos} == {"UNKNOWN"}


def test_emulator_canonicalize_requires_devices(tmp_path: Path) -> None:
    src = tmp_path / "emu.json"
    src.write_text(
        json.dumps({"target_commit": TARGET, "result": "PASS", "devices": []}),
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    info = app_matrix.canonicalize(
        "candidate_emulator_matrix", src, out, target_commit=TARGET
    )
    assert info["result"] == "FAIL"
