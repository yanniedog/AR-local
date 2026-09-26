"""Retained Bankwest rows, with explicit storage/selection fault controls."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from app_payload_bank_rate_source import historical_banks
from app_payload_bank_rates import attach_history, embed_bank_rate_history
from app_payload_common import CORE_RATE_FIELDS, VALID_SECTIONS, compact, section_filter
from cdr_finalization import finalize_observation
from tests.test_irreplaceable_finalization import make_export

DAY = "2026-09-13"
FIXTURE = Path(__file__).parent / "fixtures/bankwest_history_real_2026-09-06_to_13.json"


@pytest.fixture
def banks():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "79a2e923685ea9a7f021dc9a1572986c13edbf8c23e9e0eabec1cdc0db73c941"
    observation = next(row for row in json.loads(raw)["observations"] if row["date"] == DAY)
    products = observation["queries"]["bank_products"]["rows"]
    rates = [{"category": products[0]["category"], **row}
             for row in observation["queries"]["bank_rates"]["rows"]]
    return {"run_date": DAY, "rates": rates, "products": products}


def save_export(tmp_path, banks, revision=None, *, finalize=True):
    root = tmp_path / "runs" / DAY
    if revision:
        root = root / "_revisions" / revision
    exports = root / "_exports"
    # Operational metadata controls are separate from the unchanged real rates.
    make_export(exports, observation_date=DAY)
    latest_path = exports / "dashboard-cache/latest.json"
    latest = json.loads(latest_path.read_bytes())
    latest["banks_counts"].update(products=len(banks["products"]), rates=len(banks["rates"]))
    latest_path.write_text(json.dumps(latest), encoding="utf-8")
    path = exports / "dashboard-cache" / DAY / "banks.json"
    path.parent.mkdir()
    path.write_text(json.dumps(banks, ensure_ascii=False), encoding="utf-8")
    if finalize:
        state = tmp_path / "state"
        finalize_observation(exports, state, state / (revision or "original"), observation_date=DAY,
                             result={"run_date": DAY, "banks_counts": latest["banks_counts"]})
    return exports


def current_core(banks):
    return {"run_date": DAY, "sections": {
        section: {"rates": [compact({k: row.get(k) for k in CORE_RATE_FIELDS}) for row in banks["rates"]
                            if row["dataset"] == section and section_filter(section, row)]}
        for section in VALID_SECTIONS}}


def test_selected_revision_wins_over_original_and_newer_unselected_export(tmp_path, banks):
    # The first storage copy has one missing retained row; no rate is invented.
    incomplete = {**banks, "rates": banks["rates"][:-1]}
    original = save_export(tmp_path, incomplete)
    selected = save_export(tmp_path, banks, "corrected")
    save_export(tmp_path, incomplete, "zz-newer-rejected")
    pointer = json.loads((tmp_path / "state/observation-pointers-v2/latest-observation.json").read_bytes())
    assert pointer["export_path"] == selected.relative_to(tmp_path).as_posix()
    before = {path: path.read_bytes() for path in tmp_path.rglob("banks.json")}
    actual = current_core(banks)
    expected = deepcopy(actual)
    attach_history(expected, [(DAY, {section: data["rates"] for section, data in actual["sections"].items()})], [DAY])
    embed_bank_rate_history(actual, original)
    assert actual.pop("bank_rate_history_catalogue")["schema_version"] == 2
    assert actual == expected
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_historical_selection_still_wins_after_global_pointer_advances(tmp_path, banks):
    original = save_export(tmp_path, {**banks, "rates": banks["rates"][:-1]})
    selected = save_export(tmp_path, banks, "corrected")
    pointer_path = tmp_path / "state/observation-pointers-v2/latest-observation.json"
    pointer = json.loads(pointer_path.read_bytes())
    pointer["observation_date"] = "2026-09-14"  # Pointer-routing fault control only.
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    assert historical_banks(original, DAY, {}) == banks
    assert selected != original


def test_historical_refusal_then_acceptance_of_same_generation_keeps_accepted_source(tmp_path, banks):
    from cdr_atomic import canonical_json_bytes
    original = save_export(tmp_path, {**banks, "rates": banks["rates"][:-1]})
    save_export(tmp_path, banks, "corrected")
    (tmp_path / "state/observation-pointers-v2/latest-observation.json").unlink()
    folder = tmp_path / "state/observation-selections-v1" / DAY
    accepted = json.loads(next(folder.glob("*.json")).read_bytes())
    assert accepted["selected"] is True
    # Operational receipt replay mirrors the real Sep13 refusal/reconsideration;
    # the immutable candidate, events and financial source rows are unchanged.
    refused = {**accepted, "selected": False,
               "reason": "previously_captured_products_missing_without_fresh_withdrawal"}
    raw = canonical_json_bytes(refused)
    (folder / (hashlib.sha256(raw).hexdigest() + ".json")).write_bytes(raw)
    assert historical_banks(original, DAY, {}) == banks


@pytest.mark.parametrize("fault", ["bytes", "missing", "symlink"])
def test_selected_source_corruption_never_falls_back_to_original(tmp_path, banks, fault):
    original = save_export(tmp_path, {**banks, "rates": banks["rates"][:-1]})
    selected = save_export(tmp_path, banks, "corrected")
    path = selected / "dashboard-cache" / DAY / "banks.json"
    if fault == "bytes":
        path.write_text("{}", encoding="utf-8")
    else:
        path.unlink()
        if fault == "symlink":
            try:
                path.symlink_to(original / "dashboard-cache" / DAY / "banks.json")
            except OSError:
                pytest.skip("Symlink creation is unavailable")
    with pytest.raises(ValueError, match="source"):
        historical_banks(original, DAY, {})


def test_missing_historical_selection_is_explicit_gap(tmp_path, banks):
    original = save_export(tmp_path, {**banks, "rates": banks["rates"][:-1]})
    save_export(tmp_path, banks, "corrected")
    (tmp_path / "state/observation-pointers-v2/latest-observation.json").unlink()
    for path in (tmp_path / "state/observation-selections-v1" / DAY).glob("*.json"):
        path.unlink()
    core = current_core(banks)
    embed_bank_rate_history(core, original)
    history = core["bank_rate_history"]
    assert history["run_dates"] == [DAY]
    assert history["unavailable_dates"] == {DAY: "historical_selection_unresolved"}
    assert all(not spans for spans in history["sections"]["Savings"])


def test_single_legacy_export_remains_readable_but_competing_exports_are_unknown(tmp_path, banks):
    original = save_export(tmp_path, banks, finalize=False)
    assert historical_banks(original, DAY, {}) == banks
    save_export(tmp_path, banks, "unbound", finalize=False)
    unavailable = {}
    assert historical_banks(original, DAY, unavailable) == {}
    assert unavailable == {DAY: "historical_selection_unresolved"}


def test_corrupt_single_contract_is_not_treated_as_uncontracted_legacy(tmp_path, banks):
    original = save_export(tmp_path, banks)
    (tmp_path / "state/observation-pointers-v2/latest-observation.json").unlink()
    path = next((tmp_path / "state/export-contracts-v2" / DAY).glob("*.json"))
    path.write_text("invalid JSON", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid retained contract"):
        historical_banks(original, DAY, {})


@pytest.mark.parametrize("rates", [None, "corrupt", {}, [None], ["corrupt"]])
def test_malformed_legacy_rates_are_rejected_instead_of_blank_history(tmp_path, banks, rates):
    exports = save_export(tmp_path, banks, finalize=False)
    path = exports / "dashboard-cache" / DAY / "banks.json"
    # Invalid container shapes are storage fault controls, never financial rows.
    path.write_text(json.dumps({**banks, "rates": rates}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid rates schema"):
        historical_banks(exports, DAY, {})


def test_shared_observed_axis_preserves_calendar_gap_with_real_bankwest_rows(tmp_path, banks):
    from app_payload_bank_rates import bank_rate_history_rows
    from app_payload_mobile import build_history_assets
    from cdr_ribbon_normalize import normalized_rate_value

    observations = json.loads(FIXTURE.read_bytes())["observations"]
    days = ["2026-09-06", DAY]
    for day in days:
        observation = next(row for row in observations if row["date"] == day)
        products = observation["queries"]["bank_products"]["rows"]
        rows = [{"category": products[0]["category"], **row}
                for row in observation["queries"]["bank_rates"]["rows"]]
        folder = tmp_path / "dashboard-cache" / day
        folder.mkdir(parents=True)
        (folder / "banks.json").write_text(json.dumps({"run_date": day, "rates": rows}), encoding="utf-8")
    core = current_core(banks)
    _, aggregate = build_history_assets(
        tmp_path, run_date=DAY, load_json=lambda path: json.loads(path.read_bytes()),
        section_filter=section_filter, normalized_rate_value=normalized_rate_value,
        observations=bank_rate_history_rows(core, tmp_path), rba_calendar=[])
    assert aggregate["run_dates"] == days
    history = core["bank_rate_history"]
    assert len(history["run_dates"]) == 8
    assert history["run_dates"][0] == days[0] and history["run_dates"][-1] == days[-1]
    savings_spans = [span for series in history["sections"]["Savings"] for span in series]
    assert savings_spans
    assert all(start in (0, 7) and length == 1 for start, length, _ in savings_spans)


def test_standalone_dated_and_rolling_cores_have_identical_complete_history(tmp_path, banks, monkeypatch):
    import app_payload_build as builder
    exports = save_export(tmp_path, banks)
    monkeypatch.setattr(builder.cdr_brand_logos, "fetch_register_logos", lambda **_: {})
    monkeypatch.setenv("AR_LOCAL_RBA_OFFICIAL_FETCH", "0")
    results = []
    for tag in ("app-payload-" + DAY, "app-payload-latest"):
        folder = tmp_path / tag
        manifest = builder.build_payload(exports, folder, tag=tag)
        core = json.loads(gzip.decompress((folder / manifest["files"]["core"]["name"]).read_bytes()))
        assert core["bank_rate_history"]["run_dates"] == [DAY]
        assert any(core["bank_rate_history"]["sections"]["Savings"])
        results.append(manifest["files"]["core"]["sha256"])
    assert results[0] == results[1]


def test_rolling_tiers_reuse_aggregate_read_pass(tmp_path, banks, monkeypatch):
    import app_payload_build as builder
    exports = save_export(tmp_path, banks)
    monkeypatch.setattr(builder.cdr_brand_logos, "fetch_register_logos", lambda **_: {})
    monkeypatch.setenv("AR_LOCAL_RBA_OFFICIAL_FETCH", "0")
    target = exports / "dashboard-cache" / DAY / "banks.json"
    reads = []
    for method in ("read_bytes", "read_text"):
        original = getattr(Path, method)

        def read(path, *args, _read=original, **kwargs):
            if path == target:
                reads.append(path)
            return _read(path, *args, **kwargs)

        monkeypatch.setattr(Path, method, read)
    builder._compute_payload(exports)
    # Current catalogue, combined tier/aggregate pass, and existing spread pass.
    assert len(reads) == 3


def test_current_payload_rejects_an_unselected_export_before_building(tmp_path, banks):
    from app_payload_build import _compute_payload
    original = save_export(tmp_path, {**banks, "rates": banks["rates"][:-1]})
    save_export(tmp_path, banks, "corrected")
    with pytest.raises(ValueError, match="not the selected observation"):
        _compute_payload(original)


def test_unknown_observation_breaks_aggregate_rate_move_chain(tmp_path, monkeypatch):
    import app_payload_mobile as mobile
    from cdr_ribbon_normalize import normalized_rate_value
    fixture = json.loads(FIXTURE.read_bytes())["observations"]
    stream = []
    for observation in fixture[-3:]:
        day = observation["date"]
        rows = observation["queries"]["bank_rates"]["rows"]
        folder = tmp_path / "dashboard-cache" / day
        folder.mkdir(parents=True)
        (folder / "banks.json").write_text(json.dumps({"run_date": day, "rates": rows}), encoding="utf-8")
        # Missing selected source is an explicit storage/evidence fault control.
        stream.append((day, [] if day == "2026-09-12" else rows))
    seen = []
    original = mobile._provider_events

    def events(day, section, previous, providers):
        seen.append((day, section, deepcopy(previous)))
        return original(day, section, previous, providers)

    monkeypatch.setattr(mobile, "_provider_events", events)
    mobile.build_history_assets(tmp_path, run_date=DAY, load_json=lambda path: json.loads(path.read_bytes()),
                                section_filter=section_filter, normalized_rate_value=normalized_rate_value,
                                observations=iter(stream), rba_calendar=[])
    assert any(day == DAY and section == "Savings" for day, section, _ in seen)
    assert all(not previous for day, _, previous in seen if day == DAY)


def test_retained_evidence_does_not_borrow_identity_or_later_details(banks):
    from app_payload_bank_catalogue import retained_evidence
    product = banks["products"][0]
    key = product["product_key"]
    assert retained_evidence([product])[key]["status"] == "known"
    assert retained_evidence([{**product, "details_json": "{}"}])[key] == {"status": "unknown"}
    corrupt = {**product, "provider": "identity mismatch control"}
    assert key not in retained_evidence([product, corrupt])
