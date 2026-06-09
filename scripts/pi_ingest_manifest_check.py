"""Check GitHub app-payload manifest freshness; alert when ingest is stale."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ar_local_ingest_schedule import DAILY_INGEST_UTC_HOUR, expected_run_date_for_due, latest_daily_due_utc

MANIFEST_URL = (
    "https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json"
)
DEFAULT_GRACE_MINUTES = 90


def fetch_manifest(url: str = MANIFEST_URL, timeout: int = 30) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify app-payload manifest run_date is current.")
    parser.add_argument(
        "--expected-tz",
        default=None,
        help="IANA timezone; expected run_date is today's calendar date in this zone.",
    )
    parser.add_argument("--grace-minutes", type=int, default=DEFAULT_GRACE_MINUTES)
    parser.add_argument("--manifest-url", default=MANIFEST_URL)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--alert", action="store_true", help="Send SMTP email when stale (Pi-side).")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    now_utc = datetime.now(timezone.utc)

    manifest_error: Optional[str] = None
    run_date = ""
    generated_at = ""
    try:
        manifest = fetch_manifest(args.manifest_url)
        run_date = str(manifest.get("run_date") or "")
        generated_at = str(manifest.get("generated_at") or "")
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        manifest_error = str(exc)

    if args.expected_tz:
        tz = ZoneInfo(args.expected_tz)
        expected = datetime.now(tz).date().isoformat()
        stale = manifest_error is not None or not run_date or run_date < expected
        payload = {
            "now_utc": now_utc.isoformat(),
            "expected_tz": args.expected_tz,
            "expected_run_date": expected,
            "manifest_run_date": run_date,
            "generated_at": generated_at,
            "stale": stale,
            "manifest_error": manifest_error,
        }
    else:
        due_utc = latest_daily_due_utc(now_utc)
        expected = expected_run_date_for_due(due_utc)
        ready_at = due_utc + timedelta(minutes=max(0, args.grace_minutes))
        stale = manifest_error is not None or (run_date < expected and now_utc >= ready_at)
        payload = {
            "now_utc": now_utc.isoformat(),
            "due_utc": due_utc.isoformat(),
            "ready_at_utc": ready_at.isoformat(),
            "expected_run_date": expected,
            "manifest_run_date": run_date,
            "generated_at": generated_at,
            "stale": stale,
            "schedule_utc_hour": DAILY_INGEST_UTC_HOUR,
            "manifest_error": manifest_error,
        }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        status = "stale" if stale else "ok"
        print(
            f"pi_ingest_manifest_check: {status} expected={expected} manifest={run_date} "
            f"generated_at={generated_at}"
        )
        if manifest_error:
            print(f"pi_ingest_manifest_check: manifest_error={manifest_error}")

    if stale and args.alert:
        from pi_ingest_alert import main as alert_main

        details = (
            f"GitHub manifest run_date={run_date or 'missing'} is older than expected {expected}.\n"
            f"generated_at={generated_at}\n"
            f"manifest_url={args.manifest_url}"
        )
        if manifest_error:
            details += f"\nmanifest_error={manifest_error}"
        return alert_main(
            [
                "--reason",
                "manifest-stale",
                "--run-date",
                expected,
                "--details",
                details,
            ]
        )

    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
