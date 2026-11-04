#!/usr/bin/env python3
"""HTTP /api/latest smoke helpers for Pi deploy verify."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

from ar_local_pi_runtime import manifest_banks_rate_count

EXIT_OK = 0
EXIT_VERIFY_FAIL = 1


def http_smoke(
    base_url: str,
    *,
    require_rates: bool = True,
    timeout_seconds: float = 30.0,
) -> int:
    latest = base_url.rstrip("/") + "/api/latest"
    try:
        with urllib.request.urlopen(latest, timeout=timeout_seconds) as resp:
            if int(resp.status) != 200:
                print(f"pi_deploy_verify: {latest} HTTP {resp.status}", file=sys.stderr)
                return EXIT_VERIFY_FAIL
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"pi_deploy_verify: {latest} HTTP {exc.code}", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    except Exception as exc:
        print(f"pi_deploy_verify: {latest} failed: {exc}", file=sys.stderr)
        return EXIT_VERIFY_FAIL

    rates = manifest_banks_rate_count(payload)
    run_date = payload.get("run_date")
    if require_rates and rates <= 0:
        print(
            f"pi_deploy_verify: /api/latest run_date={run_date!r} banks_counts.rates={rates}",
            file=sys.stderr,
        )
        return EXIT_VERIFY_FAIL
    print(f"pi_deploy_verify: HTTP OK {latest} run_date={run_date} rates={rates}")
    return EXIT_OK


def wait_for_http_smoke(
    base_url: str,
    *,
    require_rates: bool = True,
    attempts: int = 13,
    delay_seconds: float = 10.0,
    budget_seconds: float = 120.0,
) -> int:
    """Allow the dashboard's preload phase to finish after a service restart."""
    deadline = time.monotonic() + max(0.0, budget_seconds)
    result = EXIT_VERIFY_FAIL
    for attempt in range(1, attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = http_smoke(
            base_url,
            require_rates=require_rates,
            timeout_seconds=min(30.0, remaining),
        )
        if result == EXIT_OK:
            return EXIT_OK
        remaining = deadline - time.monotonic()
        if attempt < attempts and remaining > 0:
            sleep_seconds = min(delay_seconds, remaining)
            print(
                f"pi_deploy_verify: dashboard not ready after restart "
                f"(attempt {attempt}/{attempts}); retrying in {sleep_seconds:g}s"
            )
            time.sleep(sleep_seconds)
    return result
