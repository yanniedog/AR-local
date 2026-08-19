"""Per-holder circuit breaker (audit P0-retry Phase-4).

When a holder's product-detail fetches are mostly failing (a real outage, not a
few bad products), ingest_brand stops probing the rest of that holder and fails
them fast (status "circuit_open") instead of hammering a down endpoint.
"""

import cdr_ingest_lib as lib
from cdr_ingest_support import FetchResult

ENDPOINT = "http://holder/products"


def _run(monkeypatch, tmp_path, *, n_products, detail_ok, detail_workers=1):
    """Drive ingest_brand with a per-detail ok(i) policy; capture fetch count +
    the failure records append_failure would write."""
    detail_calls = {"n": 0}
    failures = []

    def fake_fetch(url, *, versions=None, timeout, max_retries, sleep_ms, **_kw):
        if url == ENDPOINT:  # product-index page always succeeds
            return FetchResult(ok=True, status=200, url=url, text='{"data": {}}', version=4)
        i = detail_calls["n"]
        detail_calls["n"] += 1
        ok = detail_ok(i)
        return FetchResult(
            ok=ok, status=(200 if ok else 503), url=url,
            text='{"data": {}}' if ok else "", version=4 if ok else None,
        )

    monkeypatch.setattr(lib, "fetch_cdr_json", fake_fetch)
    monkeypatch.setattr(
        lib, "extract_products",
        lambda parsed: [{"productId": f"P{i}", "name": f"A{i}"} for i in range(n_products)],
    )
    monkeypatch.setattr(lib, "next_link", lambda parsed, url: None)
    ds_key = next(iter(lib.DATASET_TO_FOLDER))
    monkeypatch.setattr(lib, "classify_product_for_ingest", lambda *a, **k: (ds_key, None))
    monkeypatch.setattr(lib, "append_failure", lambda date_root, entry, lock=None: failures.append(entry))
    monkeypatch.setattr(lib, "BREAKER_RECOVERY_DELAY_SECONDS", 0)

    lib.ingest_brand(
        {"endpoint_url": ENDPOINT},
        date_root=tmp_path, resume=False, sleep_ms=0, timeout=1, max_retries=0,
        max_pages=None, max_products=None, fetch_unknown_detail=False,
        bank_dir_name="holder", detail_workers=detail_workers, log=lambda *_a, **_k: None,
    )
    return detail_calls["n"], failures


def test_failing_holder_trips_and_reports_circuit_open(tmp_path, monkeypatch):
    n = 40
    calls, failures = _run(monkeypatch, tmp_path, n_products=n, detail_ok=lambda i: False)
    # BREAKER_MIN_SAMPLE details, plus the single recovery probe that confirms the
    # holder is still down. A holder that never recovers costs exactly one extra
    # request, not a retry storm.
    assert calls == lib.BREAKER_MIN_SAMPLE + 1
    statuses = [f["status"] for f in failures]
    assert statuses.count(503) == lib.BREAKER_MIN_SAMPLE + 1  # real attempts, probe included
    # Everything the open circuit deferred except the probe, which recorded its own
    # failure rather than being written off twice.
    assert statuses.count("circuit_open") == n - lib.BREAKER_MIN_SAMPLE - 1
    assert len(failures) == n


def test_recovered_holder_refetches_every_deferred_detail(tmp_path, monkeypatch):
    """The point of the change: a passing outage no longer costs the day.

    An open circuit used to write off the holder's whole remaining catalogue, and
    that day can never be re-observed. Deferred work is now retried once the probe
    shows the holder is answering again.
    """
    n = 40
    calls, failures = _run(
        monkeypatch,
        tmp_path,
        n_products=n,
        detail_ok=lambda i: i >= lib.BREAKER_MIN_SAMPLE,
    )
    # 20 failures open the circuit, the probe succeeds, and all 19 remaining
    # deferred products are fetched instead of abandoned.
    assert calls == n
    statuses = [f["status"] for f in failures]
    assert statuses.count("circuit_open") == 0
    assert statuses.count("circuit_open_after_recovery") == 0
    assert statuses.count(503) == lib.BREAKER_MIN_SAMPLE


def test_relapse_after_recovery_is_recorded_distinctly(tmp_path, monkeypatch):
    """A holder that answers the probe then fails again is not retried forever."""
    n = 60
    probe_index = lib.BREAKER_MIN_SAMPLE

    calls, failures = _run(
        monkeypatch,
        tmp_path,
        n_products=n,
        detail_ok=lambda i: i == probe_index,
    )
    statuses = [f["status"] for f in failures]
    # Only the probe succeeded, so the retry pass re-opens the circuit and the
    # remainder is written off under its own status — one recovery attempt, no loop.
    assert statuses.count("circuit_open_after_recovery") > 0
    assert statuses.count("circuit_open") == 0
    assert calls == 2 * lib.BREAKER_MIN_SAMPLE + 1


def test_healthy_holder_never_trips(tmp_path, monkeypatch):
    n = 40
    calls, failures = _run(monkeypatch, tmp_path, n_products=n, detail_ok=lambda i: True)
    assert calls == n
    assert not any(f["status"] == "circuit_open" for f in failures)


def test_below_threshold_failures_stay_closed(tmp_path, monkeypatch):
    # ~1 in 6 fails (<< 80%): the breaker stays closed and every product is fetched.
    n = 40
    calls, failures = _run(monkeypatch, tmp_path, n_products=n, detail_ok=lambda i: i % 6 != 0)
    assert calls == n
    assert not any(f["status"] == "circuit_open" for f in failures)


def test_prefetched_details_survive_open_breaker(tmp_path, monkeypatch):
    # Products 0-19 need a Phase-2 fetch (which fails, opening the breaker); products
    # 20-39 were already prefetched OK in Phase 1. The prefetched ones must still be
    # written even though the breaker is open by the time they're processed (Codex).
    n = 40
    ds_key = next(iter(lib.DATASET_TO_FOLDER))
    good = FetchResult(ok=True, status=200, url="u", text='{"data": {"x": 1}}', version=4)

    def fake_fetch(url, *, versions=None, timeout, max_retries, sleep_ms, **_kw):
        if url == ENDPOINT:
            return FetchResult(ok=True, status=200, url=url, text='{"data": {}}', version=4)
        return FetchResult(ok=False, status=503, url=url, text="", version=None)

    def fake_classify(product, **_k):
        idx = int(product["productId"][1:])
        return (ds_key, good if idx >= lib.BREAKER_MIN_SAMPLE else None)

    monkeypatch.setattr(lib, "fetch_cdr_json", fake_fetch)
    monkeypatch.setattr(
        lib, "extract_products",
        lambda parsed: [{"productId": f"P{i}", "name": f"A{i}"} for i in range(n)],
    )
    monkeypatch.setattr(lib, "next_link", lambda parsed, url: None)
    monkeypatch.setattr(lib, "classify_product_for_ingest", fake_classify)

    lib.ingest_brand(
        {"endpoint_url": ENDPOINT},
        date_root=tmp_path, resume=False, sleep_ms=0, timeout=1, max_retries=0,
        max_pages=None, max_products=None, fetch_unknown_detail=True,
        bank_dir_name="holder", detail_workers=1, log=lambda *_a, **_k: None,
    )

    # The 20 prefetched-OK products are written despite the open breaker.
    written = list(tmp_path.rglob("product-detail.json"))
    assert len(written) == n - lib.BREAKER_MIN_SAMPLE


def test_breaker_trips_under_concurrency(tmp_path, monkeypatch):
    # With multiple detail workers and a down holder, the shared breaker still trips:
    # at least the min sample runs, well short of all products.
    n = 60
    calls, failures = _run(monkeypatch, tmp_path, n_products=n, detail_ok=lambda i: False, detail_workers=4)
    assert lib.BREAKER_MIN_SAMPLE <= calls < n
    assert any(f["status"] == "circuit_open" for f in failures)
