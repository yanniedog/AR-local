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
        return FetchResult(ok=True, status=200, url=url, text='{"data": {}}', version=4)

    monkeypatch.setattr(lib, "fetch_cdr_json", fake_fetch)
    monkeypatch.setattr(lib, "extract_products", lambda parsed: [{"productId": "P1", "name": "Acct"}])
    monkeypatch.setattr(lib, "next_link", lambda parsed, url: None)
    ds_key = next(iter(lib.DATASET_TO_FOLDER))
    monkeypatch.setattr(lib, "classify_product_for_ingest", lambda *a, **k: (ds_key, None))

    lib.ingest_brand(
        {"endpoint_url": "http://holder/cds-au/v1/banking/products"},
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

    # First request negotiates from the top (version unknown); after v4 is learned
    # from the page, the product-detail fetch tries [4] first.
    assert versions_seen, "expected at least the page + a detail fetch"
    assert versions_seen[0] is None
    assert [4] in versions_seen[1:]


def test_version_list_helper():
    assert lib._version_list(None) is None
    assert lib._version_list(4) == [4]
