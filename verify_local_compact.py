"""Bounded validation of the dashboard's compact-history HTTP contract."""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
from datetime import date

# Same decoded-body budget as tests/test_audit_budgets.py; no raw history rows.
from verify_local_json_worker import MAX_JSON_BYTES

WORKER = Path(__file__).with_name("verify_local_json_worker.py")
STATS = ("min", "max", "mean", "median")


def read_json(url: str, timeout: float) -> dict:
    if not math.isfinite(timeout) or not 0 < timeout <= 90:
        raise ValueError("request timeout must be greater than zero and at most 90 seconds")
    # Socket timeouts cannot bound DNS or trickled headers. A stdlib-only worker
    # gives the parent cancellation authority over the complete transfer. run()
    # kills AND waits for that direct child on timeout or interruption, using
    # platform-native process termination (never a Windows signal-zero probe).
    try:
        response = subprocess.run([sys.executable, "-I", "-B", str(WORKER), url, str(timeout)],
                                  capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("JSON response exceeded whole request deadline") from error
    if response.returncode:
        raise ValueError("JSON worker failed: " + response.stderr[:1024].decode("utf-8", errors="replace").strip())
    if len(response.stdout) > MAX_JSON_BYTES:
        raise ValueError("JSON response exceeds 20 MiB body limit")
    result = json.loads(response.stdout.decode("utf-8"),
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
    # Current ribbon and the compact anchor use the same standard-only SQL rate
    # filter and aggregate_ribbon kernel. Gap filling never extends past the last
    # observed date. Compare real values, including zero/null, so an older positive
    # same-day edition cannot pass. Only floating summation-order noise is allowed.
    if run_date in dates:
        point = points[dates.index(run_date)]
        if point["count"] != ribbon_count or current_provider_count != ribbon_count:
            invalid("current-day history/provider counts differ from the live ribbon")
        for key in STATS:
            actual, expected = point[key], ribbon["range"][key]
            if (actual is None or expected is None):
                equal = actual is expected
            else:
                equal = math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
            if not equal:
                invalid("current-day history statistics differ from the live ribbon")
    if ribbon_count:
        point = points[dates.index(run_date)]
        if not point["count"] or any(point[key] is None for key in STATS) or not current_provider_count:
            invalid("current ribbon has rates but compact history has no usable current-day series")
