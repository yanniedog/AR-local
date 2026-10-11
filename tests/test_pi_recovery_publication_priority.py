"""Queue admission is control metadata; no historical source is recaptured."""
import json
from datetime import timedelta
from unittest.mock import Mock

import pytest

import pi_cdr_recovery as recovery
import pi_daily_sync as sync
import pi_payload_retry_policy as retries
from tests.test_pi_same_day_recovery import DATE, NOW, stage
from tests.test_pi_recovery_selection_retry import staged_revision
from cdr_observation_selection import selected_observation


def pointer(day):
    return {"schema_version": 2, "observation_date": day,
            "generation_id": f"obs-{day}-" + "a" * 16,
            "observation_state": "partial", "ledger_event_digest": "b" * 64,
            "marker_path": f"{day}.done.json", "export_path": f"runs/{day}/_exports"}


def pending_runtime(tmp_path, monkeypatch, record):
    state, _ = stage(monkeypatch, tmp_path)
    monkeypatch.setattr(sync, "data_state_root", lambda _: state)
    monkeypatch.setattr(retries, "data_state_root", lambda _: state)
    path = sync.payload_publication_pending_path(tmp_path)
    path.write_text(json.dumps(record), encoding="utf-8")
    return state, path


@pytest.mark.parametrize("revision", [False, True])
def test_old_backoff_publications_do_not_starve_current_seeded_recovery(tmp_path, monkeypatch, revision):
    record = {"pointer": pointer("2026-09-01"), "queued_pointers": [pointer("2026-09-02")]}
    if revision:
        record["queued_pointers"][0].update(marker_path="2026-09-02.revision.later.json",
            export_path="runs/2026-09-02/_revisions/later/_exports")
    state, path = pending_runtime(tmp_path, monkeypatch, record)
    reservation = retries.retry_admission(tmp_path, record, now_utc=NOW - timedelta(minutes=1), reserve=True)
    retries.finish_retry(tmp_path, reservation, succeeded=False, reason="upload_failed", now_utc=NOW)
    retry_path = retries.retry_state_path(tmp_path, reservation["source_key"])
    before = {path: path.read_bytes(), retry_path: retry_path.read_bytes()}
    assert retries.retry_admission(tmp_path, record, now_utc=NOW)["reason"] == "publication_retry_cooldown"
    probe = Mock(return_value={"ok": True, "body_sha256": "c" * 64})
    monkeypatch.setattr(recovery, "probe_request", probe)
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result["status"] == "capture_finished" and result["capture_attempted"]
    launch.assert_called_once_with(DATE, 1800, "g1")
    probe.assert_called_once()
    assert all(item.read_bytes() == body for item, body in before.items())
    history = recovery._history(state / "cdr-recovery-v1" / DATE, DATE)
    assert [row["kind"] for row in history].count("capture") == 1


@pytest.mark.parametrize("day", [DATE, "2026-09-08"])
@pytest.mark.parametrize("queued", [False, True])
def test_current_or_future_pending_must_settle_before_probes(tmp_path, monkeypatch, day, queued):
    record = ({"pointer": pointer("2026-09-01"), "queued_pointers": [pointer(day)]}
              if queued else {"pointer": pointer(day)})
    _, path = pending_runtime(tmp_path, monkeypatch, record)
    before = path.read_bytes()
    probe = Mock(side_effect=AssertionError("pending current publication must settle"))
    monkeypatch.setattr(recovery, "probe_register", probe)
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result["status"] == "pending_publication_must_settle"
    assert result["publication_required"] and not result["capture_attempted"]
    assert path.read_bytes() == before
    probe.assert_not_called()
    launch.assert_not_called()


@pytest.mark.parametrize("record", [
    {}, {"pointer": None}, {"pointer": pointer("2026-09-01"), "queued_pointers": None},
    {"pointer": pointer("2026-09-01"), "queued_pointers": [None]},
    {"pointer": pointer("2026-09-01"), "queued_pointers": [{}]},
    {"pointer": {**pointer("2026-09-01"), "observation_date": "2026-02-30"}},
    {"pointer": {**pointer("2026-09-01"), "observation_date": "20260901"}},
    {"pointer": {**pointer("2026-09-01"), "generation_id": ""}},
    {"pointer": {**pointer("2026-09-01"), "generation_id": pointer(DATE)["generation_id"]}},
    {"pointer": {**pointer("2026-09-01"), "schema_version": 1}},
    {"pointer": {**pointer("2026-09-01"), "marker_path": "../outside"}},
    {"pointer": {**pointer("2026-09-01"), "marker_path": f"{DATE}.done.json"}},
    {"pointer": {**pointer("2026-09-01"), "export_path": f"runs/{DATE}/_exports"}},
    {"pointer": {**pointer("2026-09-01"), "marker_path": "2026-09-01.revision.other.json",
                 "export_path": "runs/2026-09-01/_revisions/later/_exports"}},
    {"pointer": {**pointer("2026-09-01"), "ledger_event_digest": None}},
    {"pointer": pointer("2026-09-01"), "queued_pointers": [{**pointer("2026-09-02"), "generation_id": ""}]},
    {"pointer": pointer("2026-09-01"), "run_date": DATE},
    {"pointer": pointer("2026-09-01"), "selection_retry": {}},
])
def test_ambiguous_pending_metadata_stays_fail_closed(tmp_path, monkeypatch, record):
    _, path = pending_runtime(tmp_path, monkeypatch, record)
    before = path.read_bytes()
    probe = Mock(side_effect=AssertionError("ambiguous publication must settle"))
    monkeypatch.setattr(recovery, "probe_register", probe)
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result["status"] == "pending_publication_must_settle"
    assert path.read_bytes() == before
    probe.assert_not_called()
    launch.assert_not_called()


def test_unreadable_pending_marker_never_starts_recovery(tmp_path, monkeypatch):
    _, path = pending_runtime(tmp_path, monkeypatch, {})
    path.write_text("truncated", encoding="utf-8")
    probe = Mock(side_effect=AssertionError("unreadable publication must settle"))
    monkeypatch.setattr(recovery, "probe_register", probe)
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result["status"] == "recovery_evidence_unavailable"
    assert path.read_text(encoding="utf-8") == "truncated"
    probe.assert_not_called()
    launch.assert_not_called()


def test_historical_queue_does_not_bypass_interrupted_selection_settlement(tmp_path, monkeypatch):
    state, parent, _ = staged_revision(tmp_path, monkeypatch)
    sync.mark_payload_publication_pending(tmp_path, "older_failure", pointer("2026-09-01"))
    path = sync.payload_publication_pending_path(tmp_path)
    before = path.read_bytes()
    probe = Mock(side_effect=AssertionError("interrupted selection must settle first"))
    monkeypatch.setattr(recovery, "probe_register", probe)
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result["status"] == "pending_publication_must_settle"
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]
    assert path.read_bytes() == before
    probe.assert_not_called()
    launch.assert_not_called()
