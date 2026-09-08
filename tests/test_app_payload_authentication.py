"""Public credential failures cannot strand unrelated, valid daily rates."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest import mock

import pytest

import app_payload_build
import app_payload_observation_gate as gate
import cdr_ingest_lib as ingest
import cdr_ingest_support as support
import pi_daily_sync
from cdr_compatibility import classify_fetch_failure
from cdr_finalization import finalize_observation
from cdr_raw_attempt_journal import RawAttemptJournal
from tests.test_app_payload_observation_gate import _banks_with_coverage, _contract, _load_backfill


AUTH = "public_endpoint_auth_required"
CAPTURED = json.loads((Path(__file__).parent / "fixtures/cdr-september7/failures.json").read_text())
AUTH_RESPONSES = [row for row in CAPTURED if "requires API Key" in row["body"]]


def _auth_contract(*, auth=1200, other=17, failed=False):
    providers = [{
        "provider_uid": f"provider-{index}", "brand_name": f"Provider {index}",
        "state": "complete", "failure_records": 0, "failure_categories": {},
    } for index in range(118)]
    for index in range(20):
        providers[index].update(
            state="failed" if failed else "partial", failure_records=auth // 20,
            failure_categories={AUTH: auth // 20},
        )
    if other:
        providers[-1].update(state="partial", failure_records=other,
                             failure_categories={"transient_upstream": other})
    contract = _contract(
        failure_records=auth + other, providers_partial=(0 if failed else 20) + bool(other),
        providers_failed=20 if failed else 0,
    )
    contract["provider_states"] = providers
    return contract


@pytest.mark.parametrize("row", AUTH_RESPONSES, ids=lambda row: row["provider"])
def test_each_captured_bank_authentication_response_is_nonblocking(row, tmp_path):
    assert len(AUTH_RESPONSES) == 5
    failure = {"bank": row["provider"], "phase": row["phase"],
               "status": row["status"], "snippet": row["body"]}
    (tmp_path / "failures.jsonl").write_text(json.dumps(failure) + "\n")
    summary = support.summarize_failures(tmp_path)
    assert summary["by_provider_failure_category"] == {row["provider"]: {AUTH: 1}}
    assert summary["total"] == 1 and summary["incomplete"] is True


@pytest.mark.parametrize("status,body", [
    (400, "API key is required"), (400, '{"message":"Missing Authentication Token"}'),
    (400, "Invalid APIKey"), (422, "Subscription key is invalid"),
    (500, "The service requires an API key"), (401, ""), (403, "Forbidden"),
    (407, "Proxy Authentication Required"), (401, '{"error":"invalid_token"}'),
])
def test_new_holders_and_authentication_dialects_need_no_configuration(status, body):
    result = classify_fetch_failure(status, body)
    assert result.category in {AUTH, "access_denied"}
    assert not result.retryable and not result.negotiate


@pytest.mark.parametrize("status,body", [
    (200, "API key required"), (503, "Service unavailable"),
    (495, "API key required"), (599, "authentication required"),
    (406, "Unsupported version; API key required"),
])
def test_non_authentication_failures_keep_their_existing_policy(status, body):
    assert classify_fetch_failure(status, body).category not in {AUTH, "access_denied"}


@pytest.mark.parametrize("failed", [False, True])
def test_authentication_does_not_consume_any_failure_or_provider_budget(failed):
    contract = _auth_contract(failed=failed)
    original = copy.deepcopy(contract)
    assert gate.publication_allowed(contract) == (
        True, "bounded_partial_with_nonblocking_authentication",
    )
    assert contract == original  # The ledger's incomplete coverage is never rewritten.
    public = gate.contract_coverage(contract)
    assert public["failure_records"] == 1217
    assert public["nonblocking_authentication"]["failure_records"] == 1200
    assert len(public["nonblocking_authentication"]["providers"]) == 20


def test_authentication_only_partial_can_publish_a_small_valid_catalogue():
    contract = _auth_contract(other=0)
    contract["coverage"]["products_discovered"] = 1
    assert gate.publication_allowed(contract)[0]


def test_mixed_provider_does_not_hide_other_failures():
    contract = _auth_contract(failed=True)
    provider = contract["provider_states"][0]
    provider["failure_categories"][AUTH] -= 1
    provider["failure_categories"]["invalid_response"] = 1
    assert not gate.publication_allowed(contract)[0]
    assert not gate.publication_allowed(_auth_contract(other=31))[0]


@pytest.mark.parametrize("field,value", [
    ("failure_provenance_complete", False), ("register_provenance_complete", False),
    ("corrupt_failure_records", 1), ("unattributed_failure_records", 1),
    ("providers_attempted", 117), ("register_sources_complete", 0),
    ("products_discovered", 0),
])
def test_authentication_cannot_override_control_plane_or_integrity_failures(field, value):
    contract = _auth_contract()
    contract["coverage"][field] = value
    assert not gate.publication_allowed(contract)[0]


@pytest.mark.parametrize("mutation", [
    lambda c: c.pop("provider_states"),
    lambda c: c["provider_states"][0].pop("failure_categories"),
    lambda c: c["provider_states"][0]["failure_categories"].update({AUTH: -1}),
    lambda c: c["provider_states"][0]["failure_categories"].update({AUTH: True}),
    lambda c: c["provider_states"][0]["failure_categories"].update({AUTH: 61}),
    lambda c: c["provider_states"][0].update(provider_uid="provider-1"),
])
def test_unreconciled_classification_never_grants_a_blanket_exemption(mutation):
    contract = _auth_contract()
    mutation(contract)
    assert not gate.publication_allowed(contract)[0]


def test_recorded_category_cannot_mislabel_a_server_failure_as_authentication(tmp_path):
    row = {"bank": "New Holder", "phase": "products_index", "status": 503,
           "snippet": "Service unavailable", "failure_category": AUTH}
    (tmp_path / "failures.jsonl").write_text(json.dumps(row) + "\n")
    assert support.summarize_failures(tmp_path)["by_provider_failure_category"] == {
        "New Holder": {"transient_upstream": 1},
    }


def test_ingest_binds_classification_to_provider_state(tmp_path):
    root = tmp_path / "banks"
    root.mkdir()
    brand = {"brand_name": "New Holder", "endpoint_url": "https://holder.example/products"}
    directory = support.allocate_bank_dir(brand["brand_name"], "", brand["endpoint_url"], set())
    body = AUTH_RESPONSES[0]["body"]
    (root / "failures.jsonl").write_text(json.dumps({
        "bank": directory, "phase": "products_index", "status": 400, "snippet": body,
    }) + "\n")
    snapshot = support.RegisterSnapshot(
        register_ok=True, register_provenance_complete=True, banking_brands=[brand],
        banking_count_before_filter=1,
        register_attempts=[{"ok": True, "sha256": "a" * 64}],
    )
    status = ingest._persist_ingest_status(
        banks_root=root, run_root=tmp_path, snapshot=snapshot,
        bank_work=[(brand, directory)],
        attempt_journal=RawAttemptJournal(tmp_path / "_raw-attempt-journals-v1", "test"),
    )
    assert status["provider_states"][0]["failure_categories"] == {AUTH: 1}
    assert status["provider_states"][0]["state"] == "partial"


def test_daily_and_backfill_publish_from_the_same_verified_auth_contract(tmp_path, monkeypatch):
    date = "2026-09-07"
    exports, state = tmp_path / "runs" / date / "_exports", tmp_path / "state"
    (exports / "dashboard-cache").mkdir(parents=True)
    contract = _auth_contract(other=0)
    (exports / "dashboard-cache/latest.json").write_text(json.dumps({
        "run_date": date, "banks_counts": {"products": 3027, "rates": 17150},
    }))
    (exports / "ingest-status.json").write_text(json.dumps({
        "total": 1200, "incomplete": True, "failure_provenance_complete": True,
        "register_provenance_complete": True,
        "register_attempts": [{"ok": True, "sha256": "a" * 64}],
        "providers_registered": 118, "providers_attempted": 118,
        "provider_states": contract["provider_states"],
    }))
    finalize_observation(exports, state, state / f"{date}.done.json",
                         observation_date=date, result={"run_date": date, "banks_counts": {"rates": 17150}})
    allowed, reason, finalized = _load_backfill().observation_gate(state, date, force=False)
    assert allowed and reason == "bounded_partial_with_nonblocking_authentication"
    assert finalized["observation_state"] == "partial"
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _: state)
    # Exercise the verified daily gate and its dated/rolling, v2 and index calls;
    # tests never upload a release or contact macro-data services.
    monkeypatch.setattr(pi_daily_sync, "refresh_economic_data", lambda _: None)
    monkeypatch.setattr(pi_daily_sync, "v2_publication_allowed", lambda: True)
    with mock.patch("app_payload.build_and_publish_dual", return_value=({"run_date": date}, True, True)) as publish, \
         mock.patch("app_payload.build_and_publish_v2", return_value=({"run_date": date}, True)) as v2, \
         mock.patch("app_payload.refresh_dates_index") as index:
        assert pi_daily_sync.maybe_publish_app_payload(tmp_path) == pi_daily_sync.PUBLISH_PUBLISHED
    assert publish.call_args.kwargs["contract_coverage"]["nonblocking_authentication"]["failure_records"] == 1200
    v2.assert_called_once()
    index.assert_called_once()


def test_payload_discloses_authentication_gaps_without_subtracting_failure_totals():
    contract = _auth_contract()
    public = app_payload_build._stable_payload_coverage(
        _banks_with_coverage(), {}, "2026-09-07", contract_coverage=gate.contract_coverage(contract),
    )
    assert public["counts"]["providers_partial"] == 21
    assert public["nonblocking_authentication"]["failure_records"] == 1200
    assert len(public["nonblocking_authentication"]["providers"]) == 20
