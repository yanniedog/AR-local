"""Real Restic transport contract, without business data or cloud acceptance."""
import json
import shutil
import subprocess

import pytest

import pi_drive_backup as backup


def test_native_no_scan_retains_exact_files_summary_incremental_and_restore(tmp_path, monkeypatch):
    executable = shutil.which("restic")
    if not executable:
        pytest.skip("requires the native Restic binary")
    version = subprocess.run([executable, "version"], check=True, capture_output=True,
                             text=True, timeout=10).stdout
    if not version.startswith("restic 0.18."):
        pytest.skip("transport contract is pinned to deployed Restic 0.18")
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    password = spool / "password"
    password.write_text("temporary-native-transport-test")
    password.chmod(0o600)
    files = tmp_path / "source"
    files.mkdir()
    chosen = [files / "first [literal].txt", files / "second file.txt"]
    for path in chosen:
        path.write_bytes(b"transport fixture\n" * 4096)
    (files / "unselected.txt").write_bytes(b"must not enter the snapshot")
    file_list = spool / "files.raw"
    file_list.write_bytes(b"".join(str(path).encode() + b"\0" for path in chosen))
    client = backup.Restic(backup.Config(files, spool, str(tmp_path / "repository"),
                           password, spool / "unused-rclone", [], restic=executable))
    monkeypatch.setattr(backup, "guard_window", lambda: None)
    client.run("init", "--repository-version", "2")
    snapshots = []
    for content in (None, b"changed transport fixture\n" * 4096):
        if content:
            chosen[0].write_bytes(content)
        summary = json.loads(client.run("backup", "--json", "--no-scan", "--files-from-raw", str(file_list)))
        assert summary["total_files_processed"] == 2
        assert summary["total_bytes_processed"] == sum(path.stat().st_size for path in chosen)
        snapshots.append(summary["snapshot_id"])
    assert snapshots[0] != snapshots[1]
    assert summary["files_unmodified"] == 1 and summary["files_changed"] == 1
    client.run("check")
    restored = tmp_path / "restored"
    client.run("restore", snapshots[-1], "--target", str(restored), "--verify")
    actual = {path.name: path.read_bytes() for path in restored.rglob("*") if path.is_file()}
    assert actual == {path.name: path.read_bytes() for path in chosen}
