"""Resource-amplification guard for CDR requests."""

import cdr_ingest_support as cis

# One CDR logical fetch must not exceed the shared attempt budget across versions.
MAX_CDR_ATTEMPTS = 8


def test_cdr_logical_fetch_capped_at_attempt_budget(monkeypatch):
    # A persistent 5xx must not exceed the shared attempt budget for one logical
    # fetch (the audit's amplification guard: 6 versions x 7 retries = 42 -> <= 8).
    monkeypatch.setattr(cis.time, "sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def fake_http(url, headers, *, timeout):
        calls["n"] += 1
        return 503, "", None

    monkeypatch.setattr(cis, "http_request", fake_http)
    res = cis.fetch_cdr_json("http://x", timeout=1, max_retries=6, sleep_ms=0)
    assert res.attempts <= MAX_CDR_ATTEMPTS
    assert calls["n"] <= MAX_CDR_ATTEMPTS
