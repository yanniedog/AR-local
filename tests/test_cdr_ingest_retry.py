"""Regression tests for the shared CDR retry budget (audit P0-retry).

Before the budget, fetch_cdr_json walked all 6 API versions with a fresh
max_retries budget each, then walked them again - 6 * (6 + 1) = 42 upstream hits
for one logical fetch on a persistent outage. These lock in the cap while keeping
version negotiation (and per-version reserve) working.
"""

import hashlib
import json

import cdr_ingest_support as cis
from cdr_http_policy import PolicyResponse
from cdr_raw_attempt_journal import RawAttemptJournal


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
    # Default budget remains the locked eight-attempt amplification ceiling.
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
    # A naive RFC 1123 date (no timezone) is treated as UTC.
    naive = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime("%a, %d %b %Y %H:%M:%S")
    naive_secs = cis._parse_retry_after(naive)
    assert naive_secs is not None and 20 <= naive_secs <= 40
    # A huge value is capped so it can't park a worker thread (Gemini security-high).
    assert cis._parse_retry_after("100000") == cis.MAX_RETRY_AFTER_SECONDS


def _seq_http(monkeypatch, seq):
    sleeps: list = []
    monkeypatch.setattr(cis.time, "sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}

    def fake_http(url, headers, *, timeout):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    monkeypatch.setattr(cis, "http_request", fake_http)
    return sleeps


def test_retry_after_header_extends_backoff(monkeypatch):
    # A 503 with Retry-After: 7 must make the retry wait at least 7s, then succeed.
    sleeps = _seq_http(monkeypatch, [(503, "", 7.0), (200, '{"data": {}}', None)])
    res = cis.fetch_cdr_json("http://x", timeout=1, max_retries=6, sleep_ms=0)
    assert res.ok is True
    assert any(s >= 7.0 for s in sleeps), sleeps


def test_retry_after_shorter_than_backoff_does_not_shrink_delay(monkeypatch):
    # A tiny Retry-After must NOT reduce the wait below the exponential backoff.
    sleeps = _seq_http(monkeypatch, [(503, "", 0.1), (200, '{"data": {}}', None)])
    res = cis.fetch_cdr_json("http://x", timeout=1, max_retries=6, sleep_ms=0)
    assert res.ok is True
    # attempt-1 backoff base is 1s; the 0.1 Retry-After can't shrink it.
    assert sleeps and all(s >= 1.0 for s in sleeps), sleeps


def test_version_switch_honors_retry_after_without_per_version_retries(monkeypatch):
    # Codex P1: with no same-version retry budget (reserve path), a 503 + Retry-After
    # on one x-v must still pace the switch to the next version by Retry-After,
    # not just the ~0.25s version-switch pace.
    sleeps = _seq_http(monkeypatch, [(503, "", 8.0), (200, '{"data": {}}', None)])
    res = cis.fetch_cdr_json("http://x", timeout=1, max_retries=6, sleep_ms=0, max_total_attempts=2)
    assert res.ok is True
    assert any(s >= 8.0 for s in sleeps), sleeps


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


def test_compact_406_advertisement_is_tried_next(monkeypatch):
    seen: list[int] = []

    def fake_http(url, headers, *, timeout):
        seen.append(int(headers["x-v"]))
        if len(seen) == 1:
            return 406, '{"detail":"Requested: 6-6 Available: 8"}', None
        return 200, '{"data": {}}', None

    monkeypatch.setattr(cis, "http_request", fake_http)
    result = cis.fetch_cdr_json(
        "http://x", versions=[6], timeout=1, max_retries=0, sleep_ms=0
    )
    assert result.ok is True and result.version == 8
    assert seen == [6, 8]


def test_out_of_range_long_advertisement_cannot_consume_attempt(monkeypatch):
    seen: list[int] = []

    def fake_http(url, headers, *, timeout):
        seen.append(int(headers["x-v"]))
        if len(seen) == 1:
            return 406, '{"detail":"Versions available: 100, 6"}', None
        return 200, '{"data": {}}', None

    monkeypatch.setattr(cis, "http_request", fake_http)
    result = cis.fetch_cdr_json(
        "http://x", versions=[5], timeout=1, max_retries=0, sleep_ms=0
    )
    assert result.ok is True and result.version == 6
    assert seen == [5, 6]


def test_caller_cannot_expand_attempt_or_retry_caps(monkeypatch):
    calls = _count_calls(monkeypatch, 503)
    res = cis.fetch_cdr_json(
        "https://holder.example/products",
        timeout=999,
        max_retries=999,
        sleep_ms=0,
        max_total_attempts=999,
    )
    assert res.ok is False
    assert calls["n"] == cis.DEFAULT_HTTP_POLICY.max_total_attempts


def test_upstream_5xx_retries_but_deterministic_policy_failures_do_not(monkeypatch):
    upstream_calls = _count_calls(monkeypatch, 501)
    cis.fetch_with_retries(
        "https://holder.example/products",
        {},
        timeout=1,
        max_retries=1,
        sleep_ms=0,
        retry_on=cis.retryable_status,
    )
    assert upstream_calls["n"] == 2

    policy_calls = _count_calls(monkeypatch, 596)
    cis.fetch_with_retries(
        "https://holder.example/products",
        {},
        timeout=1,
        max_retries=6,
        sleep_ms=0,
        retry_on=cis.retryable_status,
    )
    assert policy_calls["n"] == 1


def test_retry_attempts_are_immutably_journaled_with_version_context(tmp_path, monkeypatch):
    replies = iter((503, 200))

    def fake_request(url, headers, *, timeout):
        status = next(replies)
        body = b'{"data":{}}' if status == 200 else b"unavailable"
        return PolicyResponse(
            status=status,
            url=url,
            headers={"content-type": "application/json"},
            body=body,
            wire_bytes=len(body),
            inflated_bytes=len(body),
            wire_sha256=hashlib.sha256(body).hexdigest(),
            peer_ip="8.8.8.8",
            redirects=(),
        )

    monkeypatch.setattr(cis, "request_https", fake_request)
    monkeypatch.setattr(cis.time, "sleep", lambda *_args: None)
    journal = RawAttemptJournal(tmp_path, "session-1")
    result = cis.fetch_cdr_json(
        "https://holder.example/products",
        versions=[4],
        timeout=5,
        max_retries=6,
        sleep_ms=0,
        max_total_attempts=2,
        attempt_journal=journal,
        attempt_context={"phase": "products_index", "request_id": "holder:page:1"},
    )

    assert result.ok is True and result.attempts == 2
    events = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(journal.events.glob("*.json"))
    ]
    assert [event["sequence"] for event in events] == [1, 2]
    assert [event["context"]["retry_ordinal"] for event in events] == [1, 2]
    assert [event["context"]["cdr_version"] for event in events] == [4, 4]
    assert journal.summary()["attempts"] == 2
