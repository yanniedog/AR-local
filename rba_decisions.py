#!/usr/bin/env python3
"""RBA cash-rate decision calendar — the recorded-fact reference behind the
RateWatch countdown, the macro pressure gauge, and every bank rate-pass-through
metric.

Recorded fact, never inferred. Every Monetary Policy Board meeting is recorded,
including HELD meetings (delta_bps == 0), so downstream analytics can distinguish
"no meeting" from "the Board met and held". Each entry is sourced from the RBA
cash-rate target table and the RBA monetary-policy decision records (see ``META``).
Update this file when the Board next decides; that is the whole maintenance burden.

Coverage: complete meeting-by-meeting from 2025 (the Monetary Policy Board era)
through the present, plus a single pre-2025 baseline anchor (the Nov 2023 hike to
4.35%) so ``current_rate`` is correct across 2024. 2024's held meetings are
intentionally omitted — no decision changed the rate, they pre-date the Monetary
Policy Board, and they sit over a year before the CDR ledger epoch (2026-05-13),
which is the earliest date any pass-through metric can use.

Design (audit-aligned):
  - Pure data + pure functions, zero I/O — importable and unit-testable without
    standing up the server or touching the ledger. Deliberately NOT trapped in a
    server closure.
  - Rates are stored as integer basis points (e.g. 435 == 4.35% p.a.), so rate
    continuity is exact integer arithmetic with no float rounding; ``Decision``
    exposes ``new_rate`` as a percentage float at the boundary.
  - Self-validating: ``validate()`` asserts chronology + rate continuity
    (rate_bps == previous + delta_bps) — the ledger-integrity ethos applied to the
    calendar, so a typo in a future edit fails a test instead of shipping a wrong
    countdown or pass-through baseline.
  - Timezone-correct WITHOUT a tzdata dependency: the Sydney UTC offset is derived
    from the Australian Eastern DST rule (AEDT +11 from the first Sunday in October
    to the first Sunday in April, else AEST +10), so the 14:30 announcement instant
    is right on both the Linux Pi and a Windows dev box.

The Board announces each outcome at 14:30 Sydney time on the second day of the
meeting; a rate change takes effect the next business day. Decisions are keyed on
the ANNOUNCEMENT date (``Decision.date``) — when lenders learn the outcome and the
t0 for pass-through analysis. ``current_rate`` instead looks up by EFFECTIVE date,
because the prevailing target does not change until the effective date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional, Union

ANNOUNCE_TIME = time(14, 30)  # 2:30pm Sydney, day 2 of the meeting
SYDNEY_TZ = "Australia/Sydney"

# --- Recorded meetings (announcement date = meeting day 2) --------------------
# (announce_date, effective_date | None, new_target_rate_bps, delta_bps)
# rate is integer basis points (435 == 4.35%); delta_bps == 0 is a HELD meeting.
# Sources in META.
_DECISIONS = [
    ("2023-11-07", "2023-11-08", 435, 25),   # baseline anchor (hike to 4.35%)
    ("2025-02-18", "2025-02-19", 410, -25),
    ("2025-04-01", None, 410, 0),            # held
    ("2025-05-20", "2025-05-21", 385, -25),
    ("2025-07-08", None, 385, 0),            # held
    ("2025-08-12", "2025-08-13", 360, -25),
    ("2025-09-30", None, 360, 0),            # held
    ("2025-11-04", None, 360, 0),            # held
    ("2025-12-09", None, 360, 0),            # held
    ("2026-02-03", "2026-02-04", 385, 25),
    ("2026-03-17", "2026-03-18", 410, 25),
    ("2026-05-05", "2026-05-06", 435, 25),
    ("2026-06-16", None, 435, 0),            # held
]

# --- Scheduled future meetings (announcement date = meeting day 2) ------------
_SCHEDULE = [
    "2026-08-11",
    "2026-09-29",
    "2026-11-03",
    "2026-12-08",
]

META = {
    "timezone": SYDNEY_TZ,
    "announce_time": "14:30",
    "sources": [
        "https://www.rba.gov.au/statistics/cash-rate/",
        "https://www.rba.gov.au/monetary-policy/int-rate-decisions/",
        "https://www.rba.gov.au/schedules-events/board-meeting-schedules.html",
    ],
    "updated": "2026-06-21",
}


@dataclass(frozen=True)
class Decision:
    date: date  # announcement date (meeting day 2)
    effective: Optional[date]  # None for a held meeting (no rate change)
    rate_bps: int  # resulting cash-rate target in basis points (435 == 4.35%)
    delta_bps: int

    @property
    def new_rate(self) -> float:
        """Resulting cash-rate target as a percentage (e.g. 4.35)."""
        return self.rate_bps / 100.0

    @property
    def effective_date(self) -> date:
        """When the target takes effect: the effective date for a change, or the
        announcement date for a held meeting (the level is simply confirmed)."""
        return self.effective if self.effective is not None else self.date

    @property
    def outcome(self) -> str:
        if self.delta_bps > 0:
            return "hike"
        if self.delta_bps < 0:
            return "cut"
        return "hold"


@dataclass(frozen=True)
class Meeting:
    date: date  # announcement date (meeting day 2)
    announce_utc: datetime


def _d(value: str) -> date:
    return date.fromisoformat(value)


def _as_date(value: Union[date, datetime]) -> date:
    """Coerce to a calendar date. An aware ``datetime`` is interpreted in the RBA's
    Sydney frame — so an instant already "tomorrow" in Sydney resolves to the Sydney
    date, matching the default ``current_rate`` path rather than disagreeing for the
    hours between Sydney and UTC midnight. A naive ``datetime`` is taken at face
    value. (``datetime`` is a subclass of ``date``, but ordering a ``date`` against a
    ``datetime`` raises ``TypeError``, so this also prevents a crash when a datetime
    reaches the ``date``-typed helpers below.)"""
    if isinstance(value, datetime):
        return sydney_today(value) if value.tzinfo is not None else value.date()
    return value


def _first_sunday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7)


def sydney_utc_offset_hours(day: Union[date, datetime]) -> int:
    """Australian Eastern offset for ``day``: AEDT (+11) from the first Sunday in
    October to the first Sunday in April, otherwise AEST (+10)."""
    day = _as_date(day)
    dst_start = _first_sunday(day.year, 10)
    dst_end = _first_sunday(day.year, 4)
    return 11 if (day >= dst_start or day < dst_end) else 10


def announce_instant(day: date) -> datetime:
    """UTC instant of the 14:30 Sydney announcement on ``day``."""
    local = datetime.combine(day, ANNOUNCE_TIME)
    return (local - timedelta(hours=sydney_utc_offset_hours(day))).replace(tzinfo=timezone.utc)


def sydney_today(now: Optional[datetime] = None) -> date:
    """The calendar date in Sydney (the RBA's frame of reference) at ``now`` —
    defaults to the current instant. Aware datetimes are normalised to UTC first."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc)
    return (now + timedelta(hours=sydney_utc_offset_hours(now.date()))).date()


def decisions() -> List[Decision]:
    return [
        Decision(_d(ann), _d(eff) if eff else None, int(rate_bps), int(delta))
        for ann, eff, rate_bps, delta in _DECISIONS
    ]


def schedule() -> List[Meeting]:
    return [Meeting(_d(s), announce_instant(_d(s))) for s in _SCHEDULE]


def validate() -> List[str]:
    """Return a list of integrity issues; empty means the calendar is consistent."""
    issues: List[str] = []
    decs = decisions()

    for prev, cur in zip(decs, decs[1:]):
        if cur.date <= prev.date:
            issues.append(f"decisions out of order: {prev.date} -> {cur.date}")
        if cur.rate_bps != prev.rate_bps + cur.delta_bps:
            issues.append(
                f"rate discontinuity at {cur.date}: "
                f"{prev.rate_bps} + {cur.delta_bps}bps != {cur.rate_bps}"
            )

    for dec in decs:
        if dec.delta_bps % 25 != 0:
            issues.append(f"unusual delta at {dec.date}: {dec.delta_bps}bps")
        if dec.effective is not None and dec.effective < dec.date:
            issues.append(f"effective precedes announcement at {dec.date}")

    sched = schedule()
    if decs and sched and sched[0].date <= decs[-1].date:
        issues.append("schedule overlaps recorded decisions")
    for prev, cur in zip(sched, sched[1:]):
        if cur.date <= prev.date:
            issues.append(f"schedule out of order: {prev.date} -> {cur.date}")

    return issues


def last_decision_on_or_before(day: Union[date, datetime]) -> Optional[Decision]:
    """Latest decision whose ANNOUNCEMENT date is on or before ``day``."""
    day = _as_date(day)
    found: Optional[Decision] = None
    for dec in decisions():
        if dec.date <= day:
            found = dec
        else:
            break
    return found


def current_rate(asof: Optional[Union[date, datetime]] = None) -> Optional[float]:
    """The prevailing cash-rate target (percent) as of ``asof``, by EFFECTIVE date.

    Defaults to today in Sydney — the RBA's frame of reference — so the answer does
    not flip a day early around the UTC/Sydney boundary. Returns ``None`` before the
    baseline anchor's effective date.
    """
    asof = _as_date(asof) if asof is not None else sydney_today()
    found: Optional[Decision] = None
    for dec in decisions():
        if dec.effective_date <= asof:
            found = dec
        else:
            break
    return found.new_rate if found else None


def decisions_in_range(start: Union[date, datetime], end: Union[date, datetime]) -> List[Decision]:
    """Recorded decisions (incl. holds) with announcement date in [start, end] —
    the join input for bank pass-through metrics over a ledger window."""
    start = _as_date(start)
    end = _as_date(end)
    return [dec for dec in decisions() if start <= dec.date <= end]


def next_meeting(now: Optional[datetime] = None) -> Optional[Meeting]:
    """The next scheduled meeting whose announcement is still in the future.

    The boundary is exclusive: exactly at the 14:30 announcement instant the meeting
    is no longer "upcoming" (its outcome is being announced), so the next meeting is
    returned."""
    now = now or datetime.now(timezone.utc)
    for meeting in schedule():
        if meeting.announce_utc > now:
            return meeting
    return None


def countdown(now: Optional[datetime] = None) -> Optional[timedelta]:
    now = now or datetime.now(timezone.utc)
    meeting = next_meeting(now)
    return (meeting.announce_utc - now) if meeting else None


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="RBA cash-rate decision calendar.")
    parser.add_argument("command", nargs="?", default="status", choices=("status", "verify", "next"))
    args = parser.parse_args(argv)

    issues = validate()
    if args.command == "verify":
        for issue in issues:
            print(f"ISSUE: {issue}")
        print(f"rba_decisions: {len(issues)} issue(s)")
        return 1 if issues else 0

    meeting = next_meeting()
    remaining = countdown()
    if args.command == "next":
        print(json.dumps(
            {
                "next_announcement_utc": meeting.announce_utc.isoformat() if meeting else None,
                "days_until": remaining.days if remaining else None,
            },
            indent=2,
        ))
        return 0

    print(f"current cash rate: {current_rate()}%")
    if meeting and remaining:
        print(f"next decision: {meeting.date.isoformat()} "
              f"(announce {meeting.announce_utc.isoformat()}), in {remaining.days}d")
    print(f"integrity: {len(issues)} issue(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
