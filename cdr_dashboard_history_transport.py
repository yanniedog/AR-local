"""Lossless bounded dictionary transport for the dashboard's per-row history.

Rows, ordering, missing fields, nulls and carry-forward provenance are unchanged.
The legacy raw endpoint remains available; this representation avoids repeating
large product strings for every observed and carried-forward date.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date

FORMAT = "ar-dashboard-history-dictionary-v1"
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 1_000_000
MAX_TEMPLATES = 100_000
MAX_VALUES = 300_000
MAX_COLUMNS = 64
VARIABLES = ("run_date", "carry_forward")


def encode(payload: dict) -> bytes:
    rows = payload["rates"]
    if len(rows) > MAX_ROWS:
        raise ValueError("Dashboard history row budget exceeded")
    columns = sorted({key for row in rows for key in row if key not in VARIABLES})
    if len(columns) > MAX_COLUMNS or any(not isinstance(k, str) or not 0 < len(k) <= 128 for k in columns):
        raise ValueError("Dashboard history column budget exceeded")
    values, value_ids, templates, template_ids, observations = [], {}, [], {}, []

    def value_id(value):
        if type(value) not in (str, int, float, bool, type(None)):
            raise ValueError("Dashboard history requires scalar field values")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Dashboard history contains a non-finite value")
        key = (type(value), value.hex() if isinstance(value, float) else value)
        if key not in value_ids:
            if len(values) >= MAX_VALUES:
                raise ValueError("Dashboard history value budget exceeded")
            value_ids[key] = len(values)
            values.append(value)
        return value_ids[key]

    for row in rows:
        template = tuple(value_id(row[key]) if key in row else -1 for key in columns)
        if template not in template_ids:
            if len(templates) >= MAX_TEMPLATES:
                raise ValueError("Dashboard history template budget exceeded")
            template_ids[template] = len(templates)
            templates.append(template)
        observations.append([template_ids[template], *(
            value_id(row[key]) if key in row else -1 for key in VARIABLES)])
    result = {key: value for key, value in payload.items() if key != "rates"}
    result.update(format=FORMAT, columns=columns, values=values, templates=templates,
                  observations=observations, row_count=len(rows))
    body = json.dumps(result, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf8")
    if len(body) > MAX_BYTES:
        raise ValueError("Dashboard history transport exceeds 20 MiB")
    return body


def validate(payload: dict, section: str, run_date: str) -> None:
    """Validate the complete response, without constructing a second row array."""
    if payload.get("format") != FORMAT or "rates" in payload or payload.get("section") != section:
        raise ValueError("Dashboard history format or section differs")
    columns, values = payload.get("columns"), payload.get("values")
    templates, observations = payload.get("templates"), payload.get("observations")
    if (not isinstance(columns, list) or len(columns) > MAX_COLUMNS
            or any(not isinstance(k, str) or not 0 < len(k) <= 128 or k in VARIABLES for k in columns)
            or len(set(columns)) != len(columns)):
        raise ValueError("Invalid dashboard history columns")
    if (not isinstance(values, list) or len(values) > MAX_VALUES or any(
            type(v) not in (str, int, float, bool, type(None)) or isinstance(v, float) and not math.isfinite(v)
            for v in values)):
        raise ValueError("Invalid dashboard history values")
    if (not isinstance(templates, list) or len(templates) > MAX_TEMPLATES
            or not isinstance(observations, list) or len(observations) > MAX_ROWS
            or type(payload.get("row_count")) is not int or payload["row_count"] != len(observations)):
        raise ValueError("Invalid dashboard history row count")
    valid_index = lambda value: type(value) is int and -1 <= value < len(values)
    if any(not isinstance(t, list) or len(t) != len(columns) or not all(map(valid_index, t)) for t in templates):
        raise ValueError("Invalid dashboard history template")
    dates = payload.get("run_dates")
    if (not isinstance(dates, list) or any(not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
                                         or day > run_date for day in dates) or dates != sorted(set(dates))):
        raise ValueError("Invalid dashboard history dates")
    known_dates = set(dates)
    carried = 0
    for row in observations:
        if (not isinstance(row, list) or len(row) != 3 or type(row[0]) is not int
                or not 0 <= row[0] < len(templates) or not all(map(valid_index, row[1:]))
                or row[1] == -1 or values[row[1]] not in known_dates):
            raise ValueError("Invalid dashboard history observation")
        carried += row[2] != -1 and values[row[2]] == "1"
    if type(payload.get("carry_forward_count")) is not int or payload["carry_forward_count"] != carried:
        raise ValueError("Invalid dashboard history carry-forward count")


def validate_current(payload: dict, current: dict, section: str, run_date: str) -> None:
    """Compare shared wire fields and duplicate counts across the two projections."""
    rows = current.get("rates")
    if (current.get("run_date") != run_date or current.get("section") != section
            or not isinstance(rows, list) or len(rows) > MAX_ROWS
            or current.get("counts", {}).get("rates") != len(rows)
            or any(not isinstance(row, dict) for row in rows)):
        raise ValueError("Invalid current section for history reconciliation")
    def token(row):
        return json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # Current-only rate_index is absent from the legacy history projection.
    expected = Counter(token({k: v for k, v in row.items() if k != "rate_index"}) for row in rows)
    actual = Counter()
    columns, values, templates = payload["columns"], payload["values"], payload["templates"]
    for template_id, day_id, carried_id in payload["observations"]:
        if values[day_id] != run_date or carried_id != -1 and values[carried_id] == "1":
            continue
        template = templates[template_id]
        # The current section deliberately omits comparison_rate; history carries
        # it for fee-inclusive aggregates. All shared fields stay exact.
        row = {key: values[index] for key, index in zip(columns, template)
               if index != -1 and key != "comparison_rate"}
        actual[token(row)] += 1
    if actual != expected:
        raise ValueError("History current rows differ from complete current section")
