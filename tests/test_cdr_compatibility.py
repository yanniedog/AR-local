"""Replay real September 7 errors and corrupt captured shapes at protocol boundaries."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import cdr_ingest_lib as lib
import cdr_ingest_support as support
from cdr_compatibility import (
    HolderVersionCache, classify_fetch_failure, pagination_accounting_error,
    parse_supported_versions, response_shape_error,
)


FIXTURES = Path(__file__).parent / "fixtures"
RESPONSES = json.loads((FIXTURES / "cdr_failures_real_2026-09-07.json").read_text(encoding="utf-8"))["responses"]
DEFENCE = json.loads((FIXTURES / "cdr-september7" / "defence.json").read_text(encoding="utf-8"))


def _captured(provider, status):
    return next(row for row in RESPONSES if row["provider"] == provider and row["status"] == status)


@pytest.mark.parametrize("advertisement,expected", [
    ("x-v. Supported max version 5 and min version 4", [5, 4]),
    ("Supported minimum version 4 and maximum versions 5", [5, 4]),
    ("supported versions include: [3, 4, 5]", [5, 4, 3]),
    ("Supported versions are: 6, 1, 3, 5, 4, 2.", [6, 5, 4, 3, 2, 1]),
    ("Supported versions: min = 5, max = 5.", [5]),
    ("Min version supported: 1, Max version supported: 5", [5, 4, 3, 2, 1]),
    ("Versions available: 4 and 5", [5, 4]),
    ("Requested: 7-7 Available: 8", [8]),
    ("Minimum version supported is 8 and Maximum version supported is 9", [9, 8]),
    ("Versions available: 100, 8", [8]),
    ("Supported minimum version 0 and maximum version 999", []),
    ("Requested x-v version 6 is not supported", []),
])
def test_advertisements_cover_captured_dialects_and_bounded_future_versions(advertisement, expected):
    assert parse_supported_versions(advertisement) == expected


@pytest.mark.parametrize("provider,status,category,retryable", [
    ("Aussie Home Loans", 404, "endpoint_not_found", False),
    ("Bank of Sydney", 422, "upstream_schema_invalid", False),
    ("Bank of Queensland Limited", 500, "upstream_schema_invalid", False),
    ("Geelong Bank", 400, "public_endpoint_auth_required", False),
    ("CommFCU", 400, "product_inactive", False),
    ("SWSbank", 400, "upstream_rejection", False),
    ("Darling Downs Bank", 599, "transport", True),
    ("DDH Graham", 500, "transient_upstream", True),
    ("Family First", 503, "transient_upstream", True),
])
def test_real_failure_dispositions(provider, status, category, retryable):
    row = _captured(provider, status)
    result = classify_fetch_failure(status, row["body"] or row["error"])
    assert (result.category, result.retryable) == (category, retryable)


@pytest.mark.parametrize("provider,status", [
    ("Aussie Home Loans", 404), ("Bank of Sydney", 422),
    ("Bank of Queensland Limited", 500), ("Geelong Bank", 400),
    ("CommFCU", 400), ("SWSbank", 400),
])
def test_decisive_upstream_rejections_do_not_sweep_versions_or_retry(monkeypatch, provider, status):
    row = _captured(provider, status)
    calls = []
    monkeypatch.setattr(support, "http_request", lambda url, headers, **_: (
        calls.append(headers["x-v"]) or status, row["body"], None,
    ))
    monkeypatch.setattr(support.time, "sleep", lambda _: pytest.fail("terminal errors must not retry"))
    result = support.fetch_cdr_json(row["url"], timeout=5, max_retries=6, sleep_ms=0)
    assert not result.ok and not result.retryable and result.attempts == len(calls) == 1
    assert result.text == row["body"]


@pytest.mark.parametrize("status", [400, 406, 422])
def test_advertised_future_version_negotiates_without_code_changes(monkeypatch, status):
    row = _captured("AMP Bank GO", 406)
    # Mutate only advertised protocol versions to exercise a future retirement;
    # successful business data is the untouched captured Defence response.
    error = row["body"].replace("max version 5 and min version 4", "max version 9 and min version 8")
    success = json.dumps(DEFENCE["product_detail"]["body"])
    calls = []

    def request(url, headers, **_):
        calls.append(int(headers["x-v"]))
        return (200, success, None) if headers["x-v"] == "9" else (status, error, None)

    monkeypatch.setattr(support, "http_request", request)
    result = support.fetch_cdr_json(
        DEFENCE["product_detail"]["url"], versions=[7, 6], timeout=5,
        max_retries=0, sleep_ms=0, max_total_attempts=2,
        attempt_context={"phase": "product_detail", "product_id": "249"},
    )
    assert result.ok and result.version == 9 and calls == [7, 9]


def test_detail_cache_is_separate_and_recovers_from_retired_version(monkeypatch):
    cache = HolderVersionCache(lib.PRODUCT_DETAIL_VERSION_ORDER)
    seen = []
    replies = iter((6, 6, 8))

    def fetch(url, **kwargs):
        seen.append(kwargs["versions"])
        return support.FetchResult(True, 200, url, json.dumps(DEFENCE["product_detail"]["body"]), version=next(replies))

    monkeypatch.setattr(lib, "fetch_cdr_json", fetch)
    for _ in range(3):
        lib._fetch_detail(
            DEFENCE["product_detail"]["url"], timeout=5, max_retries=1, sleep_ms=0,
            version_cache=cache, deadline=None, attempt_journal=None,
            context={"phase": "product_detail", "product_id": "249"},
        )
    assert [versions[0] for versions in seen] == [7, 6, 6]
    assert cache.order()[0] == 8
    cache.record(ok=False, version=None, attempted=6)
    assert cache.order()[0] == 8  # an older in-flight failure cannot evict newer capability
    cache.record(ok=False, version=None, attempted=8)
    assert cache.order() == lib.PRODUCT_DETAIL_VERSION_ORDER
    assert lib._index_version_list(None) == lib.PRODUCT_INDEX_VERSION_ORDER


def test_additive_fields_and_unknown_rate_enums_remain_accepted():
    data = copy.deepcopy(DEFENCE["product_detail"]["body"])
    data["newEnvelopeField"] = {"future": True}
    data["data"]["depositRates"][0]["depositRateType"] = "FUTURE_PROVIDER_RATE_TYPE"
    assert response_shape_error(data, phase="product_detail", product_id="249") is None


@pytest.mark.parametrize("invalid_rate", [None, True, "not a number", "NaN", "Infinity", float("-inf")])
def test_invalid_rates_never_become_successful_details(invalid_rate):
    data = copy.deepcopy(DEFENCE["product_detail"]["body"])
    data["data"]["depositRates"][0]["rate"] = invalid_rate
    assert response_shape_error(data, phase="product_detail", product_id="249")


def test_wrong_identity_and_truncated_index_are_visible_failures(monkeypatch):
    body = DEFENCE["product_detail"]["body"]
    assert response_shape_error(body, phase="product_detail", product_id="wrong-id")
    index = DEFENCE["products_index"]["body"]
    assert pagination_accounting_error(index, pages=3, products=52, has_next=False) is None
    assert pagination_accounting_error(index, pages=1, products=12, has_next=False)
    malformed = copy.deepcopy(index)
    del malformed["data"]["products"]
    monkeypatch.setattr(support, "http_request", lambda *_, **__: (200, json.dumps(malformed), None))
    result = support.fetch_cdr_json(
        DEFENCE["products_index"]["url"], versions=[6], timeout=5, max_retries=0,
        sleep_ms=0, attempt_context={"phase": "products_index"},
    )
    assert not result.ok and result.failure_category == "invalid_response"
    assert result.validation_error == "product index has no products array"


def test_expired_recovery_makes_no_detail_request_or_delay(tmp_path, monkeypatch):
    monkeypatch.setattr(lib.time, "monotonic", lambda: 10)
    monkeypatch.setattr(lib.time, "sleep", lambda _: pytest.fail("expired recovery must not sleep"))
    monkeypatch.setattr(lib, "fetch_cdr_json", lambda *_, **__: pytest.fail("expired recovery must not request"))
    result = lib._fetch_bank_detail(
        lib._BankWork("249", tmp_path, None), "https://product.defencebank.com.au/cds-au/v1/banking/products",
        timeout=5, max_retries=1, sleep_ms=500, date_root=tmp_path,
        bank_dir_name="Defence Bank", failure_lock=None, deadline=10,
    )
    assert not result
    row = json.loads((tmp_path / "failures.jsonl").read_text())
    assert row["status"] == "recovery_budget_exhausted"


def test_summary_exposes_failure_causes_and_retryability(tmp_path):
    rows = [_captured("Geelong Bank", 400), _captured("Family First", 503)]
    for row in rows:
        support.append_failure(tmp_path, {
            "phase": row["phase"], "bank": row["provider"],
            "status": row["status"], "snippet": row["body"],
        })
    result = support.summarize_failures(tmp_path)
    assert result["by_failure_category"] == {"public_endpoint_auth_required": 1, "transient_upstream": 1}
    assert result["by_retryable"] == {"false": 1, "true": 1}


def _run_resume(tmp_path, monkeypatch, *, duplicate=False, invalid=False):
    detail = DEFENCE["product_detail"]["body"]
    leaf = tmp_path / "TD" / "Defence Bank" / detail["data"]["name"] / "249"
    leaf.mkdir(parents=True)
    (leaf / "product-id.txt").write_text("249\n")
    (leaf / "product-detail.json").write_text("{}" if invalid else json.dumps(detail))
    if duplicate:
        other = tmp_path / "Savings" / "Defence Bank" / "duplicate" / "249"
        other.mkdir(parents=True)
        (other / "product-id.txt").write_text("249\n")
        (other / "product-detail.json").write_text(json.dumps(detail))
    # Reduce the captured data to one real product, then rename it in the index
    # to reproduce a mutable-name change between the first capture and recovery.
    renamed = copy.deepcopy(detail["data"])
    renamed["name"] += " (renamed)"
    renamed["productCategory"] = "TRANS_AND_SAVINGS_ACCOUNTS"
    index = {"data": {"products": [renamed]}, "meta": {"totalRecords": 1, "totalPages": 1}}
    endpoint = DEFENCE["product_detail"]["url"].rsplit("/", 1)[0]
    calls = []

    def fetch(url, **_):
        calls.append(url)
        return support.FetchResult(True, 200, url, json.dumps(index if url == endpoint else detail), version=7)

    monkeypatch.setattr(lib, "fetch_cdr_json", fetch)
    lib.ingest_brand(
        {"endpoint_url": endpoint}, date_root=tmp_path, resume=True, sleep_ms=0,
        timeout=5, max_retries=1, max_pages=None, max_products=None,
        fetch_unknown_detail=False, bank_dir_name="Defence Bank", detail_workers=1,
        log=lambda _: None,
    )
    return leaf, calls


def test_resume_reuses_stable_identity_despite_renamed_or_reclassified_index(tmp_path, monkeypatch):
    leaf, calls = _run_resume(tmp_path, monkeypatch)
    assert len(calls) == 1
    assert list(tmp_path.glob("*/*/*/*/product-detail.json")) == [leaf / "product-detail.json"]


def test_resume_refetches_invalid_cached_detail_into_the_existing_identity_leaf(tmp_path, monkeypatch):
    leaf, calls = _run_resume(tmp_path, monkeypatch, invalid=True)
    assert len(calls) == 2
    assert json.loads((leaf / "product-detail.json").read_text()) == DEFENCE["product_detail"]["body"]
    assert len(list(tmp_path.glob("*/*/*/*/product-detail.json"))) == 1


def test_resume_detects_existing_identity_conflict_without_another_copy(tmp_path, monkeypatch):
    _, calls = _run_resume(tmp_path, monkeypatch, duplicate=True)
    assert len(calls) == 1
    assert len(list(tmp_path.glob("*/*/*/*/product-detail.json"))) == 2
    row = json.loads((tmp_path / "failures.jsonl").read_text())
    assert row["status"] == "resume_identity_conflict" and not row["retryable"]
