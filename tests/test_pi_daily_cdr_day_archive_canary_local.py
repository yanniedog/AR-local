"""Isolated canary local-archive transport coverage (D-028, no Drive)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import pi_daily_cdr_day_archive as archive
import pi_daily_cdr_day_archive_transport as transport


def test_resolve_archive_remote_preserves_absolute_local_path():
    remote = "canary_local:/srv/ar-local/canary/prep-x/data/day-archive-remote"
    resolved = transport.resolve_archive_remote(remote, preserve_absolute=True)
    assert resolved == (
        "canary_local:/srv/ar-local/canary/prep-x/data/"
        "day-archive-remote/daily-cdr-raw-records"
    )
    # Without preserve_absolute, leading slash is stripped (Drive-style paths).
    stripped = transport.resolve_archive_remote(remote)
    assert stripped.startswith("canary_local:srv/")


def _seed_local_canary_tree(tmp_path: Path, monkeypatch, *, name: str = "prep-local"):
    parent = tmp_path / "canary-parent"
    canary = parent / name
    config_dir = canary / "config"
    remote_dir = canary / "data" / "day-archive-remote"
    config_dir.mkdir(parents=True)
    remote_dir.mkdir(parents=True)
    env_path = config_dir / "day-archive.env"
    rclone_conf = config_dir / "rclone.conf"
    env_path.write_text(
        "\n".join(
            [
                f"AR_LOCAL_DAY_ARCHIVE_SPOOL={canary / 'data' / 'archive-spool'}",
                f"AR_LOCAL_DAY_ARCHIVE_REMOTE=canary_local:{remote_dir}",
                f"RCLONE_CONFIG={rclone_conf}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    rclone_conf.write_text(
        "[canary_local]\ntype = local\nnounc = true\n", encoding="utf-8"
    )
    rclone_conf.chmod(0o600)
    monkeypatch.setattr(transport, "CANARY_ROOT_PARENT", parent)
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_ENV", str(env_path))
    return canary, remote_dir, rclone_conf, env_path


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="unix rclone ownership checks")
def test_day_archive_rclone_accepts_local_canary(tmp_path: Path, monkeypatch):
    _canary, remote_dir, rclone_conf, _env = _seed_local_canary_tree(
        tmp_path, monkeypatch
    )
    client = transport.DayArchiveRclone(
        rclone_conf, f"canary_local:{remote_dir}", ""
    )
    assert client.local_backend is True
    assert client.remote.endswith("/daily-cdr-raw-records")
    assert client.remote.startswith("canary_local:/")


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="unix rclone ownership checks")
def test_day_archive_rclone_rejects_local_without_canary_env(
    tmp_path: Path, monkeypatch
):
    _canary, remote_dir, rclone_conf, _env = _seed_local_canary_tree(
        tmp_path, monkeypatch
    )
    monkeypatch.delenv("AR_LOCAL_DAY_ARCHIVE_ENV", raising=False)
    with pytest.raises(ValueError, match="AR_LOCAL_DAY_ARCHIVE_ENV"):
        transport.DayArchiveRclone(rclone_conf, f"canary_local:{remote_dir}", "")


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="unix rclone ownership checks")
def test_day_archive_rclone_rejects_local_outside_canary(tmp_path: Path, monkeypatch):
    _canary, _remote_dir, rclone_conf, _env = _seed_local_canary_tree(
        tmp_path, monkeypatch
    )
    other = tmp_path / "outside"
    other.mkdir(parents=True)
    with pytest.raises(ValueError, match="under canary root"):
        transport.DayArchiveRclone(rclone_conf, f"canary_local:{other}", "")


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="unix rclone ownership checks")
def test_day_archive_rclone_rejects_drive_under_canary_env(
    tmp_path: Path, monkeypatch
):
    _canary, remote_dir, rclone_conf, _env = _seed_local_canary_tree(
        tmp_path, monkeypatch
    )
    rclone_conf.write_text(
        "[canary_drive]\ntype = drive\nscope = drive.file\n"
        'token = {"refresh_token":"x"}\n',
        encoding="utf-8",
    )
    rclone_conf.chmod(0o600)
    with pytest.raises(ValueError, match="type=local"):
        transport.DayArchiveRclone(rclone_conf, f"canary_drive:{remote_dir}", "")


def test_require_day_archive_writes_allowed_skips_drive_hold_for_local():
    # local_backend skips hold entirely — must not raise even without fixtures.
    archive.require_day_archive_writes_allowed(Path("/tmp/unused"), local_backend=True)


def test_canary_root_rejects_non_generation_parent(tmp_path: Path, monkeypatch):
    canary_parent = tmp_path / "canary-parent"
    monkeypatch.setattr(transport, "CANARY_ROOT_PARENT", canary_parent)
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_ENV", "/config/day-archive.env")
    with pytest.raises(ValueError, match="existing generation directory"):
        transport._canary_root_from_env()

    outside = tmp_path / "outside" / "generation" / "config" / "day-archive.env"
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_ENV", str(outside))
    with pytest.raises(ValueError, match="existing generation directory"):
        transport._canary_root_from_env()

    missing = canary_parent / "missing" / "config" / "day-archive.env"
    monkeypatch.setenv("AR_LOCAL_DAY_ARCHIVE_ENV", str(missing))
    with pytest.raises(ValueError, match="existing generation directory"):
        transport._canary_root_from_env()
