"""Cloud/UNC/network refuse checks for laptop backup targets."""

from __future__ import annotations

from pathlib import Path

import pytest

import laptop_backup_target as target_guard
import laptop_pull_backup as receiver


def test_refuse_cloud_backup_root_blocks_google_drive_label(tmp_path: Path):
    target = tmp_path / "backups" / "AR-local-pi5"
    target.mkdir(parents=True)
    with pytest.raises(ValueError, match="cloud/virtual root"):
        receiver.refuse_cloud_backup_root(
            target,
            probe={"root": "G:\\", "label": "Google Drive", "filesystem": "FAT32"},
        )


def test_refuse_cloud_backup_root_blocks_remote_filesystem(tmp_path: Path):
    target = tmp_path / "mnt" / "share"
    target.mkdir(parents=True)
    with pytest.raises(ValueError, match="remote/virtual"):
        receiver.refuse_cloud_backup_root(
            target,
            probe={"root": "/mnt/share", "label": "", "filesystem": "cifs"},
        )


def test_refuse_cloud_backup_root_blocks_unc_path():
    with pytest.raises(ValueError, match="UNC/network"):
        receiver.refuse_cloud_backup_root(Path(r"\\server\share\backups"))


def test_refuse_cloud_backup_root_blocks_cloud_path_segment(tmp_path: Path):
    target = tmp_path / "OneDrive" / "AR-local-pi5"
    with pytest.raises(ValueError, match="cloud-synced"):
        receiver.refuse_cloud_backup_root(target)


def test_refuse_cloud_backup_root_blocks_remote_drive_type(tmp_path: Path):
    target = tmp_path / "mapped" / "AR-local-pi5"
    target.mkdir(parents=True)
    with pytest.raises(ValueError, match="remote/network drive"):
        receiver.refuse_cloud_backup_root(
            target,
            probe={"root": "Z:\\", "label": "Data", "filesystem": "NTFS", "drive_type": "4"},
        )


def test_canonical_target_refuses_before_mkdir(tmp_path: Path):
    target = tmp_path / "Dropbox" / "missing" / "AR-local-pi5"
    with pytest.raises(ValueError, match="cloud-synced"):
        receiver.canonical_target(target)
    assert not target.exists()


def test_canonical_target_allows_local_volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "backups" / "AR-local-pi5"
    monkeypatch.setattr(
        target_guard,
        "volume_probe",
        lambda _path: {"root": str(tmp_path), "label": "Local Disk", "filesystem": "NTFS"},
    )
    monkeypatch.setattr(target_guard, "_windows_drive_type", lambda _path: 3)
    assert receiver.canonical_target(target) == target.resolve()


def test_decode_proc_mounts_field_handles_space_escape():
    assert target_guard._decode_proc_mounts_field(r"/mnt/remote\040share") == "/mnt/remote share"


def test_volume_probe_matches_escaped_cifs_mountpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mount = tmp_path / "remote share"
    mount.mkdir()
    target = mount / "AR-local-pi5"
    target.mkdir()
    mounts_file = tmp_path / "mounts"
    escaped_root = tmp_path.as_posix().replace(" ", r"\040")
    mounts_file.write_text(
        f"//server/share {escaped_root}/remote\\040share cifs rw 0 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(target_guard, "os", type("O", (), {"name": "posix"})())
    real_open = open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/proc/mounts":
            return real_open(mounts_file, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    identity = target_guard.volume_probe(target)
    assert identity["filesystem"] == "cifs"
