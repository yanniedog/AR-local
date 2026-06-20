#!/usr/bin/env python3
"""Bank rate-pass-through analytics — the data layer behind the RateWatch "Lender
Lab".

Joins the ledger's per-provider rate-move events (emitted by the single history pass
in ``app_payload_mobile.build_history_assets``) to the recorded RBA decision calendar
(``rba_decisions``) to answer the switcher's question: when the RBA moved, how fast
and how fully did each lender follow?

Design (keystone pattern):
  - Pure and importable: no I/O, no ledger access, not trapped in a server closure.
    A later PR computes this in the existing single pass and ships a compact asset;
    the Lender Lab renders it with zero on-device aggregation.
  - Decoupled: ``decisions`` are duck-typed (anything exposing ``date`` / ``outcome``
    / ``delta_bps``, e.g. ``rba_decisions.Decision``), so this module does not import
    the calendar.

Honesty rule (the ledger ethos applied to analytics): the ledger epoch is recent, so
pass-through samples are small. Every metric carries its sample size and a confidence
label, and low-sample metrics are reported as such instead of being dressed up as
established patterns — the unbackfillable ledger makes them grow over time.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Dict, List, Mapping, Optional, Sequence

# A lender "follows" an RBA hike with a same-section rate hike, and a cut with a cut.
# Move events tagged "mixed" (or RBA "hold" decisions) never match.
FOLLOW_DIRECTIONS = ("hike", "cut")


def confidence(n: int) -> str:
    """Sample-size -> confidence label. Under-claims until the ledger accumulates
    enough RBA cycles to make a behavioural pattern credible."""
    if n >= 10:
        return "established"
    if n >= 6:
        return "emerging"
    if n >= 3:
        return "early"
    return "insufficient"


def _event_date(event: Mapping[str, Any]) -> Optional[date]:
    raw = event.get("date")
    if isinstance(raw, datetime):  # datetime is a date subclass; normalise to a date
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def pass_through_observations(
    events: Sequence[Mapping[str, Any]],
    decisions: Sequence[Any],
    *,
    section: str,
    window_days: int = 60,
) -> List[Dict[str, Any]]:
    """One observation per (provider, RBA hike/cut decision) where the provider made
    its first same-direction move in ``section`` within ``window_days`` after the
    announcement.

    Each move is attributed to at most ONE decision — the most recent decision on or
    before the move — by capping every decision's window at the day before the next
    decision. This prevents a single move from being counted against several RBA
    decisions whose default windows overlap (closely spaced moves).

    ``days`` = announcement date -> first matching move; ``bps`` = magnitude passed
    (absolute); ``ratio`` = bps passed / |RBA delta bps|.
    """
    moves: Dict[str, List] = {}  # provider -> [(date, dir, abs_bps)] in this section
    for event in events:
        if event.get("section") != section or event.get("dir") not in FOLLOW_DIRECTIONS:
            continue
        moved_on = _event_date(event)
        provider = event.get("provider")
        if moved_on is None or not provider:
            continue
        moves.setdefault(provider, []).append(
            (moved_on, event["dir"], abs(float(event.get("avg_bps") or 0.0)))
        )
    for series in moves.values():
        series.sort(key=lambda m: m[0])

    decs = sorted(decisions, key=lambda d: d.date)
    observations: List[Dict[str, Any]] = []
    for idx, dec in enumerate(decs):
        if getattr(dec, "outcome", None) not in FOLLOW_DIRECTIONS:
            continue
        window_end = dec.date + timedelta(days=window_days)
        if idx + 1 < len(decs):  # cap at the day before the next decision (no overlap)
            window_end = min(window_end, decs[idx + 1].date - timedelta(days=1))
        rba_bps = abs(int(getattr(dec, "delta_bps")))
        for provider, series in moves.items():
            for moved_on, move_dir, move_bps in series:
                if move_dir != dec.outcome:
                    continue
                if dec.date <= moved_on <= window_end:
                    observations.append({
                        "provider": provider,
                        "section": section,
                        "direction": dec.outcome,
                        "decision_date": dec.date.isoformat(),
                        "days": (moved_on - dec.date).days,
                        "bps": round(move_bps, 1),
                        "ratio": round(move_bps / rba_bps, 3) if rba_bps else None,
                    })
                    break  # first matching move only
    return observations


def _direction_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(items)
    if not n:
        return {"n": 0, "days_median": None, "bps_median": None, "ratio_median": None,
                "confidence": "insufficient"}
    ratios = [i["ratio"] for i in items if i["ratio"] is not None]
    return {
        "n": n,
        "days_median": round(median(i["days"] for i in items), 1),
        "bps_median": round(median(i["bps"] for i in items), 1),
        "ratio_median": round(median(ratios), 3) if ratios else None,
        "confidence": confidence(n),
    }


def pass_through_summary(
    events: Sequence[Mapping[str, Any]],
    decisions: Sequence[Any],
    *,
    section: str,
    window_days: int = 60,
) -> Dict[str, Any]:
    """Per-provider pass-through summary for ``section``: for each direction, the
    median days-to-follow, median bps passed, median pass-through ratio, sample size
    and confidence."""
    observations = pass_through_observations(events, decisions, section=section, window_days=window_days)
    by_provider: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for obs in observations:
        bucket = by_provider.setdefault(obs["provider"], {d: [] for d in FOLLOW_DIRECTIONS})
        bucket[obs["direction"]].append(obs)

    providers = {
        provider: {direction: _direction_summary(dirs[direction]) for direction in FOLLOW_DIRECTIONS}
        for provider, dirs in sorted(by_provider.items())
    }
    return {"section": section, "window_days": window_days, "providers": providers}
