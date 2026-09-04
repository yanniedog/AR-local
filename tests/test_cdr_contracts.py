from __future__ import annotations

import json
from pathlib import Path

import pytest

import cdr_clean_export
from cdr_contracts import canonical_authority, parse_rate_string, product_uid, provider_uid
from cdr_ingest_parsing import infer_cdr_dataset
from cdr_ingest_support import iter_banking_brands_from_payload


FIXTURES = Path(__file__).parent / "fixtures"


def test_real_register_brand_without_both_controlled_ids_uses_fallback() -> None:
    item = json.loads(
        (FIXTURES / "register_brand_summary_real_2026-09-02.json").read_text(encoding="utf-8")
    )["record"]
    uid, status = provider_uid(
        data_holder_id=item.get("dataHolderId"),
        data_holder_brand_id=item.get("dataHolderBrandId"),
        interim_id=item.get("interimId"),
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
        "interim_id": "fe051e80-e743-44e1-ae83-a4d6286eb596",
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
    changed_case, _ = provider_uid(
        data_holder_id="Holder-1",
        data_holder_brand_id="brand-1",
        endpoint_urls=(),
        display_name="Name A",
    )
    assert changed_case != provider
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
        data_holder_brand_id=None,
        endpoint_urls=("https://bank.example/products",),
        display_name="Bank  Name",
    )
    second, _ = provider_uid(
        data_holder_id=None,
        data_holder_brand_id=None,
        endpoint_urls=("https://bank.example/other",),
        display_name="Bank\tName",
    )
    changed_case, _ = provider_uid(
        data_holder_id=None,
        data_holder_brand_id=None,
        endpoint_urls=("https://bank.example",),
        display_name="bank name",
    )
    assert first == second
    assert first != changed_case


def test_one_controlled_id_is_insufficient_for_official_identity() -> None:
    first = provider_uid(
        data_holder_id=None,
        data_holder_brand_id=None,
        interim_id="Interim-1",
        endpoint_urls=("https://one.example",),
        display_name="Temporary Name",
    )
    second = provider_uid(
        data_holder_id="holder-1",
        data_holder_brand_id=None,
        interim_id="interim-1",
        endpoint_urls=("https://one.example/changed",),
        display_name="Temporary Name",
    )
    assert first == second
    assert first[1] == "fallback"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", "0"), ("0.004500", "0.0045"), ("1", "1"), ("1.0", "1")],
)
def test_rate_string_is_decimal_and_never_rescaled(raw: str, expected: str) -> None:
    assert parse_rate_string(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, "", 0.05, "5", "-0", "-0.00", "-0.01", "NaN", "Infinity", "not-a-number"],
)
def test_rate_string_rejects_wrong_types_units_and_non_finite_values(raw: object) -> None:
    with pytest.raises(ValueError):
        parse_rate_string(raw)


def test_unknown_deposit_category_uses_only_unambiguous_dataset_evidence() -> None:
    base = {
        "productCategory": "NEW_UNMAPPED_CATEGORY",
        "depositRates": [{"depositRateType": "VARIABLE", "rate": "0.04"}],
    }
    assert infer_cdr_dataset({**base, "name": "12 Month Term Deposit"}) == "term_deposits"
    assert infer_cdr_dataset({**base, "name": "Everyday Account"}) is None


def test_fallback_identity_uses_smallest_authority_from_whole_register_record() -> None:
    item = {
        "dataHolderBrandId": "brand-only",
        "brandName": "Example Bank",
        "industries": ["banking"],
        "publicBaseUri": "https://z.example/cds-au/v1",
        "productBaseUri": "https://z.example/cds-au/v1",
        "logoUri": "https://a.example/logo.png",
    }
    row = next(iter(iter_banking_brands_from_payload({"data": [item]})))
    expected, _ = provider_uid(
        data_holder_id=None,
        data_holder_brand_id="brand-only",
        endpoint_urls=("https://a.example",),
        display_name="Example Bank",
    )
    assert row["identity_authority"] == "a.example"
    assert row["provider_uid"] == expected


def test_unknown_lending_category_requires_mortgage_specific_evidence() -> None:
    generic = {
        "productCategory": "NEW_VEHICLE_LOAN",
        "name": "Vehicle Finance",
        "lendingRates": [
            {
                "lendingRateType": "VARIABLE",
                "repaymentType": "PRINCIPAL_AND_INTEREST",
                "rate": "0.07",
            }
        ],
    }
    assert infer_cdr_dataset(generic) is None
    mortgage = {
        **generic,
        "lendingRates": [{**generic["lendingRates"][0], "loanPurpose": "OWNER_OCCUPIED"}],
    }
    assert infer_cdr_dataset(mortgage) == "home_loans"


def test_known_out_of_scope_category_wins_over_product_name() -> None:
    assert (
        infer_cdr_dataset(
            {"productCategory": "BUSINESS_LOANS", "name": "Business Home Loan"}
        )
        is None
    )


def _write_rate_product(root: Path, rate: str, **details: object) -> None:
    provider = "Holder"
    holder = root / "banks" / "_holders" / provider
    holder.mkdir(parents=True)
    (holder / "_register-brand.json").write_text(
        json.dumps(
            {
                "brand_name": provider,
                "endpoint_url": "https://holder.example/cds-au/v1/banking/products",
                "provider_uid": "provider-fallback:v1:" + "a" * 64,
                "provider_identity_status": "fallback",
            }
        ),
        encoding="utf-8",
    )
    detail = root / "banks" / "Savings" / provider / "Saver" / "P1"
    detail.mkdir(parents=True)
    (detail / "product-detail.json").write_text(
        json.dumps(
            {
                "data": {
                    "productId": "P1",
                    "name": "Saver",
                    "depositRates": [{"depositRateType": "VARIABLE", "rate": rate}],
                    **details,
                }
            }
        ),
        encoding="utf-8",
    )


def test_clean_export_keeps_exact_cdr_rate_and_relative_evidence_path(tmp_path: Path) -> None:
    run = tmp_path / "2026-09-02"
    _write_rate_product(run, "0.04500")
    banks = cdr_clean_export.parse_banks_run(run)
    assert banks["rates"][0]["rate"] == "0.045"
    assert banks["products"][0]["source_file"] == "Savings/Holder/Saver/P1/product-detail.json"
    assert banks["quarantines"] == []


def test_clean_export_quarantines_out_of_unit_rate(tmp_path: Path) -> None:
    run = tmp_path / "2026-09-02"
    _write_rate_product(run, "4.5")
    banks = cdr_clean_export.parse_banks_run(run)
    assert banks["products"] == []
    assert banks["rates"] == []
    assert banks["quarantines"][0]["status"] == "rate_invalid"


def test_clean_export_quarantines_product_without_provider_identity(
    tmp_path: Path,
) -> None:
    run = tmp_path / "2026-09-02"
    _write_rate_product(run, "0.045")
    (run / "banks/_holders/Holder/_register-brand.json").unlink()

    banks = cdr_clean_export.parse_banks_run(run)

    assert banks["products"] == []
    assert banks["provider_observations"] == []
    assert banks["quarantines"][0]["status"] == "identity_mismatch"


def test_clean_export_keeps_numeric_metadata_nested_in_a_rate(tmp_path: Path) -> None:
    run = tmp_path / "2026-09-02"
    _write_rate_product(
        run,
        "0.045",
        depositRates=[
            {
                "depositRateType": "VARIABLE",
                "rate": "0.045",
                "additionalValue": "12",
            }
        ],
    )

    banks = cdr_clean_export.parse_banks_run(run)

    assert len(banks["products"]) == 1
    assert len(banks["rates"]) == 1
    assert banks["quarantines"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fees", {"feeType": "PERIODIC"}),
        ("features", ["OFFSET"]),
        ("eligibility", None),
        ("constraints", [1]),
    ],
)
def test_clean_export_omits_malformed_optional_detail_arrays(
    tmp_path: Path, field: str, value: object
) -> None:
    run = tmp_path / "2026-09-02"
    _write_rate_product(run, "0.045", **{field: value})

    banks = cdr_clean_export.parse_banks_run(run)

    assert len(banks["products"]) == 1
    assert len(banks["rates"]) == 1
    assert banks["products"][0]["details_complete"] is False
    assert field not in json.loads(banks["products"][0]["details_json"])
    assert banks[field] == []
    assert banks["quarantines"] == [
        {
            "phase": "normalization",
            "bank": "Holder",
            "product_id": "P1",
            "status": "field_omitted_invalid",
            "affected_sections": [field],
            "evidence_digest": banks["products"][0]["evidence_id"],
            "source_file": "Savings/Holder/Saver/P1/product-detail.json",
        }
    ]
