"""Publication retry collision, crash backoff, and tree cleanup regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

import pi_daily_watchdog as watchdog
import pi_payload_retry_policy as policy
import pi_process_group as process_group
from ar_local_ingest_schedule import DAILY_INGEST_TZ, next_daily_due_utc


def local_time(hour=10, minute=0, second=0, *, day=1):
    return datetime(2026, 10, day, hour, minute, second,
                    tzinfo=DAILY_INGEST_TZ).astimezone(timezone.utc)


@pytest.fixture
def retry_state(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "data_state_root", lambda _: tmp_path / "state")
    return policy.retry_state_path(tmp_path, policy.publication_source_key(PENDING))


PENDING = {"pointer": {"observation_date": "2026-10-01", "generation_id": "october-1"},
           "reason": "publish_failed"}


@pytest.mark.parametrize("clock,expected", [
    ((0, 0, 0), "protected_natural_ingest_window"),
    ((0, 30, 0), "protected_natural_ingest_window"),
    ((1, 0, 0), "protected_natural_ingest_window"),
    ((3, 29, 59), "protected_natural_ingest_window"),
    ((3, 30, 0), ""),
    ((21, 29, 15), ""),
    ((21, 29, 16), "insufficient_publication_window"),
    ((22, 0, 0), "protected_natural_ingest_window"),
])
@pytest.mark.parametrize("day", [1, 4, 5])
def test_retry_cannot_overlap_natural_ingest_or_quiet_hours(clock, expected, day):
    # Includes the Oct 4 Hobart DST transition: host timezone must not matter.
    assert policy.payload_retry_window_reason(local_time(*clock, day=day)) == expected


def test_retry_gate_does_not_move_the_natural_timer():
    midnight = local_time(0)
    assert next_daily_due_utc(midnight).astimezone(DAILY_INGEST_TZ).hour == 1
    timer = Path(__file__).resolve().parents[1] / "deploy/pi/ar-local-daily.timer"
    assert "OnCalendar=*-*-* 01:00:00" in timer.read_text(encoding="utf-8")


@pytest.mark.parametrize("clock,expected", [
    ((0, 45), False), ((1, 0), False), ((1, 30), True),
    ((21, 58), True), ((21, 59), False), ((22, 0), False),
])
def test_catch_up_is_current_day_only_and_finishes_before_quiet_hours(monkeypatch, capsys, clock, expected):
    now = local_time(*clock)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(watchdog, "datetime", FixedDatetime)
    monkeypatch.setattr(watchdog, "ensure_runtime_data_writable", lambda _: None)
    monkeypatch.setattr(watchdog, "run_complete", lambda _: False)
    monkeypatch.setattr(watchdog, "service_active", lambda: False)
    monkeypatch.setattr(watchdog, "payload_publication_pending", lambda _: False)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "0")
    launch = Mock()
    monkeypatch.setattr(watchdog, "run_daily_ingest", launch)
    assert watchdog.main(["--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["started"] is expected
    if expected:
        assert launch.call_args.args[0] == "2026-10-01"
        budget = launch.call_args.kwargs["timeout_seconds"]
        finish = (now + timedelta(seconds=budget + policy.CLEANUP_SECONDS)).astimezone(DAILY_INGEST_TZ)
        assert finish.date().isoformat() == "2026-10-01" and finish.hour <= 22
        assert 60 <= budget <= watchdog.SUBPROCESS_INGEST_TIMEOUT_SEC
    else:
        launch.assert_not_called()


def test_catch_up_passes_its_reduced_budget_to_process_fence(monkeypatch):
    fence = Mock()
    monkeypatch.setattr(watchdog, "run_ingest_process_group", fence)
    watchdog.run_daily_ingest("2026-10-01", False, timeout_seconds=75)
    assert fence.call_args.kwargs["timeout_seconds"] == 75


def test_dry_run_never_creates_retry_state_or_lock(retry_state, tmp_path):
    assert policy.retry_admission(tmp_path, PENDING, now_utc=local_time())["status"] == "ready"
    assert not retry_state.parent.exists()


def test_midnight_retry_never_reserves_or_launches(retry_state, tmp_path, monkeypatch):
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(watchdog, "read_payload_publication_pending", lambda _: PENDING)
    real_admission = policy.retry_admission
    monkeypatch.setattr(watchdog, "retry_admission", lambda repo, marker, **kwargs:
                        real_admission(repo, marker, now_utc=local_time(0, 45), **kwargs))
    launch = Mock(side_effect=AssertionError("publication must yield to natural ingest"))
    monkeypatch.setattr(watchdog, "run_ingest_process_group", launch)
    assert watchdog.run_payload_retry(False) == {
        "status": "deferred", "reason": "protected_natural_ingest_window"}
    assert not retry_state.parent.exists()
    launch.assert_not_called()


def test_failed_retry_cools_down_from_completion_and_recovers(retry_state, tmp_path):
    start = local_time()
    attempt = policy.retry_admission(tmp_path, PENDING, now_utc=start, reserve=True)
    assert json.loads(retry_state.read_text())["status"] == "running"
    completed = start + timedelta(minutes=30)
    policy.finish_retry(tmp_path, attempt, succeeded=False, reason="TimeoutExpired", now_utc=completed)
    assert policy.retry_admission(tmp_path, PENDING, now_utc=completed + timedelta(minutes=15),
                                 reserve=True)["reason"] == "publication_retry_cooldown"
    second = policy.retry_admission(tmp_path, PENDING, now_utc=completed + timedelta(hours=1), reserve=True)
    assert second["status"] == "ready"
    assert second["attempts"] == 2 and second["cooldown_seconds"] == 2 * 3600


def test_crashed_retry_keeps_durable_cooldown(retry_state, tmp_path):
    start = local_time()
    reservation = policy.retry_admission(tmp_path, PENDING, now_utc=start, reserve=True)
    # No finish callback: the next process must honor the pre-spawn reservation.
    assert policy.retry_admission(tmp_path, PENDING, now_utc=start + timedelta(minutes=45),
                                 reserve=True)["status"] == "deferred"
    after = datetime.fromisoformat(reservation["next_attempt_at"])
    assert policy.retry_admission(tmp_path, PENDING, now_utc=after, reserve=True)["attempts"] == 2


def test_new_source_is_not_trapped_behind_older_failure(retry_state, tmp_path):
    old = policy.retry_admission(tmp_path, PENDING, now_utc=local_time(), reserve=True)
    revised = {"pointer": {**PENDING["pointer"], "generation_id": "october-1-revised"}}
    new = policy.retry_admission(tmp_path, revised, now_utc=local_time(10, 31), reserve=True)
    assert new["status"] == "ready" and new["attempts"] == 1
    policy.finish_retry(tmp_path, old, succeeded=False, now_utc=local_time(10, 32))
    new_path = policy.retry_state_path(tmp_path, new["source_key"])
    assert json.loads(new_path.read_text())["status"] == "running"
    assert policy.retry_admission(tmp_path, PENDING, now_utc=local_time(10, 33),
                                 reserve=True)["status"] == "deferred"


def test_retry_reason_changes_do_not_reset_the_same_source(retry_state, tmp_path):
    policy.retry_admission(tmp_path, PENDING, now_utc=local_time(), reserve=True)
    changed = {**PENDING, "reason": "interrupted", "created_at": "later"}
    assert policy.retry_admission(tmp_path, changed, now_utc=local_time(10, 31),
                                 reserve=True)["status"] == "deferred"


def test_unreadable_state_fails_closed(retry_state, tmp_path):
    retry_state.parent.mkdir(parents=True)
    retry_state.write_text("truncated", encoding="utf-8")
    assert policy.retry_admission(tmp_path, PENDING, now_utc=local_time(), reserve=True)["reason"] == (
        "publication_retry_state_unreadable")
    assert retry_state.read_text() == "truncated"


def stage_payload_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(watchdog, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(watchdog, "read_payload_publication_pending", lambda _: PENDING)
    real_admission = policy.retry_admission
    monkeypatch.setattr(watchdog, "retry_admission", lambda repo, marker, **kwargs:
                        real_admission(repo, marker, now_utc=local_time(), **kwargs))
    real_finish = policy.finish_retry
    monkeypatch.setattr(watchdog, "finish_retry", lambda repo, attempt, **kwargs:
                        real_finish(repo, attempt, now_utc=local_time(10, 30), **kwargs))


def test_retry_timeout_is_fenced_and_next_tick_does_not_repeat(retry_state, tmp_path, monkeypatch):
    stage_payload_retry(tmp_path, monkeypatch)
    launch = Mock(side_effect=subprocess.TimeoutExpired("publisher", 1800))
    monkeypatch.setattr(watchdog, "run_ingest_process_group", launch)
    with pytest.raises(subprocess.TimeoutExpired):
        watchdog.run_payload_retry(False)
    assert launch.call_args.kwargs["timeout_seconds"] == 1800
    assert json.loads(retry_state.read_text())["reason"] == "TimeoutExpired"
    assert watchdog.run_payload_retry(False)["reason"] == "publication_retry_cooldown"
    assert launch.call_count == 1


def test_zero_exit_with_pending_marker_is_a_failed_retry(retry_state, tmp_path, monkeypatch):
    stage_payload_retry(tmp_path, monkeypatch)
    monkeypatch.setattr(watchdog, "run_ingest_process_group", Mock())
    monkeypatch.setattr(watchdog, "payload_publication_pending", lambda _: True)
    assert watchdog.run_payload_retry(False)["status"] == "failed"
    assert json.loads(retry_state.read_text())["reason"] == "publication_still_pending"


def test_success_with_another_queued_source_is_progress(retry_state, tmp_path, monkeypatch):
    stage_payload_retry(tmp_path, monkeypatch)
    revised = {"pointer": {**PENDING["pointer"], "generation_id": "next-generation"}}
    monkeypatch.setattr(watchdog, "read_payload_publication_pending", Mock(side_effect=[PENDING, revised]))
    monkeypatch.setattr(watchdog, "run_ingest_process_group", Mock())
    monkeypatch.setattr(watchdog, "payload_publication_pending", lambda _: True)
    outcome = watchdog.run_payload_retry(False)
    assert outcome["status"] == "published" and outcome["more_pending"]
    assert json.loads(retry_state.read_text())["status"] == "published"


def test_withheld_head_cooldown_does_not_starve_current_queued_source(retry_state, tmp_path, monkeypatch):
    stage_payload_retry(tmp_path, monkeypatch)
    policy.retry_admission(tmp_path, PENDING, now_utc=local_time(), reserve=True)
    current = {**PENDING["pointer"], "generation_id": "current-generation"}
    marker = {**PENDING, "queued_pointers": [current]}
    # The child settles current, preserving the older unresolved head.
    monkeypatch.setattr(watchdog, "read_payload_publication_pending", Mock(side_effect=[marker, PENDING]))
    launch = Mock()
    monkeypatch.setattr(watchdog, "run_ingest_process_group", launch)
    monkeypatch.setattr(watchdog, "payload_publication_pending", lambda _: True)
    assert watchdog.run_payload_retry(False)["status"] == "published"
    command = launch.call_args.args[0]
    assert command[command.index("--publication-source-key") + 1] == policy.publication_source_key(
        {"pointer": current})
    assert json.loads(retry_state.read_text())["status"] == "running"


def test_payload_timeout_kills_children_even_when_parent_exits(monkeypatch, tmp_path):
    child = Mock(pid=4321)
    child.wait.side_effect = [subprocess.TimeoutExpired("publisher", 1800), 0, 0]
    monkeypatch.setattr(process_group.subprocess, "Popen", Mock(return_value=child))
    kill = Mock()
    monkeypatch.setattr(process_group.os, "killpg", kill, raising=False)
    with pytest.raises(subprocess.TimeoutExpired):
        process_group.run_process_group(["publisher"], cwd=tmp_path, timeout_seconds=1800,
                                        process_groups_supported=True)
    assert [call.args[1] for call in kill.call_args_list] == [
        process_group.signal.SIGTERM, process_group.FORCE_KILL_SIGNAL]
    assert all(call.kwargs.get("timeout", 0) > 0 for call in child.wait.call_args_list)


def test_timed_out_publisher_releases_lock_and_leaves_no_running_grandchild(tmp_path):
    from ar_local_operation_lock import production_lock
    from process_safety import process_alive

    root = Path(__file__).resolve().parents[1]
    worker = tmp_path / "worker.py"
    child_code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    lock_path = tmp_path / "daily-ingest.lock"
    pid_path = tmp_path / "grandchild.pid"
    worker.write_text(
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "from ar_local_operation_lock import production_lock\n"
        f"with production_lock(Path({str(lock_path)!r}), 'publication'):\n"
        f" child = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        f" Path({str(pid_path)!r}).write_text(str(child.pid))\n"
        " time.sleep(60)\n", encoding="utf-8")
    with pytest.raises(subprocess.TimeoutExpired):
        process_group.run_process_group([sys.executable, str(worker)], cwd=root,
            timeout_seconds=1, terminate_grace_seconds=.2, kill_wait_seconds=2)
    pid = int(pid_path.read_text())
    until = time.monotonic() + 2
    while time.monotonic() < until and process_alive(pid):
        stat = Path(f"/proc/{pid}/stat")
        # An adopted POSIX zombie has no executing code or open descriptors.
        if os.name != "nt" and stat.exists() and stat.read_text().split()[2] == "Z":
            break
        time.sleep(.01)
    else:
        assert not process_alive(pid)
    with production_lock(lock_path, "ingest"):
        assert "role=ingest" in lock_path.read_text()
