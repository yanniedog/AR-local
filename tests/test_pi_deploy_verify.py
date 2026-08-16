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
    assert "kill -0" in captured[0]
    assert "trap cleanup_lock EXIT" in captured[0]
    assert "trap 'exit 143' TERM" in captured[0]


def test_exact_commit_install_preserves_busy_lock_result(monkeypatch, capsys):
    monkeypatch.setattr(
        pi_deploy_verify,
        "run_ssh",
        lambda *_args, **_kwargs: (
            pi_deploy_verify.EXIT_BUSY,
            "",
            "pi_deploy_verify: ingest/deploy lock is busy",
        ),
    )

    assert (
        pi_deploy_verify.deploy_pull_all("a" * 40)
        == pi_deploy_verify.EXIT_BUSY
    )
    assert "ingest/deploy lock is busy" in capsys.readouterr().err


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
    assert "apply-pi-runtime-units.sh" in command
    assert "sudo sh /srv/ar-local/AR-local/deploy/pi/apply-pi-runtime-units.sh" not in command
    assert "/srv/ar-local/AR-local /srv/ar-local/australianrates /srv/ar-local/data" in command
    assert "systemctl cat ar-local-deploy-watchdog.service" in command
    assert "ExecStart=/srv/ar-local/AR-local/deploy/pi/ar-local-deploy-watchdog.sh" in command


def test_runtime_unit_activation_is_ingest_locked_and_complete():
    text = (ROOT / "deploy" / "pi" / "apply-pi-runtime-units.sh").read_text(
        encoding="utf-8"
    )
    assert "daily-ingest.lock" in text
    assert "ingest/deploy lock is busy" in text
    assert "ar-local-daily.service" in text
    assert "ar-local-daily-watchdog.service" in text
    assert "ar-local-ingest-now.service" in text
    assert "sudo systemctl daemon-reload" in text
    assert "sudo systemctl restart ar-local-dashboard.service" in text
    assert "git fetch" not in text
    assert "git checkout" not in text
    assert "apt-get" not in text


def test_runtime_unit_activation_preserves_busy_lock_result(monkeypatch, capsys):
    monkeypatch.setattr(
        pi_deploy_verify,
        "run_ssh",
        lambda *_args, **_kwargs: (
            pi_deploy_verify.EXIT_BUSY,
            "",
            "apply-pi-runtime-units: ingest/deploy lock is busy",
        ),
    )

    assert pi_deploy_verify.deploy_services() == pi_deploy_verify.EXIT_BUSY
    assert "ingest/deploy lock is busy" in capsys.readouterr().err


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


def test_pi_capacity_monitor_changes_require_pi_deploy():
    assert pi_deploy_verify.paths_touch_pi_deploy(["pi_capacity_monitor.py"])


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
        "CAPACITY_TIMER_ENABLED": "enabled",
        "CAPACITY_TIMER_ACTIVE": "active",
        "DAILY_KILL_MODE": "control-group",
        "DAILY_START_TIMEOUT": "6h 15min",
        "WATCHDOG_KILL_MODE": "control-group",
        "WATCHDOG_START_TIMEOUT": "6h 15min",
        "MANUAL_KILL_MODE": "control-group",
        "MANUAL_START_TIMEOUT": "6h 15min",
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


def test_ingest_fence_verification_rejects_partial_unit_rollout():
    assert pi_deploy_verify.pi_ingest_service_fences_ok(_service_snapshot())
    assert not pi_deploy_verify.pi_ingest_service_fences_ok(
        _service_snapshot(WATCHDOG_START_TIMEOUT="infinity")
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


def test_windows_openssh_quirk_tolerates_the_truncated_sentinel(monkeypatch):
    """The crash this guard exists for is what destroys the sentinel.

    Windows OpenSSH aborts at socket close *after* the remote command has run,
    and that abort truncates the tail of stdout — where the sentinel is printed.
    Requiring the sentinel therefore made the guard dead code in its own case, so
    a deploy that had actually succeeded was reported as EXIT_SSH.
    """
    monkeypatch.setattr(pi_deploy_verify.sys, "platform", "win32")
    marker = "close - IO is still pending on closed socket"
    assert pi_deploy_verify._windows_openssh_exit_quirk(
        3221225477,
        f"nginx ok\n{pi_deploy_verify.SSH_SUCCESS_SENTINEL}",
        marker,
    )
    # Sentinel lost to the crash: still the documented quirk, still accepted.
    assert pi_deploy_verify._windows_openssh_exit_quirk(3221225477, "nginx ok", marker)


def test_windows_openssh_quirk_still_requires_its_evidence(monkeypatch):
    """Loosening the sentinel must not turn the quirk into a blanket amnesty."""
    monkeypatch.setattr(pi_deploy_verify.sys, "platform", "win32")
    marker = "close - IO is still pending on closed socket"
    # No remote output at all -> nothing suggests the command ran.
    assert not pi_deploy_verify._windows_openssh_exit_quirk(3221225477, "", marker)
    # A non-zero exit without the crash signature is a real remote failure.
    assert not pi_deploy_verify._windows_openssh_exit_quirk(1, "nginx ok", "permission denied")
    # The quirk is Windows-only.
    monkeypatch.setattr(pi_deploy_verify.sys, "platform", "linux")
    assert not pi_deploy_verify._windows_openssh_exit_quirk(3221225477, "nginx ok", marker)


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


class _FakeProc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _remote_run_shell(monkeypatch, results, *, sleeps=None):
    """Drive run_shell down its ssh branch with a scripted sequence of results."""
    monkeypatch.setattr(pi_deploy_verify, "on_pi_host", lambda: False)
    monkeypatch.setattr(pi_deploy_verify, "ssh_host", lambda: "ar-local-pi5")
    # Bind the list itself: `sleeps or []` would swap in a throwaway list while
    # the recorder is still empty, and silently drop every backoff.
    recorded = sleeps if sleeps is not None else []
    monkeypatch.setattr(pi_deploy_verify.time, "sleep", recorded.append)
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        outcome = results[min(len(calls) - 1, len(results) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(pi_deploy_verify.subprocess, "run", fake_run)
    return calls


def test_ssh_exit_zero_without_sentinel_is_trusted(monkeypatch, capsys):
    """A perturbed stdout tail must not fail a command that ssh reported as OK.

    ssh exits with the remote command's status, so 0 already means success. The
    sentinel is corroboration; demanding it turned every imperfect link into a
    failed deploy.
    """
    calls = _remote_run_shell(monkeypatch, [_FakeProc(0, "nginx ok")])
    code, out, _err = pi_deploy_verify.run_shell("systemctl is-active nginx")
    assert code == 0
    assert out == "nginx ok"
    assert len(calls) == 1, "a successful command must not be re-run"
    assert "trusting the exit status" in capsys.readouterr().err


def test_ssh_transport_failure_is_retried(monkeypatch, capsys):
    sleeps = []
    calls = _remote_run_shell(
        monkeypatch,
        [
            _FakeProc(pi_deploy_verify.SSH_TRANSPORT_EXIT, "", "kex_exchange_identification"),
            _FakeProc(0, f"ok\n{pi_deploy_verify.SSH_SUCCESS_SENTINEL}"),
        ],
        sleeps=sleeps,
    )
    code, out, _err = pi_deploy_verify.run_shell("uptime")
    assert code == 0
    assert out == "ok"
    assert len(calls) == 2
    assert sleeps == [pi_deploy_verify.SSH_RETRY_BACKOFF_SEC[0]]
    assert "transport failure" in capsys.readouterr().err


def test_remote_command_failure_is_never_retried(monkeypatch):
    """Only ssh's own 255 is safe to repeat; a remote status may have side effects."""
    calls = _remote_run_shell(monkeypatch, [_FakeProc(1, "", "boom")])
    code, _out, _err = pi_deploy_verify.run_shell("false")
    assert code == 1
    assert len(calls) == 1


def test_ssh_transport_failure_gives_up_after_the_retry_budget(monkeypatch):
    calls = _remote_run_shell(
        monkeypatch,
        [_FakeProc(pi_deploy_verify.SSH_TRANSPORT_EXIT, "", "unreachable")],
    )
    code, _out, _err = pi_deploy_verify.run_shell("uptime")
    assert code == pi_deploy_verify.SSH_TRANSPORT_EXIT
    assert len(calls) == pi_deploy_verify.SSH_TRANSPORT_RETRIES + 1


def test_ssh_timeout_is_retried_then_reported(monkeypatch, capsys):
    calls = _remote_run_shell(
        monkeypatch,
        [pi_deploy_verify.subprocess.TimeoutExpired(cmd="ssh", timeout=120)],
    )
    code, _out, _err = pi_deploy_verify.run_shell("uptime")
    assert code == pi_deploy_verify.EXIT_SSH
    assert len(calls) == pi_deploy_verify.SSH_TRANSPORT_RETRIES + 1
    assert "timed out after" in capsys.readouterr().err


def test_ssh_invocation_carries_keepalives():
    assert "ServerAliveInterval=15" in pi_deploy_verify.SSH_OPTIONS
    assert "ServerAliveCountMax=3" in pi_deploy_verify.SSH_OPTIONS
    assert "BatchMode=yes" in pi_deploy_verify.SSH_OPTIONS
