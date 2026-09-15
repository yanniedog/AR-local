"""Per-ingest integration uses retained real source bytes and isolated outputs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cdr_terms.ingest import registry_context

from tests.cdr_terms_source_fixture import source_generation
from cdr_terms.acquisition import FetchFailure
from cdr_terms.acquisitions_queue import AcquisitionQueue, process_next_acquisition
from cdr_terms.identity import byte_digest, digest
from cdr_terms.ingest import capture_finalized, capture_if_configured, retry_capture_if_configured
from cdr_terms.queue import TermsQueue
from cdr_terms.store import EvidenceStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/cdr-canary-2026-09-07/Bank of Melbourne-null-detail.json"
OBSERVED = "2026-09-07T00:00:00Z"
NOW = "2026-09-14T01:00:00Z"


@pytest.fixture
def source_tree(tmp_path):
    run, _, finalized = source_generation(tmp_path, "2026-09-07", OBSERVED)
    path = next((run / "banks").rglob("product-detail.json"))
    return run, tmp_path / "derived", finalized, path


def test_full_raw_capture_is_no_network_and_same_generation_idempotent(source_tree, monkeypatch):
    run, root, finalized, source = source_tree
    def forbidden(*args, **kwargs):
        raise AssertionError("ingest must not access network or invoke a model")
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    receipt = capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=OBSERVED)
    again = capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=NOW)
    assert receipt == again and receipt["products"] == 1
    assert receipt["analysis_jobs"] == 1 and receipt["acquisition_requests"] == 3
    assert receipt["network_called"] is False and receipt["codex_called"] is False
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    with EvidenceStore(root) as store:
        assert store.read_blob(receipt["sources"][0]["sha256"]) == before[0]
        assert store.db.execute("SELECT COUNT(*) FROM acquisition_requests").fetchone()[0] == 3
        assert store.db.execute("SELECT COUNT(*) FROM analysis_jobs").fetchone()[0] == 1


def test_each_new_ingest_rechecks_documents_even_when_cdr_last_updated_and_bytes_unchanged(source_tree):
    run, root, finalized, _ = source_tree
    first = capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=OBSERVED)
    next_ingest = {**finalized, "generation_id": finalized["generation_id"] + "-next", "run_date": "2026-09-14"}
    second = capture_finalized(run, next_ingest, root, forbidden_roots=[run.parent], observed_at=NOW)
    assert first["sources"][0]["sha256"] == second["sources"][0]["sha256"]
    with EvidenceStore(root) as store:
        assert store.db.execute("SELECT COUNT(*) FROM acquisition_requests").fetchone()[0] == 6
        assert store.db.execute("SELECT COUNT(*) FROM analysis_jobs").fetchone()[0] == 1


def test_disabled_hook_has_no_filesystem_or_network_effects(tmp_path, monkeypatch):
    monkeypatch.delenv("AR_LOCAL_TERMS_ROOT", raising=False)
    missing = tmp_path / "does-not-exist"
    assert capture_if_configured(missing, {}, state_dir=missing, runs_root=missing, export_root=missing) is None
    assert retry_capture_if_configured(missing, state_dir=missing, runs_root=missing) is None
    assert not missing.exists()


def test_archive_cannot_be_inside_or_parent_of_source_or_ledger(source_tree):
    run, _, finalized, _ = source_tree
    for dangerous in (run / "terms", run.parent, run.parent.parent):
        with pytest.raises(ValueError, match="separate"):
            capture_finalized(run, finalized, dangerous, forbidden_roots=[run.parent], observed_at=OBSERVED)


def test_capture_failure_retains_source_and_durable_separate_receipt(source_tree, monkeypatch):
    run, root, finalized, source = source_tree
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(root))
    wrong_counts = {**finalized, "banks": {"products": 2}}
    state = run.parent.parent / "state"
    receipt = capture_if_configured(run, wrong_counts, state_dir=state, runs_root=run.parent, export_root=run / "_exports")
    assert receipt["status"] == "CAPTURE_FAILED" and receipt["raw_stage_preserved"]
    assert source.read_bytes() == FIXTURE.read_bytes()
    assert len(list((state / "terms-capture-receipts").glob("*.json"))) == 1
    assert finalized["ledger_state"] == "finalized" and "terms_evidence" not in finalized
    with EvidenceStore(root) as store:
        assert AcquisitionQueue(store).next_due(NOW) is None


def test_capture_retries_from_verified_marker_without_reingest(source_tree, monkeypatch):
    run, root, finalized, _ = source_tree
    state = run.parent.parent / "state"
    state.mkdir(exist_ok=True)
    marker = state / "done.json"
    marker.write_text(json.dumps(finalized), encoding="utf-8")
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(root))
    receipt = retry_capture_if_configured(marker, state_dir=state, runs_root=run.parent)
    assert receipt["status"] == "CAPTURED_AND_QUEUED"
    assert "sources" not in receipt and Path(receipt["receipt_path"]).is_file()


def test_capture_detects_changed_source_on_repeated_generation(source_tree):
    run, root, finalized, source = source_tree
    capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=OBSERVED)
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="raw_source_changed"):
        capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=NOW)


def test_acquisition_idle_path_never_fetches_or_calls_codex(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no due requests must perform no network operation")
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", forbidden)
    with EvidenceStore(tmp_path / "empty") as store:
        assert process_next_acquisition(store, registry_context=registry_context()) == {"result": "NO_WORK", "network_called": False, "codex_called": False}


def test_document_failure_retries_after_deadline_without_fabricating_terms(source_tree, monkeypatch):
    run, root, finalized, _ = source_tree
    capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=OBSERVED)
    def failed(*args, **kwargs):
        raise FetchFailure("http_error", 503)
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", failed)
    with EvidenceStore(root) as store:
        result = process_next_acquisition(store, registry_context=registry_context())
        assert result["result"] == "INCOMPLETE" and result["codex_called"] is False
        latest = store.db.execute("SELECT * FROM acquisition_events WHERE request_id=? ORDER BY sequence DESC LIMIT 1", (result["request_id"],)).fetchone()
        assert latest["status"] == "retry_wait" and latest["retry_after"] > latest["observed_at"]
        assert store.db.execute("SELECT COUNT(*) FROM term_revisions").fetchone()[0] == 0


def test_acquisition_lease_recovers_crash_and_rejects_stale_owner(source_tree):
    run, root, finalized, _ = source_tree
    capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=OBSERVED)
    with EvidenceStore(root) as store:
        queue = AcquisitionQueue(store)
        first = queue.claim(NOW, lease_seconds=1)
        sibling = queue.claim("2026-09-14T01:00:02Z")
        assert sibling["request_id"] != first["request_id"]
        recovered = queue.claim("2026-09-14T01:05:03Z")
        assert recovered["request_id"] == first["request_id"] and recovered["lease_id"] != first["lease_id"]
        store.record_check(document_id=first["document_id"], check_id="failed-transport", checked_at=NOW,
                           status="failed", error_code="transport_error")
        with pytest.raises(ValueError, match="stale completion"):
            queue.finish(first, "failed-transport", now="2026-09-14T01:05:04Z")
        with pytest.raises(ValueError, match="within its accepted lease"):
            queue.finish(recovered, "failed-transport", now="2026-09-14T01:05:04Z")
        store.record_check(document_id=first["document_id"], check_id="retried-transport", checked_at="2026-09-14T01:05:03Z",
                           status="failed", error_code="transport_error")
        queue.finish(recovered, "retried-transport", now="2026-09-14T01:05:04Z")
