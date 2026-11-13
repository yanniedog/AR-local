"""Incomplete-capture change guards replaying retained Defence Bank details."""
import json
from pathlib import Path

import pytest

from cdr_outputs import _exclude_failed_missing_product_groups, _exclude_failed_missing_products
from cdr_product_changes import diff_normalized_product_fact_groups
from cdr_product_facts import clean_fact_rows


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
