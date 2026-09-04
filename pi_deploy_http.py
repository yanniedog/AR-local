"""Small HTTP contract probes shared by Pi deploy and rollback."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from ar_local_pi_runtime import export_manifest_is_valid
from pi_runtime_health import status_contract_error

EXIT_OK = 0
EXIT_VERIFY_FAIL = 1
Probe = Callable[..., int]


def _read_json(url: str, timeout_seconds: float) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            if int(response.status) != 200:
                return None
            value = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, ValueError, urllib.error.HTTPError):
        return None
    return value if isinstance(value, dict) else None


def status_smoke(base_url: str, *, timeout_seconds: float = 30.0) -> int:
    url = base_url.rstrip("/") + "/api/status"
    payload = _read_json(url, timeout_seconds)
    contract_error = status_contract_error(payload) if payload is not None else "missing status"
    if contract_error is not None:
        print(f"pi_deploy_verify: invalid status contract at {url}", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    observation = payload["observation"]
    print(f"pi_deploy_verify: HTTP OK {url} observation={observation['date']}")
    return EXIT_OK


def legacy_smoke(base_url: str, *, timeout_seconds: float = 30.0) -> int:
    url = base_url.rstrip("/") + "/api/latest"
    payload = _read_json(url, timeout_seconds)
    if payload is None or not export_manifest_is_valid(payload):
        print(
            f"pi_deploy_verify: invalid protected dashboard contract at {url}",
            file=sys.stderr,
        )
        return EXIT_VERIFY_FAIL
    print(f"pi_deploy_verify: protected HTTP OK {url}")
    return EXIT_OK


def wait_for_smoke(
    probe: Probe,
    base_url: str,
    *,
    attempts: int = 10,
    delay_seconds: float = 2.0,
    budget_seconds: float = 30.0,
) -> int:
    deadline = time.monotonic() + max(0.0, budget_seconds)
    result = EXIT_VERIFY_FAIL
    for attempt in range(1, attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = probe(base_url, timeout_seconds=min(30.0, remaining))
        if result == EXIT_OK:
            return EXIT_OK
        remaining = deadline - time.monotonic()
        if attempt < attempts and remaining > 0:
            delay = min(delay_seconds, remaining)
            print(
                f"pi_deploy_verify: HTTP contract not ready "
                f"(attempt {attempt}/{attempts}); retrying in {delay:g}s"
            )
            time.sleep(delay)
    return result
