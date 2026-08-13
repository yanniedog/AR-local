"""Regression tests for Pi deploy path classification."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_deploy_verify  # noqa: E402


def test_app_payload_changes_require_pi_deploy():
    assert pi_deploy_verify.paths_touch_pi_deploy(["app_payload.py"])


def test_non_pi_mobile_and_docs_changes_do_not_require_pi_deploy():
    assert not pi_deploy_verify.paths_touch_pi_deploy(
        ["docs/HANDOFF.md", "mobile/src/components/BankAvatar.tsx"]
    )


def test_empty_change_list_does_not_require_pi_deploy():
    assert not pi_deploy_verify.paths_touch_pi_deploy([])


def test_pi_runtime_health_changes_require_pi_deploy():
    assert pi_deploy_verify.paths_touch_pi_deploy(["pi_runtime_health.py"])


def _service_snapshot(**overrides: str) -> dict[str, str]:
    snapshot = {
        "DASHBOARD_WD": "/srv/ar-local/AR-local",
        "DASHBOARD_EXEC": "/usr/bin/python3 /srv/ar-local/AR-local/cdr_dashboard_server.py --runs /srv/ar-local/data/runs",
        "DASHBOARD_ENV": "AR_LOCAL_DATA_ROOT=/srv/ar-local/data",
        "DAILY_WD": "/srv/ar-local/AR-local",
        "DAILY_EXEC": "/usr/bin/python3 /srv/ar-local/AR-local/pi_daily_sync.py",
        "DAILY_ENV": "AR_LOCAL_DATA_ROOT=/srv/ar-local/data HOME=/home/pi XDG_CONFIG_HOME=/home/pi/.config",
        "DF_AR": "/dev/nvme0n1p2|/",
        "DF_SITE": "/dev/nvme0n1p2|/",
        "DF_DATA": "/dev/nvme0n1p2|/",
    }
    snapshot.update(overrides)
    return snapshot


def test_service_paths_allow_pi_home_and_xdg_environment():
    assert pi_deploy_verify.pi_service_paths_ok(_service_snapshot())


def test_service_paths_reject_bootstrap_checkout():
    assert not pi_deploy_verify.pi_service_paths_ok(
        _service_snapshot(DASHBOARD_WD="/home/pi/AR-local")
    )


def test_service_paths_reject_data_root_under_bootstrap_home():
    assert not pi_deploy_verify.pi_service_paths_ok(
        _service_snapshot(DAILY_ENV="AR_LOCAL_DATA_ROOT=/home/pi/data HOME=/home/pi")
    )


def test_service_paths_parse_quoted_values_and_embedded_equals():
    assert pi_deploy_verify.pi_service_paths_ok(
        _service_snapshot(
            DAILY_ENV=(
                'AR_LOCAL_DATA_ROOT="/srv/ar-local/data=primary" '
                'HOME="/home/pi" XDG_CONFIG_HOME="/home/pi/.config"'
            )
        )
    )


@pytest.mark.parametrize("sibling", ["/home/pilot/data", "/home/pine", "/mnt/home/pi"])
def test_service_paths_allow_paths_outside_pi_home_boundary(sibling):
    assert pi_deploy_verify.pi_service_paths_ok(
        _service_snapshot(DASHBOARD_WD=sibling, DAILY_ENV=f"AR_LOCAL_DATA_ROOT={sibling}")
    )


def test_windows_openssh_quirk_requires_remote_success_sentinel(monkeypatch):
    monkeypatch.setattr(pi_deploy_verify.sys, "platform", "win32")
    marker = "close - IO is still pending on closed socket"
    assert pi_deploy_verify._windows_openssh_exit_quirk(
        3221225477,
        f"nginx ok\n{pi_deploy_verify.SSH_SUCCESS_SENTINEL}",
        marker,
    )
    assert not pi_deploy_verify._windows_openssh_exit_quirk(3221225477, "nginx ok", marker)
    assert not pi_deploy_verify._windows_openssh_exit_quirk(
        3221225477,
        f"{pi_deploy_verify.SSH_SUCCESS_SENTINEL}\nremote failure",
        marker,
    )


@pytest.mark.parametrize(
    "output,expected",
    [
        (pi_deploy_verify.SSH_SUCCESS_SENTINEL, ""),
        (f"output\n  {pi_deploy_verify.SSH_SUCCESS_SENTINEL}  ", "output"),
        (
            f"{pi_deploy_verify.SSH_SUCCESS_SENTINEL}\noutput\n{pi_deploy_verify.SSH_SUCCESS_SENTINEL}",
            f"{pi_deploy_verify.SSH_SUCCESS_SENTINEL}\noutput",
        ),
        (
            f"prefix {pi_deploy_verify.SSH_SUCCESS_SENTINEL} suffix",
            f"prefix {pi_deploy_verify.SSH_SUCCESS_SENTINEL} suffix",
        ),
    ],
)
def test_strip_success_sentinel_removes_only_terminal_protocol_marker(output, expected):
    assert pi_deploy_verify._strip_success_sentinel(output) == expected


def test_remote_wrapper_reports_success_only_after_command_status_check():
    wrapped = pi_deploy_verify._remote_command_with_success_sentinel("false && echo skipped")
    assert "__ar_pi_remote_status=$?" in wrapped
    assert wrapped.index("exit \"$__ar_pi_remote_status\"") < wrapped.index("printf")


def test_remote_wrapper_keeps_marker_outside_trailing_comment():
    wrapped = pi_deploy_verify._remote_command_with_success_sentinel("echo ok # trailing comment")
    assert "trailing comment\n}" in wrapped
    assert wrapped.rstrip().endswith(pi_deploy_verify.shell_quote(pi_deploy_verify.SSH_SUCCESS_SENTINEL))


def test_deploy_smoke_waits_for_dashboard_preload(monkeypatch):
    results = iter(
        [
            pi_deploy_verify.EXIT_VERIFY_FAIL,
            pi_deploy_verify.EXIT_VERIFY_FAIL,
            pi_deploy_verify.EXIT_OK,
        ]
    )
    sleeps = []
    monkeypatch.setattr(pi_deploy_verify, "http_smoke", lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(pi_deploy_verify.time, "sleep", sleeps.append)

    assert (
        pi_deploy_verify.wait_for_http_smoke(
            "http://pi/", attempts=3, delay_seconds=2.5
        )
        == pi_deploy_verify.EXIT_OK
    )
    assert sleeps == [2.5, 2.5]


def test_deploy_smoke_returns_immediately_when_ready(monkeypatch):
    sleeps = []
    calls = []
    monkeypatch.setattr(
        pi_deploy_verify,
        "http_smoke",
        lambda *_args, **kwargs: calls.append(kwargs) or pi_deploy_verify.EXIT_OK,
    )
    monkeypatch.setattr(pi_deploy_verify.time, "sleep", sleeps.append)

    assert (
        pi_deploy_verify.wait_for_http_smoke(
            "http://pi/", require_rates=False, attempts=3, delay_seconds=2.5
        )
        == pi_deploy_verify.EXIT_OK
    )
    assert calls[0]["require_rates"] is False
    assert calls[0]["timeout_seconds"] <= 30.0
    assert sleeps == []


def test_deploy_smoke_fails_after_bounded_retries(monkeypatch):
    attempts = []
    sleeps = []
    monkeypatch.setattr(
        pi_deploy_verify,
        "http_smoke",
        lambda *_args, **_kwargs: attempts.append(True) or pi_deploy_verify.EXIT_VERIFY_FAIL,
    )
    monkeypatch.setattr(pi_deploy_verify.time, "sleep", sleeps.append)

    assert (
        pi_deploy_verify.wait_for_http_smoke(
            "http://pi/", attempts=3, delay_seconds=1.0
        )
        == pi_deploy_verify.EXIT_VERIFY_FAIL
    )
    assert len(attempts) == 3
    assert sleeps == [1.0, 1.0]


def test_deploy_smoke_caps_request_to_remaining_budget(monkeypatch):
    timeouts = []
    sleeps = []
    ticks = iter([100.0, 100.0, 125.0, 125.0])
    monkeypatch.setattr(pi_deploy_verify.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(pi_deploy_verify.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        pi_deploy_verify,
        "http_smoke",
        lambda *_args, **kwargs: timeouts.append(kwargs["timeout_seconds"])
        or pi_deploy_verify.EXIT_SSH,
    )

    assert (
        pi_deploy_verify.wait_for_http_smoke(
            "http://pi/", attempts=13, delay_seconds=10.0, budget_seconds=20.0
        )
        == pi_deploy_verify.EXIT_SSH
    )
    assert timeouts == [20.0]
    assert sleeps == []
