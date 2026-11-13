"""Incomplete-capture change guards replaying retained Defence Bank details."""
import json
from pathlib import Path

import pytest

from cdr_outputs import _exclude_failed_missing_product_groups, _exclude_failed_missing_products
from cdr_product_changes import diff_normalized_product_fact_groups
from cdr_product_facts import clean_fact_rows

import cdr_outputs


def captured_facts():
    fixture = Path(__file__).parent / "fixtures" / "cdr-september7" / "defence.json"
    record = json.loads(fixture.read_text())["product_detail"]["body"]["data"]
    base = {
        "provider": "Defence Bank", "product_id": record["productId"],
        "dataset": "TD", "product_name": record["name"],
        "product_key": "TD|Defence Bank|" + record["productId"],
    }
    return clean_fact_rows(record, base), (base["provider"], base["product_id"], base["dataset"])


@pytest.mark.parametrize("phase", ["product_detail", "classification_detail"])
def test_failed_detail_classification_never_becomes_product_removal(phase):
    previous, key = captured_facts()
    # Failure metadata varies; all product/fact values remain captured source.
    failures = [{"phase": phase, "bank": key[0], "product_id": key[1], "status": 503}]
    flat, count = _exclude_failed_missing_products(previous, [], failures)
    groups, counters = _exclude_failed_missing_product_groups(iter([(key, previous)]), [], failures)
    diff = diff_normalized_product_fact_groups(groups, [])

    assert not flat and count == counters["suppressed"] == 1
    assert diff["events"] == []


def test_successfully_captured_product_is_compared_despite_prior_failure():
    previous, key = captured_facts()
    failures = [{"phase": "classification_detail", "bank": key[0], "product_id": key[1], "status": 503}]
    groups, counters = _exclude_failed_missing_product_groups(iter([(key, previous)]), previous, failures)
    diff = diff_normalized_product_fact_groups(groups, previous)

    assert counters["suppressed"] == 0
    assert diff["products"]["joined"] == 1 and diff["events"] == []


def test_absence_without_recorded_detail_failure_preserves_existing_removal_behavior():
    previous, key = captured_facts()
    groups, counters = _exclude_failed_missing_product_groups(iter([(key, previous)]), [], [])
    diff = diff_normalized_product_fact_groups(groups, [])

    assert counters["suppressed"] == 0
    assert any(event["event_type"] == "product_removed" for event in diff["events"])


def westpac_groups():
    """Identity/metadata facts from the actual nonempty index preceding the outage."""
    fixture = Path(__file__).parent / "fixtures" / "ingest-capture-20261015" / "westpac-prior-page1.json"
    products = json.loads(fixture.read_text())["data"]["products"]
    groups = []
    for record in products:
        if record["productCategory"] != "TRANS_AND_SAVINGS_ACCOUNTS":
            continue
        base = {"provider": "Westpac", "product_id": record["productId"], "dataset": "Savings",
                "product_name": record["name"], "product_key": "Savings|Westpac|" + record["productId"]}
        groups.append((("Westpac", record["productId"], "Savings"), clean_fact_rows(record, base)))
        if len(groups) == 2:
            return groups
    raise AssertionError("retained index no longer contains the two test products")


def test_export_empty_successful_index_does_not_emit_prior_product_removals(tmp_path, monkeypatch):
    root = tmp_path / "2026-10-15"
    pages = root / "banks" / "_holders" / "Westpac" / "_products-index"
    pages.mkdir(parents=True)
    fixture = Path(__file__).parent / "fixtures" / "ingest-capture-20261015" / "westpac-empty.json"
    (pages / "page-0001.json").write_bytes(fixture.read_bytes())
    # Isolate prior streaming/storage; identity and metadata facts are captured,
    # and the current run uses the untouched real HTTP-200 empty response.
    monkeypatch.setattr(cdr_outputs, "iter_run_fact_groups", lambda _: iter(westpac_groups()))
    cdr_outputs.build_outputs(root, previous_run_root=tmp_path / "2026-10-14")
    export = json.loads((root / "_exports" / "banks-2026-10-15.json").read_text())

    assert export["products"] == export["failures"] == export["product_changes"] == []
    assert export["product_change_summary"]["suppressed_incomplete_products"] == 2
    assert export["product_change_summary"]["suppression_reasons"] == {"provider_population_absent": 2}


@pytest.mark.parametrize("phase", [None, "products_index", "holder", "product_detail", "classification_detail"])
def test_partial_capture_suppresses_but_complete_nonempty_provider_allows_removal(phase):
    previous = westpac_groups()
    missing_key = previous[0][0]
    current = previous[1][1]
    failures = [] if phase is None else [{
        "phase": phase, "bank": "Westpac", "product_id": missing_key[1], "status": 503,
    }]
    groups, counters = _exclude_failed_missing_product_groups(
        iter(previous), current, failures, current_providers=["Westpac"],
    )
    diff = diff_normalized_product_fact_groups(groups, current)
    removals = [event for event in diff["events"] if event["event_type"] == "product_removed"]

    assert counters["suppressed"] == (0 if phase is None else 1)
    assert len(removals) == (1 if phase is None else 0)
    if removals:
        assert removals[0]["product_id"] == missing_key[1]


def test_unknown_provider_rename_does_not_authorize_removal():
    previous = westpac_groups()
    groups, counters = _exclude_failed_missing_product_groups(
        iter(previous), [], [], current_providers=["Renamed provider"],
    )
    assert diff_normalized_product_fact_groups(groups, [])["events"] == []
    assert counters["reasons"] == {"provider_population_absent": 2}
    flat, count = _exclude_failed_missing_products(
        [fact for _, facts in previous for fact in facts], [], [],
        current_providers=["Renamed provider"],
    )
    assert not flat and count == 2
