"""Current official register and non-bank mortgage response, without live I/O."""
import hashlib
import gzip
import json
from pathlib import Path

import pytest

import cdr_ingest_support as support

FIXTURES = Path(__file__).parent / "fixtures/cdr-financial-register-20261113"


def retained(name):
    provenance = json.loads((FIXTURES / "provenance.json").read_bytes())
    path = FIXTURES / name
    raw = path.read_bytes() if path.exists() else gzip.decompress(
        (FIXTURES / (name + ".gz")).read_bytes())
    assert hashlib.sha256(raw).hexdigest() == provenance["files"][name]["sha256"]
    return raw


def test_all_registered_financial_brands_are_discovered_without_energy():
    register = json.loads(retained("register.json"))
    rows = list(support.iter_banking_brands_from_payload(register))
    expected = [row for row in register["data"]
                if set(row["industries"]) & {"banking", "non-bank-lending"}]
    assert len(rows) == len(expected) == 306
    assert {row["brand_name"] for row in rows} == {row["brandName"] for row in expected}
    assert all(row["endpoint_url"].endswith("/cds-au/v1/banking/products") for row in rows)
    banks = [row for row in register["data"] if "banking" in row["industries"]]
    assert len(banks) == 115
    assert all(any(candidate["brand_name"] == row["brandName"]
                   and candidate["endpoint_url"] == support.normalize_banking_products_url(
                       row.get("productBaseUri") or row["publicBaseUri"])
                   for candidate in rows) for row in banks)


def test_registered_nonbank_mortgages_use_existing_category_contract():
    index = json.loads(retained("360mms-index.json"))
    assert support.response_shape_error(index, phase="products_index") is None
    products = support.extract_products(index)
    assert len(products) == index["meta"]["totalRecords"] == 12
    assert {support.dataset_from_cdr_category(row["productCategory"]) for row in products} == {"home_loans"}


@pytest.mark.parametrize("industries", [[], None, {}, "banking", ["unknown"], ["energy"]])
def test_explicit_unknown_or_malformed_industry_does_not_use_legacy_fallback(industries):
    row = json.loads(retained("register.json"))["data"][0]
    row["industries"] = industries
    assert list(support.iter_banking_brands_from_payload({"data": [row]})) == []


def test_legacy_row_without_industries_remains_compatible():
    row = json.loads(retained("register.json"))["data"][0]
    row.pop("industries")
    result = list(support.iter_banking_brands_from_payload({"data": [row]}))
    assert len(result) == 1
    assert result[0]["brand_name"] == row["brandName"]


def test_register_snapshot_counts_financial_scope_before_holder_filter(monkeypatch):
    raw = retained("register.json")
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return support.FetchResult(True, 200, url, raw.decode(), version=2)

    monkeypatch.setattr(support, "fetch_cdr_json", fetch)
    snapshot = support.collect_register_snapshot(
        timeout=1, max_retries=0, sleep_ms=0, holders_filter="360 MMS")
    assert snapshot.register_ok and snapshot.register_provenance_complete
    assert snapshot.banking_count_before_filter == 306
    assert [row["brand_name"] for row in snapshot.banking_brands] == ["360 MMS"]
    assert calls == [support.REGISTER_URL_SUMMARY]
    assert snapshot.register_attempts[0]["sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("change", [
    {"links": {"next": "https://api.cdr.gov.au/next"}},
    {"meta": {"totalRecords": 391}}, {"meta": {"totalRecords": "390"}},
    {"meta": {"totalPages": 2}}, {"meta": []}, {"links": None},
])
def test_changed_register_keeps_obtainable_providers_but_marks_partial(monkeypatch, change):
    register = json.loads(retained("register.json"))
    register.update(change)
    raw = json.dumps(register)
    monkeypatch.setattr(support, "fetch_cdr_json", lambda *a, **k:
                        support.FetchResult(True, 200, support.REGISTER_URL_SUMMARY, raw, version=2))
    snapshot = support.collect_register_snapshot(timeout=1, max_retries=0, sleep_ms=0, holders_filter=None)
    assert snapshot.register_ok  # Capture all usable rows instead of losing them.
    assert len(snapshot.banking_brands) == 306
    assert not snapshot.register_provenance_complete
    assert snapshot.register_attempts[0]["ok"] is False
    assert snapshot.register_attempts[0]["error"]


def test_unclassified_brand_makes_register_incomplete_without_losing_other_rows(monkeypatch):
    register = json.loads(retained("register.json"))
    bank = next(row for row in register["data"] if "banking" in row["industries"])
    bank["industries"] = None
    monkeypatch.setattr(support, "fetch_cdr_json", lambda *a, **k:
                        support.FetchResult(True, 200, support.REGISTER_URL_SUMMARY, json.dumps(register), version=2))
    snapshot = support.collect_register_snapshot(timeout=1, max_retries=0, sleep_ms=0, holders_filter=None)
    assert snapshot.register_ok and len(snapshot.banking_brands) == 305
    assert not snapshot.register_provenance_complete
