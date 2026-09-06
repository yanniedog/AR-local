"""Shared source metadata, numeric units and freshness for every macro reader."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping

from cdr_macro_sources import SERIES_METADATA, SERIES_VISIBLE_FROM, SOURCE_URLS

MAX_SOURCE_CHECK_AGE_HOURS = 48
OBSERVATION_AGE_DAYS = {"daily": 10, "monthly": 75, "quarterly": 150,
                        "semiannual": 250, "annual": 550, "policy": 550}


def parse_timestamp(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def series_metadata(series_id: str, catalog: Mapping[str, Any]) -> dict:
    meta = dict(catalog)
    meta.update(SERIES_METADATA.get(series_id, {}))
    if series_id in SOURCE_URLS:
        meta["source_url"] = SOURCE_URLS[series_id]
        meta["source_label"] = "ABS Data API" if "/rest/data/" in SOURCE_URLS[series_id] else "RBA"
    if "label" in SERIES_METADATA.get(series_id, {}):
        meta["short_label"] = meta["label"]
    return meta


def source_definition_current(series_id: str, freshness: Mapping[str, Any] | None) -> bool:
    # An HTTP 200 from the ceased CPI_M dataflow is not the complete monthly
    # CPI. Keep that history on disk, but never splice it into the new measure.
    return series_id not in SERIES_VISIBLE_FROM or "/rest/data/CPI/" in str((freshness or {}).get("source_url", ""))


def observation_value(series_id: str, value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number / 1000.0 if series_id == "hours_worked" else number


def assess_freshness(
    series_id: str, stored: Mapping[str, Any] | None, *, frequency: str | None,
    now: str | datetime | None = None,
) -> dict:
    """A publication timestamp never changes the age of the source check."""
    stamp = parse_timestamp(now) if now is not None else datetime.now(timezone.utc)
    if stamp is None:
        raise ValueError("macro freshness requires a valid assessment timestamp")
    row = {"last_checked_at": None, "last_success_at": None,
           "last_observation_date": None, **dict(stored or {})}
    checked = parse_timestamp(row.get("last_checked_at"))
    success = parse_timestamp(row.get("last_success_at"))
    observed = parse_timestamp(row.get("last_observation_date"))
    check_age = (stamp - success).total_seconds() / 3600 if success else None
    observation_age = (stamp - observed).days if observed else None
    max_observation_age = OBSERVATION_AGE_DAYS.get(str(frequency), 150)
    check_overdue = check_age is None or check_age > MAX_SOURCE_CHECK_AGE_HOURS
    observation_overdue = observation_age is None or observation_age > max_observation_age
    source_status = row.get("status") or "missing"
    if not source_definition_current(series_id, row):
        status, message = "error", "Source definition changed; the retired CPI indicator is not current monthly CPI."
    elif source_status not in {"ok", "missing"}:
        status, message = "error", str(row.get("message") or "The latest source refresh failed.")[:400]
    elif not stored or observed is None or success is None:
        status, message = "missing", "No successful local source observation is available."
    elif success > stamp or checked is None or checked > stamp:
        status, message = "error", "Invalid or future source-check timestamp."
    elif check_overdue or observation_overdue:
        status = "stale"
        message = "Source check is overdue." if check_overdue else "Source observations are overdue for the published cadence."
    else:
        status, message = "ok", str(row.get("message") or "Source checked.")[:400]
    row.update(status=status, source_status=source_status, message=message,
               checked_age_hours=round(check_age, 2) if check_age is not None else None,
               observation_age_days=observation_age, check_overdue=check_overdue,
               observation_overdue=observation_overdue,
               max_check_age_hours=MAX_SOURCE_CHECK_AGE_HOURS,
               max_observation_age_days=max_observation_age)
    if "last_value" in row:
        row["last_value"] = observation_value(series_id, row["last_value"])
    return row
