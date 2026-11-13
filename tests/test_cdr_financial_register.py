"""Current official register and non-bank mortgage response, without live I/O."""
import hashlib
import gzip
import json
from pathlib import Path

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
