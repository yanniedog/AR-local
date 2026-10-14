"""Lossless mortgage LVR intervals in the existing string facet contract.

Legacy canonical bands use (lo, hi]. Structured CDR minima are inclusive;
non-canonical intervals retain that distinction with an explicit >= prefix.
Neither a missing upper bound nor a product cap is a single rate bucket.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Optional, Tuple

Bounds = Tuple[Optional[float], Optional[float]]
CANONICAL_BANDS = ((0, 60), (60, 70), (70, 80), (80, 85), (85, 90), (90, 95))


def minimum_inclusive(item: Any, minimum: Any, parse_context: Callable) -> bool:
    """Retain the operator when a missing structured minimum comes from text."""
    flags = []
    for tier in item.get('tiers') or []:
        if not isinstance(tier, dict):
            continue
        explicit = percent(tier.get('minimumValue'))
        if explicit is not None and explicit == percent(minimum):
            flags.append(True)
        elif explicit is None:
            named = parse_context(str(tier.get('name') or ''))
            if named and named[0] is not None and percent(named[0]) == percent(minimum):
                flags.append(named[2])
    return all(flags)


def invalid_structured_bounds(item: Any, product_constraints: Any) -> bool:
    """Malformed explicit limits cannot turn into an uncapped interval."""
    signal = re.compile(r"(?<![a-z])(?:lvr|ltv|loan[\s_-]*to[\s_-]*value)(?![a-z])", re.I)
    for tier in item.get('tiers') or []:
        if not isinstance(tier, dict):
            continue
        label = ' '.join(str(tier.get(field) or '') for field in ('name', 'unitOfMeasure', 'rateApplicationMethod'))
        if signal.search(label):
            for field in ('minimumValue', 'maximumValue'):
                value = tier.get(field)
                if value not in (None, '') and percent(value) is None:
                    return True
    for constraint in [*(item.get('constraints') or []), *product_constraints]:
        if not isinstance(constraint, dict):
            continue
        kind = str(constraint.get('constraintType') or '').upper()
        if signal.search(kind + ' ' + str(constraint.get('additionalInfo') or '')):
            for field in ('additionalValue', 'minValue', 'maxValue'):
                value = constraint.get(field)
                if value not in (None, '') and percent(value) is None:
                    return True
    return False


def percent(value: Any) -> Optional[float]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number > 100:
        return None
    return round(number * 100 if 0 < number <= 1 else number, 4)


def intersect_bounds(rate: Bounds, product: Bounds) -> Bounds:
    """Intersect in percent units, including a product cap on an open rate tier."""
    lows = [n for value in (rate[0], product[0]) if (n := percent(value)) is not None]
    highs = [n for value in (rate[1], product[1]) if (n := percent(value)) is not None]
    # Fractions can safely pass through the shared unit parser again.
    return (max(lows) / 100 if lows else None, min(highs) / 100 if highs else None)


def interval_tier(minimum: Any, maximum: Any, *, inclusive: bool = True) -> str:
    """Use a canonical band only when it represents the complete source interval."""
    lo, hi = percent(minimum), percent(maximum)
    if any(value not in (None, '') and normalized is None for value, normalized in ((minimum, lo), (maximum, hi))):
        return "lvr_unspecified"
    if lo is None and hi is None:
        return "lvr_unspecified"
    if hi is not None and (hi <= 0 or (lo is not None and (lo > hi or (lo == hi and not inclusive)))):
        return "lvr_unspecified"
    if lo in (None, 0):
        return f"lvr_={hi:g}%" if hi is not None else "lvr_unspecified"
    # The historical bands encode the next 0.01% step as an exclusive boundary.
    # NAB's 60.01–70% etc. keep their existing keys; multi-band ranges do not.
    for lower, upper in CANONICAL_BANDS[1:]:
        if hi == upper and ((inclusive and lo == lower + 0.01) or (not inclusive and lo == lower)):
            return f"lvr_{lower}-{upper}%"
    operator = ">=" if inclusive else ">"
    upper = f"-{hi:g}" if hi is not None else ""
    return f"lvr_{operator}{lo:g}{upper}%"
