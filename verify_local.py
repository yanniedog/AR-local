#!/usr/bin/env python3
"""Verify the read-only AR-local status API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from pi_runtime_health import status_contract_error


DEFAULT_LOCAL_URL = "http://127.0.0.1:8808/"


def request_json(url: str, *, timeout: float) -> tuple[int, dict[str, Any], dict[str, str]]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            headers = {key.lower(): value for key, value in response.headers.items()}
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        headers = {key.lower(): value for key, value in exc.headers.items()}
        raw = exc.read()
    if status == 404:
        return status, {}, headers
    value = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(value, dict):
        raise ValueError(f"{url} did not return a JSON object")
    return status, value, headers


def validate_headers(url: str, headers: dict[str, str]) -> None:
    if not headers.get("content-type", "").lower().startswith("application/json"):
        raise ValueError(f"{url} has a non-JSON content type")
    if headers.get("cache-control", "").lower() != "no-store":
        raise ValueError(f"{url} is cacheable")
    if headers.get("x-content-type-options", "").lower() != "nosniff":
        raise ValueError(f"{url} lacks nosniff")


def validate_status(value: dict[str, Any], *, expected_date: str) -> None:
    error = status_contract_error(value)
    if error is not None:
        raise ValueError(error)
    observation = value["observation"]
    observed_date = str(observation["date"])
    if expected_date and observed_date != expected_date:
        raise ValueError(f"observation date {observed_date!r}, expected {expected_date!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AR_PI_BASE_URL", "").strip() or DEFAULT_LOCAL_URL,
    )
    parser.add_argument("--expect-run-date", default="")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base = args.base_url.strip().rstrip("/") + "/"
    try:
        health_code, health, health_headers = request_json(base + "healthz", timeout=args.timeout)
        status_code, status, status_headers = request_json(base + "api/status", timeout=args.timeout)
        if health_code != 200 or status_code != 200:
            raise ValueError(f"health={health_code}, status={status_code}")
        validate_headers(base + "healthz", health_headers)
        validate_headers(base + "api/status", status_headers)
        validate_status(status, expected_date=args.expect_run_date)
        if health != {
            "schema_version": 1,
            "service": "ar-local",
            "status": "ok",
        }:
            raise ValueError("invalid health contract")
        removed_code, _, _ = request_json(base + "api/latest", timeout=args.timeout)
        if removed_code != 404:
            raise ValueError("removed dashboard API is still exposed")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"verify_local: FAIL {base}: {exc}", file=sys.stderr)
        return 1
    print(f"verify_local: OK {base} observation={status['observation']['date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
