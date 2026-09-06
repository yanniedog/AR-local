"""Runtime health must not undo an ingest's deliberate dashboard pause."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import ar_local_operation_lock as operation_lock
import pi_cdr_recovery as recovery
import pi_daily_sync
import pi_runtime_health as health


@pytest.fixture
def staged(monkeypatch, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(health, "data_state_root", lambda _: state)
    monkeypatch.setattr(health, "ensure_runtime_data_writable", lambda _: None)
    monkeypatch.setattr(health, "is_raspberry_pi", lambda: False)
    monkeypatch.setattr(health.time, "sleep", lambda _: None)
    monkeypatch.setattr(health, "run_http_probes", Mock(return_value=(False, ["HTTP 502"])))
    monkeypatch.setattr(health, "check_tailscale", Mock(return_value=(True, ["tailnet transport OK"])))
    monkeypatch.setattr(health, "restart_dashboard_and_nginx", Mock(return_value=0))
    monkeypatch.setattr(health, "restart_tailscaled", Mock(return_value=0))
    # Never call POSIX os.kill(pid, 0) on a Windows test process.
    monkeypatch.setattr(operation_lock, "_current_boot_id", lambda: "test-boot")
    monkeypatch.setattr(operation_lock, "_boot_epoch", lambda: None)
    monkeypatch.setattr(operation_lock, "_pid_is_alive", lambda _: True)
    health.save_state({"http_fail_streak": 2, "tailscale_fail_streak": 0})
    args = health.build_parser().parse_args(["--heal", "--retries", "0"])
    return state, args


@pytest.mark.parametrize("role", ["ingest", "backup", "deploy"])
def test_existing_production_owner_prevents_both_service_mutations(staged, role):
    state, args = staged
    lock = state / "daily-ingest.lock"
    with operation_lock.production_lock(lock, role):
        before = lock.read_bytes()
        assert health.cmd_heal(args) == health.EXIT_OK
        assert lock.read_bytes() == before
    health.restart_dashboard_and_nginx.assert_not_called()
    health.restart_tailscaled.assert_not_called()
    receipt = health.load_state()
    assert receipt["http_fail_streak"] == 2
    assert receipt["http_heal_deferred_reason"] == "production_lock_unavailable"
    assert "last_http_heal_at" not in receipt
    health.check_tailscale.assert_called_once_with(http_timeout=args.timeout, probe_application=False)


def test_ingest_acquired_after_failed_probe_is_not_restarted(staged, monkeypatch):
    state, args = staged
    lock = state / "daily-ingest.lock"
    evidence = b"pid=987654321\nrole=ingest\nboot_id=test-boot\n"

    def probe(**_kwargs):
        lock.write_bytes(evidence)
        return False, ["HTTP 502 while ingest starts"]

    monkeypatch.setattr(health, "run_http_probes", Mock(side_effect=probe))
    assert health.cmd_heal(args) == health.EXIT_OK
    assert lock.read_bytes() == evidence
    health.restart_dashboard_and_nginx.assert_not_called()
    assert health.load_state()["http_fail_streak"] == 2
    assert "last_http_heal_at" not in health.load_state()


def test_backup_starting_before_lease_acquisition_is_rechecked_inside_lease(staged, monkeypatch):
    state, args = staged
    checks = []

    def activity(*, include_ingest_lock=True):
        checks.append(include_ingest_lock)
        if not include_ingest_lock:
            assert "role=runtime-health" in (state / "daily-ingest.lock").read_text()
            return "backup_source_active"
        return ""

    monkeypatch.setattr(health, "_production_activity_block_reason", activity)
    assert health.cmd_heal(args) == health.EXIT_OK
    assert checks[-1] is False
    assert not (state / "daily-ingest.lock").exists()
    health.restart_dashboard_and_nginx.assert_not_called()
    receipt = health.load_state()
    assert receipt["http_heal_deferred_reason"] == "backup_source_active"
    assert receipt["http_fail_streak"] == 2
    assert "last_http_heal_at" not in receipt


def test_restart_holds_the_same_exclusive_lease_as_daily_ingest(staged, monkeypatch):
    state, args = staged
    monkeypatch.setattr(health, "run_http_probes", Mock(side_effect=[(False, ["fail"]), (True, ["OK"])]))

    def restart(*, dry_run):
        assert dry_run is False
        lock = state / "daily-ingest.lock"
        before = lock.read_bytes()
        assert b"role=runtime-health" in before
        with pytest.raises(RuntimeError, match="production lock is active"):
            with pi_daily_sync.DailyIngestLock(lock):
                pytest.fail("ingest overlapped dashboard/nginx restart")
        assert lock.read_bytes() == before
        return 0

    monkeypatch.setattr(health, "restart_dashboard_and_nginx", Mock(side_effect=restart))
    assert health.cmd_heal(args) == health.EXIT_OK
    health.restart_dashboard_and_nginx.assert_called_once_with(dry_run=False)
    assert not (state / "daily-ingest.lock").exists()
    receipt = health.load_state()
    assert receipt["http_fail_streak"] == 0
    assert "last_http_heal_at" in receipt
    assert "http_heal_deferred_reason" not in receipt


@pytest.mark.parametrize("reason", ["production_ingest_or_backup_lock_active", "scheduled_or_manual_ingest_active",
                                   "backup_source_active", "production_activity_unavailable"])
def test_known_coordinated_work_skips_application_probes_and_healing(staged, monkeypatch, reason):
    _, args = staged
    monkeypatch.setattr(health, "_production_activity_block_reason", Mock(return_value=reason))
    assert health.cmd_heal(args) == health.EXIT_OK
    health.run_http_probes.assert_not_called()
    health.restart_dashboard_and_nginx.assert_not_called()
    receipt = health.load_state()
    assert receipt["http_heal_deferred_reason"] == reason
    assert receipt["http_fail_streak"] == 2
    assert "last_http_heal_at" not in receipt


def test_failed_service_restart_releases_lease_without_claiming_heal(staged, monkeypatch):
    state, args = staged
    monkeypatch.setattr(health, "restart_dashboard_and_nginx", Mock(return_value=1))
    assert health.cmd_heal(args) == health.EXIT_UNHEALTHY
    assert not (state / "daily-ingest.lock").exists()
    receipt = health.load_state()
    assert receipt["http_fail_streak"] == 3
    assert "last_http_heal_at" not in receipt


def test_later_idle_tick_clears_deferral_and_heals(staged, monkeypatch):
    _, args = staged
    activity = Mock(return_value="backup_source_active")
    monkeypatch.setattr(health, "_production_activity_block_reason", activity)
    assert health.cmd_heal(args) == health.EXIT_OK
    assert "http_heal_deferred_reason" in health.load_state()
    activity.return_value = ""
    monkeypatch.setattr(health, "run_http_probes", Mock(side_effect=[(False, ["fail"]), (True, ["OK"])]))
    assert health.cmd_heal(args) == health.EXIT_OK
    health.restart_dashboard_and_nginx.assert_called_once_with(dry_run=False)
    assert "http_heal_deferred_reason" not in health.load_state()


def test_pi_guard_reuses_actual_activity_inventory(staged, monkeypatch):
    monkeypatch.setattr(health, "is_raspberry_pi", lambda: True)
    checker = Mock(return_value="backup_source_active")
    monkeypatch.setattr(recovery, "recovery_block_reason", checker)
    assert health._production_activity_block_reason(include_ingest_lock=False) == "backup_source_active"
    checker.assert_called_once_with(health.REPO_ROOT, include_ingest_lock=False)
    checker.side_effect = OSError("process inventory unavailable")
    assert health._production_activity_block_reason() == "production_activity_unavailable"


@pytest.mark.parametrize("fault", [None, "unit", "tcp", "journal"])
def test_deferred_application_keeps_independent_tailscale_checks(monkeypatch, fault):
    monkeypatch.setattr(health, "tailscale_check_applicable", lambda: True)
    monkeypatch.setattr(health, "unit_is_active", lambda _: fault != "unit")
    monkeypatch.setattr(health.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    monkeypatch.setattr(health, "tailnet_ip", lambda: health.PI_TAILSCALE_IP)
    monkeypatch.setattr(health, "tcp_probe", Mock(return_value=fault != "tcp"))
    monkeypatch.setattr(health, "tailscale_journal_unhealthy", lambda: (fault == "journal", "journal checked"))
    app_probe = Mock(side_effect=AssertionError("paused dashboard is not a tailscale fault"))
    monkeypatch.setattr(health, "http_probe", app_probe)
    ok, _ = health.check_tailscale(http_timeout=5, probe_application=False)
    assert ok is (fault is None)
    app_probe.assert_not_called()


def test_real_tailscale_failure_can_still_heal_during_application_pause(staged, monkeypatch):
    _, args = staged
    health.save_state({"http_fail_streak": 2, "tailscale_fail_streak": 1})
    monkeypatch.setattr(health, "_production_activity_block_reason", Mock(return_value="backup_source_active"))
    monkeypatch.setattr(health, "check_tailscale", Mock(return_value=(False, ["tailscaled.service not active"])))
    assert health.cmd_heal(args) == health.EXIT_OK
    health.restart_dashboard_and_nginx.assert_not_called()
    health.restart_tailscaled.assert_called_once_with(dry_run=False)
    receipt = health.load_state()
    assert receipt["http_fail_streak"] == 2
    assert "last_http_heal_at" not in receipt
    assert "last_tailscale_heal_at" in receipt
