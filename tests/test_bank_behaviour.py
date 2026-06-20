"""Bank rate-pass-through analytics — joins per-provider move events to the RBA
decision calendar.

Exercises the join logic with synthetic move events against real
``rba_decisions.Decision`` objects: direction/hold matching, the response window,
pre-decision exclusion, first-match-only, section filtering, aggregation, and the
sample-size confidence model.
"""

from datetime import date, datetime
from types import SimpleNamespace

import bank_behaviour as bb
from rba_decisions import Decision

HIKE = Decision(date(2026, 2, 3), date(2026, 2, 4), 385, 25)
HIKE2 = Decision(date(2026, 3, 17), date(2026, 3, 18), 410, 25)
CUT = Decision(date(2025, 2, 18), date(2025, 2, 19), 410, -25)
HOLD = Decision(date(2026, 6, 16), None, 435, 0)


def ev(d, provider, section, direction, bps):
    return {"date": d, "provider": provider, "section": section, "dir": direction,
            "moved": 1, "total": 1, "avg_bps": bps}


def test_confidence_thresholds():
    assert bb.confidence(0) == "insufficient"
    assert bb.confidence(2) == "insufficient"
    assert bb.confidence(3) == "early"
    assert bb.confidence(6) == "emerging"
    assert bb.confidence(10) == "established"


def test_pass_through_observation_basic():
    events = [ev("2026-02-05", "FastBank", "Mortgage", "hike", 25.0)]
    obs = bb.pass_through_observations(events, [HIKE], section="Mortgage")
    assert len(obs) == 1
    o = obs[0]
    assert o["provider"] == "FastBank" and o["direction"] == "hike"
    assert o["days"] == 2 and o["bps"] == 25.0 and o["ratio"] == 1.0


def test_direction_and_hold_are_ignored():
    events = [
        ev("2026-02-05", "P", "Mortgage", "cut", -25.0),   # wrong direction vs a hike
        ev("2026-02-05", "Q", "Mortgage", "mixed", 10.0),  # mixed never follows
    ]
    assert bb.pass_through_observations(events, [HIKE], section="Mortgage") == []
    # a hold decision implies no expected move
    follow = [ev("2026-06-18", "P", "Mortgage", "hike", 25.0)]
    assert bb.pass_through_observations(follow, [HOLD], section="Mortgage") == []


def test_window_and_pre_decision_excluded():
    events = [
        ev("2026-02-01", "Early", "Mortgage", "hike", 25.0),  # before announcement
        ev("2026-04-20", "Late", "Mortgage", "hike", 25.0),   # ~76 days, outside 60d window
    ]
    assert bb.pass_through_observations(events, [HIKE], section="Mortgage", window_days=60) == []


def test_first_matching_move_only():
    events = [
        ev("2026-02-20", "P", "Mortgage", "hike", 10.0),
        ev("2026-02-05", "P", "Mortgage", "hike", 25.0),  # earlier -> the one that counts
    ]
    obs = bb.pass_through_observations(events, [HIKE], section="Mortgage")
    assert len(obs) == 1 and obs[0]["days"] == 2 and obs[0]["bps"] == 25.0


def test_section_filter():
    events = [ev("2026-02-05", "P", "Savings", "hike", 25.0)]
    assert bb.pass_through_observations(events, [HIKE], section="Mortgage") == []
    assert len(bb.pass_through_observations(events, [HIKE], section="Savings")) == 1


def test_cut_decision_matches_cut_move():
    events = [ev("2025-02-21", "P", "Mortgage", "cut", 25.0)]  # 3 days after the cut
    obs = bb.pass_through_observations(events, [CUT], section="Mortgage")
    assert len(obs) == 1 and obs[0]["direction"] == "cut" and obs[0]["days"] == 3


def test_summary_aggregates_and_confidence():
    events = [
        ev("2026-02-05", "FastBank", "Mortgage", "hike", 25.0),
        ev("2026-03-01", "SlowBank", "Mortgage", "hike", 12.5),
    ]
    summary = bb.pass_through_summary(events, [HIKE], section="Mortgage")
    assert summary["section"] == "Mortgage" and summary["window_days"] == 60
    fast = summary["providers"]["FastBank"]["hike"]
    assert fast["n"] == 1 and fast["days_median"] == 2 and fast["ratio_median"] == 1.0
    assert fast["confidence"] == "insufficient"  # n = 1
    slow = summary["providers"]["SlowBank"]["hike"]
    assert slow["days_median"] == 26 and slow["ratio_median"] == 0.5
    assert summary["providers"]["FastBank"]["cut"]["n"] == 0  # no cut observations


def test_empty_inputs():
    assert bb.pass_through_observations([], [HIKE], section="Mortgage") == []
    assert bb.pass_through_summary([], [], section="Mortgage")["providers"] == {}


def test_real_calendar_with_no_events_is_empty():
    # Honest "early ledger" state: the real calendar + no move events -> no patterns.
    import rba_decisions
    summary = bb.pass_through_summary([], rba_decisions.decisions(), section="Mortgage")
    assert summary["providers"] == {}


def test_no_double_counting_across_overlapping_windows():
    # The 2026 hikes are < window_days apart; one move must attribute to exactly one
    # decision (the most recent one), not both (Codex P1 / Gemini critical).
    events = [ev("2026-03-20", "P", "Mortgage", "hike", 25.0)]
    obs = bb.pass_through_observations(events, [HIKE, HIKE2], section="Mortgage", window_days=60)
    assert len(obs) == 1
    assert obs[0]["decision_date"] == "2026-03-17" and obs[0]["days"] == 3


def test_event_date_accepts_datetime():
    events = [ev(datetime(2026, 2, 5, 9, 30), "P", "Mortgage", "hike", 25.0)]
    obs = bb.pass_through_observations(events, [HIKE], section="Mortgage")
    assert len(obs) == 1 and obs[0]["days"] == 2


def test_malformed_event_dates_are_ignored():
    events = [
        ev("not-a-date", "P", "Mortgage", "hike", 25.0),
        ev(12345, "Q", "Mortgage", "hike", 25.0),
        {"provider": "R", "section": "Mortgage", "dir": "hike", "avg_bps": 25.0},  # no date
    ]
    assert bb.pass_through_observations(events, [HIKE], section="Mortgage") == []


def test_window_boundaries_are_inclusive():
    events = [
        ev("2026-02-03", "Same", "Mortgage", "hike", 25.0),  # day 0
        ev("2026-04-04", "Edge", "Mortgage", "hike", 25.0),  # exactly 60 days
        ev("2026-04-05", "Past", "Mortgage", "hike", 25.0),  # 61 days -> excluded
    ]
    obs = bb.pass_through_observations(events, [HIKE], section="Mortgage", window_days=60)
    assert sorted(o["days"] for o in obs) == [0, 60]


def test_zero_delta_decision_yields_none_ratio():
    # Defensive: a follow-direction decision with a 0 bps delta must not divide by zero.
    weird = SimpleNamespace(date=date(2026, 2, 3), outcome="hike", delta_bps=0)
    obs = bb.pass_through_observations(
        [ev("2026-02-05", "P", "Mortgage", "hike", 25.0)], [weird], section="Mortgage"
    )
    assert len(obs) == 1 and obs[0]["ratio"] is None
