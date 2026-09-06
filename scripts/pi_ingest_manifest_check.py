"""Check GitHub app-payload manifest freshness; alert when ingest is stale."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ar_local_ingest_schedule import (
    DAILY_INGEST_LOCAL_HOUR,
    DAILY_INGEST_SCHEDULE_LABEL,
    DAILY_INGEST_TZ_KEY,
    expected_run_date_for_due,
    latest_daily_due_utc,
)
from pi_payload_freshness import check_publication, configured_publication_urls, fetch_document

MANIFEST_URL = (
    "https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json"
)
DEFAULT_GRACE_MINUTES = 90


def fetch_manifest(url: str = MANIFEST_URL, timeout: int = 30) -> dict:
    return fetch_document(url, timeout=timeout)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify app-payload manifest run_date is current.")
    parser.add_argument(
        "--expected-tz",
        default=None,
        help="IANA timezone; expected run_date is today's calendar date in this zone.",
    )
    parser.add_argument("--grace-minutes", type=int, default=DEFAULT_GRACE_MINUTES)
    parser.add_argument("--manifest-url", default=configured_publication_urls()[0])
    parser.add_argument("--dates-index-url", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--alert", action="store_true", help="Send SMTP email when stale (Pi-side).")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    now_utc = datetime.now(timezone.utc)

    if args.expected_tz:
        try:
            tz = ZoneInfo(args.expected_tz)
        except KeyError:
            print(f"Error: invalid timezone {args.expected_tz!r}", file=sys.stderr)
            return 1
        expected = datetime.now(tz).date().isoformat()
        payload = {
            "now_utc": now_utc.isoformat(),
            "expected_tz": args.expected_tz,
            "expected_run_date": expected,
        }
        check_due = True
    else:
        due_utc = latest_daily_due_utc(now_utc)
        expected = expected_run_date_for_due(due_utc)
        ready_at = due_utc + timedelta(minutes=max(0, args.grace_minutes))
        check_due = now_utc >= ready_at
        payload = {
            "now_utc": now_utc.isoformat(),
            "due_utc": due_utc.isoformat(),
            "ready_at_utc": ready_at.isoformat(),
            "expected_run_date": expected,
            "schedule": DAILY_INGEST_SCHEDULE_LABEL,
            "schedule_local_hour": DAILY_INGEST_LOCAL_HOUR,
            "schedule_timezone": DAILY_INGEST_TZ_KEY,
        }
    publication = check_publication(
        expected, manifest_url=args.manifest_url,
        index_url=args.dates_index_url or args.manifest_url.rsplit("/", 1)[0] + "/dates-index.json",
        fetch=fetch_manifest,
    )
    stale = check_due and not publication["publication_current"]
    payload.update(publication)
    payload["stale"] = stale
    run_date = publication["manifest_run_date"]
    generated_at = publication["generated_at"]
    manifest_error = publication["manifest_error"]
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
        if publication["publication_issues"]:
            print("pi_ingest_manifest_check: " + ", ".join(publication["publication_issues"]))

    if stale and args.alert:
        from pi_ingest_alert import main as alert_main

        details = (
            f"GitHub app publication is unavailable or inconsistent for {expected}.\n"
            f"manifest_run_date={run_date or 'missing'}\n"
            f"dates_index_latest_date={publication['dates_index_latest_date'] or 'missing'}\n"
            f"generated_at={generated_at}\n"
            f"manifest_url={args.manifest_url}"
            f"\npublication_issues={','.join(publication['publication_issues'])}"
        )
        if manifest_error:
            details += f"\nmanifest_error={manifest_error}"
        alert_main(
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
