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


def test_docs_changes_do_not_require_pi_deploy():
    assert not pi_deploy_verify.paths_touch_pi_deploy(
        ["docs/HANDOFF.md", "docs/MOBILE_APP.md"]
    )


def test_empty_change_list_does_not_require_pi_deploy():
    assert not pi_deploy_verify.paths_touch_pi_deploy([])


def test_deploy_requires_exact_approved_commit(capsys):
    args = pi_deploy_verify.build_parser().parse_args(["--deploy"])
    assert pi_deploy_verify.cmd_deploy(args) == pi_deploy_verify.EXIT_CONFIG
    assert "requires --expected-commit" in capsys.readouterr().err


def test_deploy_rejects_commit_other_than_current_main(monkeypatch, capsys):
    args = pi_deploy_verify.build_parser().parse_args(
        ["--deploy", "--expected-commit", "a" * 40]
    )
    monkeypatch.setattr(pi_deploy_verify, "origin_main_sha_local", lambda: "b" * 40)
    assert pi_deploy_verify.cmd_deploy(args) == pi_deploy_verify.EXIT_CONFIG
    assert "not the current local origin/main" in capsys.readouterr().err


def test_deploy_dry_run_uses_exact_commit_without_ssh(monkeypatch):
    expected = "a" * 40
    args = pi_deploy_verify.build_parser().parse_args(
        ["--deploy", "--expected-commit", expected, "--dry-run"]
    )
    calls = []
    monkeypatch.setattr(pi_deploy_verify, "origin_main_sha_local", lambda: expected)
    monkeypatch.setattr(
        pi_deploy_verify,
        "deploy_pull_all",
        lambda commit, dry_run=False: calls.append(("pull", commit, dry_run))
        or pi_deploy_verify.EXIT_OK,
    )
    monkeypatch.setattr(
        pi_deploy_verify,
        "deploy_services",
        lambda dry_run=False: calls.append(("services", dry_run))
        or pi_deploy_verify.EXIT_OK,
    )
    monkeypatch.setattr(
        pi_deploy_verify,
        "pi_remote_snapshot",
        lambda **_kwargs: pytest.fail("dry-run must not contact the Pi"),
    )
    assert pi_deploy_verify.cmd_deploy(args) == pi_deploy_verify.EXIT_OK
    assert calls == [("pull", expected, True), ("services", True)]


def test_exact_commit_install_does_not_move_site_checkout(monkeypatch):
    captured = []
    monkeypatch.setattr(
        pi_deploy_verify,
        "run_ssh",
        lambda command, dry_run=False: captured.append(command) or (0, "", ""),
    )
    expected = "a" * 40
    assert pi_deploy_verify.deploy_pull_all(expected) == pi_deploy_verify.EXIT_OK
    assert expected in captured[0]
    assert "git merge --ff-only" in captured[0]
    assert pi_deploy_verify.pi_site_repo() not in captured[0]
    assert "daily-ingest.lock" in captured[0]
    assert "role=deploy" in captured[0]
    assert "trap 'rm -f" in captured[0]


def test_runtime_activation_rearms_only_the_verify_only_deploy_watchdog(monkeypatch):
    captured = []
    monkeypatch.setattr(
        pi_deploy_verify,
        "run_ssh",
        lambda command, dry_run=False: captured.append(command) or (0, "", ""),
    )
    assert pi_deploy_verify.deploy_services() == pi_deploy_verify.EXIT_OK
    command = captured[0]
    assert "chown -R" not in command
    assert "mkdir -p" not in command
    assert "enable --now ar-local-daily.timer ar-local-daily-watchdog.timer ar-local-deploy-watchdog.timer" in command
    assert "restart ar-local-daily.timer ar-local-daily-watchdog.timer" in command
    assert "systemctl cat ar-local-deploy-watchdog.service" in command
    assert "ExecStart=/srv/ar-local/AR-local/deploy/pi/ar-local-deploy-watchdog.sh" in command


def test_on_pi_watchdog_is_verify_only():
    text = (ROOT / "deploy" / "pi" / "ar-local-deploy-watchdog.sh").read_text(
        encoding="utf-8"
    )
    assert "pi_deploy_verify.py --verify" in text
    assert "pi_deploy_verify.py --deploy" not in text


def test_ingest_paths_never_activate_code():
    daily_sync = (ROOT / "pi_daily_sync.py").read_text(encoding="utf-8")
    assert '"--archive-failed-ram-stage"' in daily_sync
    for forbidden in (
        "git fetch",
        "git pull",
        "git checkout",
        "sync_repo_for_ingest",
        "sync_existing_repo",
    ):
        assert forbidden not in daily_sync

    watchdog = (ROOT / "pi_daily_watchdog.py").read_text(encoding="utf-8")
    assert watchdog.count('"--skip-git-sync"') == 2
    for unit_name in ("ar-local-daily.service", "ar-local-ingest-now.service"):
        unit = (ROOT / "deploy" / "pi" / unit_name).read_text(encoding="utf-8")
        assert "ExecStart=" in unit
        assert "--skip-git-sync" in unit


def test_github_pi_deploy_is_manual_canary_gated():
    text = (ROOT / ".github" / "workflows" / "pi-deploy-on-main.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in text
    assert "push:" not in text
    assert "AR_PI_CANARY_APPROVED_COMMIT" in text
    assert "AR_PI_CANARY_MANIFEST_SHA256" in text
    assert "AR_PI_CANARY_RELEASE_TAG" in text
    assert "canary_release_tag" in text
    assert "canary-acceptance.json" in text
    assert "pi_canary_acceptance.py" in text
    assert "'.immutable'" in text
    assert "DEPLOY_VERIFIED_CANARY" in text
    assert "--expected-commit" in text
    assert "PI_SSH_KNOWN_HOSTS" in text
    assert "ssh-keyscan" not in text
    assert "Skip deploy" not in text

    watchdog = (
        ROOT / ".github" / "workflows" / "pi-deploy-watchdog.yml"
    ).read_text(encoding="utf-8")
    assert "AR_PI_AUTO_DEPLOY" not in watchdog
    assert "deploy_on_drift" not in watchdog
    assert "pi_deploy_verify.py --deploy" not in watchdog
    assert "PI_SSH_KNOWN_HOSTS" in watchdog
    assert "ssh-keyscan" not in watchdog


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
        "DAILY_TIMER_ENABLED": "enabled",
        "DAILY_TIMER_ACTIVE": "active",
        "WATCHDOG_TIMER_ENABLED": "enabled",
        "WATCHDOG_TIMER_ACTIVE": "active",
    }
    snapshot.update(overrides)
    return snapshot


def _verified_sync_snapshot(ar_commit: str) -> dict[str, str]:
    site_commit = "c" * 40
    return {
        **_service_snapshot(),
        "AR_HEAD": ar_commit,
        "AR_ORIGIN": ar_commit,
        "SITE_HEAD": site_commit,
        "SITE_ORIGIN": site_commit,
        "AR_DIRTY": "",
        "SITE_DIRTY": "",
        "DASHBOARD": "active",
    }


def test_verify_sync_rejects_canary_commit_mismatch_before_pi_contact(
    monkeypatch, capsys
):
    expected = "a" * 40
    actual = "b" * 40
    monkeypatch.setattr(pi_deploy_verify, "origin_main_sha_local", lambda: actual)
    monkeypatch.setattr(
        pi_deploy_verify,
        "pi_remote_snapshot",
        lambda **_kwargs: pytest.fail("commit mismatch must fail before Pi contact"),
    )

    assert (
        pi_deploy_verify.verify_sync(expected_commit=expected)
        == pi_deploy_verify.EXIT_CONFIG
    )
    error = capsys.readouterr().err
    assert "local origin/main does not match approved commit" in error
    assert actual[:12] in error
    assert expected[:12] in error


@pytest.mark.parametrize("expected_commit", [None, "a" * 40])
def test_verify_sync_accepts_unset_or_matching_canary_commit(
    monkeypatch, expected_commit
):
    actual = "a" * 40
    monkeypatch.setattr(pi_deploy_verify, "origin_main_sha_local", lambda: actual)
    monkeypatch.setattr(
        pi_deploy_verify,
        "pi_remote_snapshot",
        lambda **_kwargs: _verified_sync_snapshot(actual),
    )

    assert (
        pi_deploy_verify.verify_sync(
            dry_run=True, expected_commit=expected_commit
        )
        == pi_deploy_verify.EXIT_OK
    )


def test_service_paths_allow_pi_home_and_xdg_environment():
    assert pi_deploy_verify.pi_service_paths_ok(_service_snapshot())


def test_ingest_timer_verification_fails_when_catchup_is_disarmed():
    assert pi_deploy_verify.pi_ingest_timers_ok(_service_snapshot())
    assert not pi_deploy_verify.pi_ingest_timers_ok(
        _service_snapshot(WATCHDOG_TIMER_ENABLED="disabled")
    )


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
