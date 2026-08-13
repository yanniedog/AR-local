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
import pi_daily_watchdog  # noqa: E402


SERVICE_TEMPLATES = (
    "ar-local-daily.service",
    "ar-local-daily-watchdog.service",
    "ar-local-ingest-now.service",
    "ar-local-boot-recovery.service",
)


@pytest.mark.parametrize("name", SERVICE_TEMPLATES)
def test_ingest_units_preserve_service_user_home(name: str) -> None:
    text = (ROOT / "deploy" / "pi" / name).read_text(encoding="utf-8")
    assert "Environment=HOME={{AR_LOCAL_HOME}}" in text
    assert "Environment=XDG_CONFIG_HOME={{AR_LOCAL_HOME}}/.config" in text


def test_systemd_installer_resolves_service_user_home_from_passwd() -> None:
    text = (ROOT / "deploy" / "pi" / "install-pi-systemd.sh").read_text(
        encoding="utf-8"
    )
    assert 'getent passwd "$run_user"' in text
    assert 's|{{AR_LOCAL_HOME}}|$run_home|g' in text


def test_power_resilience_does_not_arm_reboot_loop() -> None:
    text = (ROOT / "deploy" / "pi" / "install-power-resilience.sh").read_text(
        encoding="utf-8"
    )
    assert "RuntimeWatchdogSec=off" in text
    assert "RebootWatchdogSec=off" in text
    assert "ShutdownWatchdogSec=off" in text
    assert "RuntimeWatchdogSec=20" not in text

    docs = (ROOT / "docs" / "PI_POWER_RESILIENCE.md").read_text(encoding="utf-8")
    assert "RuntimeWatchdogSec=off" in docs
    assert "ShutdownWatchdogSec=off" in docs
    assert "RuntimeWatchdogSec=20" not in docs


def test_sync_failure_is_reported_and_deferred(capsys: pytest.CaptureFixture[str]) -> None:
    failure = subprocess.CalledProcessError(1, ["git", "fetch", "origin"])
    with mock.patch.object(pi_daily_sync, "sync_existing_repo", side_effect=failure):
        with mock.patch.object(pi_daily_sync, "assert_clean"):
            with mock.patch.object(pi_daily_sync, "current_branch", return_value="main"):
                with mock.patch.object(
                    pi_daily_sync,
                    "head_is_contained_by_origin_main",
                    return_value=True,
                ):
                    assert not pi_daily_sync.sync_repo_for_ingest(
                        ROOT, "https://example.invalid/repo.git"
                    )
    assert "git sync deferred" in capsys.readouterr().err


def test_sync_success_is_reported_by_return_value() -> None:
    with mock.patch.object(pi_daily_sync, "sync_existing_repo") as sync:
        assert pi_daily_sync.sync_repo_for_ingest(ROOT, "https://example.invalid/repo.git")
    sync.assert_called_once()


def test_sync_failure_on_unverifiable_checkout_is_fatal() -> None:
    failure = subprocess.CalledProcessError(1, ["git", "fetch", "origin"])
    with mock.patch.object(pi_daily_sync, "sync_existing_repo", side_effect=failure):
        with mock.patch.object(
            pi_daily_sync,
            "assert_clean",
            side_effect=RuntimeError("dirty checkout"),
        ):
            with pytest.raises(RuntimeError, match="fallback checkout is not verifiable"):
                pi_daily_sync.sync_repo_for_ingest(
                    ROOT, "https://example.invalid/repo.git"
                )


def test_sync_failure_without_main_fallback_skips_checkout_verification(
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = subprocess.CalledProcessError(1, ["git", "fetch", "origin"])
    with mock.patch.object(
        pi_daily_sync,
        "sync_existing_repo",
        side_effect=failure,
    ) as sync:
        with mock.patch.object(pi_daily_sync, "assert_clean") as assert_clean:
            with mock.patch.object(pi_daily_sync, "current_branch") as current_branch:
                assert not pi_daily_sync.sync_repo_for_ingest(
                    ROOT,
                    "https://example.invalid/repo.git",
                    require_main_fallback=False,
                )
    sync.assert_called_once()
    assert_clean.assert_not_called()
    current_branch.assert_not_called()
    assert "git sync deferred" in capsys.readouterr().err


def test_sync_failure_rejects_non_main_fallback() -> None:
    failure = subprocess.TimeoutExpired(["git", "fetch", "origin"], timeout=30)
    with mock.patch.object(pi_daily_sync, "sync_existing_repo", side_effect=failure):
        with mock.patch.object(pi_daily_sync, "assert_clean"):
            with mock.patch.object(pi_daily_sync, "current_branch", return_value="feature/wip"):
                with pytest.raises(RuntimeError, match="fallback checkout is not main"):
                    pi_daily_sync.sync_repo_for_ingest(
                        ROOT, "https://example.invalid/repo.git"
                    )


def test_sync_failure_rejects_diverged_main_fallback() -> None:
    failure = subprocess.CalledProcessError(1, ["git", "pull", "--ff-only"])
    with mock.patch.object(pi_daily_sync, "sync_existing_repo", side_effect=failure):
        with mock.patch.object(pi_daily_sync, "assert_clean"):
            with mock.patch.object(pi_daily_sync, "current_branch", return_value="main"):
                with mock.patch.object(
                    pi_daily_sync,
                    "head_is_contained_by_origin_main",
                    return_value=False,
                ):
                    with pytest.raises(RuntimeError, match="diverges from origin/main"):
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
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
    assert pi_daily_sync.payload_publication_pending(pi_daily_sync.REPO_ROOT)
    assert (
        "[pi_daily_sync] app_payload skipped reason=code_sync_deferred"
        in capsys.readouterr().err
    )


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


def test_pending_payload_retry_publishes_without_ingesting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    pi_daily_sync.mark_payload_publication_pending(pi_daily_sync.REPO_ROOT, "test")
    with mock.patch.object(
        pi_daily_sync, "maybe_publish_app_payload", return_value=True
    ) as publish:
        with mock.patch.object(pi_daily_sync, "run_checked") as ingest:
            assert (
                pi_daily_sync.main(
                    ["--skip-git-sync", "--publish-existing-payload"]
                )
                == 0
            )
    publish.assert_called_once_with(pi_daily_sync.REPO_ROOT)
    ingest.assert_not_called()
    assert not pi_daily_sync.payload_publication_pending(pi_daily_sync.REPO_ROOT)


def test_failed_payload_retry_keeps_pending_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    pi_daily_sync.mark_payload_publication_pending(pi_daily_sync.REPO_ROOT, "test")
    with mock.patch.object(
        pi_daily_sync, "maybe_publish_app_payload", return_value=False
    ):
        assert (
            pi_daily_sync.main(["--skip-git-sync", "--publish-existing-payload"])
            == 0
        )
    assert pi_daily_sync.payload_publication_pending(pi_daily_sync.REPO_ROOT)


def test_daily_watchdog_retries_payload_without_reingesting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pi_daily_watchdog, "ensure_runtime_data_writable", lambda _repo: None
    )
    monkeypatch.setattr(pi_daily_watchdog, "run_complete", lambda _date: True)
    monkeypatch.setattr(pi_daily_watchdog, "service_active", lambda: False)
    monkeypatch.setattr(
        pi_daily_watchdog, "payload_publication_pending", lambda _repo: True
    )
    with mock.patch.object(pi_daily_watchdog, "run_payload_retry") as retry:
        with mock.patch.object(pi_daily_watchdog, "run_daily_ingest") as ingest:
            assert pi_daily_watchdog.main([]) == 0
    retry.assert_called_once_with(False)
    ingest.assert_not_called()
