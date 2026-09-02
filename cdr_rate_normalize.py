"""Strict CDR RateString parsing without unit guessing."""
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from cdr_contracts import parse_rate_string


def finite_float(value: Any) -> Optional[float]:
    """Return a valid CDR decimal rate, or ``None`` for invalid evidence."""
    try:
        return float(parse_rate_string(value))
    except ValueError:
        return None


def rate_divisor(items: List[Mapping[str, Any]], family: str) -> float:
    """Compatibility shim: the CDR unit is fixed, so the divisor is always one."""
    del items, family
    return 1


def normalized_rate_value(value: Any, divisor: float, family: str) -> Optional[float]:
    """Validate and return the exact decimal rate; legacy hints are ignored."""
    del divisor, family
    return finite_float(value)
