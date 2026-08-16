"""Cheap, non-blocking Pi storage runway monitoring.

The monitor samples filesystem usage only; it never walks, prunes, moves, or
deletes retained CDR evidence.  Daily ingest has no dependency on this service.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ar_local_email_notify import email_configured, send_email
from ar_local_pi_runtime import data_state_root

REPO_ROOT = Path(__file__).resolve().parent
GIB = 1024**3
MAX_SAMPLES = 45
WARNING_FREE_BYTES = 250 * GIB
CRITICAL_FREE_BYTES = 100 * GIB
WARNING_RUNWAY_DAYS = 180
CRITICAL_RUNWAY_DAYS = 60
ALERT_COOLDOWN_SECONDS = 24 * 60 * 60


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


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


def _maybe_notify(report: dict[str, Any], state: dict[str, Any], now: datetime) -> None:
    if report["status"] == "healthy" or not email_configured():
        return
    last = float(state.get("last_alert_at") or 0)
    if now.timestamp() - last < ALERT_COOLDOWN_SECONDS and state.get("last_alert_status") == report["status"]:
        return
    fs = report["filesystem"]
    body = (
        "AR-local storage runway needs attention. Daily ingest remains enabled and no evidence was deleted.\n\n"
        f"Status: {report['status']}\n"
        f"Free: {fs['free_bytes'] / GIB:.1f} GiB\n"
        f"Growth p90: {(report['growth_bytes_per_day_p90'] or 0) / GIB:.2f} GiB/day\n"
        f"Runway: {report['runway_days'] if report['runway_days'] is not None else 'collecting samples'} days\n"
        "Required response: add verified off-Pi capacity or expand storage; do not delete source evidence."
    )
    if send_email(f"AR-local Pi storage {report['status']}", body):
        report["last_alert_at"] = now.timestamp()
        report["last_alert_status"] = report["status"]


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
    usage = shutil.disk_usage(data_root)
    state_path = args.state or _state_path()
    state = _read_state(state_path)
    now = _now()
    report = capacity_report(
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        prior_samples=state.get("samples"),
        now=now,
    )
    if args.notify:
        _maybe_notify(report, state, now)
    _write_state(state_path, report)
    print(json.dumps({key: report[key] for key in ("status", "filesystem", "growth_bytes_per_day_p90", "runway_days", "policy")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
