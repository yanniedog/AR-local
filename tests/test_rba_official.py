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


def test_inconsistent_official_rate_fails_closed():
    records = rba_official.parse_cash_rate_table(HTML)
    records[0]["rate_bps"] = 999
    with pytest.raises(rba_official.RbaOfficialError, match="continuity"):
        rba_official.merge_calendar(rba_decisions.calendar_payload(), records)
