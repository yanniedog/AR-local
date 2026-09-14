"""Revision admission against retained CDR bytes; altered fields are protocol faults."""
from __future__ import annotations

import copy
import json
import sqlite3

import pytest

from cdr_terms.identity import canonical_json, digest
from cdr_terms.observation_checks import bind_manual_check
from cdr_terms.revisions import _applicability, register_rule_set, stage_term
from tests.test_cdr_terms_evidence import LATER, NOW, _staged_term, evidence  # noqa: F401
from tests.test_cdr_terms_historical import historical  # noqa: F401


@pytest.mark.parametrize("start,end", [
    ("2026-01-01T10:00:00+10:00", "2026-01-01T01:00:00Z"),
    ("2026-01-01T01:00:00Z", "2025-12-31T22:00:00-04:00"),
    ("2026-01-01T10:00:00+10:00", "2026-01-01T00:00:00.000000Z"),
    ("2026-01-01", "2026-01-02"),
    (None, "2026-01-02"),
])
def test_effective_interval_compares_instants_and_preserves_source_spelling(evidence, start, end):
    def dated(output):
        output["terms"][0].update(effective_from=start, effective_to=end)
    _, _, _, arguments = _staged_term(evidence, output_change=dated)
    arguments["applicability"].update(effective_from=start, effective_to=end)
    identity = stage_term(evidence[0], **arguments)
    stored = json.loads(evidence[0].db.execute(
        "SELECT applicability_json FROM term_revisions WHERE term_revision_id=?", (identity,)).fetchone()[0])
    assert stored["effective_from"] == start and stored["effective_to"] == end


@pytest.mark.parametrize("start,end", [
    ("2026-01-01T01:00:00Z", "2026-01-01T10:00:00+10:00"),
    ("2025-12-31T22:00:00-04:00", "2026-01-01T01:00:00Z"),
    ("2026-01-02", "2026-01-01"),
])
def test_effective_interval_rejects_chronologically_inverted_bounds(start, end):
    scope = dict.fromkeys(("tier", "package", "cohort"))
    with pytest.raises(ValueError, match="inverted"):
        _applicability({**scope, "product_key": "source", "effective_from": start, "effective_to": end}, "source")


@pytest.mark.parametrize("start,end", [
    ("2026-01-01", "2026-01-01T01:00:00Z"),
    ("2026-01-01T00:00:00Z", "2026-01-02"),
])
def test_mixed_effective_precision_does_not_invent_a_timezone_for_a_date(start, end):
    scope = dict.fromkeys(("tier", "package", "cohort"))
    with pytest.raises(ValueError, match="precision"):
        _applicability({**scope, "product_key": "source", "effective_from": start, "effective_to": end}, "source")


def test_unknown_context_digest_cannot_create_a_revision(evidence):
    _, _, _, arguments = _staged_term(evidence, save=False)
    arguments["context_sha256"] = digest({"unrelated": "no job"})
    with pytest.raises(ValueError, match="analysis job"):
        stage_term(evidence[0], **arguments)
    assert evidence[0].db.execute("SELECT COUNT(*) FROM term_revisions").fetchone()[0] == 0


@pytest.mark.parametrize("state", ["queued", "running", "superseded"])
def test_only_an_accepted_current_staged_result_can_authorize_a_revision(evidence, state):
    queue, job, _, arguments = _staged_term(evidence, save=False)
    if state == "running":
        queue.claim(NOW)
    elif state == "superseded":
        queue.event(job, "superseded", NOW)
    with pytest.raises(ValueError, match="staged result"):
        stage_term(evidence[0], **arguments)


@pytest.mark.parametrize("source_map", [None, {}, {"unrelated": "0" * 64}])
def test_context_must_pin_the_exact_product_source(evidence, source_map):
    _, _, _, arguments = _staged_term(evidence, context_change={"source_product_sha256": source_map})
    with pytest.raises(ValueError, match="product source"):
        stage_term(evidence[0], **arguments)


def test_other_product_context_cannot_authorize_this_product(evidence):
    def other_product(output):
        output["terms"][0]["product_key"] = "another-product"
    _, _, _, arguments = _staged_term(evidence, context_change={"product_keys": ["another-product"]}, output_change=other_product)
    with pytest.raises(ValueError, match="product source"):
        stage_term(evidence[0], **arguments)


def test_same_product_different_observation_bytes_are_not_interchangeable(evidence):
    store, _, key, _, _, body, record = evidence
    _, _, _, arguments = _staged_term(evidence)
    arguments["observation_id"] = store.observe(provider=record["brand"], product_key=key,
        record=json.loads(body), source_bytes=body + b"\n", observed_at=LATER, ingest_id="byte-revision")
    with pytest.raises(ValueError, match="product source"):
        stage_term(store, **arguments)


def test_a_new_extraction_cannot_borrow_a_staged_context(evidence):
    store, _, _, _, version, _, _ = evidence
    _, _, output, arguments = _staged_term(evidence)
    original = store.db.execute("SELECT * FROM extractions WHERE extraction_id=?", (output["extraction_id"],)).fetchone()
    newer = store.register_extraction(document_version_id=version, extractor_version="protocol-new-extractor",
        text=store.read_blob(original["text_sha256"]).decode(), observed_at=NOW, status="partial", coverage={"reason": "Protocol test"})
    locator = output["clauses"][0]
    arguments["clause_ids"] = [store.add_clause(newer, start=locator["start"], end=locator["end"], section=locator["section"])]
    with pytest.raises(ValueError, match="analysis job"):
        stage_term(store, **arguments)


@pytest.mark.parametrize("field,new_value", [
    ("value", "changed source interpretation"), ("unit", "AUD"), ("parameter_key", "product.other"),
    ("tier", "unreviewed-tier"), ("package", "unreviewed-package"), ("cohort", "unreviewed-cohort"),
    ("effective_from", "2026-01-01"), ("effective_to", "2026-12-31"),
])
def test_revision_fields_must_match_one_exact_staged_term(evidence, field, new_value):
    _, _, _, arguments = _staged_term(evidence)
    if field in arguments["applicability"]:
        arguments["applicability"][field] = new_value
    else:
        arguments[field] = new_value
    with pytest.raises(ValueError, match="exact staged term"):
        stage_term(evidence[0], **arguments)


@pytest.mark.parametrize("staged_value,revision_value", [(False, 0), (0, False), (None, ""), ("0", 0)])
def test_type_exact_staging_comparison_preserves_unknown_false_zero_and_text(evidence, staged_value, revision_value):
    def altered(output):
        output["terms"][0]["value"] = staged_value
    _, _, _, arguments = _staged_term(evidence, output_change=altered)
    arguments["value"] = revision_value
    with pytest.raises(ValueError, match="exact staged term"):
        stage_term(evidence[0], **arguments)
    arguments["value"] = staged_value
    stage_term(evidence[0], **arguments)


def test_another_valid_clause_on_the_same_document_is_not_the_staged_clause(evidence):
    store = evidence[0]
    _, _, output, arguments = _staged_term(evidence)
    arguments["clause_ids"] = [store.add_clause(output["extraction_id"], start=0, end=1)]
    with pytest.raises(ValueError, match="exact staged term"):
        stage_term(store, **arguments)


@pytest.mark.parametrize("mutation", ["duplicate", "unresolved", "conditions", "exceptions", "rule_pattern"])
def test_ambiguous_or_unrepresented_staging_cannot_be_silently_promoted(evidence, mutation):
    def alter(output):
        if mutation == "duplicate":
            output["terms"].append(copy.deepcopy(output["terms"][0]))
        elif mutation == "unresolved":
            output["clauses"][0]["disposition"] = "unresolved"
        elif mutation == "rule_pattern":
            output["terms"][0][mutation] = "unreviewed-pattern"
        else:
            output["terms"][0][mutation] = ["Retained qualifier must not disappear"]
    _, _, _, arguments = _staged_term(evidence, output_change=alter)
    with pytest.raises(ValueError, match="staged term|qualifier|rule pattern"):
        stage_term(evidence[0], **arguments)


def test_accepted_result_cannot_be_reused_after_source_or_job_supersession(evidence):
    store, _, _, doc, _, body, _ = evidence
    queue, job, _, arguments = _staged_term(evidence)
    store.record_check(document_id=doc, check_id="later-source", checked_at=LATER, status="fetched", body=body + b"\n", media_type="application/json")
    bind_manual_check(store, arguments["observation_id"], "later-source")
    with pytest.raises(ValueError, match="source.*changed"):
        stage_term(store, **arguments)
    queue.event(job, "superseded", LATER)
    with pytest.raises(ValueError, match="staged result"):
        stage_term(store, **arguments)


def test_result_blob_integrity_is_rechecked_at_revision_admission(evidence):
    store = evidence[0]
    _, job, _, arguments = _staged_term(evidence)
    sha = store.db.execute("SELECT result_sha256 FROM job_events WHERE job_id=? AND status='staged'", (job,)).fetchone()[0]
    (store.blobs / sha[:2] / sha).write_bytes(b"protocol corruption")
    with pytest.raises(ValueError, match="integrity"):
        stage_term(store, **arguments)


def test_identical_context_for_another_extraction_does_not_make_the_exact_job_ambiguous(evidence):
    store, _, _, _, version, _, _ = evidence
    queue, job, output, arguments = _staged_term(evidence)
    extraction = store.db.execute("SELECT * FROM extractions WHERE extraction_id=?", (output["extraction_id"],)).fetchone()
    another = store.register_extraction(document_version_id=version, extractor_version="second-extractor",
        text=store.read_blob(extraction["text_sha256"]).decode(), observed_at=NOW, status="partial", coverage={})
    queue.enqueue(another, queue.validate_input(job), now=NOW)
    first = stage_term(store, **arguments)
    assert stage_term(store, **arguments) == first
    assert store.db.execute("SELECT COUNT(*) FROM term_revisions").fetchone()[0] == 1


def test_historical_clauses_cannot_borrow_an_unrelated_current_staged_receipt(historical):
    store, queue, _, output, context, observation, key, _, _ = historical
    current_context = {name: value for name, value in context.items() if name != "historical_target"}
    current = queue.enqueue(output["extraction_id"], current_context, priority=0, now=NOW)
    current_output = {name: value for name, value in output.items() if name != "historical_scope"}
    current_output["context_sha256"] = digest(current_context)
    claim = queue.claim(NOW)
    assert claim["job_id"] == current
    queue.save_staging(current, current_output, lease_id=claim["lease_id"], now=NOW)
    clause = store.add_clause(output["extraction_id"], start=0, end=1)
    scope = {"product_key": key, **dict.fromkeys(("tier", "package", "cohort", "effective_from", "effective_to"))}
    with pytest.raises(ValueError, match="exact staged term"):
        stage_term(store, observation_id=observation, parameter_key="source.character", value="{", unit=None,
                   applicability=scope, clause_ids=[clause], interpreter="protocol-source-reader",
                   context_sha256=current_output["context_sha256"], observed_at=NOW)
    assert store.db.execute("SELECT COUNT(*) FROM term_revisions").fetchone()[0] == 0


def test_an_orphan_staged_event_cannot_replace_lease_accepted_completion(evidence):
    store = evidence[0]
    queue, job, output, arguments = _staged_term(evidence, save=False)
    queue.claim(NOW)
    blob = store.put_blob(canonical_json(output).encode())
    with store.db:
        queue._event(job, "staged", NOW, None, None, blob, "unaccepted-lease")
    with pytest.raises(ValueError, match="lease-accepted"):
        stage_term(store, **arguments)


def test_controller_can_attach_a_registered_rule_to_exact_unqualified_staging(evidence):
    store = evidence[0]
    _, _, _, arguments = _staged_term(evidence)
    benchmark = store.put_blob(evidence[5])
    rule = register_rule_set(store, {"parameter_keys": ["product.name"]},
                             validator_version="retained-name-protocol", benchmark_sha256=benchmark)
    identity = stage_term(store, **arguments, rule_set_id=rule)
    assert store.db.execute("SELECT rule_set_id FROM term_revisions WHERE term_revision_id=?", (identity,)).fetchone()[0] == rule


def test_revision_and_source_insertions_are_atomic(evidence):
    store = evidence[0]
    _, _, _, arguments = _staged_term(evidence)
    def deny_source(action, table, *_):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT and table == "term_sources" else sqlite3.SQLITE_OK
    store.db.set_authorizer(deny_source)
    with pytest.raises(sqlite3.DatabaseError):
        stage_term(store, **arguments)
    store.db.set_authorizer(None)
    assert store.db.execute("SELECT COUNT(*) FROM term_revisions").fetchone()[0] == 0
    stage_term(store, **arguments)
