"""Regression tests for the shared CDR retry budget (audit P0-retry).

Before the budget, fetch_cdr_json walked all 6 API versions with a fresh
max_retries budget each, then walked them again - 6 * (6 + 1) = 42 upstream hits
for one logical fetch on a persistent outage. These lock in the cap while keeping
version negotiation working.
"""

import cdr_ingest_support as cis


def _count_calls(monkeypatch, status, body=""):
    calls = {"n": 0}

    def fake_http(url, headers, *, timeout):
        calls["n"] += 1
        return status, body

    monkeypatch.setattr(cis, "http_request", fake_http)
    monkeypatch.setattr(cis.time, "sleep", lambda *_a, **_k: None)
    return calls


def test_persistent_5xx_is_capped_by_default_budget(monkeypatch):
    calls = _count_calls(monkeypatch, 503)
    res = cis.fetch_cdr_json("http://x", timeout=1, max_retries=6, sleep_ms=0)
    assert res.ok is False
    # Default budget = max(max_retries + 1, len(CDR_VERSION_ORDER) + 2) = 8,
    # not 42. The whole logical fetch shares it across versions.
    assert calls["n"] == 8


def test_explicit_attempt_budget_is_honored(monkeypatch):
    calls = _count_calls(monkeypatch, 503)
    res = cis.fetch_cdr_json(
        "http://x", timeout=1, max_retries=6, sleep_ms=0, max_total_attempts=3
    )
    assert res.ok is False
    assert calls["n"] == 3


def test_first_version_success_costs_one_attempt(monkeypatch):
    calls = _count_calls(monkeypatch, 200, '{"data": {}}')
    res = cis.fetch_cdr_json("http://x", timeout=1, max_retries=6, sleep_ms=0)
    assert res.ok is True
    assert calls["n"] == 1
    assert res.attempts == 1


def test_non_retryable_status_does_not_burn_budget_on_one_version(monkeypatch):
    # 404 is not retryable: each version is tried exactly once, so the walk can
    # still negotiate across versions cheaply (no amplification).
    calls = _count_calls(monkeypatch, 404)
    res = cis.fetch_cdr_json("http://x", timeout=1, max_retries=6, sleep_ms=0)
    assert res.ok is False
    # One attempt per distinct known version, never more than the budget.
    assert calls["n"] == len(cis.CDR_VERSION_ORDER)
    assert calls["n"] <= 8
