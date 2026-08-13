"""Shared normalization for legacy CDR percentage-rate conventions."""
from __future__ import annotations

import math
from typing import Any, List, Mapping, Optional


def finite_float(value: Any) -> Optional[float]:
    """Return a finite float, rejecting NaN and infinities as non-numeric evidence."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def rate_divisor(items: List[Mapping[str, Any]], family: str) -> float:
    """Infer the retained feed's product-level percentage convention."""
    values = [number for item in items if (number := finite_float(item.get("rate"))) is not None]
    if any(value > 1 for value in values):
        return 100
    if family == "lending" and any(0.3 < value <= 1 for value in values):
        return 10
    if family == "deposit" and any(0.2 <= value <= 1 for value in values):
        return 100
    return 1


def normalized_rate_value(value: Any, divisor: float, family: str) -> Optional[float]:
    """Normalize one rate with the same conventions used by clean exports."""
    number = finite_float(value)
    if number is None:
        return None
    if divisor != 1:
        number /= divisor
    elif number > 1:
        number /= 100
    if family == "lending" and 0 < number < 0.02:
        number *= 10
    return number
