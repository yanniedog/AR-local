"""Structural journal chronology controls, with no financial acceptance data."""
from __future__ import annotations

import json

import pytest

from cdr_atomic import canonical_json_bytes
from cdr_observation_selection import selected_observation
from cdr_raw_attempt_journal import RawAttemptJournal
from tests.test_cdr_same_day_selection import DATE, ENDPOINT, finish
from tests.test_cdr_scope_withdrawals import export


def page(journal, number, count, *, status=200, wrong_url=False):
    product = {"productId": "scope" if number == 1 else f"p{number}",
               "productCategory": "BUSINESS_LOANS" if number == 1 else "RESIDENTIAL_MORTGAGES"}
    url = ENDPOINT if number == 1 else ENDPOINT + f"?page={number}"
    body = {"data": {"products": [product]}, "meta": {"totalPages": count, "totalRecords": count},
            "links": {"next": ENDPOINT + f"?page={number + 1}"} if number < count else {}}
    journal.record(f"page-{number}-{len(list((journal.root / 'events').glob('*.json')))}",
        request_url=ENDPOINT + "?wrong=1" if wrong_url else url, status=status,
        outcome="success" if status == 200 else "http_error", body=canonical_json_bytes(body),
        started_at=DATE + "T00:00:00Z", completed_at=DATE + "T00:00:01Z",
        context={"provider": "Provider", "phase": "products_index", "page": number})


@pytest.mark.parametrize("scenario,accepted", [
    ("shrink_to_one", True), ("shrink_to_two", True),
    ("failed_page_one", False), ("missing_fresh_page_two", False),
    ("new_unexpected_tail", False), ("nonmonotonic", False), ("chain_mismatch", False),
])
def test_latest_coherent_crawl_preserves_old_evidence_without_borrowing_it(tmp_path, scenario, accepted):
    state = tmp_path / "state"
    old = tmp_path / "runs" / DATE / "_exports"
    new = old.parent / "_revisions" / "scope" / "_exports"
    export(old, ["scope", "p2"], ["scope", "p2"])
    parent = finish(old, state, "done")
    status = export(new, ["p2"], ["p2"])
    journal = RawAttemptJournal(new / "attempt-evidence" / "raw-attempt-journals-v1", "current")
    for number in range(1, 4):
        page(journal, number, 3)
    original = {path: path.read_bytes() for directory in ("events", "bodies")
                for path in (journal.root / directory).iterdir() if path.is_file()}
    count = 1 if scenario in {"shrink_to_one", "failed_page_one", "new_unexpected_tail"} else 2
    if scenario == "nonmonotonic":
        count = 3
    page(journal, 1, count, status=503 if scenario == "failed_page_one" else 200)
    if scenario == "nonmonotonic":
        page(journal, 3, count)
    if count > 1 and scenario != "missing_fresh_page_two":
        page(journal, 2, count, wrong_url=scenario == "chain_mismatch")
    if scenario == "new_unexpected_tail":
        page(journal, 2, 2, status=503)
    status.update(raw_attempt_journal={"path": journal.root.relative_to(new).as_posix(),
                                      "session_id": journal.session_id},
        index_diagnostics={"Provider": {"pages": count, "pagination_complete": True,
            "raw_records": count, "declared_total_records": count, "declared_total_pages": count,
            "conflicting_duplicate_records": 0}})
    (new / "ingest-status.json").write_bytes(canonical_json_bytes(status))
    marker = finish(new, state, "revision.scope", parent["generation_id"])
    assert selected_observation(state, DATE)["contract"]["generation_id"] == (marker if accepted else parent)["generation_id"]
    receipt = json.loads(next((state / "observation-selections-v1" / DATE).glob("*.json")).read_bytes())
    if accepted:
        assert receipt["scope_reconciliation"]["scope_excluded_rate_rows"] == 1
    assert all(path.read_bytes() == body for path, body in original.items())
