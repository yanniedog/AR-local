from __future__ import annotations

import json
from pathlib import Path

import pytest

from cdr_contracts import canonical_authority, parse_rate_string, product_uid, provider_uid
from cdr_ingest_support import iter_banking_brands_from_payload


FIXTURES = Path(__file__).parent / "fixtures"


def test_real_register_brand_uses_stable_fallback_when_holder_id_is_absent() -> None:
    item = json.loads(
        (FIXTURES / "register_brand_summary_real_2026-09-02.json").read_text(encoding="utf-8")
    )["record"]
    uid, status = provider_uid(
        data_holder_id=item.get("dataHolderId"),
        data_holder_brand_id=item.get("dataHolderBrandId"),
        endpoint_urls=(item["publicBaseUri"], item["productBaseUri"]),
        display_name=item["brandName"],
    )
    assert status == "fallback"
    assert uid == "provider-fallback:v1:5b62d1baa4af7c75f2fcbc90f3bdc57478e44145fac9a47fe4c9d36858a51fb4"


def test_real_register_brand_parser_preserves_identity_evidence() -> None:
    payload = json.loads(
        (FIXTURES / "register_brand_summary_real_2026-09-02.json").read_text(encoding="utf-8")
    )
    row = next(iter(iter_banking_brands_from_payload({"data": [payload["record"]]})))
    assert row == {
        "brand_name": "Alex.Bank",
        "legal_entity_name": "",
        "endpoint_url": "https://public.cdr.alex.com.au/cds-au/v1/banking/products",
        "data_holder_id": "",
        "data_holder_brand_id": "ceca4dce-3f8f-ef11-95f6-000d3a79c46e",
        "provider_uid": "provider-fallback:v1:5b62d1baa4af7c75f2fcbc90f3bdc57478e44145fac9a47fe4c9d36858a51fb4",
        "provider_identity_status": "fallback",
        "identity_authority": "public.cdr.alex.com.au",
    }


def test_official_provider_and_product_identities_are_exact_and_name_stable() -> None:
    provider, status = provider_uid(
        data_holder_id="holder-1",
        data_holder_brand_id="brand-1",
        endpoint_urls=("https://ignored.example/path",),
        display_name="Name A",
    )
    renamed, _ = provider_uid(
        data_holder_id="holder-1",
        data_holder_brand_id="brand-1",
        endpoint_urls=("https://changed.example/path",),
        display_name="Name B",
    )
    assert status == "official"
    assert provider == renamed
    assert provider == "provider:v1:833838128d3e6060e3b65ed0f3b9526cca807acd039aeb6436ff7e83156fce18"
    assert product_uid(provider, "Mortgage", "product-1") == (
        "2fba7c40a47faa132d87f1119256ea82ffe7d264d98967cbad3758d1a3f82369"
    )
    assert product_uid(provider, "Savings", "product-1") != product_uid(
        provider, "Mortgage", "product-1"
    )


def test_fallback_authority_is_canonical_and_display_name_is_not_case_folded() -> None:
    assert canonical_authority(
        ["https://Z.example:443/a?q=1", "http://ignored.example", "https://a.example:8443/x"]
    ) == "a.example:8443"
    first, _ = provider_uid(
        data_holder_id=None,
        data_holder_brand_id="brand",
        endpoint_urls=("https://bank.example/products",),
        display_name="Bank  Name",
    )
    second, _ = provider_uid(
        data_holder_id=None,
        data_holder_brand_id="brand",
        endpoint_urls=("https://bank.example/other",),
        display_name="Bank\tName",
    )
    changed_case, _ = provider_uid(
        data_holder_id=None,
        data_holder_brand_id="brand",
        endpoint_urls=("https://bank.example",),
        display_name="bank name",
    )
    assert first == second
    assert first != changed_case


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", "0"), ("0.004500", "0.0045"), ("1", "1"), ("1.0", "1")],
)
def test_rate_string_is_decimal_and_never_rescaled(raw: str, expected: str) -> None:
    assert parse_rate_string(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, "", 0.05, "5", "-0.01", "NaN", "Infinity", "not-a-number"],
)
def test_rate_string_rejects_wrong_types_units_and_non_finite_values(raw: object) -> None:
    with pytest.raises(ValueError):
        parse_rate_string(raw)
