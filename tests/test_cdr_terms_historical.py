"""Historical staging pins real retained evidence and never publishes terms."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cdr_terms.extraction import extract_version
from cdr_terms.historical import historical_scope
from cdr_terms.identity import digest
from cdr_terms.ingest import registry_context
from cdr_terms.queue import TermsQueue
from cdr_terms.reporting import build_product_asset, publish_product_asset
from cdr_terms.revisions import stage_term
from cdr_terms.store import EvidenceStore

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/cdr-canary-2026-09-07/Bank of Melbourne-null-detail.json"
OBSERVED = "2026-09-07T00:00:00Z"
NOW = "2026-09-14T01:00:00Z"


@pytest.fixture
def historical(tmp_path):
    body = FIXTURE.read_bytes()
    source = json.loads(body)
    key = "Bank of Melbourne|" + source["data"]["productId"]
    with EvidenceStore(tmp_path / "archive") as store:
        observation = store.observe(provider=source["data"]["brand"], product_key=key, record=source,
                                    source_bytes=body, observed_at=OBSERVED, ingest_id="retained-september7")
        document = store.db.execute("SELECT document_id FROM documents WHERE source_url=?", (source["links"]["self"],)).fetchone()[0]
        version = store.last_success(document)["document_version_id"]
        extraction = extract_version(store, version)
        queue = TermsQueue(store)
        job = queue.enqueue_historical(extraction, [observation], registry_context=registry_context(), now=NOW)
        context = queue.validate_input(job)
        output = {"schema_version": 1, "extraction_id": extraction, "context_sha256": digest(context),
                  "historical_scope": historical_scope(context["historical_target"]),
                  "clauses": [], "terms": [], "unresolved": ["Retained source does not establish complete legal applicability"]}
        yield store, queue, job, output, context, observation, key, document, body


def test_historical_target_pins_observed_evidence_without_inferred_effective_dates(historical):
    store, queue, job, output, context, observation, _, _, body = historical
    target = context["historical_target"]
    assert target["scope"] == output["historical_scope"]["scope"] == "historical_only"
    assert target["observations"][0]["observation_id"] == observation
    assert target["observations"][0]["observation_date_utc"] == "2026-09-07"
    assert target["document_observed_at"] == "2026-09-07T00:00:00.000000Z"
    assert store.read_blob(target["document_content_sha256"]) == body
    assert not any("effective" in key for key in target)
    assert queue.enqueue_historical(output["extraction_id"], [observation], registry_context=registry_context(), now=NOW) == job


def test_historical_pin_survives_url_source_advance_while_current_job_is_superseded(historical):
    store, queue, job, output, context, _, key, document, body = historical
    current_context = {k: v for k, v in context.items() if k != "historical_target"}
    current = queue.enqueue(output["extraction_id"], current_context, priority=0, now=NOW)
    store.record_check(document_id=document, check_id="subsequent-source", checked_at=NOW,
                       status="fetched", body=body + b"\n", media_type="application/json")
    claim = queue.claim(NOW)
    assert claim["job_id"] == job
    assert store.db.execute("SELECT status FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1", (current,)).fetchone()[0] == "superseded"
    result = queue.save_staging(job, output, lease_id=claim["lease_id"], now="2026-09-14T01:00:01Z")
    assert json.loads(store.read_blob(result))["historical_scope"] == output["historical_scope"]
    assert build_product_asset(store, key)["revisions"] == []
    for table in ("term_revisions", "reviews", "publications"):
        assert store.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0


def test_importing_an_older_snapshot_does_not_roll_back_current_source_or_coverage(historical):
    store, queue, job, output, _, _, key, document, body = historical
    source = json.loads(body)
    current_observation = store.observe(provider=source["data"]["brand"], product_key=key, record=source,
                                        source_bytes=body + b"\n", observed_at=NOW, ingest_id="new-observation")
    current_version = store.last_success(document)["document_version_id"]
    store.observe(provider=source["data"]["brand"], product_key=key, record=source,
                  source_bytes=body, observed_at=OBSERVED, ingest_id="reimport-retained-september7")
    store.record_check(document_id=document, check_id="retained-old-failure", checked_at="2026-09-08T00:00:00Z",
                       status="failed", error_code="historical-network-failure")
    assert store.last_success(document)["document_version_id"] == current_version
    payload = build_product_asset(store, key)
    assert {item["document_version_id"] for item in payload["documents"]} == {current_version}
    assert not any("historical-network-failure" in gap for gap in payload["coverage"]["gaps"])
    claim = queue.claim(NOW)
    assert claim["job_id"] == job
    queue.save_staging(job, output, lease_id=claim["lease_id"], now="2026-09-14T01:00:01Z")
    publish_product_asset(store, payload, expected_previous_identity=None,
                          expected_observation_id=current_observation, published_at=NOW)


@pytest.mark.parametrize("field", ["document_content_sha256", "extraction_text_sha256", "document_observed_at", "target_sha256"])
def test_tampered_historical_pin_is_refused_even_with_recomputed_target_hash(historical, field):
    _, queue, _, output, context, _, _, _, _ = historical
    altered = copy.deepcopy(context)
    altered["historical_target"][field] = "0" * 64
    if field != "target_sha256":
        altered["historical_target"]["target_sha256"] = digest({k: v for k, v in altered["historical_target"].items() if k != "target_sha256"})
    with pytest.raises(ValueError, match="immutable evidence pin"):
        queue.enqueue(output["extraction_id"], altered, priority=2, now=NOW)


def test_historical_pin_rejects_boolean_schema_version_even_though_python_equals_one(historical):
    _, queue, _, output, context, _, _, _, _ = historical
    altered = copy.deepcopy(context)
    altered["historical_target"]["schema_version"] = True
    with pytest.raises(ValueError, match="immutable evidence pin"):
        queue.enqueue(output["extraction_id"], altered, priority=2, now=NOW)


@pytest.mark.parametrize("observed, expected_utc", [
    ("2026-09-14T01:00:00+10:00", "2026-09-13"),
    ("2026-10-04T03:00:00+11:00", "2026-10-03"),
])
def test_historical_date_explicitly_names_utc_across_hobart_midnight_and_dst(historical, observed, expected_utc):
    store, queue, _, output, _, _, key, _, body = historical
    source = json.loads(body)
    observation = store.observe(provider=source["data"]["brand"], product_key=key, record=source,
                                source_bytes=body, observed_at=observed, ingest_id="clock-boundary-" + expected_utc)
    job = queue.enqueue_historical(output["extraction_id"], [observation], registry_context=registry_context(), now=NOW)
    target = queue.validate_input(job)["historical_target"]
    assert target["observations"][0]["observation_date_utc"] == expected_utc
    assert historical_scope(target)["observation_dates_utc"] == [expected_utc]
    assert "observation_date" not in target["observations"][0]


def test_historical_snapshot_cannot_pin_a_different_raw_response_from_the_same_url(historical):
    store, queue, _, _, _, observation, _, document, body = historical
    version = store.record_check(document_id=document, check_id="new-format", checked_at=NOW,
                                 status="fetched", body=body + b"\n", media_type="application/json")
    newer = extract_version(store, version)
    with pytest.raises(ValueError, match="differs from the pinned raw snapshot"):
        queue.enqueue_historical(newer, [observation], registry_context=registry_context(), now=NOW)


def test_historical_lease_recovery_rejects_old_worker_result(historical):
    _, queue, job, output, _, _, _, _, _ = historical
    old = queue.claim(NOW, lease_seconds=10)
    current = queue.claim("2026-09-14T01:00:11Z")
    assert current["job_id"] == old["job_id"] == job and current["lease_id"] != old["lease_id"]
    with pytest.raises(ValueError, match="stale output"):
        queue.save_staging(job, output, lease_id=old["lease_id"], now="2026-09-14T01:00:12Z")
    queue.save_staging(job, output, lease_id=current["lease_id"], now="2026-09-14T01:00:12Z")


def test_historical_output_must_preserve_scope_and_cannot_gain_current_priority(historical):
    _, queue, job, output, context, _, _, _, _ = historical
    for altered in ({k: v for k, v in output.items() if k != "historical_scope"},
                    {**output, "historical_scope": {**output["historical_scope"], "target_sha256": "0" * 64}}):
        with pytest.raises(ValueError, match="historical-only target scope"):
            queue.validate_staging(job, altered)
    with pytest.raises(ValueError, match="cannot become current"):
        queue.enqueue(output["extraction_id"], context, priority=0, now=NOW)
    current_context = {k: v for k, v in context.items() if k != "historical_target"}
    current = queue.enqueue(output["extraction_id"], current_context, priority=0, now=NOW)
    with pytest.raises(ValueError, match="Current output"):
        queue.validate_staging(current, {**output, "context_sha256": digest(current_context)})


def test_historical_output_and_receipt_cannot_enter_current_publication(historical):
    store, queue, job, output, _, observation, key, _, _ = historical
    claim = queue.claim(NOW)
    result = queue.save_staging(job, output, lease_id=claim["lease_id"], now="2026-09-14T01:00:01Z")
    public = build_product_asset(store, key)
    for payload in (json.loads(store.read_blob(result)), {**public, "historical_scope": output["historical_scope"]}):
        with pytest.raises(ValueError, match="Historical-only staging"):
            publish_product_asset(store, payload, expected_previous_identity=None,
                                  expected_observation_id=observation, published_at=NOW)
    assert store.db.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 0
    clause = store.add_clause(output["extraction_id"], start=0, end=1)
    with pytest.raises(ValueError, match="Historical-only staging"):
        stage_term(store, observation_id=observation, parameter_key="source.character", value="{", unit=None,
                   applicability={"product_key": key, **dict.fromkeys(("tier", "package", "cohort", "effective_from", "effective_to"))},
                   clause_ids=[clause], interpreter="historical-protocol-test", context_sha256=output["context_sha256"], observed_at=NOW)
    assert store.db.execute("SELECT COUNT(*) FROM term_revisions").fetchone()[0] == 0


def test_tampered_historical_source_blob_blocks_claim_without_model_work(historical):
    store, queue, job, _, context, _, _, _, _ = historical
    sha = context["historical_target"]["document_content_sha256"]
    (store.blobs / sha[:2] / sha).write_bytes(b"deliberate archive integrity fault")
    assert queue.claim(NOW) is None
    latest = store.db.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1", (job,)).fetchone()
    assert latest["status"] == "blocked" and latest["error_code"] == "source_integrity_invalid"
