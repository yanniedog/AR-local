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


def _device_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "model": "Pixel 8",
        "os": "14",
        "abi": "arm64-v8a",
        "install_upgrade": True,
        "acquisition_checks": True,
        "lab_run_id": "lab-2026-10-26-1",
        "evidence_archive_sha256": "a" * 64,
        "result": "PASS",
    }
    row.update(overrides)
    return row


def _emulator_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "avd": "Pixel_6_API_34",
        "api": 34,
        "abi": "x86_64",
        "install_upgrade": True,
        "acquisition_checks": True,
        "userdata_snapshot": "/lab/snapshots/pixel6.img",
        "userdata_snapshot_sha256": "b" * 64,
        "result": "PASS",
    }
    row.update(overrides)
    return row


def test_matrix_canonicalize_rejects_failed_device(tmp_path: Path) -> None:
    src = tmp_path / "dev.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "candidate_device_matrix",
                "target_commit": TARGET,
                "result": "PASS",
                "devices": [_device_row(result="FAIL")],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    info = app_matrix.canonicalize(
        "candidate_device_matrix", src, out, target_commit=TARGET
    )
    assert info["result"] == "FAIL"
    assert any("devices[0].result" in f for f in info["findings"])


def test_device_canonicalize_rejects_false_install_checks(tmp_path: Path) -> None:
    src = tmp_path / "dev.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "candidate_device_matrix",
                "target_commit": TARGET,
                "result": "PASS",
                "devices": [_device_row(install_upgrade=False, acquisition_checks=False)],
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


def test_emulator_canonicalize_requires_snapshot_and_true_checks(tmp_path: Path) -> None:
    src = tmp_path / "emu.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "candidate_emulator_matrix",
                "target_commit": TARGET,
                "result": "PASS",
                "devices": [
                    {
                        "avd": "Pixel_6_API_34",
                        "api": 34,
                        "abi": "x86_64",
                        "install_upgrade": False,
                        "result": "PASS",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    info = app_matrix.canonicalize(
        "candidate_emulator_matrix", src, tmp_path / "out.json", target_commit=TARGET
    )
    assert info["result"] == "FAIL"
    assert any("install_upgrade" in f for f in info["findings"])
    assert any("userdata_snapshot" in f for f in info["findings"])


def test_matrix_canonicalize_rejects_malformed_field_types(tmp_path: Path) -> None:
    src = tmp_path / "dev.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "candidate_device_matrix",
                "target_commit": TARGET,
                "result": "PASS",
                "devices": [_device_row(model=1, os=False, evidence_archive_sha256="nope")],
            }
        ),
        encoding="utf-8",
    )
    info = app_matrix.canonicalize(
        "candidate_device_matrix", src, tmp_path / "out.json", target_commit=TARGET
    )
    assert info["result"] == "FAIL"
    assert any("model" in f for f in info["findings"])
    assert any("os" in f for f in info["findings"])
    assert any("evidence_archive_sha256" in f for f in info["findings"])


def test_matrix_canonicalize_accepts_complete_rows(tmp_path: Path) -> None:
    for gate, row in (
        ("candidate_device_matrix", _device_row()),
        ("candidate_emulator_matrix", _emulator_row()),
    ):
        src = tmp_path / f"{gate}.json"
        src.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "gate": gate,
                    "target_commit": TARGET,
                    "result": "PASS",
                    "devices": [row],
                }
            ),
            encoding="utf-8",
        )
        info = app_matrix.canonicalize(
            gate, src, tmp_path / f"{gate}-out.json", target_commit=TARGET
        )
        assert info["result"] == "PASS", info["findings"]


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
    assert "AR_LOCAL_DATA_ROOT" in steps
    assert "AR_LOCAL_DAY_ARCHIVE_ENV" in steps
    assert "day-archive.env" in steps
    assert any("day-archive.env" in item for item in body["forbidden"])
    assert any("AR_LOCAL_DATA_ROOT" in item for item in body["forbidden"])


def _write_canary_archive_env(path: Path, **overrides: str) -> None:
    values = {
        "AR_LOCAL_DAY_ARCHIVE_SPOOL": "/srv/ar-local/canary/x/data/archive-spool",
        "AR_LOCAL_DAY_ARCHIVE_REMOTE": "canary_remote:canary-backups/",
        "RCLONE_CONFIG": "/srv/ar-local/canary/x/config/rclone.conf",
    }
    values.update(overrides)
    path.write_text(
        "".join(f'{key}="{value}"\n' for key, value in values.items()),
        encoding="utf-8",
    )


def test_load_day_archive_env_prefers_override(tmp_path: Path, monkeypatch) -> None:
    import os

    import pi_daily_cdr_day_archive_ingest as archive_ingest

    canary = tmp_path / "canary.env"
    _write_canary_archive_env(canary)
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_ENV", str(canary))
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_SPOOL", "/var/lib/ar-local-day-archives")
    monkeypatch.setenv("RCLONE_CONFIG", "/etc/ar-local/rclone.conf")
    archive_ingest.load_day_archive_env()
    assert os.environ["AR_LOCAL_DAY_ARCHIVE_SPOOL"] == "/srv/ar-local/canary/x/data/archive-spool"
    assert os.environ["AR_LOCAL_DAY_ARCHIVE_REMOTE"] == "canary_remote:canary-backups/"
    assert os.environ["RCLONE_CONFIG"] == "/srv/ar-local/canary/x/config/rclone.conf"


def test_load_day_archive_env_fail_closed_for_canary(tmp_path: Path, monkeypatch) -> None:
    import os

    import pytest

    import pi_daily_cdr_day_archive_ingest as archive_ingest

    missing = tmp_path / "missing.env"
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_ENV", str(missing))
    with pytest.raises(ValueError, match="fail-closed"):
        archive_ingest.load_day_archive_env()

    canary = tmp_path / "canary.env"
    _write_canary_archive_env(
        canary, AR_LOCAL_DAY_ARCHIVE_SPOOL="/var/lib/ar-local-day-archives"
    )
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_ENV", str(canary))
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_SPOOL", "/srv/ar-local/canary/x/data/archive-spool")
    with pytest.raises(ValueError, match="production archive spool"):
        archive_ingest.load_day_archive_env()
    # Rejection must not clear prior isolation settings.
    assert os.environ["AR_LOCAL_DAY_ARCHIVE_SPOOL"] == "/srv/ar-local/canary/x/data/archive-spool"

    incomplete = tmp_path / "incomplete.env"
    incomplete.write_text(
        'AR_LOCAL_DAY_ARCHIVE_SPOOL="/srv/ar-local/canary/x/data/archive-spool"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_ENV", str(incomplete))
    with pytest.raises(ValueError, match="AR_LOCAL_DAY_ARCHIVE_REMOTE"):
        archive_ingest.load_day_archive_env()


def test_stable_app_canonicalize_accepts_ci_evidence(tmp_path: Path) -> None:
    src = tmp_path / "app.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate": "stable_app_compatibility",
                "target_commit": TARGET,
                "result": "PASS",
                "ci": {
                    "command": "npm run ci",
                    "exit_code": 0,
                    "log_sha256": "c" * 64,
                    "suites": 5,
                    "tests": 42,
                },
            }
        ),
        encoding="utf-8",
    )
    info = app_matrix.canonicalize(
        "stable_app_compatibility", src, tmp_path / "out.json", target_commit=TARGET
    )
    assert info["result"] == "PASS"


def test_stable_app_requires_ci_exit_and_log_digest(tmp_path: Path) -> None:
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
    assert info["result"] == "FAIL"
    assert any("exit_code" in f for f in info["findings"])


def test_canonicalize_rejects_boolean_schema_version(tmp_path: Path) -> None:
    src = tmp_path / "src.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": True,
                "gate": "shadow_ingest",
                "target_commit": TARGET,
                "result": "PASS",
                "exit_code": 0,
                "exports_dirs": ["/srv/ar-local/canary/x/data/runs/2026-10-26/_exports"],
            }
        ),
        encoding="utf-8",
    )
    info = shadow.validate_and_canonicalize(
        src, tmp_path / "out.json", target_commit=TARGET
    )
    assert info["result"] == "FAIL"
    assert any("schema_version" in f for f in info["findings"])
