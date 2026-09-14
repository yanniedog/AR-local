"""Retained real CDR scope plus isolated markup/transport boundary regressions.

Markup snippets test traversal mechanics only; they are not bank terms or live
acceptance evidence. All product identities and raw scopes use retained bytes.
"""
from __future__ import annotations

import json
import sqlite3
from html.parser import HTMLParser
from pathlib import Path

import pytest

from cdr_terms.acquisition import FetchPolicy, acquire_document, fetch_document
from cdr_terms.acquisitions_queue import AcquisitionQueue, process_next_acquisition
from cdr_terms.extraction import MAX_HTML_LINKS, extract_document, extract_version
from cdr_terms.graph import DocumentGraph, GraphPolicy, current_observations
from cdr_terms.identity import digest, utc_now
from cdr_terms.store import EvidenceStore

FIXTURE = Path(__file__).parent / "fixtures/cdr-canary-2026-09-07/Bank of Melbourne-null-detail.json"
HOST = "www.bankofmelbourne.com.au"
URL = "https://" + HOST + "/personal/home-loans/our-home-loans/basic-home-loan"
NOW = "2026-09-14T10:00:00Z"


@pytest.fixture
def retained(tmp_path):
    body = FIXTURE.read_bytes()
    source = json.loads(body)
    with EvidenceStore(tmp_path / "derived") as store:
        observation = store.observe(provider=source["data"]["brand"], product_key="Bank of Melbourne|BOMHLBasic",
                                    record=source, source_bytes=body, observed_at="2026-09-07T00:00:00Z", ingest_id="retained-september7")
        queue = AcquisitionQueue(store)
        queue.enqueue(observation, ingest_id="retained-september7", now=NOW)
        receipt = store.put_blob(b"isolated capture finalization boundary")
        with store.db:
            store.db.execute("INSERT INTO ingest_captures VALUES (?,?,?,1)", ("retained-september7", receipt, NOW))
        yield store, observation, queue


def start(retained, markup, *, policy=None, final_url=URL, media_type='text/html'):
    store, _, queue = retained
    target = store.db.execute("SELECT r.* FROM acquisition_requests r JOIN documents d USING(document_id) WHERE d.source_url=?", (URL,)).fetchone()
    # Complete other real CDR references with the actual retained JSON bytes.
    # No requests leave the test process; only the chosen document uses markup.
    while True:
        request = queue.claim()
        assert request
        chosen = request["request_id"] == target["request_id"]
        body = (markup if isinstance(markup, bytes) else markup.encode()) if chosen else FIXTURE.read_bytes()
        check_id = digest([request["request_id"], request["lease_id"]])
        store.record_check(document_id=request["document_id"], check_id=check_id, checked_at=utc_now(), status="fetched",
                           body=body, media_type=media_type if chosen else "application/json", metadata={"final_url": final_url if chosen else URL})
        check = dict(store.db.execute("SELECT * FROM acquisition_checks WHERE check_id=?", (check_id,)).fetchone())
        if chosen:
            root = DocumentGraph(store).seed(request, check, policy=policy)
        queue.finish(request, check_id)
        if chosen:
            return root, request, check


def test_real_raw_paths_and_product_observation_scope_remain_distinct(retained):
    store, observation, _ = retained
    root, _, check = start(retained, '<a href="#fees">A</a><a href="#rates">B</a>')
    graph = DocumentGraph(store)
    receipt = graph.advance_one()
    inventory = graph.inventory(root)
    assert receipt["counts"] == {"cycle_retained": 2}
    assert len(inventory["scopes"]) == 3  # same URL: overview, terms, eligibility
    assert {item["observation_id"] for item in inventory["scopes"]} == {observation}
    assert len({item["source_path"] for item in inventory["scopes"]}) == 3
    assert len(inventory["edges"]) == 2 and len(inventory["nodes"]) == 1
    assert all(item["parent_version_id"] == check["document_version_id"] for item in inventory["edges"])
    assert inventory["legal_completeness"] == "unknown" and inventory["effective_dates"] == "unknown"
    assert store.db.execute("SELECT COUNT(*) FROM term_revisions").fetchone()[0] == 0


@pytest.mark.parametrize('failure', ['invalid', 'encrypted', 'input_limit', 'unavailable'])
def test_unscanned_pdf_failure_cannot_be_accounted_as_zero_links(retained, monkeypatch, failure):
    import builtins
    from cdr_terms import pdf_extraction as pdf
    from tests.test_cdr_terms_pdf import protocol_pdf

    body = b'%PDF-broken' if failure == 'invalid' else protocol_pdf(['Protocol.'], encrypted=failure == 'encrypted')
    store, _, _ = retained
    root, _, _ = start(retained, body, media_type='application/pdf')
    if failure == 'input_limit':
        monkeypatch.setattr(pdf, 'MAX_PDF_BYTES', len(body) - 1)
    if failure == 'unavailable':
        original_import = builtins.__import__
        def unavailable(name, *args, **kwargs):
            if name == 'pypdf':
                raise ImportError('isolated unavailable parser')
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, '__import__', unavailable)
    graph = DocumentGraph(store)
    receipt = graph.advance_one()
    assert receipt['extraction_status'] == 'failed'
    assert receipt['reason'] == 'incorporated_reference_extraction_unsupported'
    assert receipt['links_observed'] is None and receipt['links_omitted'] is None
    assert receipt['legal_completeness'] == 'unknown'
    inventory = graph.inventory(root)
    assert len(inventory['nodes']) == 1 and inventory['edges'] == []
    expansion = inventory['nodes'][0]['expansion']
    stored = json.loads(expansion['receipt_json'])
    assert stored['links_observed'] is None and stored['reason'] == receipt['reason']
    row = store.db.execute('SELECT coverage_json FROM extractions WHERE extraction_id=?', (expansion['extraction_id'],)).fetchone()
    coverage = json.loads(row[0])
    assert 'candidate_links' not in coverage
    assert coverage['candidate_links_total'] is None and coverage['candidate_links_omitted'] is None


def test_restart_idempotency_link_occurrences_cycles_and_same_content_distinct_urls(retained, monkeypatch):
    store, _, _ = retained
    markup = '<a href="/one#x">A</a><a href="/one#y">B</a><a href="/two">C</a>'
    root, _, _ = start(retained, markup)
    graph = DocumentGraph(store)
    assert graph.advance_one()["counts"] == {"candidate_fetch_queued": 2, "existing_url_frontier": 1}
    assert graph.advance_one() is None
    # Existing source references may still be queued; drain with retained JSON.
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs["policy"]))
        return {"status": "fetched", "http_status": 200, "media_type": "text/html", "body": b'<a href="/one#cycle">A</a>', "metadata": {"final_url": url}}
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", fetch)
    before = store.db.execute("SELECT COUNT(*) FROM analysis_jobs").fetchone()[0]
    for _ in range(16):
        previous = len(calls)
        result = process_next_acquisition(store, registry_context={})
        assert len(calls) - previous <= 1
        if result["result"] == "NO_WORK":
            break
    else:
        pytest.fail("bounded frontier did not drain")
    inventory = graph.inventory(root)
    assert len(inventory["nodes"]) == 3
    children = [node for node in inventory["nodes"] if node["depth"]]
    assert len({node["check"]["document_version_id"] for node in children}) == 2
    shas = [store.db.execute("SELECT content_sha256 FROM document_versions WHERE document_version_id=?", (node["check"]["document_version_id"],)).fetchone()[0] for node in children]
    assert len(set(shas)) == 1  # content-addressed bytes, URL/version identities distinct
    assert sum(url.endswith("/one") for url, _ in calls) == 1
    assert sum(url.endswith("/two") for url, _ in calls) == 1
    assert all(policy.allowed_hosts == frozenset({HOST}) for url, policy in calls if url.endswith(("/one", "/two")))
    jobs_after = store.db.execute("SELECT COUNT(*) FROM analysis_jobs").fetchone()[0]
    assert jobs_after - before <= 3  # only independent raw CDR references; no graph-only analysis
    for child in children:
        assert store.db.execute("SELECT COUNT(*) FROM analysis_jobs j JOIN extractions e USING(extraction_id) "
                                "JOIN document_versions v USING(document_version_id) WHERE v.document_id=?", (child["document_id"],)).fetchone()[0] == 0
    counts = [store.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] for table in ("document_graph_nodes", "document_graph_edges", "acquisition_requests")]
    assert graph.pending() is None and graph.advance_one() is None
    assert counts == [store.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] for table in ("document_graph_nodes", "document_graph_edges", "acquisition_requests")]


@pytest.mark.parametrize("policy,markup,reason", [
    (GraphPolicy(max_depth=0), '<a href="/next">A</a>', "frontier_depth_limit"),
    (GraphPolicy(max_nodes=1), '<a href="/next">A</a>', "frontier_node_limit"),
    (GraphPolicy(max_links=1), '<a href="#a">A</a><a href="/next">B</a>', "frontier_link_limit"),
    (GraphPolicy(), '<a href="https://unreviewed.example/terms">A</a>', "host_not_authorized"),
    (GraphPolicy(), '<a href="mailto:terms@example.com">A</a>', "unsupported_or_unsafe_reference"),
    (GraphPolicy(), '<a href="/logo.svg">A</a>', "non_document_asset"),
    (GraphPolicy(), '<a href="https://127.0.0.1/">A</a>', "non_public_address"),
    (GraphPolicy(), '<base href="/changed/"><a href="next">A</a>', "html_base_href_requires_review"),
])
def test_every_frontier_rejection_is_durable_and_not_complete(retained, policy, markup, reason):
    store, _, _ = retained
    root, _, _ = start(retained, markup, policy=policy)
    graph = DocumentGraph(store)
    receipt = graph.advance_one()
    assert receipt["counts"][reason] == 1
    assert graph.inventory(root)["legal_completeness"] == "unknown"
    assert graph.pending() is None
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute("DELETE FROM document_graph_edges")
    store.db.rollback()


def test_extractor_limit_has_exact_omitted_count_and_anchor_occurrence(retained):
    store, _, _ = retained
    total = MAX_HTML_LINKS + 19
    root, _, _ = start(retained, '<a href="#a">A</a>' * total)
    receipt = DocumentGraph(store).advance_one()
    assert receipt["links_observed"] == total and receipt["links_omitted"] == 19
    assert receipt["omitted_reason"] == "extractor_link_limit"
    refs = [json.loads(row[0]) for row in store.db.execute("SELECT reference_json FROM document_graph_edges")]
    assert sorted(ref["anchor_index"] for ref in refs) == list(range(1, MAX_HTML_LINKS + 1))


def test_expansion_transaction_crash_restarts_without_partial_frontier(retained, monkeypatch):
    store, _, _ = retained
    root, _, _ = start(retained, '<a href="/one">A</a><a href="/two">B</a>')
    graph = DocumentGraph(store)
    original = graph._enqueue
    def crash(node, doc):
        original(node, doc)
        raise RuntimeError("isolated interruption")
    monkeypatch.setattr(graph, "_enqueue", crash)
    with pytest.raises(RuntimeError, match="interruption"):
        graph.advance_one()
    assert len(graph.inventory(root)["nodes"]) == 1 and not graph.inventory(root)["edges"]
    monkeypatch.setattr(graph, "_enqueue", original)
    assert graph.advance_one()["counts"] == {"candidate_fetch_queued": 2}


def test_source_advance_blocks_stale_frontier_without_network_or_removal(retained, monkeypatch):
    store, _, _ = retained
    root, request, check = start(retained, '<a href="/new">A</a>')
    graph = DocumentGraph(store)
    graph.advance_one()
    store.record_check(document_id=request["document_id"], check_id="source-advance", checked_at="2099-01-01T00:00:00Z",
                       status="fetched", body=b"new retained transport boundary", media_type="text/plain", metadata={"final_url": URL})
    graph_request = store.db.execute("SELECT request_id FROM document_graph_nodes WHERE root_id=? AND depth=1", (root,)).fetchone()[0]
    assert graph.request_hosts(graph_request) == frozenset()
    # Finish independent CDR requests so the selected cycle concerns the graph.
    while True:
        due = AcquisitionQueue(store).next_due()
        if due["request_id"] == graph_request:
            break
        claimed = AcquisitionQueue(store).claim()
        store.record_check(document_id=claimed["document_id"], check_id=claimed["lease_id"], checked_at=utc_now(), status="deferred", error_code="test_disposition")
        AcquisitionQueue(store).finish(claimed, claimed["lease_id"], terminal=True)
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", lambda *a, **k: pytest.fail("stale graph fetched"))
    result = process_next_acquisition(store, registry_context={})
    assert result["network_called"] is False and result["error"] == "source_scope_superseded"
    assert len(graph.inventory(root)["edges"]) == 1
    assert store.db.execute("SELECT 1 FROM document_versions WHERE document_version_id=?", (check["document_version_id"],)).fetchone()


def test_relative_links_bind_verified_final_location_and_redirect_host_grant(retained):
    store, _, _ = retained
    root, _, check = start(retained, '<a href="next.pdf#fee">A</a>', final_url="https://" + HOST + "/relocated/index")
    extraction = extract_version(store, check["document_version_id"], check_id=check["check_id"])
    coverage = json.loads(store.db.execute("SELECT coverage_json FROM extractions WHERE extraction_id=?", (extraction,)).fetchone()[0])
    assert coverage["candidate_links"][0]["sourceUrl"] == "https://" + HOST + "/relocated/next.pdf#fee"
    assert DocumentGraph(store).advance_one()["counts"] == {"candidate_fetch_queued": 1}


def test_changed_base_with_identical_bytes_has_new_extraction_identity(retained):
    store, _, _ = retained
    _, request, check = start(retained, '<a href="next">A</a>')
    first = extract_version(store, check["document_version_id"], check_id=check["check_id"])
    sha = store.db.execute("SELECT content_sha256 FROM document_versions WHERE document_version_id=?", (check["document_version_id"],)).fetchone()[0]
    version = store.record_check(document_id=request["document_id"], check_id="same-bytes-new-location", checked_at=utc_now(), status="fetched",
                                 body=store.read_blob(sha), media_type="text/html", metadata={"final_url": "https://" + HOST + "/new/index"})
    assert version == check["document_version_id"]
    second = extract_version(store, version, check_id="same-bytes-new-location")
    assert first != second
    assert DocumentGraph(store).advance_one()["reason"] == "parent_source_version_or_location_superseded"


def test_unreviewed_redirect_destination_never_grants_official_host(retained):
    _, _, _ = retained
    start(retained, '<a href="next">A</a>', final_url="https://cdn.unreviewed.example/path/index")
    assert DocumentGraph(retained[0]).advance_one()["reason"] == "redirect_host_not_authorized"


def test_historical_priority_does_not_make_current_fetch_a_historical_graph(tmp_path):
    body = FIXTURE.read_bytes()
    with EvidenceStore(tmp_path / "historical") as store:
        obs = store.observe(provider="Bank of Melbourne", product_key="Bank of Melbourne|BOMHLBasic",
                            record=json.loads(body), source_bytes=body, observed_at="2026-09-07T00:00:00Z", ingest_id="historical")
        queue = AcquisitionQueue(store)
        queue.enqueue(obs, ingest_id="historical", now=NOW, priority=2)
        with store.db:
            store.db.execute("INSERT INTO ingest_captures VALUES (?,?,?,1)", ("historical", digest("fixture"), NOW))
        request = queue.claim()
        store.record_check(document_id=request["document_id"], check_id="today", checked_at=NOW, status="fetched",
                           body=body, media_type="application/json", metadata={"final_url": URL})
        check = dict(store.db.execute("SELECT * FROM acquisition_checks WHERE check_id='today'").fetchone())
        assert DocumentGraph(store).seed(request, check) is None
        assert store.db.execute("SELECT observed_at,effective_from FROM document_versions WHERE document_version_id=?", (check["document_version_id"],)).fetchone()[1] is None


def test_tampered_root_priority_or_parent_check_cannot_rebind_graph(retained):
    store, _, _ = retained
    _, request, check = start(retained, '<a href="/next">A</a>')
    for altered_request, altered_check in (({**request, "priority": True}, check), (request, {**check, "document_version_id": digest("wrong")})):
        with pytest.raises(ValueError, match="exact retained"):
            DocumentGraph(store).seed(altered_request, altered_check)


def test_graph_only_worker_admission_uses_existing_bounded_supervisor_once(retained, monkeypatch):
    import pi_terms_acquire
    import pi_terms_worker as worker
    from tests.test_cdr_quality_resources import receipt
    store, _, queue = retained
    start(retained, '<a href="#same-document">A</a>')
    # Disposition independent source requests so only offline graph work is due.
    while request := queue.claim():
        store.record_check(document_id=request["document_id"], check_id=request["lease_id"], checked_at=utc_now(), status="deferred", error_code="isolated_disposition")
        queue.finish(request, request["lease_id"], terminal=True)
    assert queue.next_due() is None and DocumentGraph(store).pending()
    calls = []
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", lambda *a, **k: pytest.fail("cycle-only graph must not fetch"))
    def supervisor(command, output, limits, **kwargs):
        calls.append(command)
        assert limits.runtime_seconds == 120 and callable(kwargs["priority_guard"])
        value = pi_terms_acquire.run(output.parent)
        assert value["network_called"] is False and value["codex_called"] is False
        return receipt()
    monkeypatch.setattr(worker, "supervise", supervisor)
    result = worker.collect_one(store, Path(__file__).resolve().parents[1], store.root)
    assert result["result"] == "INCOMPLETE" and result["graph_progress"]["legal_completeness"] == "unknown"
    assert worker.collect_one(store, Path(__file__).resolve().parents[1], store.root)["result"] == "NO_WORK"
    assert len(calls) == 1


def test_existing_archive_reopens_idempotently_and_preserves_source_rows(retained):
    store, observation, _ = retained
    before = tuple(store.db.execute("SELECT * FROM observations WHERE observation_id=?", (observation,)).fetchone())
    source = store.read_blob(before[-1])
    with EvidenceStore(store.root) as reopened:
        assert tuple(reopened.db.execute("SELECT * FROM observations WHERE observation_id=?", (observation,)).fetchone()) == before
        assert reopened.read_blob(before[-1]) == source
        assert reopened.db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert reopened.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_two_retained_products_share_fetch_without_losing_fee_applicability(tmp_path):
    fixtures = Path(__file__).parent / "fixtures/cdr-document-graph-2026-05-19"
    proof = json.loads((fixtures / "provenance.json").read_bytes())
    with EvidenceStore(tmp_path / "two-products") as store:
        queue = AcquisitionQueue(store)
        observations = []
        for item in proof["files"]:
            body = (fixtures / item["fixture"]).read_bytes()
            assert store.put_blob(body) == item["sha256"]
            source = json.loads(body)
            obs = store.observe(provider=source["data"]["brand"], product_key="Bank of Melbourne|" + source["data"]["productId"],
                                record=source, source_bytes=body, observed_at=NOW, ingest_id="retained-may19-scope-test")
            observations.append(obs)
            queue.enqueue(obs, ingest_id="retained-may19-scope-test", now=NOW)
        with store.db:
            store.db.execute("INSERT INTO ingest_captures VALUES (?,?,?,2)", ("retained-may19-scope-test", digest(proof), NOW))
        url = "https://" + HOST + "/content/dam/bom/downloads/personal/home-loans/Loan-Accounts.pdf"
        target = store.db.execute("SELECT document_id FROM documents WHERE source_url=?", (url,)).fetchone()[0]
        while request := queue.claim():
            chosen = request["document_id"] == target
            store.record_check(document_id=request["document_id"], check_id=request["lease_id"], checked_at=utc_now(),
                               status="fetched" if chosen else "deferred", body=b'<a href="#fees">A</a>' if chosen else None,
                               media_type="text/html", metadata={"final_url": url}, error_code=None if chosen else "isolated_disposition")
            if chosen:
                check = dict(store.db.execute("SELECT * FROM acquisition_checks WHERE check_id=?", (request["lease_id"],)).fetchone())
                root = DocumentGraph(store).seed(request, check)
            queue.finish(request, request["lease_id"], terminal=not chosen)
        graph = DocumentGraph(store)
        graph.advance_one()
        inventory = graph.inventory(root)
        assert {scope["observation_id"] for scope in inventory["scopes"]} == set(observations)
        assert len({scope["product_key"] for scope in inventory["scopes"]}) == 2
        assert all(scope["source_path"] == "/additionalInformation/feesAndPricingUri" for scope in inventory["scopes"])
        assert len(inventory["nodes"]) == 1 and len(inventory["edges"]) == 1
        assert store.db.execute("SELECT COUNT(*) FROM acquisition_requests WHERE document_id=?", (target,)).fetchone()[0] == 1


def test_stale_acquisition_lease_cannot_activate_seeded_graph(retained):
    store, _, queue = retained
    first = queue.claim(NOW, lease_seconds=1)
    check_id = "orphan-attempt"
    store.record_check(document_id=first["document_id"], check_id=check_id, checked_at=NOW, status="fetched",
                       body=b'<a href="/next">A</a>', media_type="text/html", metadata={"final_url": URL})
    check = dict(store.db.execute("SELECT * FROM acquisition_checks WHERE check_id=?", (check_id,)).fetchone())
    root = DocumentGraph(store).seed(first, check)
    recovered = queue.claim("2026-09-14T10:00:02Z")
    assert recovered["request_id"] == first["request_id"]
    with pytest.raises(ValueError, match="stale completion"):
        queue.finish(first, check_id, now="2026-09-14T10:00:03Z")
    assert root is not None and DocumentGraph(store).pending() is None
    assert store.db.execute("SELECT COUNT(*) FROM document_graph_edges").fetchone()[0] == 0


def test_image_only_html_seeds_graph_despite_unavailable_interpretation(retained, monkeypatch):
    store, _, _ = retained
    body = b'<a href="/incorporated-terms.pdf"><img src="/download.svg" alt="Terms"></a>'
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", lambda url, **kwargs: {
        "status": "fetched", "http_status": 200, "body": body, "media_type": "text/html", "metadata": {"final_url": url}})
    result = process_next_acquisition(store, registry_context={})
    assert result["result"] == "INCOMPLETE" and result["analysis_job_id"] is None
    assert store.db.execute("SELECT COUNT(*) FROM document_graph_roots").fetchone()[0] == 1
    graph = DocumentGraph(store)
    assert graph.pending()
    assert graph.advance_one()["counts"] == {"candidate_fetch_queued": 1}
    assert store.db.execute("SELECT COUNT(*) FROM analysis_jobs").fetchone()[0] == 0


@pytest.mark.parametrize("parser_failure", [None, AssertionError, ValueError],
                         ids=["native-markup", "assertion-fault", "value-fault"])
def test_malformed_child_html_is_durable_and_does_not_starve_sibling_fetch(retained, monkeypatch, parser_failure):
    # CPython 3.11.7 raises for this declaration; 3.11.16 treats it as a bogus
    # comment. Exercise that native behavior, plus both explicit error boundaries
    # independently of which parser patch release happens to run this test.
    import cdr_terms.extraction as extraction
    malformed = '<![broken]><p>Unreadable declaration</p>'
    expected_status = "partial"
    native = HTMLParser()
    try:
        native.feed(malformed)
        native.close()
    except (AssertionError, ValueError):
        expected_status = "failed"
    if parser_failure:
        expected_status = "failed"
        native_feed = extraction._HTMLText.feed
        def fail_selected_document(parser, text):
            if text == malformed:
                raise parser_failure("isolated parser failure boundary")
            return native_feed(parser, text)
        monkeypatch.setattr(extraction._HTMLText, "feed", fail_selected_document)
    store, _, queue = retained
    root, _, _ = start(retained, '<a href="/one">A</a><a href="/two">B</a>')
    graph = DocumentGraph(store)
    graph.advance_one()
    children = {row[0] for row in store.db.execute("SELECT request_id FROM document_graph_nodes WHERE root_id=? AND depth=1", (root,))}
    while (due := queue.next_due())["request_id"] not in children:
        request = queue.claim()
        store.record_check(document_id=request["document_id"], check_id=request["lease_id"], checked_at=utc_now(), status="deferred", error_code="isolated_disposition")
        queue.finish(request, request["lease_id"], terminal=True)
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        body = malformed.encode() if len(calls) == 1 else b'<p>Boundary text</p>'
        return {"status": "fetched", "http_status": 200, "body": body, "media_type": "text/html", "metadata": {"final_url": url}}
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", fetch)
    process_next_acquisition(store, registry_context={})
    assert len(calls) == 1 and graph.pending()
    node = graph.pending()
    captured = graph._check(node)
    result = process_next_acquisition(store, registry_context={})
    assert len(calls) == 2
    assert result["graph_progress"]["node_id"] == node["node_id"]
    assert result["graph_progress"]["extraction_status"] == expected_status
    expected_reason = "html_parse_failed" if expected_status == "failed" else "html_layout_dynamic_content_and_incorporated_links_unreviewed"
    assert result["graph_progress"]["extraction_reason"] == expected_reason
    assert result["graph_progress"]["legal_completeness"] == "unknown"
    expansion = store.db.execute("SELECT * FROM document_graph_expansions WHERE node_id=?", (node["node_id"],)).fetchone()
    assert expansion["check_id"] == captured["check_id"]
    extracted = store.db.execute("SELECT * FROM extractions WHERE extraction_id=?", (expansion["extraction_id"],)).fetchone()
    assert extracted["document_version_id"] == captured["document_version_id"]
    assert extracted["status"] == expected_status
    assert store.read_blob(extracted["text_sha256"]).decode().strip() == ("" if expected_status == "failed" else "Unreadable declaration")
    original_sha = store.db.execute("SELECT content_sha256 FROM document_versions WHERE document_version_id=?", (captured["document_version_id"],)).fetchone()[0]
    assert store.read_blob(original_sha) == malformed.encode()
    assert graph.pending()["node_id"] != node["node_id"]
    process_next_acquisition(store, registry_context={})
    assert process_next_acquisition(store, registry_context={})["result"] == "NO_WORK"
    assert len(calls) == 2 and graph.pending() is None


def test_corrupt_retained_blob_has_durable_terminal_graph_disposition(retained):
    store, _, _ = retained
    root, _, check = start(retained, '<a href="/next">A</a>')
    sha = store.db.execute("SELECT content_sha256 FROM document_versions WHERE document_version_id=?", (check["document_version_id"],)).fetchone()[0]
    (store.blobs / sha[:2] / sha).write_bytes(b"isolated derived-blob corruption")
    graph = DocumentGraph(store)
    result = graph.advance_one()
    assert result["reason"] == "retained_evidence_unreadable_or_invalid"
    assert result["links_observed"] is None and graph.pending() is None
    assert graph.advance_one() is None and graph.inventory(root)["nodes"][0]["expansion"]


@pytest.mark.parametrize("new_time", ["2026-09-07T00:00:00Z", NOW])
def test_unfinished_capture_cannot_supersede_completed_source_even_at_equal_time(retained, new_time):
    store, observation, queue = retained
    request = queue.next_due()
    body = FIXTURE.read_bytes()
    newer = store.observe(provider="Bank of Melbourne", product_key="Bank of Melbourne|BOMHLBasic", record=json.loads(body),
                          source_bytes=body + b"\n", observed_at=new_time, ingest_id="unfinished-capture")
    queue.enqueue(newer, ingest_id="unfinished-capture", now=NOW)
    assert current_observations(store, request["request_id"]) == [observation]
    assert queue.next_due()["request_id"] == request["request_id"]
    with store.db:
        store.db.execute("INSERT INTO ingest_captures VALUES (?,?,?,1)", ("unfinished-capture", digest("completed-fixture"), NOW))
    assert current_observations(store, request["request_id"]) == []
    # Equal-time distinct completed capture identities remain ambiguous; none is
    # arbitrarily selected. A strictly newer completed source becomes eligible.
    fresh = store.db.execute("SELECT request_id FROM acquisition_bindings WHERE observation_id=? ORDER BY request_id LIMIT 1", (newer,)).fetchone()[0]
    assert current_observations(store, fresh) == ([] if new_time.startswith("2026-09-07") else [newer])


def test_reviewed_exact_host_requires_matching_retained_receipt(retained):
    store, _, _ = retained
    host = "reviewed.example"
    proof = store.put_blob(json.dumps({"schema_version": 1, "kind": "official_document_host_grant", "host": host,
                                      "decision": "approved", "reviewer": "isolated protocol reviewer", "reviewed_at": NOW}).encode())
    root, _, _ = start(retained, '<a href="https://reviewed.example/terms">A</a><a href="https://sub.reviewed.example/terms">B</a>',
                        policy=GraphPolicy(reviewed_hosts={host: proof}))
    graph = DocumentGraph(store)
    assert graph.advance_one()["counts"] == {"candidate_fetch_queued": 1, "host_not_authorized": 1}
    assert json.loads(graph.inventory(root)["root"]["policy_json"])["host_grants"][host] == [{"review_evidence_sha256": proof}]
    bad = store.put_blob(b'{"schema_version":true}')
    with pytest.raises(ValueError, match="matching explicit"):
        graph._grants([], GraphPolicy(reviewed_hosts={host: bad}))


class Response:
    def __init__(self, status, headers=None, body=b"captured text"):
        self.status, self.headers, self.body = status, headers or {}, body
    def getheader(self, name, default=None):
        return self.headers.get(name, default)
    def read(self, limit):
        value, self.body = self.body[:limit], self.body[limit:]
        return value


class Connection:
    def __init__(self, response, requests):
        self.response, self.requests, self.sock = response, requests, self
    def request(self, method, target, headers):
        self.requests.append((target, headers))
    def getresponse(self):
        return self.response
    def settimeout(self, timeout):
        pass
    def shutdown(self, how):
        pass
    def close(self):
        pass


def test_conditional_validators_bind_exact_final_url_not_merely_host(monkeypatch):
    from cdr_terms.acquisition import FetchFailure
    requests = []
    responses = iter([Response(302, {"Location": "/changed"}), Response(304)])
    monkeypatch.setattr("cdr_terms.acquisition._connection", lambda *a: Connection(next(responses), requests))
    with pytest.raises(FetchFailure, match="unbound_not_modified"):
        fetch_document("https://" + HOST + "/start", policy=FetchPolicy(), conditional={"If-None-Match": '"old"'}, conditional_url="https://" + HOST + "/prior")
    assert all("If-None-Match" not in headers for _, headers in requests)


def test_redirect_to_retained_exact_entity_sends_validator_only_there(monkeypatch):
    requests = []
    responses = iter([Response(302, {"Location": "/retained"}), Response(304)])
    monkeypatch.setattr("cdr_terms.acquisition._connection", lambda *a: Connection(next(responses), requests))
    result = fetch_document("https://" + HOST + "/start", policy=FetchPolicy(), conditional={"If-None-Match": '"old"'}, conditional_url="https://" + HOST + "/retained")
    assert result["status"] == "unchanged"
    assert "If-None-Match" not in requests[0][1] and requests[1][1]["If-None-Match"] == '"old"'


def test_304_with_changed_final_url_retains_failure_not_unchanged_version(retained, monkeypatch):
    store, _, _ = retained
    _, request, check = start(retained, "retained", final_url=URL)
    sha = store.db.execute("SELECT content_sha256 FROM document_versions WHERE document_version_id=?", (check["document_version_id"],)).fetchone()[0]
    store.record_check(document_id=request["document_id"], check_id="validator-bound", checked_at=utc_now(), status="fetched", body=store.read_blob(sha),
                       media_type="text/html", metadata={"final_url": URL, "etag": '"old"'})
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", lambda *a, **k: {"status": "unchanged", "http_status": 304, "metadata": {"final_url": "https://" + HOST + "/changed"}})
    result = acquire_document(store, request["document_id"], check_id="changed-304")
    assert result["status"] == "failed" and result["error_code"] == "unbound_not_modified"
    assert result["document_version_id"] is None
    assert store.last_success(request["document_id"])["document_version_id"] == check["document_version_id"]
