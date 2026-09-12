"""Quality recapture shares publication, revision, cooldown and budget gates."""
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

import pi_cdr_quality_repair as repair
import pi_daily_sync


@pytest.fixture
def ready(monkeypatch, tmp_path):
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 12, 5, tzinfo=timezone.utc)

    @contextmanager
    def locked(path):
        yield True

    monkeypatch.setattr(repair, "datetime", Clock)
    monkeypatch.setattr(repair, "git_state", lambda repo: {"commit": "a" * 40, "clean": True})
    monkeypatch.setattr(repair, "recovery_block_reason", lambda repo: None)
    monkeypatch.setattr(repair, "data_state_root", lambda repo: tmp_path)
    monkeypatch.setattr(repair, "_recovery_lock", locked)
    monkeypatch.setattr(repair, "selected_observation", lambda state, day: {"contract": {"generation_id": "current"}})
    monkeypatch.setattr(pi_daily_sync, "payload_publication_pending", lambda repo: False)
    return tmp_path


def run(repo, **kwargs):
    return repair.recapture(repo, "a" * 40, "current", "Reviewed repair", dry_run=True, **kwargs)


def test_exact_commit_and_clean_tree_are_required(ready, monkeypatch):
    for state in ({"commit": "b" * 40, "clean": True}, {"commit": "a" * 40, "clean": False}):
        monkeypatch.setattr(repair, "git_state", lambda repo: state)
        with pytest.raises(ValueError, match="exact tested"):
            run(ready)


def test_pending_publication_never_spends_capture_budget(ready, monkeypatch):
    monkeypatch.setattr(pi_daily_sync, "payload_publication_pending", lambda repo: True)
    assert run(ready)["reason"] == "pending_publication_must_settle"
    assert not (ready / "cdr-recovery-v1").exists()


def test_selected_revision_change_blocks_recapture(ready, monkeypatch):
    monkeypatch.setattr(repair, "selected_observation", lambda state, day: {"contract": {"generation_id": "newer"}})
    assert run(ready)["reason"] == "selected_generation_changed_or_missing"


def test_existing_recovery_cooldown_and_daily_budget_apply(ready, monkeypatch):
    latest = {"kind": "capture", "reserved_at": "2026-09-12T04:59:00+00:00"}
    monkeypatch.setattr(repair, "_history", lambda root, day: [latest])
    assert run(ready)["reason"] == "capture_cooldown"
    monkeypatch.setattr(repair, "_history", lambda root, day: [latest] * 4)
    assert run(ready)["reason"] == "daily_capture_budget_exhausted"


def test_ready_check_never_reserves_or_launches_capture(ready, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run performed a capture mutation")

    monkeypatch.setattr(repair, "_reserve", forbidden)
    monkeypatch.setattr(repair, "run_ingest_process_group", forbidden)
    assert run(ready)["status"] == "READY"
