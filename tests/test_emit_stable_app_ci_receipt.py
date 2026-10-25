"""Unit tests for scripts/emit_stable_app_ci_receipt.py (fail-closed)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "emit_stable_app_ci_receipt.py"
TARGET = "0d8cd36a478a2e8c35d2372659b42a842a14b220"
APP = "91b71b25492e45d017f12ed68ddf5a2acfcbf338"


def _run(tmp_path: Path, *, exit_code: int, log_body: str) -> subprocess.CompletedProcess:
    log = tmp_path / "ci.log"
    log.write_text(log_body, encoding="utf-8")
    out = tmp_path / "receipt.json"
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--target-commit",
            TARGET,
            "--ar-app-head",
            APP,
            "--ci-log",
            str(log),
            "--ci-exit-code",
            str(exit_code),
            "--output",
            str(out),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_pass_when_ci_green_with_jest_counts(tmp_path: Path) -> None:
    body = "Test Suites: 450 passed, 450 total\nTests:       5025 passed, 5025 total\n"
    proc = _run(tmp_path, exit_code=0, log_body=body)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert payload["result"] == "PASS"
    assert payload["ci"]["suites"] == 450
    assert payload["ci"]["tests"] == 5025
    assert payload["ci"]["command"] == "npm run ci"
    assert payload["ci"]["exit_code"] == 0
    assert len(payload["ci"]["log_sha256"]) == 64


def test_pass_when_jest_reports_skipped_before_passed(tmp_path: Path) -> None:
    body = (
        "Test Suites: 1 skipped, 449 passed, 450 total\n"
        "Tests:       2 skipped, 5025 passed, 5027 total\n"
    )
    proc = _run(tmp_path, exit_code=0, log_body=body)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert payload["result"] == "PASS"
    assert payload["ci"]["suites"] == 449
    assert payload["ci"]["tests"] == 5025


def test_fail_when_exit_nonzero(tmp_path: Path) -> None:
    body = "Test Suites: 1 passed, 1 total\nTests:       1 passed, 1 total\n"
    proc = _run(tmp_path, exit_code=1, log_body=body)
    assert proc.returncode == 1
    payload = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert payload["result"] == "FAIL"


def test_fail_without_jest_summary(tmp_path: Path) -> None:
    proc = _run(tmp_path, exit_code=0, log_body="no jest here\n")
    assert proc.returncode == 1
    payload = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert payload["result"] == "FAIL"
