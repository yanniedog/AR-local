"""Coverage inventory includes new and unpriced public register brands."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cdr_public_rates_coverage import coverage_baseline


def core():
    return {"run_date": "2026-10-14", "sections": {"Mortgage": {"rates": [{"provider": "NAB", "product_key": "public-product"}]},
        "Savings": {"rates": []}, "TD": {"rates": []}}, "coverage": {"provider_failures": []}}


def test_every_public_banking_brand_has_all_three_categories():
    register = json.loads((Path(__file__).parent / "fixtures/public_rates/cdr-register-20261014.json").read_bytes())
    result = coverage_baseline(register, core(), register_sha256="1"*64, core_sha256="2"*64)
    assert result["counts"]["providersInPublicBankingRegister"] == 116
    assert result["counts"]["providerCategories"] == 348
    assert {entry["section"] for entry in result["coverage"]} == {"Mortgage", "Savings", "TD"}
    assert len({(entry["providerId"], entry["section"]) for entry in result["coverage"]}) == 348
    assert any(entry["providerIdentityStatus"] == "interim" for entry in result["coverage"])
    assert all(entry["resolutionStatus"] == "unvalidated_legacy_pricing" for entry in result["coverage"])
    assert result["publication"] == "disabled"


def test_new_unpriced_provider_survives_and_similar_name_does_not_share_prices():
    register = {"data": [{"dataHolderBrandId": "new-brand", "brandName": "NAB Similar Name", "industries": ["banking"],
                          "publicBaseUri": "https://new-public.example.test/cdr"}]}
    result = coverage_baseline(register, core(), register_sha256="1"*64, core_sha256="2"*64)
    assert len(result["coverage"]) == 3
    assert all(entry["products"] == 0 and entry["sourceStatus"] == "unavailable" for entry in result["coverage"])
    assert result["legacyProviderNamesRequiringIdentityReconciliation"] == ["NAB"]
    register["data"].append(register["data"][0])
    with pytest.raises(ValueError, match="duplicate_public_register"):
        coverage_baseline(register, core(), register_sha256="1"*64, core_sha256="2"*64)
