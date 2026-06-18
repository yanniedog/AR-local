"""Per-holder circuit breaker (audit P0-retry Phase-4).

When a holder's product-detail fetches are mostly failing (a real outage, not a
few bad products), ingest_brand stops probing the rest of that holder and fails
them fast instead of hammering a down endpoint for every product.
"""

import cdr_ingest_lib as lib
from cdr_ingest_support import FetchResult

ENDPOINT = "http://holder/products"


def test_circuit_breaker_stops_a_failing_holder(tmp_path, monkeypatch):
    detail_calls = {"n": 0}
    n_products = 40  # > BREAKER_MIN_SAMPLE so the breaker can trip mid-run

    def fake_fetch(url, *, versions=None, timeout, max_retries, sleep_ms, **_kw):
        if url == ENDPOINT:  # the product-index page succeeds
            return FetchResult(ok=True, status=200, url=url, text='{"data": {}}', version=4)
        detail_calls["n"] += 1  # every product-detail fetch fails
        return FetchResult(ok=False, status=503, url=url, text="", version=None)

    monkeypatch.setattr(lib, "fetch_cdr_json", fake_fetch)
    monkeypatch.setattr(
        lib, "extract_products",
        lambda parsed: [{"productId": f"P{i}", "name": f"Acct{i}"} for i in range(n_products)],
    )
    monkeypatch.setattr(lib, "next_link", lambda parsed, url: None)
    ds_key = next(iter(lib.DATASET_TO_FOLDER))
    monkeypatch.setattr(lib, "classify_product_for_ingest", lambda *a, **k: (ds_key, None))

    lib.ingest_brand(
        {"endpoint_url": ENDPOINT},
        date_root=tmp_path,
        resume=False,
        sleep_ms=0,
        timeout=1,
        max_retries=0,
        max_pages=None,
        max_products=None,
        fetch_unknown_detail=False,
        bank_dir_name="holder",
        detail_workers=1,  # serial -> deterministic trip point
        log=lambda *_a, **_k: None,
    )

    # The breaker opens once BREAKER_MIN_SAMPLE attempts have all failed, so only
    # that many details are actually fetched; the remaining ~20 are skipped.
    assert detail_calls["n"] == lib.BREAKER_MIN_SAMPLE
    assert detail_calls["n"] < n_products


def test_circuit_breaker_stays_closed_for_a_healthy_holder(tmp_path, monkeypatch):
    detail_calls = {"n": 0}
    n_products = 40

    def fake_fetch(url, *, versions=None, timeout, max_retries, sleep_ms, **_kw):
        if url == ENDPOINT:
            return FetchResult(ok=True, status=200, url=url, text='{"data": {}}', version=4)
        detail_calls["n"] += 1
        return FetchResult(ok=True, status=200, url=url, text='{"data": {}}', version=4)

    monkeypatch.setattr(lib, "fetch_cdr_json", fake_fetch)
    monkeypatch.setattr(
        lib, "extract_products",
        lambda parsed: [{"productId": f"P{i}", "name": f"Acct{i}"} for i in range(n_products)],
    )
    monkeypatch.setattr(lib, "next_link", lambda parsed, url: None)
    ds_key = next(iter(lib.DATASET_TO_FOLDER))
    monkeypatch.setattr(lib, "classify_product_for_ingest", lambda *a, **k: (ds_key, None))

    lib.ingest_brand(
        {"endpoint_url": ENDPOINT},
        date_root=tmp_path, resume=False, sleep_ms=0, timeout=1, max_retries=0,
        max_pages=None, max_products=None, fetch_unknown_detail=False,
        bank_dir_name="holder", detail_workers=1, log=lambda *_a, **_k: None,
    )

    # All succeed, so the breaker never opens and every product is fetched.
    assert detail_calls["n"] == n_products
