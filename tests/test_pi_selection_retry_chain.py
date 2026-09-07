"""Publication and chain recovery use finalized structural observation fixtures."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

import cdr_finalization as finalization
import pi_cdr_recovery as recovery
import pi_cdr_selection_recovery as saved
import pi_daily_sync as sync
from cdr_observation_selection import load_pointer_observation, selected_observation
from tests.test_cdr_same_day_selection import DATE, finish, make_export
from tests.test_pi_recovery_selection_retry import NOW, staged_revision


def _deferred_revision(root, state, parent, monkeypatch, name, products, *, failures=0):
    exports = root / "runs" / DATE / "_revisions" / name / "_exports"
    status = make_export(exports, products, failures=failures)
    if failures:
        status["unresolved_requests"] = [{"provider_dir": "Provider", "phase": "product_detail",
            "product_id": "p5", "url": status["provider_states"][0]["endpoint_url"] + "/p5", "status": 404}]
        (exports / "ingest-status.json").write_text(json.dumps(status), encoding="utf-8")
    with monkeypatch.context() as fault:
        fault.setattr(finalization, "same_day_selection_reason", Mock(side_effect=OSError("one failed selection read")))
        return finish(exports, state, "revision." + name, parent["generation_id"])


def test_recovered_observation_remains_the_pending_upload_after_a_later_day(tmp_path, monkeypatch):
    state, _, candidate = staged_revision(tmp_path, monkeypatch)
    report = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert report["status"] == "finalized_selection_recovered"
    expected = selected_observation(state, DATE)["pointer"]
    next_date = "2026-09-08"
    next_exports = tmp_path / "runs" / next_date / "_exports"
    make_export(next_exports, ["p1"], failures=100, date=next_date)
    finish(next_exports, state, "done", date=next_date)
    monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sync, "ensure_runtime_data_writable", lambda _: None)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    publish = Mock(return_value=sync.PUBLISH_FAILED)
    monkeypatch.setattr(sync, "maybe_publish_app_payload", publish)
    assert sync.main(["--publish-existing-payload"]) == 0
    publish.assert_called_once_with(tmp_path, expected)
    assert sync.pending_publication_pointer(tmp_path)["generation_id"] == candidate["generation_id"]


def test_crash_after_selecting_partial_head_settles_upload_before_positive_probes(tmp_path, monkeypatch):
    state, parent, _ = staged_revision(tmp_path, monkeypatch)
    partial = _deferred_revision(tmp_path, state, parent, monkeypatch, "partial",
                                 ["p1", "p2", "p3", "p4"], failures=1)
    real = saved.repair_observation_pointers
    def interrupted(marker, *args, **kwargs):
        result = real(marker, *args, **kwargs)
        if marker["generation_id"] == partial["generation_id"]:
            assert result
            raise OSError("interruption after the partial head was selected")
        return result
    with monkeypatch.context() as fault:
        fault.setattr(saved, "repair_observation_pointers", interrupted)
        first = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert first["status"] == "recovery_evidence_unavailable"
    selected = selected_observation(state, DATE)
    assert selected["contract"]["observation_state"] == "partial"
    assert selected["contract"]["generation_id"] == partial["generation_id"]
    assert json.loads((state / "ledger-v2" / "head.json").read_text())["event_digest"] == selected["event"]["event_digest"]
    pending = sync.payload_publication_pending_path(tmp_path)
    preserved = pending.read_bytes()
    assert sync.pending_publication_pointer(tmp_path) == selected["pointer"]
    probes = Mock(return_value=([{"request_key": "positive", "body_sha256": "a" * 64}], []))
    monkeypatch.setattr(recovery, "_probe_due", probes)
    launch = Mock(side_effect=AssertionError("pending publication must not be superseded by recapture"))
    report = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert report["status"] == "pending_publication_must_settle"
    assert report["publication_required"] and not report["capture_attempted"]
    assert pending.read_bytes() == preserved
    probes.assert_not_called()
    launch.assert_not_called()


def test_older_date_upload_is_preserved_when_no_current_saved_head_needs_selection(tmp_path, monkeypatch):
    state, _, _ = staged_revision(tmp_path, monkeypatch)
    older_date = "2026-09-06"
    older_exports = tmp_path / "runs" / older_date / "_exports"
    make_export(older_exports, ["p1"], failures=0, date=older_date)
    older_marker = finish(older_exports, state, "done", date=older_date)
    event_path = state / "ledger-v2" / "events" / older_date / (older_marker["generation_id"] + ".json")
    older = saved._candidate(state, older_date, json.loads(event_path.read_text()))
    sync.mark_payload_publication_pending(tmp_path, "earlier_upload_failed", older["pointer"])
    pending = sync.payload_publication_pending_path(tmp_path)
    preserved = pending.read_bytes()
    probes = Mock(side_effect=AssertionError("older upload must settle before probing"))
    monkeypatch.setattr(recovery, "_probe_due", probes)
    launch = Mock(side_effect=AssertionError("older upload must settle before recapture"))
    report = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert report["status"] == "pending_publication_must_settle"
    assert report["publication_required"] and not report["capture_attempted"]
    assert pending.read_bytes() == preserved
    assert sync.pending_publication_pointer(tmp_path) == older["pointer"]
    probes.assert_not_called()
    launch.assert_not_called()


def test_earlier_saved_improvement_survives_a_regressing_ledger_head(tmp_path, monkeypatch):
    state, parent, improvement = staged_revision(tmp_path, monkeypatch)
    _deferred_revision(tmp_path, state, parent, monkeypatch, "regression", ["p2", "p4"])
    evidence = {p: p.read_bytes() for p in (state / "ledger-v2").rglob("*.json")}
    monkeypatch.setattr(recovery, "probe_register", Mock(side_effect=AssertionError("must not probe")))
    launch = Mock(side_effect=AssertionError("must not recapture"))
    report = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert report["status"] == "finalized_selection_recovered"
    selected = selected_observation(state, DATE)
    assert selected["contract"]["generation_id"] == improvement["generation_id"]
    assert sync.pending_publication_pointer(tmp_path) == selected["pointer"]
    assert all(p.read_bytes() == before for p, before in evidence.items())
    launch.assert_not_called()


def test_multiple_eligible_candidates_advance_in_ledger_order(tmp_path, monkeypatch):
    state, parent, first = staged_revision(tmp_path, monkeypatch)
    last = _deferred_revision(tmp_path, state, parent, monkeypatch, "last", ["p1", "p2", "p3", "p4"])
    visited = []
    real = saved.repair_observation_pointers
    def record(marker, *args, **kwargs):
        assert (state / "daily-ingest.lock").is_file()
        assert sync.pending_publication_pointer(tmp_path)["generation_id"] == marker["generation_id"]
        visited.append(marker["generation_id"])
        return real(marker, *args, **kwargs)
    monkeypatch.setattr(saved, "repair_observation_pointers", record)
    report = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert report["status"] == "finalized_selection_recovered"
    assert visited == [first["generation_id"], last["generation_id"]]
    assert selected_observation(state, DATE)["contract"]["generation_id"] == last["generation_id"]
    assert sync.pending_publication_pointer(tmp_path)["generation_id"] == last["generation_id"]


@pytest.mark.parametrize("after_advance", [False, True])
def test_crash_either_side_of_pointer_change_keeps_verified_eligible_upload(tmp_path, monkeypatch, after_advance):
    state, parent, candidate = staged_revision(tmp_path, monkeypatch)
    real = saved.repair_observation_pointers
    def interrupted(*args, **kwargs):
        target = sync.pending_publication_pointer(tmp_path)
        assert target["generation_id"] == candidate["generation_id"]
        bound = load_pointer_observation(state, target)
        assert finalization.verify_completion_marker(bound["marker"], state, DATE)
        if after_advance:
            assert real(*args, **kwargs)
        raise OSError("injected interruption at the selection boundary")
    with monkeypatch.context() as fault:
        fault.setattr(saved, "repair_observation_pointers", interrupted)
        first = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert first["status"] == "recovery_evidence_unavailable"
    assert sync.pending_publication_pointer(tmp_path)["generation_id"] == candidate["generation_id"]
    assert selected_observation(state, DATE)["contract"]["generation_id"] == (
        candidate["generation_id"] if after_advance else parent["generation_id"])
    monkeypatch.setattr(recovery, "probe_register", Mock(side_effect=AssertionError("must not probe")))
    retry = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert retry["status"] in {"pending_publication_must_settle", "finalized_selection_recovered"}
    assert selected_observation(state, DATE)["contract"]["generation_id"] == candidate["generation_id"]


def test_refused_candidate_is_never_reserved_as_an_upload(tmp_path, monkeypatch):
    state, parent, candidate = staged_revision(tmp_path, monkeypatch, products=["p2", "p3"])
    real = saved.repair_observation_pointers
    def inspect(marker, *args, **kwargs):
        assert marker["generation_id"] == candidate["generation_id"]
        assert sync.pending_publication_pointer(tmp_path)["generation_id"] == parent["generation_id"]
        return real(marker, *args, **kwargs)
    monkeypatch.setattr(saved, "repair_observation_pointers", inspect)
    report = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert report["status"] == "unresolved_request_evidence_unavailable"
    assert not sync.payload_publication_pending(tmp_path)


def test_later_artifact_failure_preserves_an_earlier_selected_upload(tmp_path, monkeypatch):
    state, parent, improvement = staged_revision(tmp_path, monkeypatch)
    last = _deferred_revision(tmp_path, state, parent, monkeypatch, "last", ["p1", "p2", "p3", "p4"])
    database = tmp_path / "runs" / DATE / "_revisions" / "last" / "_exports" / "local-cdr.sqlite"
    before = database.read_bytes()
    database.write_bytes(before + b"broken evidence")
    launch = Mock(side_effect=AssertionError("must not recapture"))
    report = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert report["status"] == "recovery_evidence_unavailable"
    assert selected_observation(state, DATE)["contract"]["generation_id"] == improvement["generation_id"]
    pending = sync.payload_publication_pending_path(tmp_path)
    preserved = pending.read_bytes()
    assert sync.pending_publication_pointer(tmp_path)["generation_id"] == improvement["generation_id"]
    database.write_bytes(before)
    assert recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)["status"] == "pending_publication_must_settle"
    assert pending.read_bytes() == preserved
    sync.clear_payload_publication_pending(tmp_path)  # Simulate the upload settling.
    retry = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert retry["status"] == "finalized_selection_recovered"
    assert selected_observation(state, DATE)["contract"]["generation_id"] == last["generation_id"]
    launch.assert_not_called()


@pytest.mark.parametrize("limit", ["MAX_SAVED_EVENTS", "MAX_EVENT_BYTES", "MAX_EVENT_SCAN_BYTES"])
def test_saved_chain_budgets_block_recapture_and_preserve_selection(tmp_path, monkeypatch, limit):
    state, parent, _ = staged_revision(tmp_path, monkeypatch)
    monkeypatch.setattr(saved, limit, 1)
    monkeypatch.setattr(recovery, "probe_register", Mock(side_effect=AssertionError("must not probe")))
    launch = Mock(side_effect=AssertionError("must not recapture"))
    report = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert report["status"] == "recovery_evidence_unavailable"
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]
    launch.assert_not_called()


def test_another_upload_reservation_appearing_during_validation_is_preserved(tmp_path, monkeypatch):
    state, parent, _ = staged_revision(tmp_path, monkeypatch)
    real = finalization.same_day_selection_reason
    replacement = []
    def replaced(*args, **kwargs):
        reason = real(*args, **kwargs)
        sync.mark_payload_publication_pending(tmp_path, "another_upload", selected_observation(state, DATE)["pointer"])
        replacement.append(sync.payload_publication_pending_path(tmp_path).read_bytes())
        return reason
    monkeypatch.setattr(finalization, "same_day_selection_reason", replaced)
    report = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert report["status"] == "recovery_evidence_unavailable"
    assert sync.payload_publication_pending_path(tmp_path).read_bytes() == replacement[-1]
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]


@pytest.mark.parametrize("selected", [False, True])
def test_v5_digest_only_reservation_gets_a_verified_pointer(tmp_path, monkeypatch, selected):
    state, parent, candidate = staged_revision(tmp_path, monkeypatch)
    before = selected_observation(state, DATE)
    contract = json.loads((state / candidate["export_contract_path"]).read_text())
    if selected:
        assert finalization.repair_observation_pointers(candidate, state, DATE, state / contract["completion_marker_path"])
    pending = sync.payload_publication_pending_path(tmp_path)
    pending.write_text(json.dumps({"reason": saved.RESERVATION_REASON, "created_at": NOW.isoformat(),
        "selection_retry": {"previous_event_digest": before["event"]["event_digest"],
                            "candidate_event_digest": candidate["ledger_event_digest"]}}))
    if not selected:
        # An unapproved old reservation must first retain the selected source;
        # its candidate cannot be published when eligibility remains unreadable.
        with monkeypatch.context() as fault:
            fault.setattr(finalization, "same_day_selection_reason", Mock(side_effect=OSError("still unreadable")))
            first = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
        assert first["status"] == "recovery_evidence_unavailable"
        assert sync.pending_publication_pointer(tmp_path)["generation_id"] == parent["generation_id"]
    report = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=Mock())
    assert report["status"] in {"pending_publication_must_settle", "finalized_selection_recovered"}
    assert report["publication_required"]
    assert sync.pending_publication_pointer(tmp_path) == selected_observation(state, DATE)["pointer"]
    assert sync.pending_publication_pointer(tmp_path)["generation_id"] == candidate["generation_id"]
