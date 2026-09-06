"""Keep unattended coverage repair distinct from a new primary observation."""
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import pi_daily_sync


def test_same_day_resume_requires_an_append_only_revision():
    with pytest.raises(SystemExit) as error:
        pi_daily_sync.parse_args(["--resume-same-day"])
    assert error.value.code == 2


def test_same_day_resume_forwards_a_single_explicit_mode():
    args = pi_daily_sync.parse_args(["--force", "--resume-same-day", "--date", "2026-09-07"])
    assert args.force and args.resume_same_day and args.date == "2026-09-07"


def test_same_day_resume_is_not_a_publication_retry():
    with pytest.raises(SystemExit) as error:
        pi_daily_sync.parse_args(["--force", "--resume-same-day", "--publish-existing-payload"])
    assert error.value.code == 2


def test_recovery_rechecks_backup_and_time_after_taking_ingest_lock(monkeypatch, tmp_path):
    events = []

    @contextmanager
    def lock(_path):
        events.append("locked")
        try:
            yield
        finally:
            events.append("unlocked")

    def guard(repo):
        assert repo == tmp_path and events == ["locked"]
        events.append("guard")
        raise RuntimeError("backup source became active")

    monkeypatch.setattr(pi_daily_sync, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path / "state")
    monkeypatch.setattr(pi_daily_sync, "DailyIngestLock", lock)
    monkeypatch.setitem(sys.modules, "pi_cdr_recovery", SimpleNamespace(assert_recovery_start_safe=guard))
    monkeypatch.setattr(pi_daily_sync, "pause_dashboard_for_ingest", lambda: pytest.fail("paused before guard"))
    monkeypatch.setattr(pi_daily_sync, "run_checked", lambda *_a, **_kw: pytest.fail("launched before guard"))

    with pytest.raises(RuntimeError, match="backup source became active"):
        pi_daily_sync.main(["--force", "--resume-same-day", "--date", "2026-09-07"])
    assert events == ["locked", "guard", "unlocked"]


def test_recovery_launches_cdr_daily_in_verified_resume_mode(monkeypatch, tmp_path):
    calls = []

    @contextmanager
    def lock(_path):
        yield

    monkeypatch.setattr(pi_daily_sync, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path / "state")
    monkeypatch.setattr(pi_daily_sync, "DailyIngestLock", lock)
    monkeypatch.setitem(sys.modules, "pi_cdr_recovery", SimpleNamespace(assert_recovery_start_safe=lambda _repo: None))
    monkeypatch.setattr(pi_daily_sync, "pause_dashboard_for_ingest", lambda: False)
    monkeypatch.setattr(pi_daily_sync, "run_checked", lambda cmd, **_kw: calls.append(cmd))
    monkeypatch.setattr(pi_daily_sync, "refresh_economic_data", lambda _repo: None)
    monkeypatch.setattr(pi_daily_sync, "_app_payload_enabled", lambda: False)
    monkeypatch.setattr(pi_daily_sync, "payload_publication_pending", lambda _repo: False)

    assert pi_daily_sync.main(["--force", "--resume-same-day", "--date", "2026-09-07", "--banks-only"]) == 0
    assert len(calls) == 1
    assert calls[0][1] == str(tmp_path / "cdr_daily.py")
    assert calls[0][-5:] == ["--banks-only", "--force", "--resume-same-day", "--date", "2026-09-07"]
