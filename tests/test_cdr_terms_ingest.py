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


def test_public_pricing_lane_failures_never_fail_the_original_capture(tmp_path, monkeypatch):
    import sys, types
    from cdr_terms import ingest as ingest_module
    fake = types.SimpleNamespace(configured=lambda: True,
        capture_public_rates=lambda *a: (_ for _ in ()).throw(RuntimeError("sqlite exploded")))
    monkeypatch.setitem(sys.modules, 'cdr_public_rates_collector', fake)
    store = types.SimpleNamespace(root=tmp_path)
    receipt = {"generation_id": "gen-1"}
    ingest_module._capture_public_pricing(store, tmp_path, receipt)
    written = list((tmp_path / "public-rate-capture-receipts").glob("*.json"))
    assert len(written) == 1 and json.loads(written[0].read_text())["status"] == "capture_failed"
    # An unwritable receipt location is also non-fatal.
    (tmp_path / "ro").write_text("file, not a directory")
    ingest_module._capture_public_pricing(types.SimpleNamespace(root=tmp_path / "ro"), tmp_path, receipt)


def test_capture_reuses_registry_context_across_distinct_real_products(source_tree, monkeypatch):
    import cdr_terms.ingest as ingest
    run, root, finalized, original = source_tree
    body = (ROOT / 'tests/fixtures/cdr-canary-2026-09-07/Border Bank-null-detail.json').read_bytes()
    record = json.loads(body)['data']
    second = run / 'banks' / 'Mortgage' / record['brand'] / record['name'] / record['productId'] / 'product-detail.json'
    second.parent.mkdir(parents=True)
    second.write_bytes(body)
    calls = []
    actual = ingest.registry_context
    monkeypatch.setattr(ingest, 'registry_context', lambda: calls.append(True) or actual())
    receipt = capture_finalized(run, {**finalized, 'banks': {'products': 2}}, root,
                                forbidden_roots=[run.parent], observed_at=OBSERVED)
    assert receipt['products'] == 2 and receipt['analysis_jobs'] == 2
    assert len(calls) == 1
    assert second.read_bytes() == body and original.read_bytes() == FIXTURE.read_bytes()


def test_existing_store_gains_version_lookup_index_without_rewriting_evidence(source_tree):
    run, root, finalized, _ = source_tree
    receipt = capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=OBSERVED)
    query = ('SELECT * FROM acquisition_checks WHERE document_version_id=? '
             'ORDER BY checked_at DESC,sequence DESC LIMIT 1')
    with EvidenceStore(root) as store:
        previous = [tuple(row) for row in store.db.execute('SELECT * FROM acquisition_checks ORDER BY sequence')]
        store.db.execute('DROP INDEX acquisition_version_observed')
        old = [row[3] for row in store.db.execute('EXPLAIN QUERY PLAN ' + query, ('version',))]
        assert any('SCAN acquisition_checks' in plan for plan in old)
    with EvidenceStore(root) as store:
        new = [row[3] for row in store.db.execute('EXPLAIN QUERY PLAN ' + query, ('version',))]
        assert any('SEARCH acquisition_checks USING INDEX acquisition_version_observed' in plan for plan in new)
        assert not any('TEMP B-TREE' in plan for plan in new)
        assert [tuple(row) for row in store.db.execute('SELECT * FROM acquisition_checks ORDER BY sequence')] == previous
        assert store.read_blob(receipt['sources'][0]['sha256']) == FIXTURE.read_bytes()
    assert capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=NOW) == receipt


def test_optional_index_interruption_preserves_archive_and_connection(source_tree, monkeypatch):
    import cdr_terms.capture_indexes as indexes
    run, root, finalized, _ = source_tree
    capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=OBSERVED)
    with EvidenceStore(root) as store:
        store.db.execute('DROP INDEX acquisition_version_observed')
        before = store.db.execute('SELECT COUNT(*) FROM acquisition_checks').fetchone()[0]
        clock = iter([0, 6])
        monkeypatch.setattr(indexes.time, 'monotonic', lambda: next(clock, 6))
        # Fire the real SQLite progress callback on each VM instruction.
        actual = store.db.set_progress_handler
        class Connection:
            in_transaction = False
            def execute(self, *args): return store.db.execute(*args)
            def set_progress_handler(self, callback, count): actual(callback, 1 if callback else 0)
        indexes.install(Connection())
        assert store.db.execute('PRAGMA busy_timeout').fetchone()[0] == 20000
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_checks').fetchone()[0] == before
        assert not store.db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (indexes.INDEX,)).fetchone()
