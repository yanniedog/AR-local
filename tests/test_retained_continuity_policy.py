"""Sealed protocol controls; no fabricated products or business acceptance."""
import json
from datetime import datetime, timezone

import pytest

import pi_daily_sync as sync
import pi_payload_continuity as continuity
from app_payload_observation_gate import publication_allowed
from app_payload_source_verification import reconciled_failure_statuses, verify_reconciled_source
from tests.test_app_payload_retained_policy import DAY, finalized_population_control


def bind_runtime(monkeypatch, state):
    monkeypatch.setattr(continuity, "data_state_root", lambda _: state)
    monkeypatch.setattr(continuity, "data_runs_root", lambda _: state.parent / "runs")
    monkeypatch.setattr(sync, "data_state_root", lambda _: state)
    monkeypatch.setattr(continuity, "payload_retry_window_reason", lambda *args: "")


@pytest.mark.parametrize("failures", [0, 1])
def test_orphaned_retained_partial_is_enqueued_without_classification_waiver(tmp_path, monkeypatch, failures):
    exports, state, contract = finalized_population_control(tmp_path, status="new_upstream_status", failures=failures)
    bind_runtime(monkeypatch, state)
    original = {p: p.read_bytes() for p in exports.rglob("*") if p.is_file()}
    assert contract["observation_state"] == "partial"
    assert publication_allowed(contract) == (True, "retained_partial")
    assert not reconciled_failure_statuses(exports, contract)
    result = continuity.reconcile_missing_publication(tmp_path, {
        "dates_index_first_date": DAY, "missing_dates": [DAY],
    }, DAY, now_utc=datetime(2026, 10, 29, 0, tzinfo=timezone.utc))
    assert result["queued_dates"] == [DAY]
    assert sync.pending_publication_pointer(tmp_path)["generation_id"] == contract["generation_id"]
    assert verify_reconciled_source(state, exports, DAY, contract)
    assert original == {p: p.read_bytes() for p in exports.rglob("*") if p.is_file()}


@pytest.mark.parametrize("fault", ["status", "marker", "event"])
def test_retained_continuity_still_refuses_broken_control_binding(tmp_path, monkeypatch, fault):
    exports, state, contract = finalized_population_control(tmp_path)
    bind_runtime(monkeypatch, state)
    paths = {"status": exports / "ingest-status.json", "marker": state / contract["completion_marker_path"],
             "event": state / "ledger-v2/events" / DAY / f'{contract["generation_id"]}.json'}
    paths[fault].write_text("{}", encoding="utf8")
    with pytest.raises((ValueError, KeyError)):
        continuity.retained_pointer(tmp_path, DAY)
    assert not sync.payload_publication_pending(tmp_path)


def test_metadata_queue_never_waives_publisher_artifact_verification(tmp_path, monkeypatch):
    exports, state, contract = finalized_population_control(tmp_path)
    bind_runtime(monkeypatch, state)
    selected, _ = continuity.retained_pointer(tmp_path, DAY)
    assert selected["generation_id"] == contract["generation_id"]
    # Continuity reads bound metadata; the publisher still hashes every artifact.
    (exports / "banks.json").write_text(json.dumps({"corrupt": True}), encoding="utf8")
    assert not verify_reconciled_source(state, exports, DAY, contract)
