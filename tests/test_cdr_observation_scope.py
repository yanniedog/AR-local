"""Real Sep13 scope-loss regression; ledger/SQLite scaffolding is test-only.

The 22 products, 30 prior row counts, current index responses and timestamps are
retained observations. Fault variants below deliberately corrupt evidence; they
are never claimed as live financial data or runtime acceptance.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

import cdr_finalization as finalization
from cdr_atomic import canonical_json_bytes
from cdr_export_contract import artifact_records
from cdr_observation_scope import verified_scope_exclusions
from cdr_observation_selection import selected_observation

DATE = "2026-09-13"
FIXTURE = Path(__file__).parent / "fixtures" / "selection-scope-real-20260913.json"


@pytest.fixture
def evidence():
    return json.loads(FIXTURE.read_bytes())


def write_export(root, evidence, *, original=False, lose_control=False, lose_rate=False):
    root.mkdir(parents=True)
    products = copy.deepcopy(evidence["missing_products"]) if original else []
    if not lose_control:
        products.append(evidence["retained_control"])
    with closing(sqlite3.connect(root / "local-cdr.sqlite")) as db:
        db.execute("CREATE TABLE bank_products(run_date TEXT, provider TEXT, product_id TEXT)")
        db.execute("CREATE TABLE bank_rates(run_date TEXT, provider TEXT, product_id TEXT)")
        for row in products:
            values = (DATE, row["provider"], row["product_id"])
            db.execute("INSERT INTO bank_products VALUES (?,?,?)", values)
            count = row["prior_rate_count"] if original else row["current_rate_count"]
            db.executemany("INSERT INTO bank_rates VALUES (?,?,?)", [values] * (0 if lose_rate else count))
        rates = db.execute("SELECT count(*) FROM bank_rates").fetchone()[0]
        db.commit()
    if not original:
        for relative, artifact in evidence["artifacts"].items():
            body = base64.b64decode(artifact["base64"])
            assert len(body) == artifact["bytes"]
            assert hashlib.sha256(body).hexdigest() == artifact["sha256"]
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
    status = copy.deepcopy(evidence["new_status"])
    if original:
        status["provider_states"] = evidence["old_provider_states"]
        status.pop("raw_attempt_journal")
        status.pop("index_diagnostics")
    status.update(total=21, incomplete=True, corrupt_records=0, unattributed_records=0,
                  failure_provenance_complete=True,
                  register_attempts=[{"ok": True, "sha256": "a" * 64}],
                  providers_registered=len(status["provider_states"]),
                  providers_attempted=len(status["provider_states"]))
    (root / "ingest-status.json").write_bytes(canonical_json_bytes(status))
    latest = root / "dashboard-cache" / "latest.json"
    latest.parent.mkdir()
    latest.write_bytes(canonical_json_bytes({"run_date": DATE, "banks_counts": {
        "products": len(products), "rates": rates, "fees": 0, "features": 0,
        "eligibility": 0, "constraints": 0, "failures": 21}}))


def complete(root, state, name, parent=None):
    return finalization.finalize_observation(
        root, state, state / f"{DATE}.{name}.json", observation_date=DATE,
        result={"run_date": DATE, "banks_counts": {"rates": 1}}, parent_generation_id=parent,
    )


def prepared(tmp_path, evidence, **kwargs):
    state = tmp_path / "state"
    original = tmp_path / "runs" / DATE / "_exports"
    candidate = original.parent / "_revisions" / "scope" / "_exports"
    write_export(original, evidence, original=True)
    parent = complete(original, state, "done")
    write_export(candidate, evidence, **kwargs)
    return state, original, candidate, parent


def observation(root, *, source=False):
    return {"export_root": root, "status": json.loads((root / "ingest-status.json").read_bytes()),
            "contract": {"observation_date": DATE, "artifacts": artifact_records(root)}}


def missing(evidence):
    return {(row["provider"], row["product_id"]) for row in evidence["missing_products"]}


def test_real_scope_exclusions_advance_with_exact_product_and_rate_reconciliation(tmp_path, evidence):
    state, old, new, parent = prepared(tmp_path, evidence)
    before = (old / "local-cdr.sqlite").read_bytes()
    marker = complete(new, state, "revision.scope", parent["generation_id"])
    assert selected_observation(state, DATE)["contract"]["generation_id"] == marker["generation_id"]
    receipts = list((state / "observation-selections-v1" / DATE).glob("*.json"))
    report = json.loads(receipts[0].read_bytes())["scope_reconciliation"]
    assert report["previous_products"] == 23 and report["candidate_products"] == 1
    assert report["previous_rate_rows"] == 31 and report["candidate_rate_rows"] == 1
    assert report["scope_excluded_rate_rows"] == 30
    assert report["rate_delta_after_scope_exclusions"] == 0
    assert report["unexplained_missing_products"] == []
    assert {(row["provider"], row["product_id"]) for row in report["scope_exclusions"]} == missing(evidence)
    assert all(len(row["body_sha256"]) == 64 and len(row["event_digest"]) == 64
               for row in report["scope_exclusions"])
    assert (old / "local-cdr.sqlite").read_bytes() == before


@pytest.mark.parametrize("fault,reason", [
    ({"lose_control": True}, "previously_captured_products_missing_without_fresh_withdrawal"),
    ({"lose_rate": True}, "in_scope_rate_coverage_regressed"),
])
def test_lost_real_in_scope_product_or_rate_still_refuses(tmp_path, evidence, fault, reason):
    state, _, new, parent = prepared(tmp_path, evidence, **fault)
    complete(new, state, "revision.scope", parent["generation_id"])
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]
    receipt = next((state / "observation-selections-v1" / DATE).glob("*.json"))
    assert json.loads(receipt.read_bytes())["reason"] == reason


@pytest.mark.parametrize("fault", ["incomplete", "provider_changed", "unbound_body", "tampered_body",
                                   "malformed_sequence", "malformed_context", "old_capture"])
def test_invalid_scope_evidence_never_excludes_products(tmp_path, evidence, fault):
    _, old, new, _ = prepared(tmp_path, evidence)
    source, candidate = observation(old), observation(new)
    provider = "Central West CUL"
    only = {key for key in missing(evidence) if key[0] == provider}
    if fault == "incomplete":
        candidate["status"]["index_diagnostics"][provider]["pagination_complete"] = False
    elif fault == "provider_changed":
        next(row for row in candidate["status"]["provider_states"] if row["provider_dir"] == provider)["provider_uid"] = "wrong-provider"
    else:
        events = [row for row in candidate["contract"]["artifacts"] if "/events/" in row["path"]]
        record = max((row for row in events if json.loads((new / row["path"]).read_bytes())["context"].get("provider") == provider),
                     key=lambda row: json.loads((new / row["path"]).read_bytes())["sequence"])
        path = new / record["path"]
        event = json.loads(path.read_bytes())
        body_path = candidate["status"]["raw_attempt_journal"]["path"] + "/" + event["body_path"]
        if fault == "unbound_body":
            candidate["contract"]["artifacts"] = [row for row in candidate["contract"]["artifacts"] if row["path"] != body_path]
        elif fault == "tampered_body":
            (new / body_path).write_bytes(b"{}")
        else:
            if fault == "malformed_sequence":
                event["sequence"] = "invalid"
            elif fault == "malformed_context":
                event["context"] = ["invalid"]
            else:
                event["request"]["started_at"] = "2026-09-10T00:00:00Z"
                event["response"]["completed_at"] = "2026-09-10T00:00:01Z"
            material = {key: value for key, value in event.items() if key != "event_digest"}
            event["event_digest"] = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
            path.write_bytes(canonical_json_bytes(event))
            record.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    try:
        result = verified_scope_exclusions(candidate, source, only)
    except ValueError:
        return
    assert result == []


def test_existing_real_valid_product_in_index_is_not_a_scope_exclusion(tmp_path, evidence):
    _, old, new, _ = prepared(tmp_path, evidence)
    row = evidence["retained_control"]
    assert verified_scope_exclusions(observation(new), observation(old),
                                     {(row["provider"], row["product_id"])}) == []


def test_watchdog_reconsiders_existing_real_scope_candidate_without_capture(tmp_path, evidence, monkeypatch):
    import cdr_observation_scope as scope
    import pi_cdr_recovery as recovery
    import pi_daily_sync as sync

    state, _, new, parent = prepared(tmp_path, evidence)
    with monkeypatch.context() as old_rule:
        old_rule.setattr(scope, "verified_scope_exclusions", lambda *_: [])
        marker = complete(new, state, "revision.scope", parent["generation_id"])
    assert selected_observation(state, DATE)["contract"]["generation_id"] == parent["generation_id"]
    refusals = {p: p.read_bytes() for p in (state / "observation-selections-v1" / DATE).glob("*.json")}
    assert len(refusals) == 1
    assert json.loads(next(iter(refusals.values())))["reason"] == "previously_captured_products_missing_without_fresh_withdrawal"
    ledger = {p: p.read_bytes() for p in (state / "ledger-v2").rglob("*.json")}
    monkeypatch.setattr(recovery, "data_state_root", lambda _: state)
    monkeypatch.setattr(sync, "data_state_root", lambda _: state)
    monkeypatch.setattr(recovery, "recovery_block_reason", lambda *a, **k: "")
    probe = Mock(side_effect=AssertionError("must not contact provider"))
    launch = Mock(side_effect=AssertionError("must not recapture"))
    monkeypatch.setattr(recovery, "probe_register", probe)
    report = recovery.run_same_day_recovery(
        tmp_path, now_utc=datetime(2026, 9, 12, 20, tzinfo=timezone.utc), dry_run=False, launch=launch,
    )
    assert report["status"] == "finalized_selection_recovered"
    assert report["publication_required"] and report["capture_attempted"] is False
    assert selected_observation(state, DATE)["contract"]["generation_id"] == marker["generation_id"]
    assert sync.pending_publication_pointer(tmp_path)["generation_id"] == marker["generation_id"]
    receipts = list((state / "observation-selections-v1" / DATE).glob("*.json"))
    assert len(receipts) == 2
    accepted = next(json.loads(p.read_bytes()) for p in receipts if json.loads(p.read_bytes())["selected"])
    assert accepted["scope_reconciliation"]["scope_excluded_rate_rows"] == 30
    assert all(path.read_bytes() == body for path, body in {**refusals, **ledger}.items())
    probe.assert_not_called()
    launch.assert_not_called()
