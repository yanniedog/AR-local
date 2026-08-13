"""Regression coverage for the recovered Pi resilience changes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_daily_sync  # noqa: E402


SERVICE_TEMPLATES = (
    "ar-local-daily.service",
    "ar-local-daily-watchdog.service",
    "ar-local-ingest-now.service",
)


@pytest.mark.parametrize("name", SERVICE_TEMPLATES)
def test_ingest_units_preserve_service_user_home(name: str) -> None:
    text = (ROOT / "deploy" / "pi" / name).read_text(encoding="utf-8")
    assert "Environment=HOME=/home/{{AR_LOCAL_USER}}" in text
    assert "Environment=XDG_CONFIG_HOME=/home/{{AR_LOCAL_USER}}/.config" in text


def test_power_resilience_does_not_arm_reboot_loop() -> None:
    text = (ROOT / "deploy" / "pi" / "install-power-resilience.sh").read_text(
        encoding="utf-8"
    )
    assert "RuntimeWatchdogSec=off" in text
    assert "RebootWatchdogSec=off" in text
    assert "RuntimeWatchdogSec=20" not in text

    docs = (ROOT / "docs" / "PI_POWER_RESILIENCE.md").read_text(encoding="utf-8")
    assert "RuntimeWatchdogSec=off" in docs
    assert "RuntimeWatchdogSec=20" not in docs


def test_sync_failure_is_reported_and_deferred(capsys: pytest.CaptureFixture[str]) -> None:
    failure = subprocess.CalledProcessError(1, ["git", "fetch", "origin"])
    with mock.patch.object(pi_daily_sync, "sync_existing_repo", side_effect=failure):
        with mock.patch.object(pi_daily_sync, "assert_clean"):
            with mock.patch.object(pi_daily_sync, "current_branch", return_value="main"):
                assert not pi_daily_sync.sync_repo_for_ingest(
                    ROOT, "https://example.invalid/repo.git"
                )
    assert "git sync deferred" in capsys.readouterr().err


def test_sync_success_is_reported_by_return_value() -> None:
    with mock.patch.object(pi_daily_sync, "sync_existing_repo") as sync:
        assert pi_daily_sync.sync_repo_for_ingest(ROOT, "https://example.invalid/repo.git")
    sync.assert_called_once()


def test_sync_failure_rejects_non_main_fallback() -> None:
    failure = subprocess.TimeoutExpired(["git", "fetch", "origin"], timeout=30)
    with mock.patch.object(pi_daily_sync, "sync_existing_repo", side_effect=failure):
        with mock.patch.object(pi_daily_sync, "assert_clean"):
            with mock.patch.object(pi_daily_sync, "current_branch", return_value="feature/wip"):
                with pytest.raises(RuntimeError, match="fallback checkout is not main"):
                    pi_daily_sync.sync_repo_for_ingest(
                        ROOT, "https://example.invalid/repo.git"
                    )


def test_dirty_checkout_still_blocks_ingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    dirty = RuntimeError("local changes; refusing automated pull")
    with mock.patch.object(pi_daily_sync, "assert_clean", side_effect=dirty):
        with mock.patch.object(pi_daily_sync, "sync_repo_for_ingest") as sync:
            with mock.patch.object(pi_daily_sync, "run_checked") as ingest:
                with pytest.raises(RuntimeError, match="local changes"):
                    pi_daily_sync.main(["--banks-only"])
    sync.assert_not_called()
    ingest.assert_not_called()


def test_transient_sync_failure_does_not_block_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    with mock.patch.object(pi_daily_sync, "assert_clean"):
        with mock.patch.object(
            pi_daily_sync,
            "sync_repo_for_ingest",
            side_effect=(False, True),
        ) as sync:
            with mock.patch.object(pi_daily_sync, "run_checked") as ingest:
                with mock.patch.object(pi_daily_sync, "maybe_publish_app_payload") as publish:
                    assert pi_daily_sync.main(["--banks-only"]) == 0
    assert sync.call_count == 2
    ingest.assert_called_once()
    publish.assert_not_called()


def test_successful_code_sync_keeps_payload_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    with mock.patch.object(pi_daily_sync, "assert_clean"):
        with mock.patch.object(pi_daily_sync, "sync_repo_for_ingest", return_value=True):
            with mock.patch.object(pi_daily_sync, "run_checked"):
                with mock.patch.object(pi_daily_sync, "maybe_publish_app_payload") as publish:
                    assert pi_daily_sync.main(["--banks-only"]) == 0
    publish.assert_called_once_with(pi_daily_sync.REPO_ROOT)
