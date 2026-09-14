"""Observation/import clocks and freshness use retained real CDR source bytes."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from tests.cdr_terms_source_fixture import source_generation
from cdr_terms import __main__ as cli
from cdr_terms.acquisitions_queue import AcquisitionQueue
from cdr_terms.acquisition import acquire_observation
from cdr_terms.identity import byte_digest, canonical_json, digest, timestamp
from cdr_terms.ingest import capture_if_configured
from cdr_terms.reporting import build_product_asset, current_observation
from cdr_terms.store import EvidenceStore
from cdr_terms.queue import TermsQueue
from cdr_terms.revisions import REVIEW_CHECKS, review_term, stage_term

FIXTURE = Path(__file__).parent / "fixtures/cdr-canary-2026-09-07/Bank of Melbourne-null-detail.json"
KEY = "Bank of Melbourne|BOMHLBasic"
PUBLIC = json.loads((Path(__file__).parent / "fixtures/product-terms-provenance/public-2026-09-14-manifest.json").read_bytes())
CURRENT = PUBLIC["generated_at"]  # retained Sep14 public generation: 01:16 Hobart
OLDER = "2026-09-06T15:10:00Z"
IMPORTED = "2026-09-20T02:00:00Z"


def capture(run, state, finalized):
    return capture_if_configured(run, finalized, state_dir=state, runs_root=run.parent, export_root=run / "_exports")


def complete(store, observation, date):
    row = store.db.execute("SELECT ingest_id FROM observations WHERE observation_id=?", (observation,)).fetchone()
    with store.db:
        store.db.execute("INSERT INTO ingest_captures VALUES (?,?,?,1)", (row[0], digest([observation]), timestamp(date)))


def test_capture_uses_bound_hobart_generation_time_not_import_clock(tmp_path, monkeypatch):
    root = tmp_path / "derived"
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(root))
    monkeypatch.setattr("cdr_terms.ingest.utc_now", lambda: IMPORTED)
    run, state, finalized = source_generation(tmp_path, "2026-09-14", CURRENT)
    result = capture(run, state, finalized)
    assert result["status"] == "CAPTURED_AND_QUEUED"
    assert result["observed_at"] == timestamp(CURRENT)
    assert result["source_run_date"] == PUBLIC["run_date"] == PUBLIC["source_observation"]["observation_date"]
    assert result["captured_at"] == timestamp(IMPORTED)


def test_older_capture_imported_last_does_not_replace_current_product(tmp_path, monkeypatch):
    root = tmp_path / "derived"
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(root))
    monkeypatch.setattr("cdr_terms.ingest.utc_now", lambda: IMPORTED)
    current = capture(*source_generation(tmp_path, "2026-09-14", CURRENT))
    monkeypatch.setattr("cdr_terms.ingest.utc_now", lambda: "2026-09-21T02:00:00Z")
    older = capture(*source_generation(tmp_path, "2026-09-07", OLDER))
    receipt = json.loads(Path(current["receipt_path"]).read_bytes())
    with EvidenceStore(root) as store:
        assert current_observation(store, receipt["sources"][0]["product_key"])["observation_id"] == receipt["sources"][0]["observation_id"]
    assert older["observed_at"] == timestamp(OLDER)


def test_backfill_contract_creation_time_cannot_impersonate_old_observation(tmp_path, monkeypatch):
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(tmp_path / "derived"))
    run, state, finalized = source_generation(tmp_path, "2026-09-07", IMPORTED)
    result = capture(run, state, finalized)
    assert result["status"] == "CAPTURE_FAILED" and result["raw_stage_preserved"]
    assert "source_observation" in result["reason"]


def test_new_observation_does_not_inherit_prior_ingest_acquisition_success(tmp_path):
    body = FIXTURE.read_bytes()
    with EvidenceStore(tmp_path / "derived") as store:
        previous = store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body, observed_at=OLDER, ingest_id="previous")
        queue = AcquisitionQueue(store)
        queue.enqueue(previous, ingest_id="previous", now=OLDER)
        complete(store, previous, OLDER)
        while request := queue.claim(CURRENT):
            store.record_check(document_id=request["document_id"], check_id=request["lease_id"], checked_at=CURRENT, status="fetched", body=body, media_type="application/json")
            queue.finish(request, request["lease_id"], now=CURRENT)
        current = store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body, observed_at=CURRENT, ingest_id="current")
        queue.enqueue(current, ingest_id="current", now=CURRENT)
        complete(store, current, CURRENT)
        payload = build_product_asset(store, KEY)
        assert payload["coverage"]["acquisition"] == {"status": "partial", "expected": 4, "observed": 1}
        assert len(payload["documents"]) == 1  # exact retained raw CDR capture only
        assert all(item["source_url"] == json.loads(body)["links"]["self"] for item in payload["documents"])


def test_archive_requires_explicit_evidence_time_before_opening_store(tmp_path):
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--store", str(tmp_path / "unused"), "archive", "--input", str(FIXTURE),
                                 "--document-id", digest("doc"), "--media-type", "application/json", "--check-id", "retained"])
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("date,instant", [("2026-10-04", "2026-10-03T16:30:00Z"),
                                         ("2026-04-05", "2026-04-04T16:30:00Z")])
def test_source_calendar_handles_hobart_dst_without_redating_utc(tmp_path, monkeypatch, date, instant):
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(tmp_path / "derived"))
    monkeypatch.setattr("cdr_terms.ingest.utc_now", lambda: "2026-11-01T00:00:00Z")
    result = capture(*source_generation(tmp_path, date, instant))
    assert result["status"] == "CAPTURED_AND_QUEUED"
    assert result["source_run_date"] == date and result["observed_at"] == timestamp(instant)
    assert result["source_provenance"]["timezone"] == "Australia/Hobart"


@pytest.mark.parametrize("mutation", ["missing", "escape", "digest", "generation"])
def test_configured_capture_requires_exact_bound_contract(tmp_path, monkeypatch, mutation):
    root = tmp_path / "derived"
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(root))
    run, state, finalized = source_generation(tmp_path, "2026-09-14", CURRENT)
    raw = next((run / "banks").rglob("product-detail.json"))
    before = raw.read_bytes(), raw.stat().st_mtime_ns
    if mutation == "missing":
        finalized.pop("export_contract_path")
    elif mutation == "escape":
        finalized["export_contract_path"] = "../unrelated.json"
    elif mutation == "digest":
        finalized["export_contract_digest"] = digest("mismatched")
    else:
        finalized["generation_id"] += "-different"
    result = capture(run, state, finalized)
    assert result["status"] == "CAPTURE_FAILED" and result["raw_stage_preserved"]
    assert (raw.read_bytes(), raw.stat().st_mtime_ns) == before
    assert not root.exists()


def test_failed_partial_capture_never_supersedes_completed_source_and_retry_keeps_clock(tmp_path, monkeypatch):
    root = tmp_path / "derived"
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(root))
    monkeypatch.setattr("cdr_terms.ingest.utc_now", lambda: IMPORTED)
    old = capture(*source_generation(tmp_path, "2026-09-07", OLDER))
    old_source = json.loads(Path(old["receipt_path"]).read_bytes())["sources"][0]
    run, state, finalized = source_generation(tmp_path, "2026-09-14", CURRENT)
    failed = capture(run, state, {**finalized, "banks": {"products": 2}})
    assert failed["status"] == "CAPTURE_FAILED"
    with EvidenceStore(root) as store:
        assert store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
        assert current_observation(store, old_source["product_key"])["observation_id"] == old_source["observation_id"]
    monkeypatch.setattr("cdr_terms.ingest.utc_now", lambda: "2026-09-21T02:00:00Z")
    retried = capture(run, state, finalized)
    assert retried["status"] == "CAPTURED_AND_QUEUED" and retried["captured_at"] == timestamp(IMPORTED)
    assert capture(run, state, finalized) == retried
    with EvidenceStore(root) as store:
        assert current_observation(store, old_source["product_key"])["observed_at"] == timestamp(CURRENT)
        assert store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.db.execute("UPDATE ingest_capture_attempts SET captured_at='redated'")
        store.db.rollback()


def test_crash_after_raw_observation_before_queue_is_not_standalone_inventory(tmp_path, monkeypatch):
    root = tmp_path / "derived"
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(root))
    def crash(*args, **kwargs):
        raise RuntimeError("injected crash before acquisition queue insertion")
    monkeypatch.setattr(AcquisitionQueue, "enqueue", crash)
    result = capture(*source_generation(tmp_path, "2026-09-14", CURRENT))
    assert result["status"] == "CAPTURE_FAILED"
    with EvidenceStore(root) as store:
        key = store.db.execute("SELECT product_key FROM observations").fetchone()[0]
        assert store.db.execute("SELECT COUNT(*) FROM acquisition_requests").fetchone()[0] == 0
        with pytest.raises(ValueError, match="no retained source inventory"):
            current_observation(store, key)


def test_completed_same_time_sources_are_ambiguous(tmp_path):
    body = FIXTURE.read_bytes()
    with EvidenceStore(tmp_path / "derived") as store:
        for ingest in ("a", "b"):
            obs = store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body,
                                observed_at=CURRENT, ingest_id=ingest)
            complete(store, obs, CURRENT)
        with pytest.raises(ValueError, match="ambiguous"):
            build_product_asset(store, KEY)


def test_manual_fetch_bindings_do_not_leak_across_observations(tmp_path, monkeypatch):
    body = FIXTURE.read_bytes()
    calls = []
    def fetched(*args, **kwargs):
        calls.append(args)
        return {"status": "fetched", "body": body, "media_type": "application/json"}
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", fetched)
    monkeypatch.setattr("cdr_terms.acquisition.utc_now", lambda: IMPORTED)
    with EvidenceStore(tmp_path / "derived") as store:
        old = store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body,
                            observed_at=OLDER, ingest_id="old")
        first = acquire_observation(store, old, check_prefix="same-prefix", max_documents=1)
        assert build_product_asset(store, KEY)["coverage"]["acquisition"]["observed"] == 2
        current = store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body,
                                observed_at=CURRENT, ingest_id="current")
        assert build_product_asset(store, KEY)["coverage"]["acquisition"]["observed"] == 1
        second = acquire_observation(store, current, check_prefix="same-prefix", max_documents=1)
        assert second[0]["check_id"] != first[0]["check_id"] and len(calls) == 2
        assert build_product_asset(store, KEY)["coverage"]["acquisition"]["observed"] == 2
        assert acquire_observation(store, current, check_prefix="same-prefix", max_documents=1) == second
        assert len(calls) == 2
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.db.execute("DELETE FROM observation_acquisitions")


def test_lease_orphan_cannot_satisfy_coverage_but_accepted_extraction_failure_can(tmp_path):
    body = FIXTURE.read_bytes()
    with EvidenceStore(tmp_path / "derived") as store:
        obs = store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body,
                            observed_at=OLDER, ingest_id="leased")
        queue = AcquisitionQueue(store)
        queue.enqueue(obs, ingest_id="leased", now=OLDER)
        complete(store, obs, OLDER)
        old = queue.claim("2026-09-14T00:00:00Z", lease_seconds=1)
        store.record_check(document_id=old["document_id"], check_id="orphan", checked_at="2026-09-14T00:00:00Z",
                           status="fetched", body=body, media_type="application/json")
        new = queue.claim("2026-09-14T00:00:02Z")
        with pytest.raises(ValueError, match="stale completion"):
            queue.finish(old, "orphan", now="2026-09-14T00:00:03Z")
        with pytest.raises(ValueError, match="within its accepted lease"):
            queue.finish(new, "orphan", now="2026-09-14T00:00:03Z")
        assert build_product_asset(store, KEY)["coverage"]["acquisition"]["observed"] == 1
        store.record_check(document_id=new["document_id"], check_id="accepted", checked_at="2026-09-14T00:00:03Z",
                           status="fetched", body=body, media_type="application/json")
        queue.finish(new, "accepted", now="2026-09-14T00:00:03Z", processing_error="unsupported_extractor")
        payload = build_product_asset(store, KEY)
        assert payload["coverage"]["acquisition"]["observed"] == 2
        assert payload["coverage"]["calculation"]["status"] == "unknown"
        assert store.db.execute("SELECT COUNT(*) FROM term_revisions").fetchone()[0] == 0


def test_archive_import_preserves_old_evidence_clock_and_idempotent_import_receipt(tmp_path, monkeypatch, capsys):
    body = FIXTURE.read_bytes()
    root = tmp_path / "derived"
    with EvidenceStore(root) as store:
        store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body + b"\n",
                      observed_at=CURRENT, ingest_id="current")
        document = store.db.execute("SELECT document_id FROM documents WHERE source_url=?", (json.loads(body)["links"]["self"],)).fetchone()[0]
        current_version = store.last_success(document)["document_version_id"]
    monkeypatch.setattr(sys, "argv", ["cdr_terms", "--store", str(root), "archive", "--input", str(FIXTURE),
        "--document-id", document, "--check-id", "retained", "--media-type", "application/json", "--observed-at", OLDER])
    monkeypatch.setattr("cdr_terms.__main__.utc_now", lambda: IMPORTED)
    assert cli.main() == 0
    monkeypatch.setattr("cdr_terms.__main__.utc_now", lambda: "2026-09-21T02:00:00Z")
    assert cli.main() == 0
    capsys.readouterr()
    with EvidenceStore(root) as store:
        check = store.db.execute("SELECT * FROM acquisition_checks WHERE check_id='retained'").fetchone()
        assert check["checked_at"] == timestamp(OLDER)
        assert json.loads(check["metadata_json"])["imported_at"] == timestamp(IMPORTED)
        assert store.last_success(document)["document_version_id"] == current_version
        assert build_product_asset(store, KEY)["coverage"]["acquisition"]["observed"] == 1
        assert store.db.execute("SELECT COUNT(*) FROM observation_acquisitions").fetchone()[0] == 0


def test_selected_failed_check_cannot_fall_back_to_other_observation_success(tmp_path, monkeypatch):
    body = FIXTURE.read_bytes()
    monkeypatch.setattr("cdr_terms.acquisition.utc_now", lambda: IMPORTED)
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", lambda *args, **kwargs:
                        {"status": "fetched", "body": body, "media_type": "application/json"})
    with EvidenceStore(tmp_path / "derived") as store:
        old = store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body,
                            observed_at=OLDER, ingest_id="old")
        acquired = acquire_observation(store, old, check_prefix="success", max_documents=1)[0]
        current = store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body,
                                observed_at=CURRENT, ingest_id="current")
        from cdr_terms.acquisition import FetchFailure
        def failed(*args, **kwargs):
            raise FetchFailure("http_error", 503)
        monkeypatch.setattr("cdr_terms.acquisition.fetch_document", failed)
        acquire_observation(store, current, check_prefix="failure", max_documents=1)
        payload = build_product_asset(store, KEY)
        assert payload["coverage"]["acquisition"] == {"status": "partial", "expected": 4, "observed": 1}
        assert any("http_error" in gap for gap in payload["coverage"]["gaps"])
        assert all(item["document_version_id"] != acquired["document_version_id"] for item in payload["documents"])
        assert store.last_success(acquired["document_id"])["document_version_id"] == acquired["document_version_id"]
        assert store.read_blob(byte_digest(body)) == body


def test_additive_schema_upgrade_preserves_existing_evidence(tmp_path):
    root = tmp_path / "derived"
    body = FIXTURE.read_bytes()
    with EvidenceStore(root) as store:
        observation = store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body,
                                    observed_at=OLDER, ingest_id="legacy")
        before = [tuple(row) for row in store.db.execute("SELECT * FROM acquisition_checks ORDER BY sequence")]
        # Reproduce the previous private schema without changing retained rows.
        store.db.execute("DROP TABLE ingest_capture_attempts")
        store.db.execute("DROP TABLE observation_acquisitions")
        store.db.commit()
    with EvidenceStore(root) as store:
        assert [tuple(row) for row in store.db.execute("SELECT * FROM acquisition_checks ORDER BY sequence")] == before
        assert current_observation(store, KEY)["observation_id"] == observation
        assert store.read_blob(byte_digest(body)) == body
        assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def accepted_name(store, job, observation, now=IMPORTED):
    """Exact real source name through the same accepted staging contract as PR731."""
    queue = TermsQueue(store)
    context = queue.validate_input(job["job_id"])
    name = json.loads(FIXTURE.read_bytes())["data"]["name"]
    extraction = store.db.execute("SELECT * FROM extractions WHERE extraction_id=?", (job["extraction_id"],)).fetchone()
    text = store.read_blob(extraction["text_sha256"]).decode()
    start = text.index(name)
    clause = store.add_clause(job["extraction_id"], start=start, end=start+len(name), section="name")
    applicability = {"product_key": observation["product_key"], **dict.fromkeys(("tier", "package", "cohort", "effective_from", "effective_to"))}
    output = {"schema_version": 1, "extraction_id": job["extraction_id"], "context_sha256": digest(context),
              "clauses": [{"start": start, "end": start+len(name), "page": None, "section": "name",
                           "disposition": "parameter", "reason": "Exact retained product name"}],
              "terms": [{"parameter_key": "product.name", "value": name, "unit": None, **applicability,
                         "clause_indexes": [0], "rule_pattern": None, "conditions": [], "exceptions": []}],
              "unresolved": ["Protocol source name only; no complete interpretation claim"]}
    queue.save_staging(job["job_id"], output, lease_id=job["lease_id"], now=now)
    return dict(observation_id=observation["observation_id"], parameter_key="product.name", value=name, unit=None,
                applicability=applicability, clause_ids=[clause], interpreter="protocol-source-reader",
                context_sha256=digest(context), observed_at=now)


def test_unfinished_new_capture_preserves_completed_staging_and_review_until_completion(tmp_path, monkeypatch):
    root = tmp_path / "derived"
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(root))
    monkeypatch.setattr("cdr_terms.ingest.utc_now", lambda: IMPORTED)
    old = capture(*source_generation(tmp_path, "2026-09-07", OLDER))
    key = json.loads(Path(old["receipt_path"]).read_bytes())["sources"][0]["product_key"]
    with EvidenceStore(root) as store:
        queue = TermsQueue(store)
        claim = queue.claim(IMPORTED)
        old_observation = current_observation(store, key)
        arguments = accepted_name(store, claim, old_observation)
        term = stage_term(store, **arguments)
        proof = store.put_blob(canonical_json({"term_revision_id": term, "passed": True, "checks": sorted(REVIEW_CHECKS)}).encode())
        review_term(store, term, status="validated", reviewer="separate-protocol-review", reviewer_kind="human",
                    reviewed_at=IMPORTED, evidence_sha256=proof, reason="Exact source name and span match")
        before = build_product_asset(store, key)
    # Mechanical byte revision; the product's real fields remain unchanged.
    run, state, finalized = source_generation(tmp_path, "2026-09-14", CURRENT, FIXTURE.read_bytes()+b"\n")
    assert capture(run, state, {**finalized, "banks": {"products": 2}})["status"] == "CAPTURE_FAILED"
    with EvidenceStore(root) as store:
        queue = TermsQueue(store)
        assert current_observation(store, key) == old_observation
        assert queue._source_current(claim["job_id"])
        assert stage_term(store, **arguments) == term  # Composed PR731 rechecks accepted staging here.
        assert build_product_asset(store, key) == before
        assert queue.next_due(IMPORTED) is None  # New raw job awaits its capture marker.
        assert queue.claim(IMPORTED) is None
        assert store.db.execute("SELECT status FROM job_events ORDER BY sequence DESC LIMIT 1").fetchone()[0] == "queued"
    assert capture(run, state, finalized)["status"] == "CAPTURED_AND_QUEUED"
    with EvidenceStore(root) as store:
        queue = TermsQueue(store)
        assert not queue._source_current(claim["job_id"])
        assert build_product_asset(store, key)["revisions"] == []
        assert queue.claim(IMPORTED)["job_id"] != claim["job_id"]


def test_pending_capture_does_not_starve_an_independent_historical_job(tmp_path, monkeypatch):
    from cdr_terms.ingest import registry_context
    root = tmp_path / "derived"
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(root))
    run, state, finalized = source_generation(tmp_path, "2026-09-14", CURRENT)
    assert capture(run, state, {**finalized, "banks": {"products": 2}})["status"] == "CAPTURE_FAILED"
    with EvidenceStore(root) as store:
        queue = TermsQueue(store)
        pending = store.db.execute("SELECT * FROM analysis_jobs").fetchone()
        observation = store.db.execute("SELECT observation_id FROM observations").fetchone()[0]
        historical = queue.enqueue_historical(pending["extraction_id"], [observation], registry_context=registry_context(), now=IMPORTED)
        assert queue.claim(IMPORTED)["job_id"] == historical
        assert store.db.execute("SELECT status FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1", (pending["job_id"],)).fetchone()[0] == "queued"


def test_replacement_analysis_waits_for_acquisition_finish_and_survives_restart(tmp_path):
    from cdr_terms.acquisitions_queue import enqueue_interpretation
    from cdr_terms.ingest import registry_context
    root = tmp_path / "derived"
    body = FIXTURE.read_bytes()
    with EvidenceStore(root) as store:
        observation = store.observe(provider="Bank of Melbourne", product_key=KEY, record=json.loads(body), source_bytes=body,
                                    observed_at=OLDER, ingest_id="retrying-document")
        acquisitions = AcquisitionQueue(store)
        acquisitions.enqueue(observation, ingest_id="retrying-document", now=OLDER)
        complete(store, observation, OLDER)
        previous = acquisitions.claim(CURRENT)
        store.record_check(document_id=previous["document_id"], check_id="first-version", checked_at=CURRENT,
                           status="fetched", body=body, media_type="application/json")
        acquisitions.finish(previous, "first-version", now=CURRENT, processing_error="retry_interpretation")
        retry = acquisitions.claim(IMPORTED)
        assert retry["request_id"] == previous["request_id"]
        version = store.record_check(document_id=retry["document_id"], check_id="replacement", checked_at=IMPORTED,
                                     status="fetched", body=body+b"\n", media_type="application/json")
        job = enqueue_interpretation(store, version, [observation], priority=0, registry_context=registry_context())
        queue = TermsQueue(store)
        assert queue._source_state(job) == "pending" and queue.claim(IMPORTED) is None
    with EvidenceStore(root) as store:
        assert TermsQueue(store).next_due(IMPORTED) is None
        AcquisitionQueue(store).finish(retry, "replacement", now=IMPORTED)
        assert TermsQueue(store)._source_current(job)
        assert TermsQueue(store).claim(IMPORTED)["job_id"] == job
