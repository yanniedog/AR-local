"""Retained canary regressions; protocol mutation tests never stand in for live acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import cdr_ingest_lib as lib
import cdr_ingest_support as support
from cdr_compatibility import response_shape_error
from cdr_raw_attempt_journal import RawAttemptJournal


FIXTURE_ROOT = Path(__file__).parent / "fixtures"
CANARY = FIXTURE_ROOT / "cdr-canary-2026-09-07"


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pages(bank):
    return [_read(path) for path in sorted(CANARY.glob(f"{bank}-index-*.json"))]


def test_retained_response_bodies_match_their_provenance():
    for row in _read(CANARY / "provenance.json")["files"]:
        assert hashlib.sha256((CANARY / row["file"]).read_bytes()).hexdigest() == row["sha256"]


@pytest.mark.parametrize("path", sorted(CANARY.glob("*-null-detail.json")), ids=lambda path: path.stem)
def test_actual_optional_null_rate_sections_are_accepted_without_changing_body(monkeypatch, path):
    body = path.read_text(encoding="utf-8")
    product_id = json.loads(body)["data"]["productId"]
    monkeypatch.setattr(support, "http_request", lambda *_, **__: (200, body, None))
    result = support.fetch_cdr_json(
        "https://holder.example/products/" + product_id,
        versions=[7], timeout=5, max_retries=0, sleep_ms=0,
        attempt_context={"phase": "product_detail", "product_id": product_id},
    )
    assert result.ok and result.attempts == 1 and result.text == body


@pytest.mark.parametrize("bad_section", [False, 0, {}, "[]", [None]])
def test_optional_nonnull_rate_sections_still_require_objects_in_an_array(bad_section):
    value = _read(CANARY / "Greater Bank Limited-null-detail.json")
    value["data"]["depositRates"] = bad_section
    assert response_shape_error(value, phase="product_detail")


def _ingest_index(tmp_path, monkeypatch, bank, pages):
    endpoint = pages[0]["links"]["self"].split("?", 1)[0]
    requested_pages, requested_products = [], []

    def fetch(url, **_):
        page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        requested_pages.append(page)
        return support.FetchResult(True, 200, url, json.dumps(pages[page - 1]), version=6)

    def detail(work, *_, **__):
        requested_products.append(work.pid)
        return lib._DetailOutcome(True, True)

    monkeypatch.setattr(lib, "fetch_cdr_json", fetch)
    monkeypatch.setattr(lib, "_fetch_bank_detail", detail)
    (tmp_path / "failures.jsonl").write_text("")
    brand = {"endpoint_url": endpoint, "brand_name": bank}
    lib.ingest_brand(
        brand, date_root=tmp_path, resume=False, sleep_ms=0, timeout=5,
        max_retries=0, max_pages=None, max_products=None, fetch_unknown_detail=False,
        bank_dir_name=bank, detail_workers=1, log=lambda _: None,
    )
    diagnostics = _read(tmp_path / "_holders" / bank / "_products-index" / "diagnostics.json")
    failures = [json.loads(line) for line in (tmp_path / "failures.jsonl").read_text().splitlines()]
    return brand, requested_pages, requested_products, diagnostics, failures


@pytest.mark.parametrize("bank,raw,unique,duplicates", [
    ("Credit Union SA", 48, 47, 1), ("Defence Bank", 52, 49, 3),
])
def test_identical_page_overlap_deduplicates_fetches_and_retains_full_accounting(
    tmp_path, monkeypatch, bank, raw, unique, duplicates,
):
    brand, pages, products, diagnostics, failures = _ingest_index(tmp_path, monkeypatch, bank, _pages(bank))
    assert pages == [1, 2, 3] and not failures
    assert len(products) == len(set(products))
    assert diagnostics == {
        "schema_version": 1, "pages": 3, "raw_records": raw, "unique_products": unique,
        "identical_duplicate_records": duplicates, "conflicting_duplicate_records": 0,
        "declared_total_records": raw, "declared_total_pages": 3, "pagination_complete": True,
    }
    snapshot = support.RegisterSnapshot(True, True, [], [brand], 1)
    status = lib._persist_ingest_status(
        banks_root=tmp_path, run_root=tmp_path, snapshot=snapshot,
        bank_work=[(brand, bank)], attempt_journal=RawAttemptJournal(tmp_path, "overlap-test"),
    )
    assert status["index_diagnostics"][bank] == diagnostics
    assert status["provider_states"][0]["state"] == "complete"


def test_same_page_repeat_does_not_abort_remaining_pages(tmp_path, monkeypatch):
    pages = _pages("Defence Bank")
    pages[0]["data"]["products"].append(copy.deepcopy(pages[0]["data"]["products"][0]))
    for page in pages:
        page["meta"]["totalRecords"] += 1
    assert response_shape_error(pages[0], phase="products_index") is None
    _, seen, products, diagnostics, failures = _ingest_index(tmp_path, monkeypatch, "Defence Bank", pages)
    assert seen == [1, 2, 3] and not failures and len(products) == len(set(products))
    assert diagnostics["raw_records"] == 53 and diagnostics["unique_products"] == 49
    assert diagnostics["identical_duplicate_records"] == 4


def test_conflicting_identity_is_reported_without_losing_unrelated_pages(tmp_path, monkeypatch):
    pages = _pages("Defence Bank")
    duplicate = next(row for row in pages[1]["data"]["products"] if row["productId"] == "284")
    duplicate["name"] += " conflict injected by regression test"
    _, seen, products, diagnostics, failures = _ingest_index(tmp_path, monkeypatch, "Defence Bank", pages)
    assert seen == [1, 2, 3] and len(products) == len(set(products))
    assert [row["status"] for row in failures] == ["conflicting_product_identity"]
    assert diagnostics["conflicting_duplicate_records"] == 1
    assert diagnostics["raw_records"] == 52 and diagnostics["pagination_complete"]


def test_truncated_page_chain_still_fails_full_record_accounting(tmp_path, monkeypatch):
    pages = _pages("Defence Bank")
    del pages[1]["links"]["next"]
    _, seen, _, diagnostics, failures = _ingest_index(tmp_path, monkeypatch, "Defence Bank", pages)
    assert seen == [1, 2]
    assert [row["status"] for row in failures] == ["pagination_incomplete"]
    assert not diagnostics["pagination_complete"]


@pytest.mark.parametrize("category,status,body", [
    ("invalid_response", 200, "{}"),
    ("upstream_schema_invalid", 422, next(
        row["body"] for row in _read(FIXTURE_ROOT / "cdr-september7" / "failures.json")
        if row["provider"] == "Bank of Sydney" and row["status"] == 422
    )),
    ("product_inactive", 400, next(
        row["body"] for row in _read(FIXTURE_ROOT / "cdr-september7" / "failures.json")
        if row["provider"] == "CommFCU" and row["status"] == 400
    )),
])
def test_bad_products_cannot_open_transport_breaker_and_hide_later_valid_product(
    tmp_path, monkeypatch, category, status, body,
):
    pages = _pages("Defence Bank")
    # Reorder the captured index only, placing the captured valid detail last.
    # Every earlier selected product receives a controlled deterministic error.
    rows = [row for page in pages for row in page["data"]["products"]]
    rows = [row for row in rows if row["productId"] != "249"] + [
        row for row in rows if row["productId"] == "249"
    ]
    for ordinal, page in enumerate(pages):
        page["data"]["products"] = rows[ordinal * 20:(ordinal + 1) * 20]
    detail = _read(FIXTURE_ROOT / "cdr-september7" / "defence.json")["product_detail"]["body"]
    endpoint = pages[0]["links"]["self"].split("?", 1)[0]
    requested = set()

    def request(url, *_, **__):
        if urlsplit(url).path == urlsplit(endpoint).path:
            page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
            return 200, json.dumps(pages[page - 1]), None
        pid = url.rsplit("/", 1)[1]
        requested.add(pid)
        return (200, json.dumps(detail), None) if pid == "249" else (status, body, None)

    monkeypatch.setattr(support, "http_request", request)
    lib.ingest_brand(
        {"endpoint_url": endpoint}, date_root=tmp_path, resume=False, sleep_ms=0,
        timeout=5, max_retries=0, max_pages=None, max_products=None,
        fetch_unknown_detail=False, bank_dir_name="Defence Bank", detail_workers=1, log=lambda _: None,
    )
    failures = [json.loads(line) for line in (tmp_path / "failures.jsonl").read_text().splitlines()]
    assert len(failures) > lib.BREAKER_MIN_SAMPLE
    assert all(row["failure_category"] == category for row in failures)
    assert "249" in requested and not any(row["status"] == "circuit_open" for row in failures)
    assert [_read(path)["data"]["productId"] for path in tmp_path.glob("*/*/*/*/product-detail.json")] == ["249"]
