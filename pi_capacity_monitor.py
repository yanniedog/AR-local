"""Cheap, non-blocking Pi storage runway monitoring.

The monitor samples filesystem usage only; it never walks, prunes, moves, or
deletes retained CDR evidence.  Daily ingest has no dependency on this service.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import smtplib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from ar_local_email_notify import email_configured, send_email
from ar_local_pi_runtime import data_state_root
from cdr_atomic import atomic_write_json
from cdr_file_lock import FileLock

REPO_ROOT = Path(__file__).resolve().parent
GIB = 1024**3
MAX_SAMPLES = 45
WARNING_FREE_BYTES = 250 * GIB
CRITICAL_FREE_BYTES = 100 * GIB
WARNING_RUNWAY_DAYS = 180
CRITICAL_RUNWAY_DAYS = 60
ALERT_COOLDOWN_SECONDS = 24 * 60 * 60
ALERT_RETRY_SECONDS = 60 * 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_path() -> Path:
    return data_state_root(REPO_ROOT) / "capacity-monitor.json"


def _read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(path: Path, value: dict[str, Any]) -> None:
    atomic_write_json(path, value)


def _valid_samples(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    out: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        day = item.get("day")
        free = item.get("free_bytes")
        if isinstance(day, str) and len(day) == 10 and isinstance(free, int) and not isinstance(free, bool) and free >= 0:
            out.append({"day": day, "free_bytes": free})
    return sorted(out, key=lambda item: item["day"])[-MAX_SAMPLES:]


def _growth_per_day(samples: Iterable[dict[str, Any]]) -> list[int]:
    ordered = list(samples)
    growth: list[int] = []
    for previous, current in zip(ordered, ordered[1:]):
        try:
            days = (
                datetime.fromisoformat(current["day"])
                - datetime.fromisoformat(previous["day"])
            ).days
        except (TypeError, ValueError):
            continue
        delta = int(previous["free_bytes"]) - int(current["free_bytes"])
        if days > 0 and delta > 0:
            growth.append((delta + days - 1) // days)
    return growth


def _percentile90(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[(len(ordered) * 9 - 1) // 10]


def capacity_report(
    *,
    total_bytes: int,
    used_bytes: int,
    free_bytes: int,
    prior_samples: Any,
    now: datetime,
) -> dict[str, Any]:
    samples = _valid_samples(prior_samples)
    today = now.date().isoformat()
    samples = [item for item in samples if item["day"] != today]
    samples.append({"day": today, "free_bytes": free_bytes})
    samples = samples[-MAX_SAMPLES:]
    growth = _percentile90(_growth_per_day(samples))
    runway = free_bytes // growth if growth else None
    reasons: list[str] = []
    status = "healthy"
    if free_bytes < CRITICAL_FREE_BYTES or (runway is not None and runway < CRITICAL_RUNWAY_DAYS):
        status = "critical"
    elif free_bytes < WARNING_FREE_BYTES or (runway is not None and runway < WARNING_RUNWAY_DAYS):
        status = "warning"
    if free_bytes < WARNING_FREE_BYTES:
        reasons.append("free_bytes")
    if runway is not None and runway < WARNING_RUNWAY_DAYS:
        reasons.append("runway_days")
    return {
        "schema_version": 1,
        "checked_at": now.isoformat(),
        "status": status,
        "reasons": reasons,
        "filesystem": {
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
        },
        "growth_bytes_per_day_p90": growth,
        "runway_days": runway,
        "samples": samples,
        "policy": {
            "warning_free_bytes": WARNING_FREE_BYTES,
            "critical_free_bytes": CRITICAL_FREE_BYTES,
            "warning_runway_days": WARNING_RUNWAY_DAYS,
            "critical_runway_days": CRITICAL_RUNWAY_DAYS,
            "retained_evidence_deleted": False,
            "blocks_daily_ingest": False,
        },
    }


def _timestamp(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    try:
        parsed = float(value)
    except OverflowError:
        return 0.0
    return parsed if math.isfinite(parsed) and parsed >= 0 else 0.0


def _carry_delivery(report: dict[str, Any], state: dict[str, Any]) -> None:
    if _timestamp(state.get("last_alert_at")):
        report["last_alert_at"] = state["last_alert_at"]
    if state.get("last_alert_status") in ("warning", "critical"):
        report["last_alert_status"] = state["last_alert_status"]
    prior = state.get("notification")
    if isinstance(prior, dict):
        report["notification"] = {key: prior[key] for key in (
            "status", "capacity_status", "error_class"
        ) if isinstance(prior.get(key), str)}
        for key in ("attempted_at", "retry_after"):
            value = prior.get(key)
            if _timestamp(value) or (type(value) in (int, float) and value == 0):
                report["notification"][key] = value


def _maybe_notify(
    report: dict[str, Any], state: dict[str, Any], now: datetime,
    *, persist: Callable[[], None] | None = None,
) -> bool:
    _carry_delivery(report, state)
    last_value = state.get("last_alert_at")
    last_status = state.get("last_alert_status")
    last = _timestamp(last_value)
    if report["status"] == "healthy":
        return True
    if now.timestamp() - last < ALERT_COOLDOWN_SECONDS and last_status == report["status"]:
        return True
    delivery = report.get("notification", {})
    if (delivery.get("capacity_status") == report["status"]
            and now.timestamp() < _timestamp(delivery.get("retry_after"))):
        return False
    try:
        configured = email_configured()
    except (OSError, ValueError, OverflowError) as error:
        report["notification"] = {
            "status": "FAILED", "capacity_status": report["status"],
            "attempted_at": now.timestamp(), "retry_after": now.timestamp() + ALERT_RETRY_SECONDS,
            "error_class": type(error).__name__,
        }
        return False
    if not configured:
        report["notification"] = {"status": "NOT_CONFIGURED"}
        return False
    report["notification"] = {
        "status": "ATTEMPTING", "capacity_status": report["status"],
        "attempted_at": now.timestamp(), "retry_after": now.timestamp() + ALERT_RETRY_SECONDS,
    }
    if persist:
        persist()  # Retain the sample and retry reservation even if the sender dies.
    try:
        sent = _send_alert(report)
    except (smtplib.SMTPException, OSError, ValueError, OverflowError) as error:
        report["notification"].update(status="FAILED", error_class=type(error).__name__)
        return False  # Exception text can contain server credentials or addresses.
    report["notification"]["status"] = "SENT" if sent else "NOT_SENT"
    if sent:
        report["last_alert_at"] = now.timestamp()
        report["last_alert_status"] = report["status"]
    return sent


def _send_alert(report: dict[str, Any]) -> bool:
    fs = report["filesystem"]
    body = (
        "AR-local storage runway needs attention. Daily ingest remains enabled and no evidence was deleted.\n\n"
        f"Status: {report['status']}\n"
        f"Free: {fs['free_bytes'] / GIB:.1f} GiB\n"
        f"Growth p90: {(report['growth_bytes_per_day_p90'] or 0) / GIB:.2f} GiB/day\n"
        f"Runway: {report['runway_days'] if report['runway_days'] is not None else 'collecting samples'} days\n"
        "Required response: add verified off-Pi capacity or expand storage; do not delete source evidence."
    )
    return send_email(f"AR-local Pi storage {report['status']}", body)


def _sample_and_notify(data_root: Path, state_path: Path, notify: bool) -> tuple[dict, bool]:
    # Serialize the entire read/assessment/reservation/outcome transaction.
    # The kernel releases ownership on exit/crash; this lock is monitor-only.
    with FileLock(state_path.with_name(state_path.name + ".lock")):
        usage = shutil.disk_usage(data_root)
        state = _read_state(state_path)
        now = _now()
        report = capacity_report(
            total_bytes=usage.total, used_bytes=usage.used, free_bytes=usage.free,
            prior_samples=state.get("samples"), now=now,
        )
        _carry_delivery(report, state)
        _write_state(state_path, report)  # Assessment survives delivery failure.
        delivered = True
        if notify:
            delivered = _maybe_notify(report, state, now, persist=lambda: _write_state(state_path, report))
        _write_state(state_path, report)
        return report, delivered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record Pi storage runway without deleting data.")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.environ.get("AR_LOCAL_DATA_ROOT", str(REPO_ROOT / "runs"))),
    )
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args(argv)
    data_root = args.data_root.expanduser().resolve()
    state_path = (args.state or _state_path()).expanduser().resolve()
    report, delivered = _sample_and_notify(data_root, state_path, args.notify)
    keys = ("status", "filesystem", "growth_bytes_per_day_p90", "runway_days", "policy", "notification")
    print(json.dumps({key: report[key] for key in keys if key in report}, sort_keys=True))
    return 0 if delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
