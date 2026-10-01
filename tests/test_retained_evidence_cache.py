"""Memoization cannot donate facts across dates, identities or conflicting copies."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import app_payload_bank_catalogue as catalogue


@pytest.fixture
def product():
    fixture = json.loads((Path(__file__).parent / "fixtures/product_facts_real_2026-05-19.json").read_bytes())
    source = fixture["products"][0]
    record = source["record"]
    return {"dataset": source["dataset"], "provider": source["provider"],
            "product_id": record["productId"], "product_key": source["provider"] + "|" + record["productId"],
            "category": "RESIDENTIAL_MORTGAGES", "details_json": record}


def test_identical_retained_inputs_reuse_projection_without_return_aliases(product):
    cache = catalogue.RetainedEvidenceCache()
    expected = catalogue.retained_evidence([product])
    with patch.object(catalogue, "feature_facts", wraps=catalogue.feature_facts) as facts:
        for _ in range(3):
            result = catalogue.retained_evidence([product], cache=cache)
            assert result == expected
            result[product["product_key"]]["detail"]["description"] = "consumer mutation"
        assert facts.call_count == 1


@pytest.mark.parametrize("field", ["details_json", "details_order", "description", "provider", "product_key", "product_id", "category", "dataset"])
def test_changed_historical_evidence_is_recomputed(product, field):
    cache = catalogue.RetainedEvidenceCache()
    catalogue.retained_evidence([product], cache=cache)
    changed = deepcopy(product)
    if field == "details_json":
        changed[field]["features"].clear()  # Withdrawn declaration control.
    elif field == "details_order":
        changed["details_json"] = dict(reversed(list(changed["details_json"].items())))
    else:
        changed[field] = str(changed.get(field, "")) + " changed source control"
    assert catalogue.retained_evidence([changed], cache=cache) == catalogue.retained_evidence([changed])
    assert catalogue.retained_evidence([product], cache=cache) == catalogue.retained_evidence([product])


def test_conflicting_product_copies_are_not_resolved_by_the_cache(product):
    cache = catalogue.RetainedEvidenceCache()
    catalogue.retained_evidence([product], cache=cache)
    changed = deepcopy(product)
    changed["details_json"]["productId"] = "wrong identity control"
    assert catalogue.retained_evidence([product, changed], cache=cache) == {}


@pytest.mark.parametrize("limits", [{"max_entries": 1}, {"max_bytes": 1}])
def test_cache_is_bounded_and_eviction_preserves_evidence(product, limits):
    cache = catalogue.RetainedEvidenceCache(**limits)
    changed = deepcopy(product)
    changed["description"] = "changed source control"
    with patch.object(catalogue, "feature_facts", wraps=catalogue.feature_facts) as facts:
        for source in (product, changed, product):
            cached = catalogue.retained_evidence([source], cache=cache)
            assert cached == catalogue.retained_evidence([source])
            assert len(cache.entries) <= cache.max_entries
            assert cache.bytes <= cache.max_bytes
        assert facts.call_count == 6
