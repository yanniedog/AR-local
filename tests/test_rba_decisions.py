"""The RBA cash-rate decision calendar — the recorded-fact reference behind the
countdown, macro gauge, and bank pass-through metrics.

Asserts the checked-in calendar is internally consistent (chronology + rate
continuity), that the announcement instant is DST-correct without a tzdata
dependency, and that the countdown / lookup helpers behave at known instants.
"""

from datetime import date, datetime, timezone

import pytest

import rba_decisions as rba


def test_checked_in_calendar_is_consistent():
    # The real shipped data must validate clean: a future typo fails here.
    assert rba.validate() == []


def test_rate_continuity_holds_across_every_change():
    decs = rba.decisions()
    for prev, cur in zip(decs, decs[1:]):
        assert round(cur.new_rate, 2) == round(prev.new_rate + cur.delta_bps / 100.0, 2)


def test_outcome_classification():
    by_date = {d.date.isoformat(): d for d in rba.decisions()}
    assert by_date["2025-02-18"].outcome == "cut"
    assert by_date["2026-05-05"].outcome == "hike"
    assert by_date["2026-06-16"].outcome == "hold"
    assert by_date["2026-06-16"].effective is None


def test_announce_instant_is_dst_correct_without_tzdata():
    # August = AEST (UTC+10): 14:30 Sydney -> 04:30 UTC.
    assert rba.announce_instant(date(2026, 8, 11)) == datetime(2026, 8, 11, 4, 30, tzinfo=timezone.utc)
    # December = AEDT (UTC+11): 14:30 Sydney -> 03:30 UTC.
    assert rba.announce_instant(date(2026, 12, 8)) == datetime(2026, 12, 8, 3, 30, tzinfo=timezone.utc)
    # February (summer) = AEDT (UTC+11): 14:30 Sydney -> 03:30 UTC.
    assert rba.announce_instant(date(2026, 2, 3)) == datetime(2026, 2, 3, 3, 30, tzinfo=timezone.utc)


def test_sydney_offset_boundaries():
    # AEST in winter, AEDT in summer.
    assert rba.sydney_utc_offset_hours(date(2026, 7, 1)) == 10
    assert rba.sydney_utc_offset_hours(date(2026, 1, 1)) == 11


def test_next_meeting_and_countdown_at_a_known_instant():
    now = datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc)
    meeting = rba.next_meeting(now)
    assert meeting is not None
    assert meeting.date == date(2026, 8, 11)
    assert rba.countdown(now) == meeting.announce_utc - now
    assert rba.countdown(now).total_seconds() > 0


def test_next_meeting_rolls_over_once_the_announcement_passes():
    aug = rba.announce_instant(date(2026, 8, 11))
    just_before = aug.replace(minute=29)
    just_after = aug.replace(minute=31)
    assert rba.next_meeting(just_before).date == date(2026, 8, 11)
    assert rba.next_meeting(just_after).date == date(2026, 9, 29)


def test_next_meeting_is_none_after_the_last_scheduled_meeting():
    after_all = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert rba.next_meeting(after_all) is None
    assert rba.countdown(after_all) is None


def test_current_rate_asof_history():
    assert rba.current_rate(date(2025, 3, 1)) == 4.10   # after Feb 2025 cut
    assert rba.current_rate(date(2026, 5, 31)) == 4.35  # after May 2026 hike
    assert rba.current_rate(date(2026, 6, 30)) == 4.35  # June hold
    assert rba.current_rate(date(2025, 1, 1)) is None    # before the first recorded decision


def test_decisions_in_range_is_the_pass_through_join_input():
    window = rba.decisions_in_range(date(2026, 1, 1), date(2026, 5, 31))
    assert [d.date.isoformat() for d in window] == ["2026-02-03", "2026-03-17", "2026-05-05"]


def test_validate_detects_a_rate_discontinuity(monkeypatch):
    bad = list(rba._DECISIONS)
    # Break continuity: a +25 that doesn't add up to the stated new_rate.
    bad[-1] = ("2026-06-16", None, 9.99, 25)
    monkeypatch.setattr(rba, "_DECISIONS", bad)
    issues = rba.validate()
    assert any("discontinuity" in i for i in issues)


def test_validate_detects_schedule_overlap(monkeypatch):
    monkeypatch.setattr(rba, "_SCHEDULE", ["2026-05-01"])  # before the last decision
    assert any("overlap" in i for i in rba.validate())
