from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import cdr_finalization as finalization
from cdr_atomic import canonical_json_bytes
from cdr_export_contract import hash_file, load_contract
from cdr_observation_selection import captured_identities, selected_observation
from cdr_raw_attempt_journal import RawAttemptJournal
from cdr_recovery_legacy import legacy_recovery_requests
from cdr_observation_selection import provider_directories

DATE = "2026-09-07"
ENDPOINT = "https://provider.example/cds-au/v1/banking/products"


def make_export(root: Path, products: list[str], *, failures: int = 1, date: str = DATE) -> dict:
    (root / "dashboard-cache").mkdir(parents=True)
    (root / "dashboard-cache" / "latest.json").write_text(json.dumps({
        "run_date": date, "banks_counts": {"products": len(products), "rates": len(products),
        "fees": 0, "features": 0, "eligibility": 0, "constraints": 0, "failures": failures},
    }))
    db = sqlite3.connect(root / "local-cdr.sqlite")
    db.execute("CREATE TABLE bank_products(run_date TEXT, provider TEXT, product_id TEXT)")
    db.executemany("INSERT INTO bank_products VALUES (?, 'Provider', ?)", [(date, pid) for pid in products])
    db.commit()
    db.close()
    status = {
        "total": failures, "corrupt_records": 0, "unattributed_records": 0,
        "failure_provenance_complete": True, "incomplete": bool(failures),
        "by_provider": {"Provider": failures} if failures else {},
        "register_provenance_complete": True,
        "register_attempts": [{"source_url": "https://register.example/brands", "mode": "cdr",
                               "ok": True, "status": 200, "bytes": 2, "sha256": "a" * 64}],
        "providers_registered": 1, "providers_attempted": 1,
        "provider_states": [{"provider_uid": "provider-1", "provider_dir": "Provider",
                             "brand_name": "Provider", "legal_entity_name": "Provider Ltd",
                             "endpoint_url": ENDPOINT, "state": "partial" if failures else "complete",
                             "failure_records": failures}],
    }
    (root / "ingest-status.json").write_text(json.dumps(status))
    return status


def finish(root: Path, state: Path, name: str, parent: str | None = None, date: str = DATE):
    return finalization.finalize_observation(
        root, state, state / f"{date}.{name}.json", observation_date=date,
        result={"run_date": date, "banks_counts": {"rates": 1}}, parent_generation_id=parent,
    )


def baseline(tmp_path):
    state = tmp_path / "state"
    root = tmp_path / "runs" / DATE / "_exports"
    make_export(root, ["p1", "p2"])
    marker = finish(root, state, "done")
    return state, root, marker


def add_withdrawal_evidence(root: Path, state: Path, parent: dict, status: dict, *, corrupt=False):
    namespace = root / "attempt-evidence" / "raw-attempt-journals-v1"
    journal = RawAttemptJournal(namespace, "current")
    body = json.dumps({"data": {"products": [{"productId": "p2"}]},
                       "meta": {"totalPages": 1, "totalRecords": 1}, "links": {}}).encode()
    event = journal.record("current-page-1", request_url=ENDPOINT, status=200, outcome="success", body=body,
                           started_at=DATE + "T00:00:00Z", completed_at=DATE + "T00:00:01Z",
                           context={"provider": "Provider", "phase": "products_index", "page": 1})
    digest = event["response"]["body_sha256"]
    proof = {"complete": True, "observed_product_ids": ["p2"],
             "pages": [{"body_sha256": digest, "event_digest": event["event_digest"],
                        "event_seq": event["sequence"], "journal_session_id": journal.session_id}],
             "fresh_index_sha256": hashlib.sha256(canonical_json_bytes({"page_body_sha256": [digest]})).hexdigest()}
    contract = load_contract(state / parent["export_contract_path"])
    status.update(
        raw_attempt_journal={"path": journal.root.relative_to(root).as_posix(), "session_id": journal.session_id},
        index_diagnostics={"Provider": {"pages": 1, "pagination_complete": True,
                           "raw_records": 1, "declared_total_records": 1, "declared_total_pages": 1}},
        same_day_reuse={"schema_version": 1, "reconciled": True, "baseline": {
            "run_date": DATE, "generation_id": parent["generation_id"],
            "export_contract_sha256": hash_file(state / parent["export_contract_path"]),
            "export_contract_digest": contract["contract_digest"], "ledger_event_digest": parent["ledger_event_digest"]},
            "withdrawals": [{"provider_dir": "Provider", "product_id": "p1", "fresh_index_sha256": proof["fresh_index_sha256"]}],
            "withdrawal_indexes": {"Provider": proof}},
    )
    if corrupt:
        proof["observed_product_ids"] = []  # Metadata must not override the raw HTTP body.
    (root / "ingest-status.json").write_text(json.dumps(status))


def test_actual_sqlite_membership_prevents_same_count_provider_product_loss(tmp_path):
    state, root, parent = baseline(tmp_path)
    original = hash_file(root / "local-cdr.sqlite")
    revision = tmp_path / "runs" / DATE / "_revisions" / "r1" / "_exports"
    make_export(revision, ["p2", "p3"], failures=0)
    rejected = finish(revision, state, "revision.r1", parent["generation_id"])
    selected = selected_observation(state, DATE)
    assert selected["contract"]["generation_id"] == parent["generation_id"]
    assert finalization.verify_completion_marker(rejected, state, DATE)
    assert captured_identities(selected) == {("Provider", "p1"), ("Provider", "p2")}
    assert hash_file(root / "local-cdr.sqlite") == original
    assert not (state / "observation-pointers-v2" / "latest-complete.json").exists()


def test_verified_fresh_index_can_withdraw_a_same_day_product(tmp_path):
    state, _, parent = baseline(tmp_path)
    revision = tmp_path / "runs" / DATE / "_revisions" / "r1" / "_exports"
    status = make_export(revision, ["p2"], failures=0)
    add_withdrawal_evidence(revision, state, parent, status)
    accepted = finish(revision, state, "revision.r1", parent["generation_id"])
    assert selected_observation(state, DATE)["contract"]["generation_id"] == accepted["generation_id"]


def test_withdrawal_list_cannot_disagree_with_contract_bound_raw_index(tmp_path):
    state, _, parent = baseline(tmp_path)
    revision = tmp_path / "runs" / DATE / "_revisions" / "r1" / "_exports"
    status = make_export(revision, ["p2"], failures=0)
    add_withdrawal_evidence(revision, state, parent, status, corrupt=True)
    finish(revision, state, "revision.r1", parent["generation_id"])
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]


def test_transient_selection_failure_can_be_retried_without_rewriting_refusal(tmp_path, monkeypatch):
    state, _, parent = baseline(tmp_path)
    revision = tmp_path / "runs" / DATE / "_revisions" / "r1" / "_exports"
    make_export(revision, ["p1", "p2", "p3"], failures=0)
    real = finalization.same_day_selection_reason
    monkeypatch.setattr(finalization, "same_day_selection_reason", lambda *a: (_ for _ in ()).throw(OSError("temporary read failure")))
    marker = finish(revision, state, "revision.r1", parent["generation_id"])
    refusals = {path: path.read_bytes() for path in (state / "observation-selections-v1" / DATE).glob("*.json")}
    assert len(refusals) == 1
    monkeypatch.setattr(finalization, "same_day_selection_reason", real)
    assert finalization.repair_observation_pointers(marker, state, DATE, state / f"{DATE}.revision.r1.json")
    assert selected_observation(state, DATE)["contract"]["generation_id"] == marker["generation_id"]
    assert all(path.read_bytes() == body for path, body in refusals.items())
    assert len(list((state / "observation-selections-v1" / DATE).glob("*.json"))) == 2


def test_lower_coverage_on_a_new_date_is_not_replaced_with_yesterdays_data(tmp_path):
    state, _, _ = baseline(tmp_path)
    next_date = "2026-09-08"
    root = tmp_path / "runs" / next_date / "_exports"
    make_export(root, ["p1"], failures=2, date=next_date)
    marker = finish(root, state, "done", date=next_date)
    assert selected_observation(state, next_date)["contract"]["generation_id"] == marker["generation_id"]


def test_legacy_bootstrap_reads_bound_failures_without_touching_retained_journal(tmp_path):
    state = tmp_path / "state"
    root = tmp_path / "runs" / DATE / "_exports"
    status = make_export(root, ["p1"])
    journal = RawAttemptJournal(root / "attempt-evidence" / "raw-attempt-journals-v1", "legacy")
    for pid in ("p1", "p2"):
        journal.record(pid, request_url=ENDPOINT + "/" + pid, status=404, outcome="http_error",
                       body=b'{"errors":[{"code":"inactive"}]}',
                       started_at=DATE + "T00:00:00Z", completed_at=DATE + "T00:00:01Z",
                       context={"provider": "Provider", "phase": "product_detail", "product_id": pid})
    status["raw_attempt_journal"] = {"session_id": journal.session_id, "path": journal.root.relative_to(root).as_posix()}
    (root / "ingest-status.json").write_text(json.dumps(status))
    finish(root, state, "done")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in journal.root.rglob("*") if path.is_file()}
    observation = selected_observation(state, DATE)
    cache = state / "cdr-recovery-v1" / DATE
    rows = legacy_recovery_requests(observation, provider_directories(status), cache)
    assert [row["product_id"] for row in rows] == ["p2"]
    assert legacy_recovery_requests(observation, provider_directories(status), cache) == rows
    assert all(path.read_bytes() == body and path.stat().st_mtime_ns == stamp
               for path, (body, stamp) in before.items())
