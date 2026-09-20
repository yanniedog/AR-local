"""No-work watchdog cleanup must not create a false ingest-priority signal."""
from contextlib import contextmanager
from datetime import datetime, timezone
import subprocess
from unittest.mock import Mock

import pytest

import pi_cdr_recovery as recovery
import pi_daily_sync


@pytest.fixture
def restore(monkeypatch, tmp_path):
    class Daytime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 20, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(recovery, "datetime", Daytime)
    monkeypatch.setattr(recovery, "data_state_root", lambda _: tmp_path)
    guard = Mock(return_value=None)
    monkeypatch.setattr(recovery, "recovery_block_reason", guard)
    query = Mock(return_value="active\n")
    monkeypatch.setattr(recovery.subprocess, "check_output", query)
    start = Mock()
    monkeypatch.setattr(recovery.subprocess, "run", start)
    leases = []

    @contextmanager
    def lock(path):
        leases.append(path)
        path.write_text("held by restoration")
        try:
            yield
        finally:
            path.unlink()

    monkeypatch.setattr(pi_daily_sync, "DailyIngestLock", lock)
    return tmp_path, guard, query, start, leases


@pytest.mark.parametrize("state", ["active", "reloading"])
def test_running_dashboard_does_not_interrupt_analysis(restore, state):
    root, guard, query, start, leases = restore
    query.return_value = state + "\n"
    assert recovery.restore_dashboard_if_idle(root) == {"status": "already_running"}
    assert leases == [] and list(root.iterdir()) == []
    start.assert_not_called()
    guard.assert_called_once_with(root)
    assert query.call_args.kwargs["timeout"] == 10


@pytest.mark.parametrize("state", ["inactive", "failed"])
def test_stopped_dashboard_still_uses_shared_priority_lease(restore, state):
    root, guard, query, start, leases = restore
    query.return_value = state + "\n"

    def during_start(*args, **kwargs):
        assert (root / "daily-ingest.lock").exists()
    start.side_effect = during_start
    assert recovery.restore_dashboard_if_idle(root) == {"status": "restored"}
    assert leases == [root / "daily-ingest.lock"]
    assert not (root / "daily-ingest.lock").exists()
    assert guard.call_count == 2
    assert guard.call_args.kwargs == {"include_ingest_lock": False}
    start.assert_called_once_with(["sudo", "-n", "systemctl", "start", "ar-local-dashboard.service"],
                                  check=True, shell=False, timeout=10)


@pytest.mark.parametrize("state", ["activating", "deactivating", "", "unknown"])
def test_unsettled_state_never_forces_start_or_takes_lease(restore, state):
    root, guard, query, start, leases = restore
    query.return_value = state
    assert recovery.restore_dashboard_if_idle(root)["reason"] == "dashboard_state_unsettled"
    assert leases == []
    start.assert_not_called()


@pytest.mark.parametrize("error", [OSError(), subprocess.TimeoutExpired("systemctl", 10),
                                  subprocess.CalledProcessError(1, "systemctl")])
def test_state_query_failure_is_explicit_and_does_not_take_lease(restore, error):
    root, guard, query, start, leases = restore
    query.side_effect = error
    assert recovery.restore_dashboard_if_idle(root) == {
        "status": "restoration_failed", "failure_category": type(error).__name__}
    assert leases == []
    start.assert_not_called()


def test_real_priority_activity_wins_before_dashboard_query(restore):
    root, guard, query, start, leases = restore
    guard.return_value = "backup_source_active"
    assert recovery.restore_dashboard_if_idle(root)["reason"] == "backup_source_active"
    query.assert_not_called()
    start.assert_not_called()
    assert leases == []
