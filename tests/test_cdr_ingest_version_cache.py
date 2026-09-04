"""Per-holder CDR version-capability cache (audit P0-retry Phase-4).

A holder on an older x-v would otherwise re-negotiate v6->v5->... on every page and
every product-detail fetch. fetch_cdr_json reports the winning version; ingest_brand
caches it per holder and tries it first for the rest of that holder's requests.
"""

import cdr_ingest_lib as lib
import cdr_ingest_support as cis
from cdr_ingest_support import FetchResult


def _seq_http(monkeypatch, seq):
    monkeypatch.setattr(cis.time, "sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def fake_http(url, headers, *, timeout):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    monkeypatch.setattr(cis, "http_request", fake_http)


def test_fetch_cdr_json_reports_winning_version(monkeypatch):
    # versions=[3] is tried first; a 200 there reports version 3.
    _seq_http(monkeypatch, [(200, '{"data": {}}', None)])
    res = cis.fetch_cdr_json("http://x", versions=[3], timeout=1, max_retries=2, sleep_ms=0)
    assert res.ok is True and res.version == 3


def test_ingest_brand_caches_holder_version(tmp_path, monkeypatch):
    versions_seen = []

    def fake_fetch(url, *, versions=None, timeout, max_retries, sleep_ms, **_kw):
        versions_seen.append(versions)
        # The product-index page negotiates to v4; details echo OK.
        product_id = url.rsplit("/", 1)[-1]
        body = '{"data": {}}' if product_id == "products" else f'{{"data": {{"productId": "{product_id}"}}}}'
        return FetchResult(ok=True, status=200, url=url, text=body, version=4)

    monkeypatch.setattr(lib, "fetch_cdr_json", fake_fetch)
    monkeypatch.setattr(lib, "extract_products", lambda parsed: [{"productId": "P1", "name": "Acct"}])
    monkeypatch.setattr(lib, "next_link", lambda parsed, url: None)
    ds_key = next(iter(lib.DATASET_TO_FOLDER))
    monkeypatch.setattr(lib, "classify_product_for_ingest", lambda *a, **k: (ds_key, None))

    lib.ingest_brand(
        {
            "endpoint_url": "http://holder/cds-au/v1/banking/products",
            "provider_uid": "provider-fallback:v1:" + "a" * 64,
            "provider_identity_status": "fallback",
        },
        date_root=tmp_path,
        resume=False,
        sleep_ms=0,
        timeout=1,
        max_retries=2,
        max_pages=None,
        max_products=None,
        fetch_unknown_detail=False,
        bank_dir_name="holder",
        detail_workers=1,
        log=lambda *_a, **_k: None,
    )

    # Product-index and detail endpoints version independently. The index caches
    # v4, while detail starts at its own current v7 contract.
    assert versions_seen, "expected at least the page + a detail fetch"
    assert versions_seen[0] == lib.PRODUCT_INDEX_VERSION_ORDER
    assert lib.PRODUCT_DETAIL_VERSION_ORDER in versions_seen[1:]


def test_version_list_helper():
    assert lib._index_version_list(None) == [6, 5, 4, 3, 2, 1]
    assert lib._index_version_list(4) == [4, 6, 5, 3, 2, 1]
    assert lib._detail_version_list() == [7, 6, 5, 4, 3, 2, 1]


def test_product_index_fallback_never_spends_attempt_on_detail_v7(monkeypatch):
    seen: list[int] = []

    def fake_http(url, headers, *, timeout):
        seen.append(int(headers["x-v"]))
        return 422, '{"errors":[{"detail":"unsupported"}]}', None

    monkeypatch.setattr(cis, "http_request", fake_http)
    cis.fetch_cdr_json(
        "http://holder/products",
        versions=lib._index_version_list(4),
        timeout=1,
        max_retries=0,
        sleep_ms=0,
    )
    assert seen == [4, 6, 5, 3, 2, 1]
    assert 7 not in seen
