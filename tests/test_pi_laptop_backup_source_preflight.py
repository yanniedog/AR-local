"""Focused safety checks for the Pi-side laptop-backup preflight."""

from __future__ import annotations

import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

import pi_laptop_backup_source as source


PROTECTED = "b" * 40


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

    assert source.production_preflight(args)["daily_timer_active"] == "active"
    timer_active[0] = "inactive"
    with pytest.raises(ValueError, match="timer is not active"):
        source.production_preflight(args)
