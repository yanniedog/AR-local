"""Compact, exact-tier history embedded in the normal verified core download.

Consecutive identical observations use run-length encoding. Missing observations
are never filled. A separate row map supplies section-local tier IDs so consumers can
apply their ordinary eligibility/profile filters before aggregating history.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

from app_payload_common import CORE_RATE_FIELDS, VALID_SECTIONS, compact, section_filter
from app_payload_mobile import _history_dates
from app_payload_bank_rate_source import historical_banks

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


class _History:
    """One pass, bounded memory: encoded tier series, never daily catalogues."""

    def __init__(self, core, dates):
        self.core, self.dates = core, dates
        self.ids, self.sections, self.row_tiers = {}, {}, {}
        self.date_index = {day: index for index, day in enumerate(dates)}
        self.seen = set()
        for section in VALID_SECTIONS:
            self.ids[section], self.sections[section], self.row_tiers[section] = {}, [], []
            for row in core["sections"][section]["rates"]:
                key = tier_signature(row)
                if key not in self.ids[section]:
                    self.ids[section][key] = len(self.sections[section])
                    self.sections[section].append([])
                self.row_tiers[section].append(self.ids[section][key])

    def observe(self, day, rows_by_section):
        if day not in self.date_index or day in self.seen:
            raise ValueError("Unknown or duplicate bank-rate observation date")
        self.seen.add(day)
        index = self.date_index[day]
        for section in VALID_SECTIONS:
            buckets = {}
            for row in rows_by_section.get(section, []):
                tier = self.ids[section].get(tier_signature(row))
                value = rate_percent(row.get("rate"))
                if tier is not None and value is not None:
                    buckets.setdefault(tier, []).append(value)
            for tier, values in buckets.items():
                values.sort()
                spans = self.sections[section][tier]
                if spans and spans[-1][0] + spans[-1][1] == index and spans[-1][2] == values:
                    spans[-1][1] += 1
                else:
                    spans.append([index, 1, values])
    def finish(self, unavailable=None):
        self.core["bank_rate_history"] = {
            "schema_version": 1, "run_dates": self.dates,
            "row_tiers": self.row_tiers, "sections": self.sections,
        }
        if unavailable:
            self.core["bank_rate_history"]["unavailable_dates"] = unavailable


def attach_history(core, observations, dates):
    history = _History(core, dates)
    for day, rows in observations:
        history.observe(day, rows)
    history.finish()


def bank_rate_history_rows(core, exports_dir):
    """Encode tiers while yielding each selected day's rows to other reducers."""
    observed = _history_dates(exports_dir, core["run_date"])
    if not observed:
        return
    start, end = date.fromisoformat(observed[0]), date.fromisoformat(core["run_date"])
    count = (end - start).days + 1
    if not 0 < count <= 5000:
        raise ValueError("Bank-rate history date range exceeds budget")
    dates = [(start + timedelta(days=i)).isoformat() for i in range(count)]
    history = _History(core, dates)
    unavailable = {}
    for day in observed:
        rows = [row for row in (historical_banks(exports_dir, day, unavailable).get("rates") or [])
                if isinstance(row, dict)]
        history.observe(day, {section: [compact({k: row.get(k) for k in CORE_RATE_FIELDS})
                                       for row in rows if row.get("dataset") == section
                                       and section_filter(section, row)]
                              for section in VALID_SECTIONS})
        yield day, rows
    history.finish(unavailable)


def embed_bank_rate_history(core, exports_dir):
    for _ in bank_rate_history_rows(core, exports_dir):
        pass
