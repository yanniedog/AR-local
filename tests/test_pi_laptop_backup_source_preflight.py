"""Focused safety checks for the Pi-side laptop-backup preflight."""

from __future__ import annotations

import subprocess
from argparse import Namespace
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest

import pi_laptop_backup_source as source


PROTECTED = "b" * 40


@pytest.mark.parametrize(
    "timer_value",
    ["Sun 2026-08-30 02:00:00 AEST", "Mon 2026-08-31 01:00:00 AEST"],
)
def test_source_rejects_wrong_next_timer_time_or_date(timer_value: str) -> None:
    with pytest.raises(ValueError, match="exact next 01:00"):
        source.validate_next_daily_timer(
            timer_value, datetime.fromisoformat("2026-08-29T20:00:00+10:00")
        )


@pytest.mark.parametrize(
    ("now", "timer_value"),
    [
        ("2027-01-05T00:29:00+11:00", "Tue 2027-01-05 01:00:00 AEDT"),
        ("2027-01-05T01:00:00+11:00", "Wed 2027-01-06 01:00:00 AEDT"),
        ("2026-08-29T00:29:00+10:00", "Sat 2026-08-29 01:00:00 AEST"),
    ],
)
def test_source_accepts_exact_same_or_next_day_hobart_timer(
    now: str, timer_value: str
) -> None:
    source.validate_next_daily_timer(timer_value, datetime.fromisoformat(now))


@pytest.mark.parametrize(
    ("now", "timer_value"),
    [
        ("2027-01-05T00:29:00+11:00", "Tue 2027-01-05 01:00:00 AEST"),
        ("2026-08-29T20:00:00+10:00", "Sun 2026-08-30 01:00:00 AEDT"),
    ],
)
def test_source_rejects_wrong_hobart_season_zone(now: str, timer_value: str) -> None:
    with pytest.raises(ValueError, match="exact next 01:00"):
        source.validate_next_daily_timer(timer_value, datetime.fromisoformat(now))


def test_source_preflight_requires_enabled_and_active_timer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args = Namespace(
        production_repo=str(tmp_path / "AR-local"),
        runs_root=str(tmp_path / "data/runs"),
        state_root=str(tmp_path / "data/state"),
        dashboard_url="http://127.0.0.1:8808/api/latest",
        expected_production_sha=PROTECTED,
    )
    for path in (Path(args.production_repo), Path(args.runs_root), Path(args.state_root)):
        path.mkdir(parents=True)
    timer_active = ["active"]
    local_now = datetime.now(source.WINDOW_TZ)
    timer_date = local_now.date() + (timedelta(days=1) if local_now.time() >= time(1) else timedelta())
    timer_next = datetime.combine(timer_date, time(1), source.WINDOW_TZ).strftime(
        "%a %Y-%m-%d %H:%M:%S %Z"
    )

    def command(*parts: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        del check
        if parts == ("systemctl", "is-active", "ar-local-daily.service"):
            return subprocess.CompletedProcess(parts, 0, stdout="inactive\n", stderr="")
        if parts == ("systemctl", "is-enabled", "ar-local-daily.timer"):
            return subprocess.CompletedProcess(parts, 0, stdout="enabled\n", stderr="")
        if parts == ("systemctl", "is-active", "ar-local-daily.timer"):
            return subprocess.CompletedProcess(
                parts, 0, stdout=f"{timer_active[0]}\n", stderr=""
            )
        if parts == (
            "systemctl",
            "show",
            "ar-local-daily.timer",
            "--property=NextElapseUSecRealtime",
            "--value",
        ):
            return subprocess.CompletedProcess(
                parts, 0, stdout=f"{timer_next}\n", stderr=""
            )
        raise AssertionError(parts)

    monkeypatch.setattr(source, "in_quiet_window", lambda: False)
    monkeypatch.setattr(
        source,
        "repo_state",
        lambda path: {
            "path": str(path),
            "commit": PROTECTED,
            "clean": True,
            "dirty_paths": [],
        },
    )
    monkeypatch.setattr(source, "command", command)
    monkeypatch.setattr(source, "http_healthy", lambda _url: True)

    preflight = source.production_preflight(args)
    assert preflight["daily_timer_active"] == "active"
    assert preflight["daily_timer_next"] == timer_next
    timer_active[0] = "inactive"
    with pytest.raises(ValueError, match="timer is not active"):
        source.production_preflight(args)
