"""Exercise saved-candidate recovery through unattended watchdog entry points."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

import cdr_finalization as finalization
import pi_cdr_recovery as recovery
import pi_daily_sync as sync
import pi_daily_watchdog as watchdog
from cdr_observation_selection import selected_observation
from tests.test_cdr_same_day_selection import DATE, baseline, finish, make_export
from tests.test_pi_same_day_recovery import FixedDatetime, NOW


def staged_revision(tmp_path, monkeypatch, *, products=None):
    state, _, parent = baseline(tmp_path)
    revision = tmp_path / "runs" / DATE / "_revisions" / "retry" / "_exports"
    make_export(revision, products or ["p1", "p2", "p3"], failures=0)
    with monkeypatch.context() as fault:
        fault.setattr(finalization, "same_day_selection_reason", Mock(side_effect=OSError("temporary read failure")))
        marker = finish(revision, state, "revision.retry", parent["generation_id"])
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]
    monkeypatch.setattr(recovery, "data_state_root", lambda _: state)
    monkeypatch.setattr(sync, "data_state_root", lambda _: state)
    monkeypatch.setattr(recovery, "datetime", FixedDatetime)
    monkeypatch.setattr(recovery, "recovery_block_reason", lambda *a, **k: "")
    return state, parent, marker


def test_watchdog_reconsiders_retained_capture_before_network_or_recapture(tmp_path, monkeypatch):
    state, _, marker = staged_revision(tmp_path, monkeypatch)
    evidence = {p: p.read_bytes() for p in (state / "ledger-v2").rglob("*.json")}
    refusals = {p: p.read_bytes() for p in (state / "observation-selections-v1").rglob("*.json")}
    monkeypatch.setattr(recovery, "probe_register", Mock(side_effect=AssertionError("must not probe")))
    launch = Mock(side_effect=AssertionError("must not recapture"))
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result["status"] == "finalized_selection_recovered"
    assert result["publication_required"] and not result["capture_attempted"]
    assert selected_observation(state, DATE)["contract"]["generation_id"] == marker["generation_id"]
    assert sync.payload_publication_pending(tmp_path)
    assert all(p.read_bytes() == body for p, body in {**evidence, **refusals}.items())
    launch.assert_not_called()


def test_actual_coverage_refusal_remains_unselected_and_clears_only_own_reservation(tmp_path, monkeypatch):
    state, parent, _ = staged_revision(tmp_path, monkeypatch, products=["p2", "p3"])
    # The queue is deliberately empty in this structural fixture; retry must
    # still reach the normal missing-evidence status after rejecting data loss.
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert result["status"] == "unresolved_request_evidence_unavailable"
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]
    assert not sync.payload_publication_pending(tmp_path)


def test_existing_publication_reservation_is_preserved_before_selection_retry(tmp_path, monkeypatch):
    state, parent, _ = staged_revision(tmp_path, monkeypatch)
    sync.mark_payload_publication_pending(tmp_path, "earlier_upload_failed")
    pending = sync.payload_publication_pending_path(tmp_path)
    before = pending.read_bytes()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert result["status"] == "pending_publication_must_settle"
    assert pending.read_bytes() == before
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]


def test_interruption_after_selection_leaves_publication_reserved(tmp_path, monkeypatch):
    state, _, marker = staged_revision(tmp_path, monkeypatch)
    import pi_cdr_selection_recovery as saved
    real = saved.repair_observation_pointers
    def interrupted(*args, **kwargs):
        assert sync.payload_publication_pending(tmp_path)
        assert real(*args, **kwargs)
        raise OSError("interrupted after pointer advancement")
    monkeypatch.setattr(saved, "repair_observation_pointers", interrupted)
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert result["status"] == "recovery_evidence_unavailable"
    assert sync.payload_publication_pending(tmp_path)
    assert selected_observation(state, DATE)["contract"]["generation_id"] == marker["generation_id"]


def test_persistent_selection_read_failure_does_not_spend_another_capture(tmp_path, monkeypatch):
    state, parent, _ = staged_revision(tmp_path, monkeypatch)
    monkeypatch.setattr(finalization, "same_day_selection_reason", Mock(side_effect=OSError("still unreadable")))
    monkeypatch.setattr(recovery, "probe_register", Mock(side_effect=AssertionError("must not probe")))
    launch = Mock(side_effect=AssertionError("must not recapture"))
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result["status"] == "recovery_evidence_unavailable"
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]
    launch.assert_not_called()


def test_preselection_interruption_reservation_can_reenter_after_reads_recover(tmp_path, monkeypatch):
    state, parent, marker = staged_revision(tmp_path, monkeypatch)
    with monkeypatch.context() as fault:
        fault.setattr(finalization, "same_day_selection_reason", Mock(side_effect=OSError("one unreadable tick")))
        first = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert first["status"] == "recovery_evidence_unavailable"
    assert sync.payload_publication_pending(tmp_path)
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]
    monkeypatch.setattr(recovery, "probe_register", Mock(side_effect=AssertionError("must not probe")))
    second = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert second["status"] == "finalized_selection_recovered"
    assert second["publication_required"]
    assert selected_observation(state, DATE)["contract"]["generation_id"] == marker["generation_id"]


def test_missing_intervening_event_never_falls_through_to_recapture(tmp_path, monkeypatch):
    state, parent, middle = staged_revision(tmp_path, monkeypatch)
    revision = tmp_path / "runs" / DATE / "_revisions" / "head" / "_exports"
    make_export(revision, ["p1", "p2", "p3", "p4"], failures=0)
    with monkeypatch.context() as fault:
        fault.setattr(finalization, "same_day_selection_reason", Mock(side_effect=OSError("temporary read failure")))
        finish(revision, state, "revision.head", parent["generation_id"])
    event = state / "ledger-v2" / "events" / DATE / f"{middle['generation_id']}.json"
    event.rename(event.with_suffix(".temporarily-unavailable"))
    monkeypatch.setattr(recovery, "probe_register", Mock(side_effect=AssertionError("must not probe")))
    launch = Mock(side_effect=AssertionError("must not recapture"))
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result["status"] == "recovery_evidence_unavailable"
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]
    launch.assert_not_called()


def staged_watchdog(monkeypatch, report):
    monkeypatch.setattr(watchdog, "datetime", FixedDatetime)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "0")
    monkeypatch.setattr(watchdog, "ensure_runtime_data_writable", lambda _: None)
    monkeypatch.setattr(watchdog, "run_complete", lambda _: True)
    monkeypatch.setattr(watchdog, "service_active", lambda: False)
    monkeypatch.setattr(watchdog, "payload_publication_pending", lambda _: False)
    monkeypatch.setattr(watchdog, "run_same_day_recovery", lambda *a, **k: report)
    monkeypatch.setattr(watchdog, "run_daily_ingest", Mock(side_effect=AssertionError("must not ingest")))
    publish = Mock()
    monkeypatch.setattr(watchdog, "run_payload_retry", publish)
    return publish


@pytest.mark.parametrize("status,code", [
    ("recovery_evidence_unavailable", 1), ("unresolved_request_evidence_unavailable", 1),
    ("capture_failed", 1), ("upstream_gaps_remain", 0), ("provider_cooldown", 0),
    ("production_ingest_or_backup_lock_active", 0),
])
def test_local_recovery_failures_reach_systemd_failure_status(monkeypatch, capsys, status, code):
    publish = staged_watchdog(monkeypatch, {"status": status})
    assert watchdog.main(["--json"]) == code
    assert json.loads(capsys.readouterr().out)["same_day_recovery"]["status"] == status
    publish.assert_not_called()


def test_newly_recovered_selection_is_published_in_the_same_watchdog_tick(monkeypatch):
    publish = staged_watchdog(monkeypatch, {"status": "finalized_selection_recovered", "publication_required": True})
    assert watchdog.main(["--json"]) == 0
    publish.assert_called_once_with(False)
