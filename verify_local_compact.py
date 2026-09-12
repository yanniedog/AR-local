"""Bounded validation of the dashboard's compact-history HTTP contract."""
from __future__ import annotations

import json
import math
import time
import urllib.request
from datetime import date

# Same decoded-body budget as tests/test_audit_budgets.py; no raw history rows.
MAX_JSON_BYTES = 20 * 1024 * 1024
STATS = ("min", "max", "mean", "median")


def read_json(url: str, timeout: float) -> dict:
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f"HTTP {response.status}")
        expected_size = response.length
        if expected_size is not None and expected_size > MAX_JSON_BYTES:
            raise ValueError("JSON response exceeds 20 MiB body limit")
        # urllib's HTTP(S) response is backed by this CPython socket. Retain it
        # before read1 can close response.fp, and spend only the remaining deadline
        # after headers; a fresh full socket timeout per chunk would extend it.
        connection = response.fp.raw._sock
        chunks, size = [], 0
        # read1 performs at most one underlying read, so a trickling response
        # cannot avoid the elapsed check until the entire body has arrived.
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise ValueError("JSON response exceeded request deadline")
            connection.settimeout(remaining)
            chunk = response.read1(min(65536, MAX_JSON_BYTES + 1 - size))
            if time.monotonic() - started > timeout:
                raise ValueError("JSON response exceeded request deadline")
            size += len(chunk)
            if size > MAX_JSON_BYTES:
                raise ValueError("JSON response exceeds 20 MiB body limit")
            chunks.append(chunk)
            if not chunk or response.isclosed():
                break
        if expected_size is not None and size != expected_size:
            raise ValueError("incomplete JSON response body")
    result = json.loads(b"".join(chunks).decode("utf-8"),
                        parse_constant=lambda value: invalid(f"non-finite JSON number: {value}"))
    if not isinstance(result, dict):
        raise ValueError("JSON response must be an object")
    return result


def invalid(message: str):
    raise ValueError(message)


def count(value) -> int:
    if type(value) is not int or value < 0:
        invalid("invalid rate count")
    return value


def day(value) -> str:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        invalid("invalid history date")
    return value


def stats(value: dict) -> int:
    if not isinstance(value, dict) or not set(STATS).issubset(value):
        invalid("missing history statistics")
    for key in STATS:
        number = value[key]
        if number is not None and (type(number) not in (int, float) or not math.isfinite(number)):
            invalid("invalid history statistic")
    return count(value.get("count"))


def envelope(value: dict, run_date: str, section: str) -> None:
    if not isinstance(value, dict) or value.get("run_date") != run_date or value.get("section") != section:
        invalid("response date/section differs from request")


def validate(history: dict, current: dict, ribbon: dict, run_date: str, section: str) -> None:
    """Check actual dated series against current SQL responses, not echoed labels.

    A section can have no rows, or only non-standard/non-positive rows. Neither
    condition requires a positive standard-rate point. Historical null statistics
    and sparse provider dates are part of the shipping contract.
    """
    day(run_date)
    for payload in (history, current, ribbon):
        envelope(payload, run_date, section)
    rows = current.get("rates")
    current_count = count((current.get("counts") or {}).get("rates"))
    if not isinstance(rows, list) or len(rows) != current_count or any(not isinstance(row, dict) for row in rows):
        invalid("invalid current section rows/count")
    ribbon_count = count((ribbon.get("counts") or {}).get("rates"))
    if ribbon_count > current_count:
        invalid("ribbon rate count exceeds current section")
    if not isinstance(ribbon.get("range"), dict):
        invalid("missing current ribbon statistics")
    stats({**ribbon["range"], "count": ribbon_count})
    if history.get("include_non_standard") is not False:
        invalid("compact response is not the requested standard-only variant")
    dates, points, providers = (history.get(key) for key in ("run_dates", "points", "providers"))
    if not isinstance(dates, list) or any(day(item) > run_date for item in dates):
        invalid("invalid history dates")
    if dates != sorted(set(dates)) or not isinstance(points, list) or len(points) != len(dates):
        invalid("history points must cover unique ordered dates")
    for expected, point in zip(dates, points):
        stats(point)
        if point.get("date") != expected:
            invalid("history point date differs from run_dates")
    if not isinstance(providers, list):
        invalid("missing provider series")
    names, current_provider_count = set(), 0
    for provider in providers:
        if not isinstance(provider, dict) or not isinstance(provider.get("provider"), str) or not provider["provider"]:
            invalid("invalid history provider")
        name, by_date = provider["provider"], provider.get("by_date")
        if name in names or not isinstance(by_date, dict) or not set(by_date).issubset(dates):
            invalid("invalid sparse provider dates")
        names.add(name)
        for when, value in by_date.items():
            total = stats(value)
            if when == run_date:
                current_provider_count += total
    if current_count and run_date not in dates:
        invalid("current section has rows but compact history has no requested-day point")
    if ribbon_count:
        point = points[dates.index(run_date)]
        if not point["count"] or any(point[key] is None for key in STATS) or not current_provider_count:
            invalid("current ribbon has rates but compact history has no usable current-day series")
