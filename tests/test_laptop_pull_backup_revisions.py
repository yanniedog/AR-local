"""Revision-specific source and restore checks for laptop observation backups."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import laptop_pull_backup as receiver
import pi_laptop_backup_source as source
from tests.test_laptop_pull_backup import create_daily_exports, source_args


def test_observation_source_includes_exact_pointer_selected_revision_marker(
    tmp_path: Path,
) -> None:
    date = "2026-08-25"
    run = tmp_path / f"data/runs/{date}"
    state = tmp_path / "data/state"
    (run / "_exports").mkdir(parents=True)
    (run / "_exports/local-cdr.sqlite").write_bytes(b"sqlite-placeholder")
    state.mkdir(parents=True)
    (state / f"{date}.done.json").write_text("{}", encoding="utf-8")
    marker_name = f"{date}.revision.later.json"
    (state / marker_name).write_text(
        '{"generation_id":"revision"}', encoding="utf-8"
    )
    pointer = state / "observation-pointers-v2/latest-observation.json"
    pointer.parent.mkdir()
    pointer.write_text(
        json.dumps(
            {
                "observation_date": date,
                "generation_id": "revision",
                "marker_path": marker_name,
            }
        ),
        encoding="utf-8",
    )

    selected, identity = source.observation_sources(source_args(tmp_path, date))
    archived = {relative for _path, relative in selected}

    assert identity["is_latest_observation"] is True
    assert f"data/state/{marker_name}" in archived


def test_latest_pointer_reconciles_its_selected_revision_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    date = "2026-08-25"
    root = tmp_path / "restored"
    create_daily_exports(root, date)
    state = root / "data/state"
    marker_name = f"{date}.revision.later.json"
    marker_path = state / marker_name
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text('{"generation_id":"revision"}', encoding="utf-8")
    revision_exports = root / f"data/runs/{date}/_revisions/later/_exports"
    revision_exports.mkdir(parents=True)
    revision_database = revision_exports / "local-cdr.sqlite"
    revision_database.write_bytes(b"selected")
    pointer_root = state / "observation-pointers-v2"
    pointer_root.mkdir()
    (pointer_root / "latest-observation.json").write_text(
        json.dumps(
            {
                "observation_date": date,
                "generation_id": "revision",
                "marker_path": marker_name,
                "export_path": f"runs/{date}/_revisions/later/_exports",
            }
        ),
        encoding="utf-8",
    )
    checked: list[Path] = []

    monkeypatch.setattr(receiver, "_completion_marker_valid", lambda *_args: True)
    monkeypatch.setattr(receiver, "_pointer_matches_marker", lambda *_args: True)

    def reconcile(path: Path) -> dict[str, object]:
        checked.append(path)
        return {"run_date": date}

    monkeypatch.setattr(receiver, "daily_reconciliation_bounded", reconcile)

    receiver.observation_checks(
        root, {"observation_date": date, "is_latest_observation": True}
    )

    assert checked == [revision_database.resolve()]
