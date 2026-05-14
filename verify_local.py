#!/usr/bin/env python3
"""HTTP smoke checks for the local CDR dashboard (replaces verify:prod for this repo)."""

from __future__ import annotations

import argparse
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
    args = parser.parse_args()
    base = args.base_url.strip().rstrip("/") + "/"
    paths = [
        "",
        "assets/app.css",
        "assets/ar-bank-brand.js",
        "assets/local-brand.js",
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
    print(f"verify_local: OK {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
