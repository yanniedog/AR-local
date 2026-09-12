#!/usr/bin/env python3
"""HTTP smoke checks for the CDR dashboard (replaces verify:prod for this repo).

Default base URL: http://127.0.0.1:8808/ (local dev). For Pi acceptance, set
AR_PI_BASE_URL (e.g. http://100.78.28.10/) or pass --base-url. See
.cursor/rules/pi-host-not-localhost.mdc and npm run verify:pi.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

_DEFAULT_LOCAL = "http://127.0.0.1:8808/"

from ar_local_pi_runtime import manifest_banks_rate_count


def http_get(url: str, timeout: float = 30.0) -> int:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception as exc:
        print(f"verify_local: failed {url}: {exc}", file=sys.stderr)
        return -1


def history_timeout(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 < seconds <= 90:
        raise argparse.ArgumentTypeError("history timeout must be greater than 0 and at most 90 seconds")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-verify local CDR dashboard HTTP endpoints.")
    env_base = os.environ.get("AR_PI_BASE_URL", "").strip()
    default_base = env_base if env_base else _DEFAULT_LOCAL
    parser.add_argument(
        "--base-url",
        default=default_base,
        help="Dashboard root URL (trailing slash optional). Default: %(default)s (AR_PI_BASE_URL when set).",
    )
    parser.add_argument(
        "--require-banks-rates",
        action="store_true",
        help="Fail unless /api/latest reports banks_counts.rates > 0.",
    )
    parser.add_argument(
        "--expect-run-date",
        default="",
        help="Fail unless /api/latest run_date equals this YYYY-MM-DD date.",
    )
    parser.add_argument("--history-timeout-seconds", type=history_timeout, default=30.0,
                        help="Header deadline for the three history/section requests only (default: 30; maximum: 90).")
    parser.add_argument("--history-mode", choices=("raw", "compact"), default="raw",
                        help="History response to verify. Routine restart checks use compact; full acceptance defaults to raw.")
    parser.add_argument("--progress", action="store_true", help="Print each request and result immediately.")
    args = parser.parse_args(argv)
    base = args.base_url.strip().rstrip("/") + "/"
    def progress(message: str) -> None:
        if args.progress:
            print(f"[{datetime.now(timezone.utc).isoformat()}] verify_local: {message}", flush=True)
    def request(path: str) -> int:
        timeout = args.history_timeout_seconds if path.startswith("api/banks/history/section") else 30.0
        started = time.monotonic()
        progress(f"GET {base + path} timeout={timeout:g}s")
        code = http_get(base + path, timeout=timeout)
        progress(f"status={code} elapsed={time.monotonic() - started:.3f}s {base + path}")
        return code
    paths = [
        "",
        "savings/",
        "savings",
        "term-deposits/",
        "term-deposits",
        "home-loans/",
        "home-loans",
        "assets/app.css",
        "assets/app.js",
        "assets/ar-bank-brand.js",
        "assets/chart.js",
        "assets/local-brand.js",
        "assets/cdr-taxonomy-tree.js",
        "site/theme.js",
        "site/foundation.css",
        "site/ar-ribbon-format.js",
        "site/ar-ribbon-tree.js",
        "api/latest",
        "api/ingest-schedule",
        "economic-data/",
        "api/economic-data/catalog",
        "api/home-loan-rates/rba/history",
    ]
    failures: list[tuple[str, int]] = []
    for path in paths:
        url = base + path
        code = request(path)
        if code != 200:
            failures.append((url, code))
    if failures:
        for url, code in failures:
            print(f"verify_local: {code} {url}", file=sys.stderr)
        return 1
    latest_url = base + "api/latest"
    try:
        started = time.monotonic()
        progress(f"GET JSON {latest_url} timeout=30s")
        with urllib.request.urlopen(latest_url, timeout=30.0) as resp:
            latest_payload = json.loads(resp.read().decode("utf-8"))
        progress(f"JSON complete elapsed={time.monotonic() - started:.3f}s {latest_url}")
    except Exception as exc:
        print(f"verify_local: failed to read {latest_url}: {exc}", file=sys.stderr)
        return 1
    run_date = latest_payload.get("run_date")
    if args.expect_run_date and run_date != args.expect_run_date:
        print(
            f"verify_local: /api/latest run_date={run_date!r}, expected {args.expect_run_date!r}",
            file=sys.stderr,
        )
        return 1
    if run_date:
        history_endpoint = "api/banks/history/section"
        if args.history_mode == "compact":
            history_endpoint += "/compact"
        for section in ("Mortgage", "Savings", "TD"):
            for path in (
                f"api/banks/ribbon?date={run_date}&section={section}",
                f"api/banks/section?date={run_date}&section={section}",
                f"{history_endpoint}?date={run_date}&section={section}",
            ):
                url = base + path
                code = request(path)
                if code != 200:
                    print(f"verify_local: {code} {url}", file=sys.stderr)
                    return 1
        for path in (
            "api/term-deposit-rates/latest?min_rate=0.01&limit=20000",
            "api/home-loan-rates/latest?rate_structure=fixed_1yr&security_purpose=owner_occupied&repayment_type=principal_and_interest&min_rate=0.01&limit=20000",
        ):
            url = base + path
            code = request(path)
            if code != 200:
                print(f"verify_local: {code} {url}", file=sys.stderr)
                return 1
    removed_endpoint = "api/" + "en" + "ergy"
    removed_code = request(removed_endpoint)
    if removed_code != 404:
        print(f"verify_local: expected 404 for removed CDR sector endpoint, got {removed_code}", file=sys.stderr)
        return 1
    removed_key = "en" + "ergy"
    if removed_key + "_counts" in latest_payload or removed_key in latest_payload:
        print("verify_local: /api/latest still exposes removed CDR sector keys", file=sys.stderr)
        return 1
    if args.require_banks_rates:
        rates = manifest_banks_rate_count(latest_payload)
        if rates <= 0:
            print(
                f"verify_local: /api/latest run_date={run_date!r} has banks_counts.rates={rates}",
                file=sys.stderr,
            )
            return 1
        print(f"verify_local: OK {base} (run_date={run_date}, banks_rates={rates}, history={args.history_mode})")
        return 0
    print(f"verify_local: OK {base} (history={args.history_mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
