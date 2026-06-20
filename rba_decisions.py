#!/usr/bin/env python3
"""RBA cash-rate decision calendar — the recorded-fact reference behind the
RateWatch countdown, the macro pressure gauge, and every bank rate-pass-through
metric.

Recorded fact, never inferred. Each decision below is sourced from the RBA
cash-rate target table and the RBA Monetary Policy Board meeting schedule (see
``META``). Update this file when the Board next decides; that is the whole
maintenance burden.

Design (audit-aligned):
  - Pure data + pure functions, zero I/O — importable and unit-testable without
    standing up the server or touching the ledger. This is deliberately NOT
    trapped in a server closure.
  - Self-validating: ``validate()`` asserts chronology and rate continuity
    (new_rate == previous + delta) — the ledger integrity ethos applied to the
    calendar, so a typo in a future edit fails a test instead of shipping a wrong
    countdown or a wrong pass-through baseline.
  - Timezone-correct WITHOUT a tzdata dependency: the Sydney UTC offset is derived
    from the Australian Eastern DST rule (AEDT +11 from the first Sunday in October
    to the first Sunday in April, else AEST +10), so the 14:30 announcement instant
    is right on both the Linux Pi and a Windows dev box.

The Board announces each outcome at 14:30 Sydney time on the second day of the
meeting; a rate change takes effect the next business day. Decisions are keyed on
the ANNOUNCEMENT date (``date``) — when lenders learn the outcome and the t0 for
pass-through analysis — while ``effective`` records the RBA table's effective date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional

ANNOUNCE_TIME = time(14, 30)  # 2:30pm Sydney, day 2 of the meeting
SYDNEY_TZ = "Australia/Sydney"

# --- Recorded decisions (announcement date = meeting day 2) -------------------
# (announce_date, effective_date, new_target_rate_pct, delta_bps)
# Sources in META. delta_bps is the change announced; new_rate is the resulting
# target (% p.a.). A held meeting is delta_bps == 0 (the Board met, no change).
_DECISIONS = [
    ("2025-02-18", "2025-02-19", 4.10, -25),
    ("2025-05-20", "2025-05-21", 3.85, -25),
    ("2025-08-12", "2025-08-13", 3.60, -25),
    ("2026-02-03", "2026-02-04", 3.85, 25),
    ("2026-03-17", "2026-03-18", 4.10, 25),
    ("2026-05-05", "2026-05-06", 4.35, 25),
    ("2026-06-16", None, 4.35, 0),  # met and held
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
        "https://www.rba.gov.au/schedules-events/board-meeting-schedules.html",
    ],
    "updated": "2026-06-21",
}


@dataclass(frozen=True)
class Decision:
    date: date  # announcement date (meeting day 2)
    effective: Optional[date]
    new_rate: float
    delta_bps: int

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


def _first_sunday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7)


def sydney_utc_offset_hours(day: date) -> int:
    """Australian Eastern offset for ``day``: AEDT (+11) from the first Sunday in
    October to the first Sunday in April, otherwise AEST (+10)."""
    dst_start = _first_sunday(day.year, 10)
    dst_end = _first_sunday(day.year, 4)
    return 11 if (day >= dst_start or day < dst_end) else 10


def announce_instant(day: date) -> datetime:
    """UTC instant of the 14:30 Sydney announcement on ``day``."""
    local = datetime.combine(day, ANNOUNCE_TIME)
    return (local - timedelta(hours=sydney_utc_offset_hours(day))).replace(tzinfo=timezone.utc)


def decisions() -> List[Decision]:
    return [
        Decision(_d(ann), _d(eff) if eff else None, float(rate), int(delta))
        for ann, eff, rate, delta in _DECISIONS
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
        expected = round(prev.new_rate + cur.delta_bps / 100.0, 2)
        if round(cur.new_rate, 2) != expected:
            issues.append(
                f"rate discontinuity at {cur.date}: "
                f"{prev.new_rate} + {cur.delta_bps}bps != {cur.new_rate}"
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


def last_decision_on_or_before(day: date) -> Optional[Decision]:
    found: Optional[Decision] = None
    for dec in decisions():
        if dec.date <= day:
            found = dec
        else:
            break
    return found


def current_rate(asof: Optional[date] = None) -> Optional[float]:
    asof = asof or datetime.now(timezone.utc).date()
    dec = last_decision_on_or_before(asof)
    return dec.new_rate if dec else None


def decisions_in_range(start: date, end: date) -> List[Decision]:
    """Recorded decisions with announcement date in [start, end] — the join input
    for bank pass-through metrics over a ledger window."""
    return [dec for dec in decisions() if start <= dec.date <= end]


def next_meeting(now: Optional[datetime] = None) -> Optional[Meeting]:
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
