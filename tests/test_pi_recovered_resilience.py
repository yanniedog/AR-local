"""Regression coverage for the recovered Pi resilience changes."""

from __future__ import annotations

import sys
import json
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_daily_sync  # noqa: E402
import pi_daily_watchdog  # noqa: E402
import ar_local_pi_runtime  # noqa: E402
from cdr_finalization import finalize_observation  # noqa: E402


SERVICE_TEMPLATES = (
    "ar-local-daily.service",
    "ar-local-daily-watchdog.service",
    "ar-local-ingest-now.service",
    "ar-local-boot-recovery.service",
)
INGEST_PROCESS_TEMPLATES = SERVICE_TEMPLATES[:3]


def test_watchdog_never_accepts_markerless_nonzero_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    date = "2026-08-14"
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    cache = runs / date / "_exports" / "dashboard-cache"
    cache.mkdir(parents=True)
    (cache / "latest.json").write_text(
        json.dumps({"run_date": date, "banks_counts": {"rates": 10}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pi_daily_watchdog, "data_runs_root", lambda _repo: runs)
    monkeypatch.setattr(pi_daily_watchdog, "data_state_root", lambda _repo: state)
    assert pi_daily_watchdog.run_complete(date) is False


def test_partial_finalized_observation_is_withheld_from_app_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    date = "2026-08-14"
    exports = tmp_path / "runs" / date / "_exports"
    cache = exports / "dashboard-cache"
    cache.mkdir(parents=True)
    (cache / "latest.json").write_text(
        json.dumps({"run_date": date, "banks_counts": {"rates": 10}}),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    state.mkdir()
    (state / f"{date}.done.json").write_text(
        json.dumps(
            {
                "run_date": date,
                "banks_counts": {"rates": 10},
                "finalization_schema_version": 2,
                "observation_state": "partial",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: state)
    monkeypatch.setattr(ar_local_pi_runtime, "data_runs_root", lambda _repo: tmp_path / "runs")
    with mock.patch("app_payload.build_and_publish_dual") as publish:
        assert (
            pi_daily_sync.maybe_publish_app_payload(pi_daily_sync.REPO_ROOT)
            == pi_daily_sync.PUBLISH_WITHHELD
        )
    publish.assert_not_called()
    assert "missing_or_invalid_observation_pointer" in capsys.readouterr().out


def _partial_contract(*, failures: int, products: int = 3027, partial: int = 7) -> dict:
    return {
        "observation_state": "partial",
        "coverage": {
            "failure_records": failures,
            "corrupt_failure_records": 0,
            "unattributed_failure_records": 0,
            "products_discovered": products,
            "providers_registered": 118,
            "providers_attempted": 118,
            "providers_partial": partial,
            "providers_failed": 0,
            "register_sources_attempted": 1,
            "register_sources_complete": 1,
            "register_provenance_complete": True,
            "failure_provenance_complete": True,
        },
    }


def test_bounded_partial_v1_policy_accepts_live_scale_but_pins_limits() -> None:
    assert pi_daily_sync._bounded_partial_v1_allowed(_partial_contract(failures=17))
    assert not pi_daily_sync._bounded_partial_v1_allowed(_partial_contract(failures=26))
    assert not pi_daily_sync._bounded_partial_v1_allowed(
        _partial_contract(failures=17, products=1600)
    )
    assert not pi_daily_sync._bounded_partial_v1_allowed(
        _partial_contract(failures=17, partial=12)
    )


def test_bounded_partial_v1_policy_requires_complete_provenance() -> None:
    contract = _partial_contract(failures=17)
    contract["coverage"]["register_provenance_complete"] = False
    assert not pi_daily_sync._bounded_partial_v1_allowed(contract)


def test_verified_bounded_partial_reaches_v1_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    date = "2026-08-16"
    exports = tmp_path / "runs" / date / "_exports"
    cache = exports / "dashboard-cache"
    cache.mkdir(parents=True)
    (cache / "latest.json").write_text(
        json.dumps(
            {
                "run_date": date,
                "banks_counts": {
                    "products": 100,
                    "rates": 10,
                    "fees": 0,
                    "features": 0,
                    "eligibility": 0,
                    "constraints": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    (exports / "banks.json").write_text('{"rates":[]}', encoding="utf-8")
    provider_states = [
        {
            "provider_uid": f"provider-{index}",
            "state": "partial" if index == 0 else "complete",
            "failure_records": 1 if index == 0 else 0,
        }
        for index in range(10)
    ]
    (exports / "ingest-status.json").write_text(
        json.dumps(
            {
                "total": 1,
                "corrupt_records": 0,
                "unattributed_records": 0,
                "failure_provenance_complete": True,
                "incomplete": True,
                "register_provenance_complete": True,
                "register_attempts": [
                    {
                        "source_url": "https://register.example/summary",
                        "mode": "cdr",
                        "ok": True,
                        "status": 200,
                        "bytes": 2,
                        "sha256": "a" * 64,
                    }
                ],
                "providers_registered": 10,
                "providers_attempted": 10,
                "provider_states": provider_states,
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    finalize_observation(
        exports,
        state,
        state / f"{date}.done.json",
        observation_date=date,
        result={"run_date": date, "banks_counts": {"rates": 10}},
    )
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: state)
    with mock.patch(
        "app_payload.build_and_publish_dual", side_effect=RuntimeError("builder reached")
    ) as publish:
        assert (
            pi_daily_sync.maybe_publish_app_payload(pi_daily_sync.REPO_ROOT)
            == pi_daily_sync.PUBLISH_FAILED
        )
    publish.assert_called_once()
    assert "bounded partial v1 promotion" in capsys.readouterr().out


def test_revision_pointer_requires_its_exact_verified_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    date = "2026-08-14"
    exports = tmp_path / "runs" / date / "_revisions" / "stamp" / "_exports"
    (exports / "dashboard-cache").mkdir(parents=True)
    state = tmp_path / "state"
    pointers = state / "observation-pointers-v2"
    pointers.mkdir(parents=True)
    marker_name = f"{date}.revision.stamp.json"
    (pointers / "latest-complete.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "observation_date": date,
                "observation_state": "complete",
                "export_path": f"runs/{date}/_revisions/stamp/_exports",
                "marker_path": marker_name,
            }
        ),
        encoding="utf-8",
    )
    (state / marker_name).write_text(
        json.dumps(
            {
                "run_date": date,
                "banks_counts": {"rates": 10},
                "finalization_schema_version": 2,
                "observation_state": "partial",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: state)
    with mock.patch("app_payload.build_and_publish_dual") as publish:
        assert (
            pi_daily_sync.maybe_publish_app_payload(pi_daily_sync.REPO_ROOT)
            == pi_daily_sync.PUBLISH_WITHHELD
        )
    publish.assert_not_called()
    assert "unverified_completion_marker" in capsys.readouterr().out


def test_watchdog_accepts_verified_revision_pointer_over_stale_primary_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    date = "2026-08-14"
    state = tmp_path / "state"
    state.mkdir()
    (state / f"{date}.done.json").write_text("{stale", encoding="utf-8")
    exports = tmp_path / "runs" / date / "_revisions" / "stamp" / "_exports"
    cache = exports / "dashboard-cache"
    cache.mkdir(parents=True)
    (cache / "latest.json").write_text(
        json.dumps(
            {
                "run_date": date,
                "banks_counts": {
                    "products": 1,
                    "rates": 2,
                    "fees": 0,
                    "features": 0,
                    "eligibility": 0,
                    "constraints": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    (exports / "banks.json").write_text('{"rates":[]}', encoding="utf-8")
    (exports / "ingest-status.json").write_text(
        json.dumps(
            {
                "total": 0,
                "corrupt_records": 0,
                "unattributed_records": 0,
                "failure_provenance_complete": True,
                "incomplete": False,
                "register_provenance_complete": True,
                "register_attempts": [
                    {
                        "source_url": "https://register.example/holders",
                        "mode": "plain",
                        "ok": True,
                        "status": 200,
                        "bytes": 2,
                        "sha256": "a" * 64,
                    }
                ],
                "providers_registered": 1,
                "providers_attempted": 1,
                "provider_states": [
                    {"provider_uid": "provider-a", "state": "complete"}
                ],
            }
        ),
        encoding="utf-8",
    )
    primary_exports = tmp_path / "runs" / date / "_exports"
    shutil.copytree(exports, primary_exports)
    primary = finalize_observation(
        primary_exports,
        state,
        state / f"{date}.primary.json",
        observation_date=date,
        result={"run_date": date, "banks_counts": {"rates": 2}},
    )
    finalize_observation(
        exports,
        state,
        state / f"{date}.revision.stamp.json",
        observation_date=date,
        result={"run_date": date, "banks_counts": {"rates": 2}},
        parent_generation_id=primary["generation_id"],
    )
    monkeypatch.setattr(pi_daily_watchdog, "data_state_root", lambda _repo: state)
    monkeypatch.setattr(
        pi_daily_watchdog, "data_runs_root", lambda _repo: tmp_path / "runs"
    )
    assert pi_daily_watchdog.run_complete(date) is True


@pytest.mark.parametrize("name", SERVICE_TEMPLATES)
def test_ingest_units_preserve_service_user_home(name: str) -> None:
    text = (ROOT / "deploy" / "pi" / name).read_text(encoding="utf-8")
    assert "Environment=HOME={{AR_LOCAL_HOME}}" in text
    assert "Environment=XDG_CONFIG_HOME={{AR_LOCAL_HOME}}/.config" in text


@pytest.mark.parametrize("name", INGEST_PROCESS_TEMPLATES)
def test_ingest_units_kill_the_whole_process_tree(name: str) -> None:
    text = (ROOT / "deploy" / "pi" / name).read_text(encoding="utf-8")
    assert "KillMode=control-group" in text
    assert "TimeoutStopSec=45s" in text
    assert "TimeoutStartSec=6h15min" in text
    assert "RuntimeMaxSec=" not in text
    assert "ExecStopPost=+/usr/bin/systemctl start ar-local-dashboard.service" in text


def test_watchdog_timeout_terminates_the_catch_up_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = ["python3", "pi_daily_sync.py"]
    process = mock.Mock(pid=4321)
    process.wait.side_effect = [
        subprocess.TimeoutExpired(command, pi_daily_watchdog.SUBPROCESS_INGEST_TIMEOUT_SEC),
        0,
    ]
    monkeypatch.setattr(pi_daily_watchdog, "PROCESS_GROUPS_SUPPORTED", True)
    popen = mock.Mock(return_value=process)
    monkeypatch.setattr(pi_daily_watchdog.subprocess, "Popen", popen)
    killpg = mock.Mock()
    monkeypatch.setattr(pi_daily_watchdog.os, "killpg", killpg, raising=False)

    with pytest.raises(subprocess.TimeoutExpired):
        pi_daily_watchdog.run_ingest_process_group(command)

    popen.assert_called_once_with(
        command,
        cwd=pi_daily_watchdog.REPO_ROOT,
        shell=False,
        start_new_session=True,
    )
    assert killpg.call_args_list == [
        mock.call(4321, pi_daily_watchdog.signal.SIGTERM),
        mock.call(4321, 0),
        mock.call(4321, pi_daily_watchdog.FORCE_KILL_SIGNAL),
    ]
    assert process.wait.call_args_list == [
        mock.call(timeout=pi_daily_watchdog.SUBPROCESS_INGEST_TIMEOUT_SEC),
        mock.call(timeout=pi_daily_watchdog.SUBPROCESS_TERMINATE_GRACE_SEC),
    ]


def test_systemd_installer_resolves_service_user_home_from_passwd() -> None:
    text = (ROOT / "deploy" / "pi" / "install-pi-systemd.sh").read_text(
        encoding="utf-8"
    )
    assert 'getent passwd "$run_user"' in text
    assert 's|{{AR_LOCAL_HOME}}|$run_home|g' in text
    assert "python3-jsonschema" in text
    assert "/usr/bin/python3 -c 'from jsonschema import" in text


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


def test_daily_ingest_never_inspects_or_changes_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    with mock.patch.object(pi_daily_sync, "run_checked") as ingest:
        with mock.patch.object(pi_daily_sync, "maybe_publish_app_payload"):
            assert pi_daily_sync.main(["--banks-only"]) == 0
    ingest.assert_called_once()


def test_pi_daily_ingest_pauses_and_resumes_dashboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setattr(pi_daily_sync, "is_raspberry_pi", lambda: True)
    events: list[str] = []

    def control(command, **_kwargs):
        events.append(command[2])
        return subprocess.CompletedProcess(command, 0)

    def ingest(*_args, **_kwargs):
        events.append("ingest")

    monkeypatch.setattr(pi_daily_sync.subprocess, "run", control)
    monkeypatch.setattr(pi_daily_sync, "run_checked", ingest)

    assert pi_daily_sync.main(["--banks-only"]) == 0
    assert events == ["stop", "ingest", "start"]


def test_pi_daily_ingest_resumes_dashboard_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setattr(pi_daily_sync, "is_raspberry_pi", lambda: True)
    events: list[str] = []

    def control(command, **_kwargs):
        events.append(command[2])
        return subprocess.CompletedProcess(command, 0)

    def fail_ingest(*_args, **_kwargs):
        events.append("ingest")
        raise subprocess.CalledProcessError(1, ["cdr_daily.py"])

    monkeypatch.setattr(pi_daily_sync.subprocess, "run", control)
    monkeypatch.setattr(pi_daily_sync, "run_checked", fail_ingest)

    with pytest.raises(subprocess.CalledProcessError):
        pi_daily_sync.main(["--banks-only"])
    assert events == ["stop", "ingest", "start"]


def test_dashboard_pause_failure_never_blocks_daily_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setattr(pi_daily_sync, "is_raspberry_pi", lambda: True)
    monkeypatch.setattr(
        pi_daily_sync.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1),
    )
    with mock.patch.object(pi_daily_sync, "run_checked") as ingest:
        assert pi_daily_sync.main(["--banks-only"]) == 0
    ingest.assert_called_once()


def test_daily_ingest_does_not_invoke_sync_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    with mock.patch.object(pi_daily_sync, "run_checked") as ingest:
        with mock.patch.object(pi_daily_sync, "maybe_publish_app_payload") as publish:
            assert pi_daily_sync.main(["--banks-only"]) == 0
    ingest.assert_called_once()
    publish.assert_called_once_with(pi_daily_sync.REPO_ROOT)


def test_compatibility_skip_git_sync_flag_is_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    with mock.patch.object(pi_daily_sync, "run_checked"):
        with mock.patch.object(pi_daily_sync, "maybe_publish_app_payload") as publish:
            assert pi_daily_sync.main(["--banks-only", "--skip-git-sync"]) == 0
    publish.assert_called_once_with(pi_daily_sync.REPO_ROOT)


@pytest.mark.parametrize(
    "arguments,should_ingest",
    [
        (["--banks-only"], True),
        (["--publish-existing-payload"], False),
    ],
)
def test_disabled_publication_preserves_existing_pending_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    should_ingest: bool,
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.delenv("AR_LOCAL_APP_PAYLOAD", raising=False)
    pi_daily_sync.mark_payload_publication_pending(pi_daily_sync.REPO_ROOT, "test")

    with mock.patch.object(pi_daily_sync, "run_checked") as ingest:
        with mock.patch.object(pi_daily_sync, "maybe_publish_app_payload") as publish:
            assert pi_daily_sync.main(arguments) == 0

    assert ingest.called is should_ingest
    publish.assert_not_called()
    assert pi_daily_sync.payload_publication_pending(pi_daily_sync.REPO_ROOT)


def test_pending_payload_retry_publishes_without_ingesting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    pi_daily_sync.mark_payload_publication_pending(pi_daily_sync.REPO_ROOT, "test")
    with mock.patch.object(
        pi_daily_sync,
        "maybe_publish_app_payload",
        return_value=pi_daily_sync.PUBLISH_PUBLISHED,
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
        pi_daily_sync,
        "maybe_publish_app_payload",
        return_value=pi_daily_sync.PUBLISH_FAILED,
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


def _stage_complete_payload_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, date: str) -> Path:
    """Stage a verified-complete observation so publication is not withheld."""
    state = tmp_path / "data" / "state"
    pointers = state / "observation-pointers-v2"
    pointers.mkdir(parents=True)
    (tmp_path / "data" / "runs" / date / "_exports").mkdir(parents=True)
    (pointers / "latest-observation.json").write_text(
        json.dumps({"observation_state": "complete", "observation_date": date}),
        encoding="utf-8",
    )
    (pointers / "latest-complete.json").write_text(
        json.dumps(
            {
                "observation_state": "complete",
                "observation_date": date,
                "export_path": f"runs/{date}/_exports",
                "marker_path": f"{date}.done.json",
            }
        ),
        encoding="utf-8",
    )
    (state / f"{date}.done.json").write_text(
        json.dumps(
            {
                "run_date": date,
                "finalization_schema_version": 2,
                "observation_state": "complete",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.delenv("AR_LOCAL_PAYLOAD_ENC", raising=False)
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: state)
    monkeypatch.setattr(pi_daily_sync, "data_runs_root", lambda _repo: tmp_path / "data" / "runs")
    monkeypatch.setattr(pi_daily_sync, "verify_completion_marker", lambda *_a, **_k: True)
    return state


def _payload_manifest(date: str) -> dict:
    return {
        "run_date": date,
        "files": {
            "core": {"name": f"core-{date}.json.gz", "sha256": "core-digest"},
            "details": {"name": f"details-{date}.json.gz", "sha256": "details-digest"},
        },
    }


def test_unuploaded_payload_is_reported_failed_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build that never reached the release must not be recorded as published.

    publish_payload returns False (it does not raise) when gh auth is missing, and
    build_and_publish_dual swallows a failed dated upload, so the old bool contract
    reported a silently-skipped upload as success and cleared the retry marker.
    """
    date = "2026-08-16"
    _stage_complete_payload_run(tmp_path, monkeypatch, date)
    manifest = _payload_manifest(date)
    with mock.patch("app_payload.build_and_publish_dual", return_value=(manifest, False, False)):
        with mock.patch("app_payload._live_manifest_status", return_value=("missing", None)):
            with mock.patch("app_payload.refresh_dates_index") as refresh:
                outcome = pi_daily_sync.maybe_publish_app_payload(pi_daily_sync.REPO_ROOT)
    assert outcome == pi_daily_sync.PUBLISH_FAILED
    refresh.assert_not_called()


def test_live_rolling_manifest_match_counts_as_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    date = "2026-08-16"
    _stage_complete_payload_run(tmp_path, monkeypatch, date)
    manifest = _payload_manifest(date)
    with mock.patch("app_payload.build_and_publish_dual", return_value=(manifest, False, False)):
        with mock.patch("app_payload._live_manifest_status", return_value=("present", manifest)):
            with mock.patch("app_payload.build_and_publish_v2", return_value=({}, True)):
                outcome = pi_daily_sync.maybe_publish_app_payload(pi_daily_sync.REPO_ROOT)
    assert outcome == pi_daily_sync.PUBLISH_PUBLISHED


def test_newer_live_rolling_manifest_is_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backfill holding a newer run_date on the rolling tag is a correct skip."""
    date = "2026-08-16"
    _stage_complete_payload_run(tmp_path, monkeypatch, date)
    newer = _payload_manifest("2026-08-17")
    with mock.patch(
        "app_payload.build_and_publish_dual", return_value=(_payload_manifest(date), False, False)
    ):
        with mock.patch("app_payload._live_manifest_status", return_value=("present", newer)):
            outcome = pi_daily_sync.maybe_publish_app_payload(pi_daily_sync.REPO_ROOT)
    assert outcome == pi_daily_sync.PUBLISH_PUBLISHED


def test_successful_publish_refreshes_dates_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression: data_runs_root was never imported, so this always raised NameError."""
    date = "2026-08-16"
    _stage_complete_payload_run(tmp_path, monkeypatch, date)
    manifest = _payload_manifest(date)
    with mock.patch("app_payload.build_and_publish_dual", return_value=(manifest, True, True)):
        with mock.patch("app_payload.build_and_publish_v2", return_value=({}, True)):
            with mock.patch("app_payload.refresh_dates_index") as refresh:
                outcome = pi_daily_sync.maybe_publish_app_payload(pi_daily_sync.REPO_ROOT)
    assert outcome == pi_daily_sync.PUBLISH_PUBLISHED
    refresh.assert_called_once()
    assert refresh.call_args.args[0] == tmp_path / "data" / "runs"
    assert "dates-index refresh failed" not in capsys.readouterr().out


def test_withheld_run_preserves_earlier_pending_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A day withheld by policy must not erase an outstanding upload from an earlier day."""
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    pi_daily_sync.mark_payload_publication_pending(pi_daily_sync.REPO_ROOT, "earlier_failure")
    with mock.patch.object(
        pi_daily_sync,
        "maybe_publish_app_payload",
        return_value=pi_daily_sync.PUBLISH_WITHHELD,
    ):
        with mock.patch.object(pi_daily_sync, "run_checked"):
            assert pi_daily_sync.main(["--banks-only", "--skip-git-sync"]) == 0
    assert pi_daily_sync.payload_publication_pending(pi_daily_sync.REPO_ROOT)


def test_withheld_retry_keeps_pending_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    pi_daily_sync.mark_payload_publication_pending(pi_daily_sync.REPO_ROOT, "test")
    with mock.patch.object(
        pi_daily_sync,
        "maybe_publish_app_payload",
        return_value=pi_daily_sync.PUBLISH_WITHHELD,
    ):
        assert pi_daily_sync.main(["--skip-git-sync", "--publish-existing-payload"]) == 0
    assert pi_daily_sync.payload_publication_pending(pi_daily_sync.REPO_ROOT)
