"""Send email when Pi daily ingest fails or is missing."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ar_local_email_notify import email_configured, send_email
from ar_local_ingest_schedule import expected_run_date_for_due, latest_daily_due_utc

REPO_ROOT = Path(__file__).resolve().parent
ALERT_COOLDOWN_SECONDS = 6 * 60 * 60
JOURNAL_LINES = 40


def state_path() -> Path:
    from ar_local_pi_runtime import data_state_root

    return data_state_root(REPO_ROOT) / "ingest-alert-state.json"


def load_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def should_send_alert(path: Path, reason: str, run_date: str) -> bool:
    state = load_state(path)
    key = f"{reason}:{run_date}"
    last_sent = float(state.get("last_sent", {}).get(key, 0))
    now = datetime.now(timezone.utc).timestamp()
    return (now - last_sent) >= ALERT_COOLDOWN_SECONDS


def mark_sent(path: Path, reason: str, run_date: str) -> None:
    state = load_state(path)
    last_sent = state.setdefault("last_sent", {})
    last_sent[f"{reason}:{run_date}"] = datetime.now(timezone.utc).timestamp()
    save_state(path, state)


def journal_tail(service: str = "ar-local-daily.service", lines: int = JOURNAL_LINES) -> str:
    try:
        result = subprocess.run(
            ["journalctl", "-u", service, "-n", str(lines), "--no-pager"],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "(journalctl unavailable)"
    return (result.stdout or result.stderr or "").strip() or "(empty journal)"


def build_subject(reason: str, run_date: str) -> str:
    return f"AR-local Pi ingest alert: {reason} ({run_date})"


def build_body(reason: str, run_date: str, details: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    lead = (
        "AR-local Pi booted/rebooted (boot-recovery self-heal ran)."
        if reason == "boot-recovery"
        else "AR-local daily CDR ingest needs attention."
    )
    lines = [
        lead,
        "",
        f"Reason: {reason}",
        f"Expected run_date: {run_date}",
        f"Alert time (UTC): {now}",
        "",
    ]
    if details.strip():
        lines.extend(["Details:", details.strip(), ""])
    if reason in ("systemd-failure", "missed-ingest", "watchdog-failure"):
        lines.extend(["Recent journal (ar-local-daily.service):", journal_tail(), ""])
    lines.extend(
        [
            "Pi host: ar-local-pi5",
            "Repo: /srv/ar-local/AR-local",
            "Dashboard: http://100.78.28.10/",
            "",
            "Manual recovery:",
            "  ssh ar-local-pi5 'cd /srv/ar-local/AR-local && git status --porcelain'",
            "  ssh ar-local-pi5 'sudo systemctl start --no-block ar-local-daily.service'",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Email alert for Pi daily ingest failures.")
    parser.add_argument(
        "--reason",
        required=True,
        choices=("systemd-failure", "missed-ingest", "watchdog-failure", "manifest-stale", "boot-recovery"),
    )
    parser.add_argument("--run-date", default="", help="YYYY-MM-DD; defaults to expected run date.")
    parser.add_argument("--details", default="", help="Extra context for the email body.")
    parser.add_argument("--force", action="store_true", help="Send even if cooldown has not elapsed.")
    parser.add_argument("--dry-run", action="store_true", help="Print email without sending.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    now_utc = datetime.now(timezone.utc)
    run_date = args.run_date.strip() or expected_run_date_for_due(latest_daily_due_utc(now_utc))
    path = state_path()

    if not args.force and not should_send_alert(path, args.reason, run_date):
        print(f"pi_ingest_alert: cooldown active for {args.reason}:{run_date}")
        return 0

    subject = build_subject(args.reason, run_date)
    body = build_body(args.reason, run_date, args.details)

    if args.dry_run:
        print(subject)
        print(body)
        return 0

    if not email_configured():
        print("pi_ingest_alert: SMTP not configured; set /etc/ar-local/notify.env", file=sys.stderr)
        return 1

    if not send_email(subject, body):
        return 1

    mark_sent(path, args.reason, run_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
