"""The RBA cash-rate decision calendar — the recorded-fact reference behind the
countdown, macro gauge, and bank pass-through metrics.

Asserts the checked-in calendar is internally consistent (chronology + rate
continuity), that holds are recorded, that the announcement instant is DST-correct
without a tzdata dependency, and that current_rate / countdown / lookup helpers
behave at known instants (including the announce->effective gap and the exact
announcement boundary).
"""

import json
from datetime import date, datetime, time, timedelta, timezone

import pytest

import rba_decisions as rba


def test_checked_in_calendar_is_consistent():
    # The real shipped data must validate clean: a future typo fails here.
    assert rba.validate() == []


def test_rate_continuity_holds_across_every_meeting():
    decs = rba.decisions()
    for prev, cur in zip(decs, decs[1:]):
        assert cur.rate_bps == prev.rate_bps + cur.delta_bps


def test_held_meetings_are_recorded():
    by_date = {d.date.isoformat(): d for d in rba.decisions()}
    assert by_date["2025-04-01"].outcome == "hold"
    assert by_date["2025-04-01"].delta_bps == 0
    assert by_date["2025-04-01"].effective is None
    assert by_date["2026-06-16"].outcome == "hold"


def test_outcome_classification():
    by_date = {d.date.isoformat(): d for d in rba.decisions()}
    assert by_date["2025-02-18"].outcome == "cut"
    assert by_date["2026-05-05"].outcome == "hike"
    assert by_date["2026-06-16"].outcome == "hold"


def test_announce_instant_is_dst_correct_without_tzdata():
    # August = AEST (UTC+10): 14:30 Sydney -> 04:30 UTC.
    assert rba.announce_instant(date(2026, 8, 11)) == datetime(2026, 8, 11, 4, 30, tzinfo=timezone.utc)
    # December = AEDT (UTC+11): 14:30 Sydney -> 03:30 UTC.
    assert rba.announce_instant(date(2026, 12, 8)) == datetime(2026, 12, 8, 3, 30, tzinfo=timezone.utc)
    # February (summer) = AEDT (UTC+11): 14:30 Sydney -> 03:30 UTC.
    assert rba.announce_instant(date(2026, 2, 3)) == datetime(2026, 2, 3, 3, 30, tzinfo=timezone.utc)


def test_sydney_offset_boundaries():
    assert rba.sydney_utc_offset_hours(date(2026, 7, 1)) == 10   # winter -> AEST
    assert rba.sydney_utc_offset_hours(date(2026, 1, 1)) == 11   # summer -> AEDT


def test_next_meeting_and_countdown_at_a_known_instant():
    now = datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc)
    meeting = rba.next_meeting(now)
    assert meeting is not None
    assert meeting.date == date(2026, 8, 11)
    assert rba.countdown(now) == meeting.announce_utc - now
    assert rba.countdown(now).total_seconds() > 0


def test_next_meeting_boundary_is_exclusive_at_the_announcement():
    aug = rba.announce_instant(date(2026, 8, 11))
    assert rba.next_meeting(aug.replace(minute=29)).date == date(2026, 8, 11)  # just before
    assert rba.next_meeting(aug).date == date(2026, 9, 29)                     # exactly at -> rolled over
    assert rba.next_meeting(aug.replace(minute=31)).date == date(2026, 9, 29)  # just after


def test_next_meeting_is_none_after_the_last_scheduled_meeting():
    after_all = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert rba.next_meeting(after_all) is None
    assert rba.countdown(after_all) is None


def test_current_rate_uses_effective_dates_not_announcement_dates():
    # Announcement day for the Feb 2025 cut: the new 4.10% target is NOT yet
    # effective (effective 2025-02-19), so the prevailing rate is still 4.35%.
    assert rba.current_rate(date(2025, 2, 18)) == 4.35
    assert rba.current_rate(date(2025, 2, 19)) == 4.10  # effective day
    assert rba.current_rate(date(2026, 5, 31)) == 4.35  # after May 2026 hike
    assert rba.current_rate(date(2026, 6, 30)) == 4.35  # June 2026 hold


def test_current_rate_baseline_and_before():
    assert rba.current_rate(date(2024, 6, 1)) == 4.35   # 2024 held at the anchor level
    assert rba.current_rate(date(2025, 1, 1)) == 4.35   # still the anchor level
    assert rba.current_rate(date(2023, 1, 1)) is None    # before the baseline anchor


def test_current_rate_default_asof_is_sydney_today():
    # A UTC instant that is already "tomorrow" in Sydney must use the Sydney date.
    late = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)  # ~06:00 22 Jun Sydney
    assert rba.sydney_today(late) == date(2026, 6, 22)


def test_current_rate_accepts_aware_datetime_in_sydney_terms():
    # Codex finding: 2025-02-18T20:00Z is already 2025-02-19 in Sydney, so the Feb
    # cut is effective and current_rate must agree with the Sydney-based default path.
    assert rba.current_rate(datetime(2025, 2, 18, 20, 0, tzinfo=timezone.utc)) == 4.10
    # A naive datetime has no zone to interpret, so it is taken at face value.
    assert rba.current_rate(datetime(2025, 2, 18, 20, 0)) == 4.35


def test_decisions_in_range_includes_holds():
    # Codex finding: a late-2025 window must surface the held meetings, not [].
    window = rba.decisions_in_range(date(2025, 9, 1), date(2025, 12, 31))
    assert [d.date.isoformat() for d in window] == ["2025-09-30", "2025-11-04", "2025-12-09"]
    assert all(d.outcome == "hold" for d in window)


def test_decisions_in_range_is_the_pass_through_join_input():
    window = rba.decisions_in_range(date(2026, 1, 1), date(2026, 5, 31))
    assert [d.date.isoformat() for d in window] == ["2026-02-03", "2026-03-17", "2026-05-05"]


def test_helpers_accept_datetime_without_typeerror():
    # date<->datetime ordering would otherwise raise TypeError (Gemini finding).
    assert rba.sydney_utc_offset_hours(datetime(2026, 7, 1, 12, 0)) == 10
    assert rba.last_decision_on_or_before(datetime(2026, 5, 31, 9, 0)).date == date(2026, 5, 5)
    window = rba.decisions_in_range(datetime(2026, 1, 1), datetime(2026, 5, 31, 23, 59))
    assert [d.date.isoformat() for d in window] == ["2026-02-03", "2026-03-17", "2026-05-05"]


def test_validate_detects_a_rate_discontinuity(monkeypatch):
    bad = list(rba._DECISIONS)
    bad[-1] = ("2026-06-16", None, 999, 0)  # 999bps does not follow 435 + 0
    monkeypatch.setattr(rba, "_DECISIONS", bad)
    assert any("discontinuity" in i for i in rba.validate())


def test_validate_detects_schedule_overlap(monkeypatch):
    monkeypatch.setattr(rba, "_SCHEDULE", ["2026-05-01"])  # before the last decision
    assert any("overlap" in i for i in rba.validate())


def test_api_payload_shape_and_values():
    now = datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc)
    p = rba.api_payload(now)
    assert p["timezone"] == "Australia/Sydney"
    assert p["current_rate"] == 4.35
    nm = p["next_meeting"]
    assert nm["date"] == "2026-08-11"
    assert nm["announce_utc"] == "2026-08-11T04:30:00+00:00"
    assert nm["days_until"] == 51
    assert nm["seconds_until"] > 0
    assert any(d["outcome"] == "hold" for d in p["decisions"])
    assert p["schedule"][0]["date"] == "2026-08-11"
    json.dumps(p)  # must be JSON-serialisable
    # off-contract inputs must not raise (naive datetime assumed UTC; bare date -> UTC midnight)
    assert rba.api_payload(datetime(2026, 6, 21, 0, 0))["current_rate"] == 4.35
    assert rba.api_payload(date(2026, 6, 21))["current_rate"] == 4.35


def test_api_payload_has_no_next_meeting_after_the_schedule():
    # Derive "after the schedule" from the schedule itself, not a brittle fixed date.
    last_meeting = max(m.date for m in rba.schedule())
    now = datetime.combine(last_meeting, time(0), tzinfo=timezone.utc) + timedelta(days=365)
    assert rba.api_payload(now)["next_meeting"] is None


def test_api_payload_generated_at_is_utc_and_truncated():
    now = datetime(2026, 6, 21, 3, 4, 5, 123456, tzinfo=timezone.utc)
    ga = datetime.fromisoformat(rba.api_payload(now)["generated_at"])
    assert ga.utcoffset() == timedelta(0)
    assert ga.microsecond == 0
    assert ga == now.replace(microsecond=0)


def test_server_rba_payload_is_small_and_valid_json():
    import cdr_dashboard_server as srv

    body = srv.rba_payload()
    assert isinstance(body, bytes)
    assert len(body) < 16 * 1024  # tiny reference payload (audit: budgets are tests)
    data = json.loads(body)
    assert data["current_rate"] is not None
    assert {"generated_at", "timezone", "next_meeting", "decisions", "schedule"} <= set(data)
    assert isinstance(data["generated_at"], str)
