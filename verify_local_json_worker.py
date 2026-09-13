"""One HTTP JSON-body transfer; the parent owns its entire wall-clock budget.

Only stdlib network I/O is performed. There are no child processes or writes to
source/data files. Keep the body bound here and recheck it in the parent.
"""
from __future__ import annotations

import argparse
import math
import sys
import urllib.request

MAX_JSON_BYTES = 20 * 1024 * 1024


def read_body(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f"HTTP {response.status}")
        expected = response.length
        if expected is not None and expected > MAX_JSON_BYTES:
            raise ValueError("JSON response exceeds 20 MiB body limit")
        raw = response.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError("JSON response exceeds 20 MiB body limit")
        if expected is not None and len(raw) != expected:
            raise ValueError("incomplete JSON response body")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("timeout", type=float)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 90:
        parser.error("request timeout must be greater than zero and at most 90 seconds")
    try:
        body = read_body(args.url, args.timeout)
    except Exception as error:
        print((type(error).__name__ + ": " + str(error))[:1024], file=sys.stderr)
        return 1
    sys.stdout.buffer.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
