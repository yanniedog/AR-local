"""Structural selection controls; IDs/counts are not financial acceptance data."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from cdr_atomic import canonical_json_bytes
from cdr_export_contract import load_contract
from cdr_observation_selection import selected_observation
from cdr_raw_attempt_journal import RawAttemptJournal
from tests.test_cdr_same_day_selection import DATE, ENDPOINT, finish, make_export


def export(root, products, rate_products):
    status = make_export(root, products)
    with closing(sqlite3.connect(root / "local-cdr.sqlite")) as db:
        db.execute("CREATE TABLE bank_rates(run_date TEXT, provider TEXT, product_id TEXT)")
        db.executemany("INSERT INTO bank_rates VALUES (?, 'Provider', ?)",
                       [(DATE, pid) for pid in rate_products])
        db.commit()
    latest = root / "dashboard-cache" / "latest.json"
    report = json.loads(latest.read_bytes())
    report["banks_counts"]["rates"] = len(rate_products)
    latest.write_bytes(canonical_json_bytes(report))
    return status


def proof(root, state, parent, status, claims):
    # p1 is absent from the fresh complete index; p2 remains in scope and the
    # existing classifier explicitly excludes scope. No verifier is mocked.
    journal = RawAttemptJournal(root / "attempt-evidence" / "raw-attempt-journals-v1", "current")
    body = canonical_json_bytes({"data": {"products": [
        {"productId": "p2", "productCategory": "RESIDENTIAL_MORTGAGES"},
        {"productId": "scope", "productCategory": "BUSINESS_LOANS"},
    ]}, "meta": {"totalPages": 1, "totalRecords": 2}, "links": {}})
    event = journal.record("page-1", request_url=ENDPOINT, status=200, outcome="success", body=body,
                           started_at=DATE + "T00:00:00Z", completed_at=DATE + "T00:00:01Z",
                           context={"provider": "Provider", "phase": "products_index", "page": 1})
    digest = event["response"]["body_sha256"]
    index = {"complete": True, "observed_product_ids": ["p2", "scope"], "pages": [{
        "body_sha256": digest, "event_digest": event["event_digest"],
        "event_seq": event["sequence"], "journal_session_id": journal.session_id}],
        "fresh_index_sha256": hashlib.sha256(canonical_json_bytes({
            "page_body_sha256": [digest]})).hexdigest()}
    contract = load_contract(state / parent["export_contract_path"])
    status.update(raw_attempt_journal={"path": journal.root.relative_to(root).as_posix(),
                                      "session_id": journal.session_id},
        index_diagnostics={"Provider": {"pages": 1, "pagination_complete": True,
            "raw_records": 2, "declared_total_records": 2, "declared_total_pages": 1,
            "conflicting_duplicate_records": 0}},
        same_day_reuse={"baseline": {"generation_id": parent["generation_id"],
            "export_contract_digest": contract["contract_digest"],
            "ledger_event_digest": parent["ledger_event_digest"]},
            "withdrawals": [{"provider_dir": "Provider", "product_id": pid,
                             "fresh_index_sha256": index["fresh_index_sha256"]} for pid in claims],
            "withdrawal_indexes": {"Provider": index}})
    (root / "ingest-status.json").write_bytes(canonical_json_bytes(status))


@pytest.mark.parametrize("old_products,new_products,new_rates,claims,accepted,withdrawn_rows", [
    (["p1", "p2", "scope"], ["p2"], ["p2"], ["p1"], True, 1),
    (["p1", "p2", "scope"], ["p2"], [], ["p1"], False, 1),
    # A duplicate claim must not double the allowance and hide the lost p2 row.
    (["p1", "p2", "scope"], ["p2"], [], ["p1", "p1"], False, 1),
    # A verified absent-index identity still retained in the normalized candidate
    # is not a removed product: its row cannot compensate for p2's lost row.
    (["p1", "p2", "scope"], ["p1", "p2"], ["p1"], ["p1"], False, 0),
    # Nor may a claim about a product never captured in the old DB add allowance.
    (["p2", "scope"], ["p2"], [], ["p1"], False, 0),
])
def test_scope_and_withdrawal_compensation_is_exact(tmp_path, old_products, new_products,
                                                   new_rates, claims, accepted, withdrawn_rows):
    state = tmp_path / "state"
    old = tmp_path / "runs" / DATE / "_exports"
    new = old.parent / "_revisions" / "scope" / "_exports"
    export(old, old_products, old_products)
    parent = finish(old, state, "done")
    status = export(new, new_products, new_rates)
    proof(new, state, parent, status, claims)
    before = (old / "local-cdr.sqlite").read_bytes()
    marker = finish(new, state, "revision.scope", parent["generation_id"])
    selected = selected_observation(state, DATE)["contract"]["generation_id"]
    assert selected == (marker if accepted else parent)["generation_id"]
    receipt = json.loads(next((state / "observation-selections-v1" / DATE).glob("*.json")).read_bytes())
    assert receipt["reason"] == ("same_day_coverage_preserved" if accepted else "in_scope_rate_coverage_regressed")
    report = receipt["scope_reconciliation"]
    assert report["scope_excluded_rate_rows"] == 1
    assert report["withdrawn_rate_rows"] == withdrawn_rows
    assert len(report["removed_withdrawals"]) == withdrawn_rows
    assert report["rate_delta_after_verified_removals"] == (0 if accepted else -1)
    assert (old / "local-cdr.sqlite").read_bytes() == before


def test_scope_product_cannot_also_claim_withdrawal_from_the_same_index(tmp_path):
    state = tmp_path / "state"
    old = tmp_path / "runs" / DATE / "_exports"
    new = old.parent / "_revisions" / "scope" / "_exports"
    export(old, ["p1", "p2", "scope"], ["p1", "p2", "scope"])
    parent = finish(old, state, "done")
    status = export(new, ["p2"], ["p2"])
    proof(new, state, parent, status, ["p1", "scope"])
    finish(new, state, "revision.scope", parent["generation_id"])
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]
    receipt = json.loads(next((state / "observation-selections-v1" / DATE).glob("*.json")).read_bytes())
    assert receipt["reason"] == "selection_evidence_unavailable:ValueError"
