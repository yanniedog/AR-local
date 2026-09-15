"""Evidence protocol regressions using the retained real September CDR corpus.

Network failures, clocks and schema-boundary values are injected at the helper
boundary; none of these fixtures constitutes a live product acceptance claim.
"""
from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from cdr_terms.ingest import registry_context

from app_payload_details import _detail_items, build_details
from cdr_clean_export import detail_json
from cdr_terms.acquisition import FetchFailure, FetchPolicy, _public_address, acquire_document, acquire_observation
from cdr_terms.discovery import discover_references, document_url
from cdr_terms.extraction import extract_document, extract_version
from cdr_terms.identity import byte_digest, canonical_json, digest, exact_value, timestamp
from cdr_terms.observation_checks import bind_manual_check
from cdr_terms.queue import TermsQueue
from cdr_terms.reporting import build_product_asset, publish_product_asset, validate_public_asset
from cdr_terms.revisions import REVIEW_CHECKS, record_change, review_term, stage_term
from cdr_terms.store import EvidenceStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/cdr-canary-2026-09-07/Bank of Melbourne-null-detail.json"
OBSERVED = "2026-09-07T00:00:00Z"
NOW = "2026-09-14T01:00:00Z"
LATER = "2026-09-14T01:20:00Z"


@pytest.fixture
def evidence(tmp_path):
    body = FIXTURE.read_bytes()
    source = json.loads(body)
    record = source["data"]
    product_key = "Bank of Melbourne|" + record["productId"]
    with EvidenceStore(tmp_path / "evidence") as store:
        observation = store.observe(provider=record["brand"], product_key=product_key,
                                    record=source, source_bytes=body, observed_at=OBSERVED, ingest_id="retained-september7")
        doc = store.db.execute("SELECT document_id FROM documents WHERE source_url=?", (source["links"]["self"],)).fetchone()[0]
        version = store.last_success(doc)["document_version_id"]
        yield store, observation, product_key, doc, version, body, record


def _clause(evidence):
    store, _, _, _, version, _, record = evidence
    extraction = extract_version(store, version)
    text_sha = store.db.execute("SELECT text_sha256 FROM extractions WHERE extraction_id=?", (extraction,)).fetchone()[0]
    text = store.read_blob(text_sha).decode("utf-8")
    start = text.index(record["name"])
    clause = store.add_clause(extraction, start=start, end=start + len(record["name"]), section="name")
    return extraction, clause


def _term(evidence, *, reviewed=True):
    store = evidence[0]
    _, _, _, arguments = _staged_term(evidence)
    term = stage_term(store, **arguments)
    if reviewed:
        proof = store.put_blob(canonical_json({"term_revision_id": term, "passed": True,
                                               "checks": sorted(REVIEW_CHECKS)}).encode())
        review_term(store, term, status="validated", reviewer="independent-test-review", reviewer_kind="human",
                    reviewed_at=NOW, evidence_sha256=proof, reason="Exact retained CDR product name and source span agree")
    return term


def _staged_term(evidence, *, context_change=None, output_change=None, save=True, retained_legacy=False):
    """A human source reader uses the same retained staging contract as a worker."""
    store, observation, key, _, _, body, record = evidence
    extraction, clause = _clause(evidence)
    applicability = dict.fromkeys(("tier", "package", "cohort", "effective_from", "effective_to"))
    applicability["product_key"] = key
    context = {"product_keys": [key], "source_product_sha256": {key: byte_digest(body)},
               **registry_context(), **(context_change or {})}
    queue = TermsQueue(store)
    if retained_legacy:
        # Explicit retained-row fixture for old revision semantics. Public
        # enqueue never admits a new unregistered interpretation context.
        context.pop('parameter_registry')
        context_sha = digest(context)
        job = digest([extraction, context_sha])
        blob = store.put_blob(canonical_json(context).encode('utf-8'))
        with store.db:
            queue._insert_job(job, extraction, context_sha, blob, 1, NOW)
    else:
        job = queue.enqueue(extraction, context, now=NOW)
    locator = json.loads(store.db.execute("SELECT locator_json FROM clauses WHERE clause_id=?", (clause,)).fetchone()[0])
    output = {"schema_version": 1, "extraction_id": extraction, "context_sha256": digest(context),
              "clauses": [{"page": None, **locator, "disposition": "parameter", "reason": "Retained product name"}],
              "terms": [{"parameter_key": "product.name", "value": record["name"], "unit": None,
                         **applicability, "clause_indexes": [0], "rule_pattern": None,
                         "conditions": [], "exceptions": []}],
              "unresolved": ["Source name only; this is not complete legal interpretation"]}
    if output_change:
        output_change(output)
    if save:
        claim = queue.claim(NOW)
        assert claim["job_id"] == job
        queue.save_staging(job, output, lease_id=claim["lease_id"], now=NOW)
    arguments = dict(observation_id=observation, parameter_key="product.name", value=record["name"],
                     unit=None, applicability=applicability, clause_ids=[clause], interpreter="test-source-reader",
                     context_sha256=digest(context), observed_at=NOW)
    return queue, job, output, arguments


def _job(evidence, priority=1, **context):
    store, _, key, _, _, _, _ = evidence
    extraction, _ = _clause(evidence)
    queue = TermsQueue(store)
    job = queue.enqueue(extraction, {"product_keys": [key], **registry_context(), **context},
                        priority=priority, now=NOW)
    output = {"schema_version": 1, "extraction_id": extraction,
              "context_sha256": store.db.execute("SELECT context_sha256 FROM analysis_jobs WHERE job_id=?", (job,)).fetchone()[0],
              "clauses": [], "terms": [], "unresolved": ["Protocol test does not establish complete interpretation"]}
    return queue, job, output


def test_real_nested_reference_paths_survive_cleaning_without_eager_payload_growth(evidence):
    _, _, key, _, _, _, record = evidence
    references = discover_references(record)
    assert len(references) == 15
    assert sum(ref.sourcePath.startswith("/lendingRates/") for ref in references) == 11
    assert len({ref.url for ref in references}) < len(references)
    cleaned = json.loads(detail_json(record))
    assert cleaned["sourceDocuments"] == [ref.as_dict() for ref in references]
    assert "additionalInfoUri" not in cleaned["lendingRates"][0]
    products = [{"product_key": key, "details_json": cleaned}]
    assert "sourceDocuments" not in build_details(products)[key]
    assert build_details(products, include_source_documents=True)[key]["sourceDocuments"] == cleaned["sourceDocuments"]


def test_reference_helper_preserves_supplementary_paths_anchors_and_nested_scopes():
    # URL/path helper cases, not acceptance product data.
    record = {"additionalInformation": {"additionalTermsUris": [
        {"description": "Terms", "additionalInfoUri": "https://example.com/t#fees"}, "https://example.com/t#rates"]}}
    references = discover_references(record)
    assert len(references) == 2
    assert {ref.url for ref in references} == {"https://example.com/t"}
    assert len({ref.sourcePath for ref in references}) == 2
    assert all("#" in ref.sourceUrl for ref in references)


@pytest.mark.parametrize("value", ["file:///etc/passwd", "https://user:password@example.com/", "javascript:alert(1)", "https://x:bad/"])
def test_reject_non_document_url(value):
    assert document_url(value) is None


def test_zero_and_false_are_not_fallback_values():
    for value in (0, False, "0"):
        items = _detail_items({"constraints": [{"constraintType": "OTHER", "additionalValue": value, "amount": "fallback"}]},
                              "constraints", "constraintType")
        assert items[0]["value"] == value


def test_original_cdr_body_and_acquisition_idempotency(evidence):
    store, observation, key, doc, version, body, record = evidence
    row = store.db.execute("SELECT * FROM observations WHERE observation_id=?", (observation,)).fetchone()
    assert store.read_blob(row["source_sha256"]) == body
    assert store.observe(provider=record["brand"], product_key=key, record=json.loads(body), source_bytes=body,
                         observed_at=OBSERVED, ingest_id="retained-september7") == observation
    store.record_check(document_id=doc, check_id="recheck", checked_at=NOW, status="fetched", body=body,
                       media_type="application/json", http_status=200)
    assert store.last_success(doc)["document_version_id"] == version
    assert store.db.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 1
    assert store.db.execute("SELECT COUNT(*) FROM acquisition_checks").fetchone()[0] == 2
    with pytest.raises(ValueError, match="different evidence"):
        store.record_check(document_id=doc, check_id="recheck", checked_at=NOW, status="failed", error_code="network")


def test_no_backdated_effective_terms_from_product_effective_from(evidence):
    store, _, _, _, version, _, record = evidence
    dated = json.loads((ROOT / "tests/fixtures/cdr-september7/defence.json").read_text(encoding="utf-8"))["product_detail"]
    assert dated["body"]["data"]["effectiveFrom"]
    store.observe(provider="Defence Bank", product_key="Defence Bank|249", record=dated["body"],
                  observed_at=dated["captured_at"], ingest_id="retained-september7")
    assert store.db.execute("SELECT COUNT(*) FROM document_versions WHERE effective_from IS NOT NULL").fetchone()[0] == 0
    row = store.db.execute("SELECT * FROM document_versions WHERE document_version_id=?", (version,)).fetchone()
    assert row["effective_from"] is None and row["effective_to"] is None
    term = _term(evidence)
    scope = json.loads(store.db.execute("SELECT applicability_json FROM term_revisions WHERE term_revision_id=?", (term,)).fetchone()[0])
    assert scope["effective_from"] is None and scope["cohort"] is None


def test_append_only_and_blob_integrity(evidence):
    store, _, _, _, version, _, _ = evidence
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute("DELETE FROM document_versions WHERE document_version_id=?", (version,))
    store.db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute("UPDATE document_versions SET effective_from='2020-01-01'")
    store.db.rollback()
    sha = store.db.execute("SELECT content_sha256 FROM document_versions WHERE document_version_id=?", (version,)).fetchone()[0]
    (store.blobs / sha[:2] / sha).write_bytes(b"corruption injection")
    with pytest.raises(ValueError, match="integrity"):
        store.read_blob(sha)


def test_refuses_to_migrate_an_unrelated_database(tmp_path):
    target = tmp_path / "unrelated"
    target.mkdir()
    with sqlite3.connect(target / "evidence.sqlite3") as connection:
        connection.execute("CREATE TABLE existing_source (value TEXT)")
    with pytest.raises(ValueError, match="non-terms"):
        EvidenceStore(target)


def test_failed_fetch_preserves_prior_terms_and_does_not_infer_removal(evidence, monkeypatch):
    store, _, key, doc, version, _, _ = evidence
    term = _term(evidence)
    def fail(*args, **kwargs):
        raise FetchFailure("http_error", 404)
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", fail)
    receipt = acquire_document(store, doc, check_id="gone")
    assert receipt["status"] == "failed"
    assert store.last_success(doc)["document_version_id"] == version
    payload = build_product_asset(store, key)
    assert payload["changes"] == []
    assert payload["revisions"][0]["term_revision_id"] == term
    assert payload["coverage"]["calculation"]["status"] == "unknown"
    # An unscoped URL failure does not replace this exact raw snapshot check.
    assert not any("failed" in gap for gap in payload["coverage"]["gaps"])
    assert payload["coverage"]["acquisition"]["observed"] == 1


def test_conditional_check_requires_retained_version_and_each_ingest_rechecks(evidence, monkeypatch):
    store, _, _, doc, version, body, _ = evidence
    url = store.db.execute("SELECT source_url FROM documents WHERE document_id=?", (doc,)).fetchone()[0]
    store.record_check(document_id=doc, check_id="verified-entity", checked_at=NOW,
                       status="fetched", body=body, media_type="application/json",
                       metadata={"final_url": url, "etag": '"retained"'})
    calls = []
    def unchanged(*args, **kwargs):
        calls.append(args)
        return {"status": "unchanged", "http_status": 304, "metadata": {"final_url": url}}
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", unchanged)
    assert acquire_document(store, doc, check_id="day1")["document_version_id"] == version
    acquire_document(store, doc, check_id="day1")
    acquire_document(store, doc, check_id="day2")
    assert len(calls) == 2
    other = store.db.execute("SELECT document_id FROM documents WHERE document_id!=? LIMIT 1", (doc,)).fetchone()[0]
    assert acquire_document(store, other, check_id="no-prior")["error_code"] == "unchanged_without_retained_version"


def test_batch_fetch_is_bounded_and_skips_already_captured_cdr_response(evidence, monkeypatch):
    store, observation, _, doc, _, _, _ = evidence
    def fail(*args, **kwargs):
        raise FetchFailure("transport_error")
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", fail)
    checks = acquire_observation(store, observation, check_prefix="bounded", max_documents=1)
    assert len(checks) == 1 and checks[0]["document_id"] != doc


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_fetch_rejects_non_public_dns(monkeypatch, address):
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", (address, 443))])
    with pytest.raises(FetchFailure, match="non_public"):
        _public_address("example.com", 443)


def test_staging_and_review_are_separate_and_source_bound(evidence):
    store, _, key, _, _, _, _ = evidence
    term = _term(evidence, reviewed=False)
    assert build_product_asset(store, key)["revisions"] == []
    proof = store.put_blob(canonical_json({"term_revision_id": term, "passed": True, "checks": sorted(REVIEW_CHECKS)}).encode())
    with pytest.raises(ValueError, match="second pass"):
        review_term(store, term, status="validated", reviewer="second-model", reviewer_kind="model",
                    reviewed_at=NOW, evidence_sha256=proof, reason="Model consensus")
    with pytest.raises(ValueError, match="benchmarked"):
        review_term(store, term, status="validated", reviewer="no-pattern", reviewer_kind="deterministic",
                    reviewed_at=NOW, evidence_sha256=proof, reason="No real benchmark")


def test_public_payload_identity_unknown_coverage_and_decimal_contract(evidence):
    store, _, key, _, _, _, _ = evidence
    _term(evidence)
    payload = build_product_asset(store, key)
    assert payload["coverage"]["discovery"]["expected"] is None
    assert payload["coverage"]["interpretation"]["status"] == "partial"
    validate_public_asset(payload)
    corrupted = copy.deepcopy(payload)
    corrupted["documents"][0]["byte_size"] += 1
    with pytest.raises(ValueError, match="identity"):
        validate_public_asset(corrupted)
    for invalid in (1.1, 9007199254740992, float("nan")):
        with pytest.raises(ValueError):
            exact_value(invalid)
    for valid in ("0.00", "1.234567890123456789", 0, False):
        exact_value(valid)


def test_new_document_version_invalidates_dependent_terms_and_stale_promotion(evidence):
    store, observation, key, doc, _, body, _ = evidence
    _term(evidence)
    original = build_product_asset(store, key)
    publish_product_asset(store, original, expected_previous_identity=None,
                          expected_observation_id=observation, published_at=NOW)
    # Mechanical byte revision, no fabricated rates or terms.
    store.record_check(document_id=doc, check_id="new-bytes", checked_at=LATER, status="fetched",
                       body=body + b"\n", media_type="application/json")
    bind_manual_check(store, observation, "new-bytes")
    assert build_product_asset(store, key)["revisions"] == []
    with pytest.raises(ValueError, match="changed before publication"):
        publish_product_asset(store, original, expected_previous_identity=original["identity_sha256"],
                              expected_observation_id=observation, published_at=LATER)
    with pytest.raises(ValueError, match="stale promotion"):
        publish_product_asset(store, original, expected_previous_identity=None,
                              expected_observation_id=observation, published_at=LATER)


def test_removal_requires_reviewed_complete_replacement(evidence):
    store, _, key, _, _, _, _ = evidence
    term = _term(evidence)
    proof = store.put_blob(canonical_json({"passed": True, "kind": "removed", "before_revision_id": term,
                                          "after_revision_id": None}).encode())
    with pytest.raises(ValueError, match="cannot prove"):
        record_change(store, product_key=key, before_revision_id=term, after_revision_id=None,
                      kind="removed", observed_at=LATER, evidence_sha256=proof)


def test_queue_idempotency_priority_and_strict_staging(evidence):
    queue, historical, _ = _job(evidence, priority=2, phase="historical")
    _, current, output = _job(evidence, priority=0, phase="changed")
    _, same, _ = _job(evidence, priority=0, phase="changed")
    assert current == same and queue.next_due(NOW)["job_id"] == current
    claimed = queue.claim(NOW)
    with pytest.raises(ValueError, match="input generation"):
        queue.validate_staging(current, {**output, "context_sha256": "0" * 64})
    queue.save_staging(current, output, lease_id=claimed["lease_id"], now="2026-09-14T01:00:01Z")
    assert queue.next_due(NOW)["job_id"] == historical
    assert evidence[0].db.execute("SELECT COUNT(*) FROM term_revisions").fetchone()[0] == 0


def test_existing_historical_job_can_gain_current_priority_without_duplicate_inference(evidence):
    queue, original, _ = _job(evidence, priority=2)
    _, promoted, _ = _job(evidence, priority=0)
    assert promoted == original
    assert queue.next_due(NOW)["priority"] == 0
    assert evidence[0].db.execute("SELECT COUNT(*) FROM analysis_jobs").fetchone()[0] == 1


def test_expired_lease_is_recovered_and_stale_worker_cannot_complete(evidence):
    queue, job, output = _job(evidence)
    original = queue.claim(NOW, lease_seconds=10)
    assert queue.claim("2026-09-14T01:00:05Z") is None
    recovered = queue.claim("2026-09-14T01:00:11Z")
    assert recovered["job_id"] == job and recovered["lease_id"] != original["lease_id"]
    with pytest.raises(ValueError, match="stale output"):
        queue.save_staging(job, output, lease_id=original["lease_id"], now="2026-09-14T01:00:12Z")
    queue.save_staging(job, output, lease_id=recovered["lease_id"], now="2026-09-14T01:00:12Z")
    events = [row[0] for row in evidence[0].db.execute("SELECT status FROM job_events WHERE job_id=? ORDER BY sequence", (job,))]
    assert events == ["queued", "running", "retry_wait", "running", "staged"]


def test_changed_source_rejects_running_staging_result(evidence):
    queue, job, output = _job(evidence)
    claimed = queue.claim(NOW)
    store, _, _, doc, _, body, _ = evidence
    store.record_check(document_id=doc, check_id="changed-during-work", checked_at=NOW,
                       status="fetched", body=body + b"\n", media_type="application/json")
    with pytest.raises(ValueError, match="changed while"):
        queue.save_staging(job, output, lease_id=claimed["lease_id"], now="2026-09-14T01:00:01Z")
    assert store.db.execute("SELECT status FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1", (job,)).fetchone()[0] == "superseded"


def test_staging_clauses_cannot_escape_source_text(evidence):
    queue, job, output = _job(evidence)
    output["clauses"] = [{"start": 0, "end": len(evidence[5]) + 100000, "page": None, "section": None,
                           "disposition": "unresolved", "reason": "Boundary injection"}]
    with pytest.raises(ValueError, match="outside"):
        queue.validate_staging(job, output)


def test_text_extraction_does_not_claim_pdf_layout_or_html_completeness():
    text, status, coverage = extract_document(b"<table><tr><td>one</td><td>two</td></tr></table>", "text/html", "https://example.com/")
    assert "\tone\ttwo" in text and status == "partial"
    assert "layout" in coverage["reason"]
    _, status, coverage = extract_document(b"%PDF-invalid", "application/pdf", "https://example.com/")
    assert status == "failed"


def test_utc_timestamps_have_stable_lexical_order():
    first = timestamp("2026-09-14T11:00:00+10:00")
    later = timestamp("2026-09-14T01:00:00.1Z")
    assert first == "2026-09-14T01:00:00.000000Z" and first < later
