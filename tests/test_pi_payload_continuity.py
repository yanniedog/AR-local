"""Control-plane crash recovery tests; no fabricated business observations."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

import pi_daily_sync as sync
import pi_daily_watchdog as watchdog
import pi_payload_continuity as continuity
from ar_local_operation_lock import production_lock

NOW = datetime(2026, 10, 11, 0, tzinfo=timezone.utc)  # 11:00 Hobart
TODAY = "2026-10-11"


def pointer(day):
    return {"observation_date": day, "generation_id": "protocol-" + day}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr(continuity, "data_state_root", lambda _: state)
    monkeypatch.setattr(sync, "data_state_root", lambda _: state)
    monkeypatch.setattr(continuity, "payload_retry_window_reason", lambda *args: "")
    return tmp_path, state


def reconcile(root, dates, **kwargs):
    return continuity.reconcile_missing_publication(root, {
        "dates_index_first_date": "2026-05-01", "dates_index_error": None, "missing_dates": dates,
    }, TODAY, now_utc=kwargs.pop("now_utc", NOW), **kwargs)


def test_crash_after_finalization_before_enqueue_is_recovered_without_capture(runtime, monkeypatch):
    root, state = runtime
    orphan = pointer("2026-10-01")
    monkeypatch.setattr(continuity, "retained_pointer", lambda *_: (orphan, "complete"))
    assert not sync.payload_publication_pending(root)
    result = reconcile(root, ["2026-10-01"])
    assert result["queued_dates"] == ["2026-10-01"]
    assert sync.pending_publication_pointer(root) == orphan
    assert not (state / "daily-ingest.lock").exists()
    # The next pass sees the original durable pointer and does not queue duplicates.
    monkeypatch.setattr(continuity, "retained_pointer", lambda *_: pytest.fail("repeated source audit"))
    assert reconcile(root, ["2026-10-01"])["inspected_dates"] == 0
    assert sync.read_payload_publication_pending(root).get("queued_pointers", []) == []


def test_queue_preserves_existing_source_and_today_has_priority(runtime, monkeypatch):
    root, _ = runtime
    sync.mark_payload_publication_pending(root, "existing failure", pointer("2026-09-23"))
    seen = []
    def retained(_, day):
        seen.append(day)
        return pointer(day), "complete"
    monkeypatch.setattr(continuity, "retained_pointer", retained)
    result = reconcile(root, ["2026-10-01", TODAY, "2026-10-12"])
    assert seen == [TODAY, "2026-10-01"]
    assert result["queued_dates"] == seen
    pending = sync.read_payload_publication_pending(root)
    assert pending["pointer"] == pointer("2026-09-23")
    assert pending["queued_pointers"] == [pointer(TODAY), pointer("2026-10-01")]


def test_missing_source_is_persisted_and_does_not_starve_other_dates(runtime, monkeypatch):
    root, state = runtime
    monkeypatch.setattr(continuity, "MAX_DATES_PER_PASS", 1)
    source = Mock(side_effect=lambda _, day: (None, "missing_export_contract") if day == "2026-05-14"
                  else (pointer(day), "complete"))
    monkeypatch.setattr(continuity, "retained_pointer", source)
    first = reconcile(root, ["2026-05-14", "2026-10-01"])
    assert first["dates"]["2026-05-14"]["status"] == "source_unavailable"
    assert first["unchecked_dates"] == ["2026-10-01"]
    second = reconcile(root, ["2026-05-14", "2026-10-01"], now_utc=NOW + timedelta(minutes=15))
    assert second["queued_dates"] == ["2026-10-01"]
    assert source.call_count == 2
    report = json.loads((state / continuity.RECONCILIATION_FILE).read_bytes())
    assert report["dates"]["2026-05-14"] == first["dates"]["2026-05-14"]


@pytest.mark.parametrize("corrupt", [False, True])
def test_unverified_source_never_creates_publication_intent(runtime, monkeypatch, corrupt):
    root, _ = runtime
    if corrupt:
        source = Mock(side_effect=ValueError("contract differs"))
    else:
        source = Mock(return_value=(None, "outside_bounded_v1_policy"))
    monkeypatch.setattr(continuity, "retained_pointer", source)
    result = reconcile(root, ["2026-10-01"])
    assert result["queued_dates"] == []
    assert result["dates"]["2026-10-01"]["status"] == ("source_unverified" if corrupt else "source_unavailable")
    assert not sync.payload_publication_pending(root)


def test_dry_run_does_not_write_locks_queue_or_report(runtime, monkeypatch):
    root, state = runtime
    monkeypatch.setattr(continuity, "retained_pointer", lambda _, day: (pointer(day), "complete"))
    assert reconcile(root, ["2026-10-01"], dry_run=True)["status"] == "dry_run"
    assert not state.exists()


def test_active_ingest_and_protected_window_defer_reconciliation(runtime, monkeypatch):
    root, state = runtime
    monkeypatch.setattr(continuity, "retained_pointer", lambda *_: pytest.fail("capture interrupted"))
    with production_lock(state / "daily-ingest.lock", "test-ingest"):
        original = (state / "daily-ingest.lock").read_bytes()
        assert reconcile(root, ["2026-10-01"])["reason"] == "production_busy"
        assert (state / "daily-ingest.lock").read_bytes() == original
    monkeypatch.setattr(continuity, "payload_retry_window_reason", lambda *args: "protected_natural_ingest_window")
    assert reconcile(root, ["2026-10-01"])["reason"] == "protected_natural_ingest_window"


def test_corrupt_pending_state_is_preserved(runtime, monkeypatch):
    root, state = runtime
    state.mkdir()
    pending = sync.payload_publication_pending_path(root)
    pending.write_text("truncated", encoding="utf-8")
    monkeypatch.setattr(continuity, "retained_pointer", lambda *_: pytest.fail("overwriting pending source"))
    assert reconcile(root, ["2026-10-01"])["reason"] == "pending_publication_source_unreadable"
    assert pending.read_text() == "truncated"


def test_retry_selects_current_day_before_older_ready_failure(runtime, monkeypatch):
    root, _ = runtime
    sync.mark_payload_publication_pending(root, "old", pointer("2026-10-01"))
    sync.mark_payload_publication_pending(root, "today", pointer(TODAY))
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(watchdog, "REPO_ROOT", root)
    admitted = Mock(return_value={"status": "ready", "source_key": "a" * 64})
    monkeypatch.setattr(watchdog, "retry_admission", admitted)
    assert watchdog.run_payload_retry(True)["status"] == "dry_run"
    assert admitted.call_args.args[1]["pointer"] == pointer(TODAY)


def test_selected_historical_revision_is_not_stranded_by_older_queued_generation(runtime, monkeypatch):
    root, _ = runtime
    old = pointer("2026-10-01")
    selected = {**old, "generation_id": "protocol-selected-revision"}
    sync.mark_payload_publication_pending(root, "old generation", old)
    monkeypatch.setattr(continuity, "retained_pointer", lambda *_: (selected, "complete"))
    assert reconcile(root, ["2026-10-01"])["queued_dates"] == ["2026-10-01"]
    pending = sync.read_payload_publication_pending(root)
    assert pending["pointer"] == old
    assert pending["queued_pointers"] == [selected]


@pytest.mark.parametrize("dates", [[None], ["2026-02-30"], "2026-10-01", ["../outside"]])
def test_invalid_missing_dates_never_touch_runtime(runtime, dates):
    root, state = runtime
    assert reconcile(root, dates)["reason"] == "invalid_publication_dates"
    assert not state.exists()


def test_corrupt_audit_record_is_preserved(runtime, monkeypatch):
    root, state = runtime
    state.mkdir()
    path = state / continuity.RECONCILIATION_FILE
    path.write_text('{"schema_version":1,"dates":{"2026-10-01":null}}', encoding="utf-8")
    original = path.read_bytes()
    monkeypatch.setattr(continuity, "retained_pointer", lambda *_: pytest.fail("corrupt audit ignored"))
    assert reconcile(root, ["2026-10-01"])["reason"] == "continuity_state_unavailable"
    assert path.read_bytes() == original
