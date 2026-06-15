"""Regression tests for the shared CDR retry budget (audit P0-retry).

Before the budget, fetch_cdr_json walked all 6 API versions with a fresh
max_retries budget each, then walked them again - 6 * (6 + 1) = 42 upstream hits
for one logical fetch on a persistent outage. These lock in the cap while keeping
version negotiation (and per-version reserve) working.
"""

import cdr_ingest_support as cis


def _count_calls(monkeypatch, status, body=""):
    """Patch http_request to count calls and return a status.

    ``status`` may be an int (always returned) or a sequence consumed in order,
    falling back to the last element once exhausted.
    """
    calls = {"n": 0}
    seq = list(status) if isinstance(status, (list, tuple)) else None

    def fake_http(url, headers, *, timeout):
        calls["n"] += 1
        if seq is not None:
            code = seq[min(calls["n"] - 1, len(seq) - 1)]
        else:
            code = status
        return code, body

    monkeypatch.setattr(cis, "http_request", fake_http)
    monkeypatch.setattr(cis.time, "sleep", lambda *_a, **_k: None)
    return calls


def test_persistent_5xx_is_capped_by_default_budget(monkeypatch):
    calls = _count_calls(monkeypatch, 503)
    res = cis.fetch_cdr_json("http://x", timeout=1, max_retries=6, sleep_ms=0)
    assert res.ok is False
    # Default budget = max(max_retries + 1, len(CDR_VERSION_ORDER) + 2) = 8, not 42.
    assert calls["n"] == 8
    # attempts reflects the cumulative HTTP attempts across the whole logical fetch.
    assert res.attempts == calls["n"]


def test_explicit_attempt_budget_is_honored(monkeypatch):
    calls = _count_calls(monkeypatch, 503)
    res = cis.fetch_cdr_json(
        "http://x", timeout=1, max_retries=6, sleep_ms=0, max_total_attempts=3
    )
    assert res.ok is False
    assert calls["n"] == 3
    assert res.attempts == 3


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
    assert calls["n"] == len(cis.CDR_VERSION_ORDER)
    assert calls["n"] <= 8
    assert res.attempts == calls["n"]


def test_reserve_lets_a_later_version_succeed_within_budget(monkeypatch):
    # Three retryable failures, then success. The per-version reserve guarantees
    # the budget is not spent entirely on the preferred version, so the walk
    # reaches the working one and the shared budget is decremented across versions.
    calls = _count_calls(monkeypatch, [503, 503, 503, 200], '{"data": {}}')
    res = cis.fetch_cdr_json(
        "http://x", timeout=1, max_retries=6, sleep_ms=0, max_total_attempts=4
    )
    assert res.ok is True
    assert calls["n"] == 4
    assert res.attempts == 4


def test_deadline_terminates_early(monkeypatch):
    # Once the wall-clock deadline passes, no further upstream requests are made.
    calls = _count_calls(monkeypatch, 503)
    ticks = iter([0.0, 0.0, 0.0])  # deadline calc + first checks, then exhausted
    monkeypatch.setattr(cis.time, "monotonic", lambda: next(ticks, 100.0))
    res = cis.fetch_cdr_json(
        "http://x", timeout=1, max_retries=6, sleep_ms=0, max_total_seconds=10
    )
    assert res.ok is False
    # Deadline trips well before the 8-attempt budget would.
    assert calls["n"] < len(cis.CDR_VERSION_ORDER)
