#!/usr/bin/env python3
"""HTTP smoke checks for the local CDR dashboard (replaces verify:prod for this repo)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


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
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8808/",
        help="Dashboard root URL (include trailing slash optional)",
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
        "api/banks/history",
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
    if args.require_banks_rates:
        latest_url = base + "api/latest"
        try:
            with urllib.request.urlopen(latest_url, timeout=30.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            print(f"verify_local: failed to read {latest_url}: {exc}", file=sys.stderr)
            return 1
        rates = int((payload.get("banks_counts") or {}).get("rates") or 0)
        run_date = payload.get("run_date")
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
