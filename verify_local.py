#!/usr/bin/env python3
"""HTTP smoke checks for the CDR dashboard (replaces verify:prod for this repo).

Default base URL: http://127.0.0.1:8808/ (local dev). For Pi acceptance, set
AR_PI_BASE_URL (e.g. http://100.78.28.10/) or pass --base-url. See
.cursor/rules/pi-host-not-localhost.mdc and npm run verify:pi.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

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


def main() -> int:
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
    args = parser.parse_args()
    base = args.base_url.strip().rstrip("/") + "/"
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
    ]
    failures: list[tuple[str, int]] = []
    for path in paths:
        url = base + path
        code = http_get(url)
        if code != 200:
            failures.append((url, code))
    if failures:
        for url, code in failures:
            print(f"verify_local: {code} {url}", file=sys.stderr)
        return 1
    latest_url = base + "api/latest"
    try:
        with urllib.request.urlopen(latest_url, timeout=30.0) as resp:
            latest_payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"verify_local: failed to read {latest_url}: {exc}", file=sys.stderr)
        return 1
    run_date = latest_payload.get("run_date")
    if run_date:
        for path in (
            f"api/banks/ribbon?date={run_date}&section=Mortgage",
            f"api/banks/section?date={run_date}&section=Mortgage",
            f"api/banks/history/section?date={run_date}&section=Mortgage",
        ):
            url = base + path
            code = http_get(url)
            if code != 200:
                print(f"verify_local: {code} {url}", file=sys.stderr)
                return 1
    if args.require_banks_rates:
        rates = manifest_banks_rate_count(latest_payload)
        if rates <= 0:
            print(
                f"verify_local: /api/latest run_date={run_date!r} has banks_counts.rates={rates}",
                file=sys.stderr,
            )
            return 1
        print(f"verify_local: OK {base} (run_date={run_date}, banks_rates={rates})")
        return 0
    print(f"verify_local: OK {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
