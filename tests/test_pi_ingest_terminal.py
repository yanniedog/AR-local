"""Failure-evidence and shared-lock tests for the scheduled Pi ingest."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_daily_sync  # noqa: E402
import pi_ingest_terminal  # noqa: E402

COMMIT = "a" * 40
DIGEST = "b" * 64


def _config(tmp_path: Path) -> Path:
    mount = tmp_path / "mount"
    destination = mount / "ar-local"
    destination.mkdir(parents=True)
    config = tmp_path / "backup.env"
    config.write_text(
        "\n".join(
            (
                f"AR_BACKUP_MOUNTPOINT={mount}",
                "AR_BACKUP_EXPECTED_SOURCE=/dev/test-backup",
                "AR_BACKUP_EXPECTED_FSTYPE=ext4",
                f"AR_BACKUP_DIRECTORY={destination}",
                f"AR_BACKUP_EXPECTED_UID={os.getuid() if hasattr(os, 'getuid') else 0}",
                f"AR_BACKUP_EXPECTED_GID={os.getgid() if hasattr(os, 'getgid') else 0}",
                f"AR_BACKUP_PLAN_GIT_COMMIT={COMMIT}",
                f"AR_BACKUP_PLAN_SHA256={DIGEST}",
                f"AR_BACKUP_PLAN_RAW_SHA256={'e' * 64}",
            )
        ),
        encoding="utf-8",
    )
    return config


def _repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(("git", "init", "-q", "-b", "main"), cwd=path, check=True)
    subprocess.run(("git", "config", "user.email", "terminal-test@example.invalid"), cwd=path, check=True)
    subprocess.run(("git", "config", "user.name", "Terminal Test"), cwd=path, check=True)
    (path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(("git", "add", "tracked.txt"), cwd=path, check=True)
    subprocess.run(("git", "commit", "-qm", "fixture"), cwd=path, check=True)


def test_terminal_failure_is_append_only_and_hash_verified(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo(repo)
    state = tmp_path / "state"
    config = _config(tmp_path)
    path = pi_ingest_terminal.record_failure(
        repo,
        state,
        "2026-08-24",
        "pytest",
        "python pi_daily_sync.py --banks-only",
        "2026-08-24T01:00:00Z",
        RuntimeError("upstream failed"),
        config_path=config,
    )
    record = pi_ingest_terminal.latest_valid_failure(
        state, "2026-08-24", config_path=config
    )
    assert record is not None
    assert record["result"] == "FAIL"
    assert record["plan_document_id"] == "ARL-OPS-001"
    assert path.is_file()
    evidence = Path(record["evidence"][0]["path"])
    evidence.write_text("tampered\n", encoding="utf-8")
    assert pi_ingest_terminal.latest_valid_failure(
        state, "2026-08-24", config_path=config
    ) is None


def test_daily_ingest_uses_shared_inode_owned_lock(tmp_path: Path) -> None:
    lock = tmp_path / "state/daily-ingest.lock"
    with pi_daily_sync.DailyIngestLock(lock):
        values = dict(
            line.split("=", 1) for line in lock.read_text(encoding="utf-8").splitlines()
        )
        assert values["role"] == "ingest"
        assert values["pid"] == str(os.getpid())
    assert not lock.exists()
