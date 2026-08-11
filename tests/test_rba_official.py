from datetime import datetime, timezone

import pytest

import rba_decisions
import rba_official


HTML = """
<table id="datatable"><thead><tr><th>Effective Date</th><th>Change</th><th>Target</th></tr></thead>
<tbody>
<tr><th scope="row">12 Aug 2026</th><td>0.00</td><td>4.35</td><td>Statement</td></tr>
<tr><th scope="row">6 May 2026</th><td>+0.25</td><td>4.35</td><td>Statement</td></tr>
</tbody></table>
"""
FEED = """
<item rdf:about="https://www.rba.gov.au/media-releases/2026/mr-26-19.html">
  <title>Statement by the Monetary Policy Board: Monetary Policy Decision</title>
  <description>At its meeting today, the Board decided to leave the cash rate target unchanged at 4.35 per cent.</description>
  <dc:date>2026-08-11T14:30:00+10:00</dc:date>
</item>
"""
OVERVIEW = """
<h2>Cash rate target</h2><p>4.35 <span>%</span></p>
<p>Effective date 12 August 2026</p>
"""


def test_parses_official_rows_and_maps_effective_to_announcement_dates():
    records = rba_official.parse_cash_rate_table(HTML)
    assert records[0]["effective"].isoformat() == "2026-08-12"
    decisions = rba_official.decision_entries(records)
    assert decisions == [
        {
            "date": "2026-05-05",
            "effective": "2026-05-06",
            "rate": 4.35,
            "delta_bps": 25,
            "outcome": "hike",
        },
        {
            "date": "2026-08-11",
            "effective": None,
            "rate": 4.35,
            "delta_bps": 0,
            "outcome": "hold",
        },
    ]


def test_parser_rejects_fractional_basis_points_and_empty_tables():
    fractional = HTML.replace("0.00", "0.001", 1)
    with pytest.raises(rba_official.RbaOfficialError, match="non-integral basis-point"):
        rba_official.parse_cash_rate_table(fractional)
    with pytest.raises(rba_official.RbaOfficialError, match="contained no usable rows"):
        rba_official.parse_cash_rate_table(
            '<table id="datatable"><tr><th>Effective Date</th><th>Change</th><th>Target</th></tr></table>'
        )


def test_merge_removes_recorded_meeting_and_keeps_next_schedule():
    calendar = rba_decisions.calendar_payload()
    merged = rba_official.merge_calendar(
        calendar,
        rba_official.parse_cash_rate_table(HTML),
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    assert merged["decisions"][-1]["date"] == "2026-08-11"
    assert merged["decisions"][-1]["outcome"] == "hold"
    assert merged["schedule"][0]["date"] == "2026-09-29"


def test_load_calendar_wires_injected_fetch_parse_and_merge():
    merged = rba_official.load_calendar(
        rba_decisions.calendar_payload(),
        fetch=lambda: HTML,
        fetch_feed=lambda: FEED,
        fetch_overview=lambda: OVERVIEW,
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    assert merged["decisions"][-1]["date"] == "2026-08-11"
    assert merged["schedule"][0]["date"] == "2026-09-29"


def test_immediate_media_release_feed_resolves_before_history_table():
    stale = rba_decisions.calendar_payload()
    stale["decisions"] = [d for d in stale["decisions"] if d["date"] != "2026-08-11"]
    stale["schedule"].insert(0, {
        "date": "2026-08-11",
        "announce_utc": "2026-08-11T04:30:00+00:00",
    })
    merged = rba_official.load_calendar(
        stale,
        fetch=lambda: (_ for _ in ()).throw(rba_official.RbaOfficialError("table lagging")),
        fetch_feed=lambda: FEED,
        fetch_overview=lambda: "unavailable",
        now=datetime(2026, 8, 11, 4, 30, tzinfo=timezone.utc),
    )
    assert merged["decisions"][-1]["date"] == "2026-08-11"
    assert merged["decisions"][-1]["outcome"] == "hold"


def test_media_release_feed_scans_past_newer_unrelated_items():
    unrelated = """
    <item><title>Payments bulletin</title>
      <dc:date>2026-08-11T15:00:00+10:00</dc:date></item>
    """
    decision = rba_official.parse_media_release_feed(unrelated + FEED, rba_decisions.calendar_payload())
    assert decision is not None
    assert decision["date"] == "2026-08-11"
    assert decision["outcome"] == "hold"


def test_checked_in_calendar_survives_a_temporary_official_outage():
    unavailable = lambda: (_ for _ in ()).throw(rba_official.RbaOfficialError("offline"))
    merged = rba_official.load_calendar(
        rba_decisions.calendar_payload(),
        fetch=unavailable,
        fetch_feed=unavailable,
        fetch_overview=unavailable,
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    assert merged["decisions"][-1]["date"] == "2026-08-11"
    assert merged["schedule"][0]["date"] == "2026-09-29"


def test_live_overview_is_an_independent_official_fallback():
    calendar = rba_decisions.calendar_payload()
    decision = rba_official.parse_cash_rate_overview(OVERVIEW, calendar)
    assert decision == {
        "date": "2026-08-11", "effective": None, "rate": 4.35,
        "delta_bps": 0, "outcome": "hold",
    }


def test_elapsed_unresolved_meeting_fails_closed_after_grace():
    calendar = rba_decisions.calendar_payload()
    calendar["decisions"] = [d for d in calendar["decisions"] if d["date"] != "2026-08-11"]
    calendar["schedule"].insert(0, {
        "date": "2026-08-11",
        "announce_utc": "2026-08-11T04:30:00+00:00",
    })
    with pytest.raises(rba_official.RbaOfficialError, match="2026-08-11"):
        rba_official.merge_calendar(
            calendar,
            [],
            now=datetime(2026, 8, 12, tzinfo=timezone.utc),
        )


def test_naive_schedule_timestamp_is_treated_as_utc():
    calendar = rba_decisions.calendar_payload()
    calendar["schedule"] = [{
        "date": "2026-09-29",
        "announce_utc": "2026-09-29T04:30:00",
    }]
    merged = rba_official.merge_calendar(
        calendar,
        [],
        now=datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc),
    )
    assert merged["schedule"][0]["date"] == "2026-09-29"


def test_inconsistent_official_rate_fails_closed():
    records = rba_official.parse_cash_rate_table(HTML)
    records[0]["rate_bps"] = 999
    with pytest.raises(rba_official.RbaOfficialError, match="continuity"):
        rba_official.merge_calendar(rba_decisions.calendar_payload(), records)
