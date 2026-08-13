"""Regression tests for Pi deploy path classification."""

from __future__ import annotations

import sys
from pathlib import Path

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
        "DAILY_ENV": "AR_LOCAL_DATA_ROOT=/srv/ar-local/data;HOME=/home/pi;XDG_CONFIG_HOME=/home/pi/.config",
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
        _service_snapshot(DAILY_ENV="AR_LOCAL_DATA_ROOT=/home/pi/data;HOME=/home/pi")
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


def test_success_sentinel_is_stripped_without_losing_remote_output():
    output = f"first\n{pi_deploy_verify.SSH_SUCCESS_SENTINEL}\nsecond"
    assert pi_deploy_verify._strip_success_sentinel(output) == "first\nsecond"
