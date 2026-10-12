from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

import pi_daily_repair_once as gate
from pi_daily_repair_work import repair
from pi_ingest_observe import observe


def test_concurrent_claims_allow_one_and_failure_never_reopens_day(tmp_path):
    now = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda n: gate.claim_day(tmp_path, now, str(n)), range(8)))
    assert sum(status == "claimed" for _, status in results) == 1
    assert gate.claim_day(tmp_path, now, "retry")[1] == "already_attempted_today"


@pytest.mark.parametrize("utc,allowed", [("2026-10-12T08:59:00+00:00", False),
    ("2026-10-12T09:00:00+00:00", True), ("2026-10-12T11:00:00+00:00", False),
    ("2027-06-01T09:59:00+00:00", False), ("2027-06-01T10:00:00+00:00", True)])
def test_window_is_hobart_with_daylight_saving(tmp_path, utc, allowed):
    assert (gate.claim_day(tmp_path, datetime.fromisoformat(utc), "id")[0] is not None) == allowed


def supervisor():
    return {"Id": gate.UNIT, "Type": "notify", "NotifyAccess": "main", "MainPID": "123",
            "ControlGroup": "/system.slice/" + gate.UNIT, "KillMode": "control-group",
            "SendSIGKILL": "yes", "Restart": "no", "RuntimeMaxUSec": "18min 40s",
            "TimeoutStartUSec": "1min 1s", "TimeoutStopUSec": "10s"}


@pytest.mark.parametrize("key,bad", [("Type", "oneshot"), ("RuntimeMaxUSec", "infinity"),
    ("TimeoutStartUSec", "infinity"), ("TimeoutStopUSec", "90s"), ("KillMode", "process"),
    ("SendSIGKILL", "no"), ("Restart", "always"), ("MainPID", "456"), ("NotifyAccess", "all")])
def test_repair_refuses_unbounded_or_wrong_supervisor(key, bad):
    details = supervisor()
    gate.validate_supervisor(details, details["ControlGroup"], 123)
    details[key] = bad
    with pytest.raises(RuntimeError):
        gate.validate_supervisor(details, details["ControlGroup"], 123)


def test_observation_has_no_mutation_capabilities():
    # Only read-only capabilities are supplied: accidental repair calls fail.
    w = SimpleNamespace(HOBART=ZoneInfo("Australia/Hobart"), REPO_ROOT=Path("/repo"),
        check_publication=lambda d: {"publication_current": False},
        run_complete=lambda d: False, service_active=lambda: False,
        payload_publication_pending=lambda r: True)
    result = observe(w, datetime(2026, 10, 12, 9, tzinfo=timezone.utc))
    assert result["observation_only"] and result["repair_started"] is False
    assert result["capture_finalized"] is False


@pytest.mark.parametrize("pending", [{"run_date": "2026-10-11"},
    {"run_date": "2026-10-12", "pointer": {"observation_date": "2026-10-11"}},
    {"run_date": "2026-10-12", "pointer": {"observation_date": "2026-10-12"}, "queued_pointers": [{}]}])
def test_repair_cannot_publish_historical_or_ambiguous_queue(pending):
    w = Mock(REPO_ROOT=Path("/repo"))
    w.read_payload_publication_pending.return_value = pending
    r = Mock()
    r.recovery_block_reason.return_value = ""
    r.selected_observation.return_value = {"verified": True}
    assert repair(w, r, "2026-10-12", None)["status"] == "blocked"
    w.run_payload_retry.assert_not_called()
    r.run_same_day_recovery.assert_not_called()


def test_busy_ingest_prevents_all_repair_work():
    w, r = Mock(), Mock()
    r.recovery_block_reason.return_value = "scheduled_or_manual_ingest_active"
    assert repair(w, r, "2026-10-12", None)["status"] == "blocked"
    r.selected_observation.assert_not_called()
    w.run_payload_retry.assert_not_called()


def test_service_has_no_timer_or_restart_and_kernel_total_is_bounded():
    root = Path(__file__).resolve().parents[1]
    text = (root / "deploy/pi/ar-local-queue-task-daily-repair.service").read_text()
    assert "\n[Install]" not in text
    assert "Restart=no" in text and "KillMode=control-group" in text
    assert "TimeoutStartSec=61s" in text and "RuntimeMaxSec=1120s" in text
    assert "TimeoutStopSec=10s" in text and 61 + 1120 + 10 <= 1200
    assert not (root / "deploy/pi/ar-local-queue-task-daily-repair.timer").exists()
