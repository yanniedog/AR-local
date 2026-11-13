"""Permanent cross-midnight maintenance, with the natural ingest still protected."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ar_local_ingest_schedule import DAILY_INGEST_TZ as TZ, maintenance_closes_at, maintenance_window_open
from app_payload_backfill_window import validate_containment
from pi_cdr_quality_window import deadline
from tests.test_backfill_ingest_window import properties


def local(clock, day="2026-11-14"):
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=TZ)


@pytest.mark.parametrize("day", ["2026-04-05", "2026-10-04", "2026-11-14"])
@pytest.mark.parametrize("clock,allowed", [("00:00", True), ("00:29:59", True),
    ("00:30", False), ("01:00", False), ("03:29:59", False), ("03:30", True),
    ("22:00", True), ("23:59:59", True)])
def test_maintenance_window_uses_hobart_across_midnight_and_dst(day, clock, allowed):
    assert maintenance_window_open(local(clock, day).astimezone(timezone.utc)) is allowed


@pytest.mark.parametrize("clock,next_day", [("00:00", False), ("00:29:59", False),
    ("03:30", True), ("21:00", True), ("22:00", True), ("23:59", True)])
def test_default_deadline_is_the_immediate_0030_cutoff(clock, next_day):
    now = local(clock)
    expected = local("00:30") + timedelta(days=int(next_day))
    assert maintenance_closes_at(now) == expected
    assert deadline(now, None) == expected
    assert deadline(now, expected + timedelta(hours=1)) == expected
    assert deadline(now, now + timedelta(seconds=5)) == min(expected, now + timedelta(seconds=5))


@pytest.mark.parametrize("clock", ["23:30", "23:59", "00:00", "00:29"])
def test_full_backfill_cannot_overrun_current_night_cutoff(clock):
    with pytest.raises(RuntimeError, match="terminate before"):
        validate_containment(properties(), local(clock))


def test_short_backfill_after_midnight_keeps_termination_reserve():
    short = properties(); short["RuntimeMaxUSec"] = "60s"
    validate_containment(short, local("00:27"))
    with pytest.raises(RuntimeError, match="terminate before"):
        validate_containment(short, local("00:28"))


@pytest.mark.parametrize("clock,allowed", [("00:29", True), ("00:30", False),
    ("01:00", False), ("03:29", False), ("03:30", True), ("22:00", True), ("23:59", True)])
def test_installed_root_guard_matches_window_without_importing_candidate(monkeypatch, clock, allowed):
    import pi_ci_activate as root
    now = local(clock)
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    monkeypatch.setattr(root, "datetime", Fixed)
    calls = []
    backend = SimpleNamespace(deadline=float("inf"),
        context={"plan": {"expires_at": (now + timedelta(hours=1)).isoformat()}},
        lease=lambda: calls.append("held"))
    if allowed:
        root.Native.guard(backend)
        assert calls == ["held"]
    else:
        with pytest.raises(RuntimeError, match="protected"):
            root.Native.guard(backend)
        assert calls == []


@pytest.mark.parametrize("clock,day", [("23:59", "2026-11-14"), ("00:15", "2026-11-13")])
def test_quality_selection_uses_latest_due_ingest_not_next_midnight(tmp_path, monkeypatch, clock, day):
    import pi_cdr_quality_activate as quality
    now = local(clock)
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    monkeypatch.setattr(quality, "datetime", Fixed)
    directory = tmp_path / "state/observation-pointers-v2"; directory.mkdir(parents=True)
    exports = tmp_path / "exports"; exports.mkdir()
    pointer = directory / "latest-observation.json"
    value = dict(run_date=day, generation_id=f"obs-{day}-qualified", export_path="exports")
    pointer.write_text(json.dumps(value), encoding="utf8")
    assert quality.current_state(tmp_path) == (day, value["generation_id"], exports)
    value["run_date"] = "2026-11-12"
    pointer.write_text(json.dumps(value), encoding="utf8")
    with pytest.raises(ValueError, match="latest scheduled"):
        quality.current_state(tmp_path)
