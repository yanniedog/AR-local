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
        return code, body, None

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
    # Clock crosses the deadline right after the first request, so the walk stops
    # far short of the 8-attempt budget instead of walking every version.
    monkeypatch.setattr(cis.time, "monotonic", lambda: 0.0 if calls["n"] < 1 else 100.0)
    res = cis.fetch_cdr_json(
        "http://x", timeout=1, max_retries=6, sleep_ms=0, max_total_seconds=10
    )
    assert res.ok is False
    assert calls["n"] <= 2


def test_request_timeout_capped_to_remaining_deadline(monkeypatch):
    # The per-request timeout is clamped to the time left on the shared deadline.
    seen = {"timeout": None}

    def fake_http(url, headers, *, timeout):
        seen["timeout"] = timeout
        return 503, "", None

    monkeypatch.setattr(cis, "http_request", fake_http)
    monkeypatch.setattr(cis.time, "sleep", lambda *_a, **_k: None)
    # Deadline 3s away but per-request timeout is 90s: the request must use <= ~3s.
    clock = iter([0.0, 0.0, 0.0])
    monkeypatch.setattr(cis.time, "monotonic", lambda: next(clock, 0.0))
    cis.fetch_cdr_json(
        "http://x", timeout=90, max_retries=0, sleep_ms=0, max_total_seconds=3
    )
    assert seen["timeout"] is not None and seen["timeout"] <= 3.0


def test_parse_retry_after_seconds_and_date_and_junk():
    from email.utils import format_datetime
    from datetime import datetime, timedelta, timezone

    assert cis._parse_retry_after("5") == 5.0
    assert cis._parse_retry_after(None) is None
    assert cis._parse_retry_after("not-a-thing") is None
    # An HTTP-date ~30s out parses to a positive, roughly-30s delta.
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30))
    secs = cis._parse_retry_after(future)
    assert secs is not None and 20 <= secs <= 40
    # An elapsed date clamps to 0 (never negative).
    past = format_datetime(datetime.now(timezone.utc) - timedelta(seconds=60))
    assert cis._parse_retry_after(past) == 0.0


def test_retry_after_header_extends_backoff(monkeypatch):
    # A 503 with Retry-After: 7 must make the retry wait at least 7s, then succeed.
    sleeps: list = []
    monkeypatch.setattr(cis.time, "sleep", lambda s: sleeps.append(s))
    seq = [(503, "", 7.0), (200, '{"data": {}}', None)]
    calls = {"n": 0}

    def fake_http(url, headers, *, timeout):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    monkeypatch.setattr(cis, "http_request", fake_http)
    res = cis.fetch_cdr_json("http://x", timeout=1, max_retries=6, sleep_ms=0)
    assert res.ok is True
    assert any(s >= 7.0 for s in sleeps), sleeps


def test_zero_total_attempts_makes_no_request(monkeypatch):
    # An explicit budget of 0 means "make no upstream request" (e.g. exhausted
    # quota), rather than being silently coerced up to one attempt.
    calls = _count_calls(monkeypatch, 503)
    res = cis.fetch_cdr_json(
        "http://x", timeout=1, max_retries=6, sleep_ms=0, max_total_attempts=0
    )
    assert res.ok is False
    assert calls["n"] == 0
    assert res.attempts == 0
