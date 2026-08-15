"""Strict RFC3339 parsing shared by schemas and semantic validation."""

from __future__ import annotations

import re
from datetime import datetime


RFC3339_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)


def parse_rfc3339(value: object) -> datetime:
    if not isinstance(value, str) or not RFC3339_PATTERN.fullmatch(value):
        raise ValueError("value is not an RFC3339 date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("value is not an RFC3339 date-time") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("RFC3339 date-time must include a UTC offset")
    return parsed


def is_rfc3339(value: object) -> bool:
    try:
        parse_rfc3339(value)
    except ValueError:
        return False
    return True
