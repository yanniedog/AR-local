#!/usr/bin/env python3
"""Verify the read-only AR-local status API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any


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
    if value.get("schema_version") != 1 or value.get("service") != "ar-local":
        raise ValueError("invalid status contract identity")
    if value.get("status") not in {"ok", "degraded"}:
        raise ValueError(f"status is {value.get('status')!r}")
    observation = value.get("observation")
    if not isinstance(observation, dict):
        raise ValueError("status lacks observation")
    observed_date = str(observation.get("date") or "")
    date.fromisoformat(observed_date)
    observed_at = datetime.fromisoformat(str(observation.get("observed_at") or "").replace("Z", "+00:00"))
    if observed_at.tzinfo is None:
        raise ValueError("observed_at lacks a timezone")
    if expected_date and observed_date != expected_date:
        raise ValueError(f"observation date {observed_date!r}, expected {expected_date!r}")
    if observation.get("state") not in {"complete", "degraded"}:
        raise ValueError("invalid observation state")
    if not str(observation.get("accounting_id") or "").strip():
        raise ValueError("missing accounting_id")
    for name in ("providers", "products", "issues"):
        summary = observation.get(name)
        if not isinstance(summary, dict) or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in summary.values()
        ):
            raise ValueError(f"invalid {name} summary")


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
        removed_code, removed, _ = request_json(base + "api/latest", timeout=args.timeout)
        if removed_code != 404 or removed.get("status") != "not_found":
            raise ValueError("removed dashboard API is still exposed")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"verify_local: FAIL {base}: {exc}", file=sys.stderr)
        return 1
    print(f"verify_local: OK {base} observation={status['observation']['date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
