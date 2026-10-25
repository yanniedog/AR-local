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
                "schema_version": 1,
                "gate": "shadow_ingest",
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
                "schema_version": 1,
                "gate": "shadow_ingest",
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
        json.dumps(
            {
                "schema_version": 1,
                "gate": "candidate_emulator_matrix",
                "target_commit": TARGET,
                "result": "PASS",
                "devices": [],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    info = app_matrix.canonicalize(
        "candidate_emulator_matrix", src, out, target_commit=TARGET
    )
    assert info["result"] == "FAIL"


def test_device_canonicalize_rejects_emulator_gate(tmp_path: Path) -> None:
    src = tmp_path / "emu.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "candidate_emulator_matrix",
                "target_commit": TARGET,
                "result": "PASS",
                "devices": [{"avd": "x", "result": "PASS"}],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    info = app_matrix.canonicalize(
        "candidate_device_matrix", src, out, target_commit=TARGET
    )
    assert info["result"] == "FAIL"
    assert any("gate" in f for f in info["findings"])


def test_matrix_canonicalize_rejects_failed_device(tmp_path: Path) -> None:
    src = tmp_path / "dev.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "candidate_device_matrix",
                "target_commit": TARGET,
                "result": "PASS",
                "devices": [{"id": "a", "result": "FAIL"}],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    info = app_matrix.canonicalize(
        "candidate_device_matrix", src, out, target_commit=TARGET
    )
    assert info["result"] == "FAIL"
    assert any("devices[0]" in f for f in info["findings"])


def test_device_canonicalize_rejects_false_install_checks(tmp_path: Path) -> None:
    src = tmp_path / "dev.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "candidate_device_matrix",
                "target_commit": TARGET,
                "result": "PASS",
                "devices": [
                    {
                        "model": "Pixel",
                        "os": "14",
                        "abi": "arm64-v8a",
                        "install_upgrade": False,
                        "acquisition_checks": False,
                        "result": "PASS",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    info = app_matrix.canonicalize(
        "candidate_device_matrix", src, tmp_path / "out.json", target_commit=TARGET
    )
    assert info["result"] == "FAIL"
    assert any("install_upgrade" in f for f in info["findings"])
    assert any("acquisition_checks" in f for f in info["findings"])


def test_shadow_canonicalize_rejects_non_list_exports(tmp_path: Path) -> None:
    src = tmp_path / "src.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "shadow_ingest",
                "target_commit": TARGET,
                "result": "PASS",
                "exit_code": 0,
                "exports_dirs": "not-an-array",
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    info = shadow.validate_and_canonicalize(src, out, target_commit=TARGET)
    assert info["result"] == "FAIL"
    assert any("must be a list" in f for f in info["findings"])


def test_shadow_canonicalize_requires_exit_and_exports(tmp_path: Path) -> None:
    src = tmp_path / "src.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "producer_contracts",
                "target_commit": TARGET,
                "result": "PASS",
                "exports_dirs": ["/srv/ar-local/canary/x/data/runs/2026-10-26/_exports"],
            }
        ),
        encoding="utf-8",
    )
    info = shadow.validate_and_canonicalize(
        src, tmp_path / "out.json", target_commit=TARGET
    )
    assert info["result"] == "FAIL"
    assert any("gate" in finding for finding in info["findings"])
    assert any("exit_code" in finding for finding in info["findings"])


def test_stable_app_requires_ci_evidence(tmp_path: Path) -> None:
    src = tmp_path / "app.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "stable_app_compatibility",
                "target_commit": TARGET,
                "result": "PASS",
            }
        ),
        encoding="utf-8",
    )
    info = app_matrix.canonicalize(
        "stable_app_compatibility", src, tmp_path / "out.json", target_commit=TARGET
    )
    assert info["result"] == "FAIL"
    assert any("ci.command" in finding for finding in info["findings"])


def test_write_json_atomic_create_once_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    app_matrix.write_json_atomic(path, {"result": "FAIL", "n": 1})
    try:
        app_matrix.write_json_atomic(path, {"result": "PASS", "n": 2})
        raise AssertionError("expected AppMatrixError on create-once collision")
    except app_matrix.AppMatrixError as exc:
        assert "immutable path" in str(exc).lower() or "already exists" in str(exc).lower()
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["result"] == "FAIL"
    assert body["n"] == 1


def test_shadow_template_forbids_production_archive(tmp_path: Path) -> None:
    out = tmp_path / "shadow-template.json"
    shadow.emit_template(out, target_commit=TARGET, candidate_generation="prep-test")
    body = json.loads(out.read_text(encoding="utf-8"))
    steps = "\n".join(body["operator_steps"])
    assert "AR_LOCAL_DAY_ARCHIVE_ENV" in steps
    assert "day-archive.env" in steps
    assert any("day-archive.env" in item for item in body["forbidden"])


def test_load_day_archive_env_prefers_override(tmp_path: Path, monkeypatch) -> None:
    import os

    import pi_daily_cdr_day_archive_ingest as archive_ingest

    production = tmp_path / "production.env"
    production.write_text('AR_LOCAL_DAY_ARCHIVE_SPOOL="/var/lib/ar-local-day-archives"\n', encoding="utf-8")
    canary = tmp_path / "canary.env"
    canary.write_text('AR_LOCAL_DAY_ARCHIVE_SPOOL="/srv/ar-local/canary/x/data/archive-spool"\n', encoding="utf-8")
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_ENV", str(canary))
    monkeypatch.delenv("AR_LOCAL_DAY_ARCHIVE_SPOOL", raising=False)
    # Ensure production path is not the default fall-through by leaving it unused.
    archive_ingest.load_day_archive_env()
    assert os.environ["AR_LOCAL_DAY_ARCHIVE_SPOOL"] == "/srv/ar-local/canary/x/data/archive-spool"


def test_stable_app_canonicalize_accepts_ci_evidence(tmp_path: Path) -> None:
    src = tmp_path / "app.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "stable_app_compatibility",
                "target_commit": TARGET,
                "result": "PASS",
                "ci": {"command": "npm run ci", "suites": 5, "tests": 42},
            }
        ),
        encoding="utf-8",
    )
    info = app_matrix.canonicalize(
        "stable_app_compatibility", src, tmp_path / "out.json", target_commit=TARGET
    )
    assert info["result"] == "PASS"
