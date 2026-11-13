"""Publication protocol controls, not synthetic business acceptance evidence."""
import copy
import json
from pathlib import Path

import pytest

import app_payload_build
import app_payload_observation_gate as gate
import pi_daily_sync
from app_payload_retained_policy import retained_partial_allowed
from app_payload_source_verification import verify_reconciled_source
from cdr_export_contract import build_contract, load_contract
from tests.test_app_payload_partial_accounting import seal
from cdr_finalization import finalize_observation
from tests.test_irreplaceable_finalization import make_export

DAY = "2026-10-29"


@pytest.mark.parametrize("finding", [
    {"provider": "Wise"},
    {"provider": "Wise", "population_known": True, "disposition": "UNVERIFIED_SOURCE_ABSENCE"},
    {"provider": "Wise", "population_known": False, "disposition": "other"},
])
def test_incomplete_population_metadata_does_not_authorize_recovery(finding):
    from cdr_population_coverage import has_unverified_provider_population
    assert not has_unverified_provider_population({"coverage": {"provider_population_unverified": [finding]}})


def retained_accounting(tmp_path, day=DAY):
    """Retained real counts; only the protocol date is varied for policy tests."""
    retained = json.loads((Path(__file__).parent / "fixtures" /
                           "publication-accounting-2026-09-22.json").read_bytes())
    return build_contract(tmp_path, observation_date=day,
        observed_at=f"{day}T01:00:00+11:00", observation_state="partial",
        source_path=f"runs/{day}/_exports", completion_marker_path=f"{day}.done.json",
        coverage=retained["coverage"], provider_states=retained["provider_states"],
        register_hashes=retained["register_hashes"], artifacts=[retained["artifact"]],
        normalization_version="protocol-policy-date-control")


@pytest.mark.parametrize("day,expected", [("2026-10-28", False), (DAY, True), ("2026-11-13", True)])
def test_standing_policy_date_scope(tmp_path, day, expected):
    contract = retained_accounting(tmp_path, day)
    assert retained_partial_allowed(contract) is expected
    assert gate.publication_allowed(contract)[1] == ("retained_partial" if expected else "reconciled_partial")


@pytest.mark.parametrize("field", ["contract_digest", "source_generation_digest", "generation_id"])
def test_standing_policy_never_accepts_unsealed_identity(tmp_path, field):
    contract = retained_accounting(tmp_path)
    contract[field] = "0" * 64
    assert not retained_partial_allowed(contract)
    assert gate.publication_allowed(contract) == (False, "invalid_retained_partial")


@pytest.mark.parametrize("state", ["failed", "unknown", "complete"])
def test_standing_partial_policy_cannot_relabel_other_states(tmp_path, state):
    contract = retained_accounting(tmp_path)
    contract["observation_state"] = state
    assert not retained_partial_allowed(contract)


@pytest.mark.parametrize("field", ["products_discovered", "eligible_rate_rows"])
@pytest.mark.parametrize("value", [0, -1, True, "1", None])
def test_standing_policy_requires_nonempty_usable_population(tmp_path, field, value):
    contract = retained_accounting(tmp_path)
    contract["coverage"][field] = value
    seal(contract)
    assert not retained_partial_allowed(contract)
    assert gate.publication_allowed(contract) == (False, "invalid_retained_partial")


def finalized_population_control(tmp_path, *, status="worker_crash", failures=1):
    exports, state = tmp_path / "runs" / DAY / "_exports", tmp_path / "state"
    make_export(exports, failures=failures, observation_date=DAY)
    status_path = exports / "ingest-status.json"
    data = json.loads(status_path.read_bytes())
    data["by_status"] = {status: failures} if failures else {}
    status_path.write_text(json.dumps(data), encoding="utf8")
    # Protocol uncertainty control; no product/rate row is invented.
    (exports / "provider-population-report.json").write_text(json.dumps({
        "run_date": DAY, "provider_population": {"status": "WARN", "findings": [{
            "provider": "provider-a", "code": "provider_population_disappeared",
            "population_known": False, "disposition": "UNVERIFIED_SOURCE_ABSENCE"}]}}), encoding="utf8")
    marker = finalize_observation(exports, state, state / f"{DAY}.done.json",
        observation_date=DAY, result={"run_date": DAY, "banks_counts": {"rates": 7}})
    contract = load_contract(state / marker["export_contract_path"])
    return exports, state, contract


def test_population_uncertainty_and_unknown_status_publish_as_partial(tmp_path):
    exports, state, contract = finalized_population_control(tmp_path)
    original = copy.deepcopy(contract)
    assert gate.publication_allowed(contract) == (True, "retained_partial")
    assert verify_reconciled_source(state, exports, DAY, contract)
    coverage = gate.contract_coverage(contract)
    public = app_payload_build._stable_payload_coverage({}, {}, DAY, coverage)
    assert public["observation_state"] == "partial"
    assert public["provider_population_unverified"] == contract["coverage"]["provider_population_unverified"]
    assert public["publication_policy"]["previous_verdict"] == "unverified_provider_population"
    assert public["publication_policy"]["absence_is_removal"] is False
    assert public["provider_observations"][0]["population_known"] is False
    assert contract == original


def test_provider_disclosure_excludes_transport_urls(tmp_path):
    public = gate.contract_coverage(retained_accounting(tmp_path))
    assert len(public["provider_observations"]) == 117
    assert all("endpoint_url" not in p for p in public["provider_observations"])
    assert any(p.get("brand_name") for p in public["provider_observations"])


def test_historical_population_disclosure_strips_nested_transport(tmp_path):
    _, _, contract = finalized_population_control(tmp_path)
    finding = contract["coverage"]["provider_population_unverified"][0]
    finding["provider_identity"] = {"endpoint_url": "https://private.example/transport"}
    finding["historical_absence"] = {"provider_identity": finding["provider_identity"]}
    finding["last_nonempty"] = {"observation_date": "2026-10-28", "products": 4,
                                "rates": 7, "endpoint_url": "https://private.example/transport"}
    seal(contract)
    public = app_payload_build._stable_payload_coverage({}, {}, DAY, gate.contract_coverage(contract))
    disclosed = public["provider_population_unverified"][0]
    assert disclosed["provider"] == finding["provider"]
    assert disclosed["last_nonempty"] == {"observation_date": "2026-10-28", "products": 4, "rates": 7}
    assert "endpoint_url" not in json.dumps(disclosed)
    assert "private.example" not in json.dumps(disclosed)
    direct = app_payload_build._stable_payload_coverage({}, {}, DAY, contract["coverage"])
    assert direct["provider_population_unverified"] == public["provider_population_unverified"]


@pytest.mark.parametrize("fault", ["status", "artifact", "marker", "contract", "event", "source"])
def test_standing_policy_still_rejects_tampered_source(tmp_path, fault):
    exports, state, contract = finalized_population_control(tmp_path)
    if fault == "status":
        (exports / "ingest-status.json").write_text("{}", encoding="utf8")
    elif fault == "artifact":
        (exports / "banks.json").write_text("{}", encoding="utf8")
    elif fault == "marker":
        (state / contract["completion_marker_path"]).write_text("{}", encoding="utf8")
    elif fault == "contract":
        contract["coverage"]["failure_records"] += 1
    elif fault == "event":
        (state / "ledger-v2" / "events" / DAY / f'{contract["generation_id"]}.json').write_text("{}", encoding="utf8")
    else:
        exports = tmp_path / "wrong-source"
    assert not verify_reconciled_source(state, exports, DAY, contract)


def test_natural_daily_path_publishes_same_finalized_partial_with_disclosure(tmp_path, monkeypatch):
    import app_payload
    exports, state, contract = finalized_population_control(tmp_path)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _: state)
    monkeypatch.setattr(pi_daily_sync, "v2_publication_allowed", lambda: False)
    monkeypatch.setattr(app_payload, "refresh_dates_index", lambda *a, **k: None)
    built = []
    def build(source, **kwargs):
        built.append((source, kwargs))
        return {"run_date": DAY}, True, True
    monkeypatch.setattr(app_payload, "build_and_publish_dual", build)
    assert pi_daily_sync.maybe_publish_app_payload(tmp_path) == pi_daily_sync.PUBLISH_PUBLISHED
    assert built[0][0] == exports
    assert built[0][1]["source_observation"]["contract_digest"] == contract["contract_digest"]
    assert built[0][1]["contract_coverage"]["publication_policy"]["id"] == "best-available-retained-v1"


def test_zero_capture_never_reaches_natural_publisher(tmp_path, monkeypatch):
    import app_payload
    exports, state = tmp_path / "runs" / DAY / "_exports", tmp_path / "state"
    make_export(exports, failures=1, observation_date=DAY)
    cache = exports / "dashboard-cache/latest.json"
    latest = json.loads(cache.read_bytes())
    latest["banks_counts"].update(products=0, rates=0)
    cache.write_text(json.dumps(latest), encoding="utf8")
    marker = finalize_observation(exports, state, state / f"{DAY}.done.json",
        observation_date=DAY, result={"run_date": DAY, "banks_counts": {"rates": 0}})
    contract = load_contract(state / marker["export_contract_path"])
    assert contract["observation_state"] == "partial"
    assert not gate.publication_allowed(contract)[0]
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _: state)
    monkeypatch.setattr(app_payload, "build_and_publish_dual", lambda *a, **k: pytest.fail("empty capture published"))
    assert pi_daily_sync.maybe_publish_app_payload(tmp_path) == pi_daily_sync.PUBLISH_WITHHELD
