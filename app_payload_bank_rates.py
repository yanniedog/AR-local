"""Compact, exact-tier history embedded in the normal verified core download.

Consecutive identical observations use run-length encoding. Missing observations
are never filled. Current rows carry section-local tier IDs so consumers can
apply their ordinary eligibility/profile filters before aggregating history.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

from app_payload_common import CORE_RATE_FIELDS, VALID_SECTIONS, compact, section_filter, _load_json
from app_payload_mobile import _banks, _history_dates

OBSERVATION_FIELDS = frozenset({
    "rate", "comparison_rate", "ongoing_rate", "last_updated", "rate_index",
    "exact_alert_eligible", "bank_rate_tier",
})


def tier_signature(row):
    return json.dumps({k: v for k, v in row.items() if k not in OBSERVATION_FIELDS},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def rate_percent(value):
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number if number > 1 else number * 100


def attach_history(core, observations, dates):
    """One pass, bounded memory: keep encoded tier series, never daily catalogues."""
    ids, sections = {}, {}
    for section in VALID_SECTIONS:
        ids[section], sections[section] = {}, []
        for row in core["sections"][section]["rates"]:
            key = tier_signature(row)
            if key not in ids[section]:
                ids[section][key] = len(sections[section])
                sections[section].append([])
            row["bank_rate_tier"] = ids[section][key]
    date_index = {day: index for index, day in enumerate(dates)}
    seen = set()
    for day, rows_by_section in observations:
        if day not in date_index or day in seen:
            raise ValueError("Unknown or duplicate bank-rate observation date")
        seen.add(day)
        index = date_index[day]
        for section in VALID_SECTIONS:
            buckets = {}
            for row in rows_by_section.get(section, []):
                tier = ids[section].get(tier_signature(row))
                value = rate_percent(row.get("rate"))
                if tier is not None and value is not None:
                    buckets.setdefault(tier, []).append(value)
            for tier, values in buckets.items():
                values.sort()
                spans = sections[section][tier]
                if spans and spans[-1][0] + spans[-1][1] == index and spans[-1][2] == values:
                    spans[-1][1] += 1
                else:
                    spans.append([index, 1, values])
    core["bank_rate_history"] = {"schema_version": 1, "run_dates": dates, "sections": sections}


def embed_bank_rate_history(core, exports_dir):
    observed = _history_dates(exports_dir, core["run_date"])
    if not observed:
        return
    start, end = date.fromisoformat(observed[0]), date.fromisoformat(core["run_date"])
    count = (end - start).days + 1
    if not 0 < count <= 5000:
        raise ValueError("Bank-rate history date range exceeds budget")
    dates = [(start + timedelta(days=i)).isoformat() for i in range(count)]

    def observations():
        for day in observed:
            path = _banks(exports_dir, day)
            if path is None:
                continue
            rows = _load_json(path).get("rates") or []
            yield day, {section: [compact({k: row.get(k) for k in CORE_RATE_FIELDS})
                                 for row in rows if isinstance(row, dict)
                                 and row.get("dataset") == section and section_filter(section, row)]
                        for section in VALID_SECTIONS}

    attach_history(core, observations(), dates)
