"""Fail-closed tests for the Pi backup and restoration foundation."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import subprocess
import sys
import shutil
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ar_local_backup_policy as policy_module  # noqa: E402
import ar_local_checkout  # noqa: E402
import ar_local_deployment_chain as deployment_chain  # noqa: E402
import ar_local_operation_lock as operation_lock  # noqa: E402
import ar_local_rollback_record as rollback_record  # noqa: E402
import pi_backup_foundation as backup  # noqa: E402
import cdr_outputs  # noqa: E402
import cdr_finalization  # noqa: E402

COMMIT = "a" * 40
DIGEST = "b" * 64


def valid_snapshot_manifest(files: list[dict[str, object]]) -> dict[str, object]:
    timestamp = "2026-08-24T00:00:00+00:00"
    return {
        "schema_version": 1,
        "snapshot_id": "pytest-snapshot",
        "created_at": timestamp,
        "started_at": timestamp,
        "completed_at": timestamp,
        "operator": "pytest",
        "plan_document_id": "ARL-OPS-001",
        "plan_version": "1.0",
        "plan_git_commit": COMMIT,
        "plan_sha256": DIGEST,
        "plan_raw_sha256": "e" * 64,
        "candidate_code_sha": COMMIT,
        "repositories": {},
        "source_paths": {},
        "secret_locations": [],
        "data_scope": {
            "policy_version": 1,
            "included": ["runs", "state"],
            "excluded": [
                {
                    "path": ".daily-export-stage",
                    "exists": False,
                    "contents_copied": False,
                    "reason": "transient staging",
                },
                {
                    "path": "netdata",
                    "exists": False,
                    "contents_copied": False,
                    "reason": "telemetry state",
                },
            ],
            "unknown_roots_allowed": False,
        },
        "system_configuration": [],
        "systemd_enablement": [],
        "macro_backup": {
            "table_counts": {"ingest_runs": 0, "series_observations": 0}
        },
        "source_data_bytes": 0,
        "capacity_plan": {
            "snapshot_payload_bytes": 0,
            "staged_payload_bytes": 0,
            "per_snapshot_metadata_reserve_bytes": 1,
            "retained_snapshots": 0,
            "remaining_slots": 1,
            "required_free_bytes": 1,
            "required_after_staging_bytes": 1,
            "available_free_bytes": 1,
            "available_after_staging_bytes": 1,
        },
        "category_summary": {},
        "files": files,
        "exact_commands": [],
        "deviations": [],
        "result": "PASS",
    }


def make_policy(tmp_path: Path) -> policy_module.BackupPolicy:
    mount = tmp_path / "mount"
    destination = mount / "ar-local"
    destination.mkdir(parents=True)
    os.chmod(destination, 0o700)
    return policy_module.BackupPolicy(
        mountpoint=mount,
        expected_source="/dev/test-backup",
        expected_fstype="ext4",
        backup_dir=destination,
        expected_uid=os.getuid() if hasattr(os, "getuid") else 0,
        expected_gid=os.getgid() if hasattr(os, "getgid") else 0,
        max_backup_age_hours=36,
        max_restore_age_hours=192,
        max_boot_proof_age_hours=2160,
        min_free_bytes=1,
        retention_count=30,
        plan_git_commit=COMMIT,
        plan_sha256=DIGEST,
        plan_raw_sha256="e" * 64,
    )


def test_policy_loads_only_absolute_child_destination(tmp_path: Path) -> None:
    (tmp_path / "mount/ar-local").mkdir(parents=True)
    config = tmp_path / "backup.env"
    config.write_text(
        "\n".join(
            (
                f"AR_BACKUP_MOUNTPOINT={tmp_path / 'mount'}",
                "AR_BACKUP_EXPECTED_SOURCE=/dev/disk/by-uuid/backup",
                "AR_BACKUP_EXPECTED_FSTYPE=ext4",
                f"AR_BACKUP_DIRECTORY={tmp_path / 'mount/ar-local'}",
                "AR_BACKUP_EXPECTED_UID=1000",
                "AR_BACKUP_EXPECTED_GID=1000",
                f"AR_BACKUP_PLAN_GIT_COMMIT={COMMIT}",
                f"AR_BACKUP_PLAN_SHA256={DIGEST}",
                f"AR_BACKUP_PLAN_RAW_SHA256={'e' * 64}",
            )
        ),
        encoding="utf-8",
    )
    loaded = policy_module.BackupPolicy.from_env_file(config)
    assert loaded.plan_identity()["plan_document_id"] == "ARL-OPS-001"
    assert loaded.backup_dir == tmp_path / "mount/ar-local"


def test_policy_rejects_destination_outside_mount(tmp_path: Path) -> None:
    (tmp_path / "mount").mkdir()
    (tmp_path / "elsewhere").mkdir()
    config = tmp_path / "backup.env"
    config.write_text(
        f"AR_BACKUP_MOUNTPOINT={tmp_path / 'mount'}\n"
        "AR_BACKUP_EXPECTED_SOURCE=/dev/test\nAR_BACKUP_EXPECTED_FSTYPE=ext4\n"
        f"AR_BACKUP_DIRECTORY={tmp_path / 'elsewhere'}\n"
        "AR_BACKUP_EXPECTED_UID=1\nAR_BACKUP_EXPECTED_GID=1\n"
        f"AR_BACKUP_PLAN_GIT_COMMIT={COMMIT}\nAR_BACKUP_PLAN_SHA256={DIGEST}\n",
        encoding="utf-8",
    )
    config.write_text(
        config.read_text(encoding="utf-8") + f"AR_BACKUP_PLAN_RAW_SHA256={'e' * 64}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="below the mountpoint"):
        policy_module.BackupPolicy.from_env_file(config)


def test_policy_rejects_nonpositive_capacity(tmp_path: Path) -> None:
    (tmp_path / "mount/ar-local").mkdir(parents=True)
    config = tmp_path / "backup.env"
    config.write_text(
        f"AR_BACKUP_MOUNTPOINT={tmp_path / 'mount'}\n"
        "AR_BACKUP_EXPECTED_SOURCE=/dev/test\nAR_BACKUP_EXPECTED_FSTYPE=ext4\n"
        f"AR_BACKUP_DIRECTORY={tmp_path / 'mount/ar-local'}\n"
        "AR_BACKUP_EXPECTED_UID=1\nAR_BACKUP_EXPECTED_GID=1\nAR_BACKUP_MIN_FREE_BYTES=-1\n"
        f"AR_BACKUP_PLAN_GIT_COMMIT={COMMIT}\nAR_BACKUP_PLAN_SHA256={DIGEST}\n"
        f"AR_BACKUP_PLAN_RAW_SHA256={'e' * 64}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be positive"):
        policy_module.BackupPolicy.from_env_file(config)


def test_policy_rejects_retention_below_two(tmp_path: Path) -> None:
    (tmp_path / "mount/ar-local").mkdir(parents=True)
    config = tmp_path / "backup.env"
    config.write_text(
        f"AR_BACKUP_MOUNTPOINT={tmp_path / 'mount'}\n"
        "AR_BACKUP_EXPECTED_SOURCE=/dev/test\nAR_BACKUP_EXPECTED_FSTYPE=ext4\n"
        f"AR_BACKUP_DIRECTORY={tmp_path / 'mount/ar-local'}\n"
        "AR_BACKUP_EXPECTED_UID=1\nAR_BACKUP_EXPECTED_GID=1\nAR_BACKUP_RETENTION_COUNT=1\n"
        f"AR_BACKUP_PLAN_GIT_COMMIT={COMMIT}\nAR_BACKUP_PLAN_SHA256={DIGEST}\n"
        f"AR_BACKUP_PLAN_RAW_SHA256={'e' * 64}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="retention count"):
        policy_module.BackupPolicy.from_env_file(config)


def test_policy_rejects_lexical_traversal_even_when_target_is_inside_mount(tmp_path: Path) -> None:
    (tmp_path / "mount/ar-local").mkdir(parents=True)
    (tmp_path / "mount/unused").mkdir()
    config = tmp_path / "backup.env"
    config.write_text(
        f"AR_BACKUP_MOUNTPOINT={tmp_path / 'mount'}\n"
        "AR_BACKUP_EXPECTED_SOURCE=/dev/test\nAR_BACKUP_EXPECTED_FSTYPE=ext4\n"
        f"AR_BACKUP_DIRECTORY={tmp_path / 'mount/unused/../ar-local'}\n"
        "AR_BACKUP_EXPECTED_UID=1\nAR_BACKUP_EXPECTED_GID=1\n"
        f"AR_BACKUP_PLAN_GIT_COMMIT={COMMIT}\nAR_BACKUP_PLAN_SHA256={DIGEST}\n"
        f"AR_BACKUP_PLAN_RAW_SHA256={'e' * 64}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="canonical"):
        policy_module.BackupPolicy.from_env_file(config)


def test_mount_preflight_rejects_same_physical_device(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    protected = tmp_path / "production"
    protected.mkdir()
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        f"36 25 8:1 / {policy.mountpoint} rw,relatime - ext4 /dev/test-backup rw\n",
        encoding="utf-8",
    )
    report = policy_module.mount_preflight(
        policy, (protected,), mountinfo_path=mountinfo, perform_probe=False
    )
    assert not report["ok"]
    assert any(str(item).startswith("backup_not_physically_separate") for item in report["findings"])


def test_physical_device_identity_supports_nvme_partition_paths(tmp_path: Path) -> None:
    disk = tmp_path / "devices/pci0000_00/nvme/nvme0/nvme0n1"
    partition = disk / "nvme0n1p2"
    partition.mkdir(parents=True)
    (disk / "dev").write_text("259:0\n", encoding="ascii")
    (partition / "dev").write_text("259:2\n", encoding="ascii")
    (partition / "partition").write_text("2\n", encoding="ascii")
    assert policy_module._root_block_device(partition) == "nvme0n1@259:0"


def test_immutable_json_record_cannot_be_rewritten(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    policy_module.atomic_create_json(target, {"result": "PASS"})
    with pytest.raises(FileExistsError):
        policy_module.atomic_create_json(target, {"result": "FAIL"})
    assert json.loads(target.read_text())["result"] == "PASS"


def test_verified_evidence_copy_never_replaces_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    target = tmp_path / "archive.log"
    source.write_text("new evidence\n", encoding="utf-8")
    target.write_text("existing evidence\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        policy_module.atomic_copy_verified(source, target, policy_module.sha256_file(source))
    assert target.read_text(encoding="utf-8") == "existing evidence\n"


def test_sqlite_online_backup_includes_committed_wal_rows(tmp_path: Path) -> None:
    source = tmp_path / "macro.sqlite"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE series_observations(id INTEGER)")
    connection.execute("CREATE TABLE ingest_runs(id INTEGER)")
    connection.execute("INSERT INTO series_observations VALUES (1)")
    connection.execute("INSERT INTO ingest_runs VALUES (2)")
    connection.commit()
    destination = tmp_path / "backup.sqlite"
    report = backup._sqlite_backup(source, destination)
    connection.close()
    assert report["quick_check"] == "ok"
    with sqlite3.connect(destination) as restored:
        assert restored.execute("SELECT COUNT(*) FROM series_observations").fetchone()[0] == 1
        assert restored.execute("SELECT COUNT(*) FROM ingest_runs").fetchone()[0] == 1


def test_snapshot_verification_detects_same_size_tamper(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    artifact = snapshot / "artifact.bin"
    artifact.write_bytes(b"good")
    manifest = valid_snapshot_manifest(
        [{"path": "artifact.bin", "size": 4, "sha256": policy_module.sha256_file(artifact)}]
    )
    (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert backup.verify_snapshot(snapshot)["ok"]
    artifact.write_bytes(b"evil")
    report = backup.verify_snapshot(snapshot)
    assert not report["ok"]
    assert report["findings"] == ["changed:artifact.bin"]


def test_snapshot_verification_hashes_nested_manifest_files(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    nested = snapshot / "data/runs/2026-08-24/_exports/dashboard-cache"
    nested.mkdir(parents=True)
    artifact = nested / "manifest.json"
    artifact.write_bytes(b"good")
    relative = artifact.relative_to(snapshot).as_posix()
    manifest = valid_snapshot_manifest(
        [
            {
                "path": relative,
                "size": artifact.stat().st_size,
                "sha256": policy_module.sha256_file(artifact),
            }
        ]
    )
    (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert backup.verify_snapshot(snapshot)["ok"]
    artifact.write_bytes(b"evil")
    report = backup.verify_snapshot(snapshot)
    assert not report["ok"]
    assert f"changed:{relative}" in report["findings"]


def test_snapshot_verification_rejects_malformed_and_extra_entries(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "extra.bin").write_bytes(b"extra")
    (snapshot / "manifest.json").write_text(json.dumps({"files": [{"path": "missing-size"}, "bad"]}), encoding="utf-8")
    report = backup.verify_snapshot(snapshot)
    assert not report["ok"]
    assert "invalid_entry:0" in report["findings"]
    assert "invalid_entry:1" in report["findings"]
    assert "unmanifested:extra.bin" in report["findings"]


def test_snapshot_verification_rejects_path_escape(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text(
        json.dumps({"files": [{"path": "../escape", "size": 0, "sha256": "a" * 64}]}),
        encoding="utf-8",
    )
    report = backup.verify_snapshot(snapshot)
    assert not report["ok"]
    assert "invalid_entry:0" in report["findings"]


def test_snapshot_verification_rejects_manifest_without_scope_contract(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text('{"files":[]}\n', encoding="utf-8")
    report = backup.verify_snapshot(snapshot)
    assert not report["ok"]
    assert any(
        item.startswith("manifest_schema_invalid:$:") and "data_scope" in item
        for item in report["findings"]
    )


def test_snapshot_verification_rejects_symlinked_directory(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "secret.txt").write_text("outside\n", encoding="utf-8")
    try:
        (snapshot / "linked").symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    (snapshot / "manifest.json").write_text('{"files":[]}\n', encoding="utf-8")
    report = backup.verify_snapshot(snapshot)
    assert not report["ok"]
    assert "symlink:linked" in report["findings"]


def test_snapshot_verification_rejects_special_file(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    try:
        os.mkfifo(snapshot / "pipe")
    except OSError as exc:
        pytest.skip(f"FIFO creation unavailable: {exc}")
    (snapshot / "manifest.json").write_text('{"files":[]}\n', encoding="utf-8")
    report = backup.verify_snapshot(snapshot)
    assert not report["ok"]
    assert "special:pipe" in report["findings"]


def test_backup_lock_recovers_dead_owner_and_removes_own_lock(monkeypatch, tmp_path: Path) -> None:
    lock = tmp_path / "daily-ingest.lock"
    lock.write_text("pid=999999\nrole=backup\nboot_id=current\n", encoding="utf-8")
    monkeypatch.setattr(operation_lock, "_current_boot_id", lambda: "current")
    monkeypatch.setattr(operation_lock, "_boot_epoch", lambda: None)
    monkeypatch.setattr(operation_lock, "_pid_is_alive", lambda _pid: False)
    with operation_lock.production_lock(lock, "backup"):
        assert "role=backup" in lock.read_text(encoding="utf-8")
    assert not lock.exists()


def test_backup_lock_never_replaces_live_owner(monkeypatch, tmp_path: Path) -> None:
    lock = tmp_path / "daily-ingest.lock"
    lock.write_text("pid=1234\nrole=ingest\nboot_id=current\n", encoding="utf-8")
    monkeypatch.setattr(operation_lock, "_current_boot_id", lambda: "current")
    monkeypatch.setattr(operation_lock, "_boot_epoch", lambda: None)
    monkeypatch.setattr(operation_lock, "_pid_is_alive", lambda _pid: True)
    with pytest.raises(RuntimeError, match="production lock is active"):
        with operation_lock.production_lock(lock, "backup"):
            pass
    assert "role=ingest" in lock.read_text(encoding="utf-8")


def test_backup_lock_recovers_prior_boot_even_if_pid_was_reused(monkeypatch, tmp_path: Path) -> None:
    lock = tmp_path / "daily-ingest.lock"
    lock.write_text("pid=1234\nrole=backup\nboot_id=prior\n", encoding="utf-8")
    monkeypatch.setattr(operation_lock, "_current_boot_id", lambda: "current")
    monkeypatch.setattr(operation_lock, "_boot_epoch", lambda: None)
    monkeypatch.setattr(operation_lock, "_pid_is_alive", lambda _pid: True)
    with operation_lock.production_lock(lock, "backup"):
        assert "boot_id=current" in lock.read_text(encoding="utf-8")
    assert not lock.exists()


def test_stale_lock_recovery_rechecks_under_recovery_mutex(monkeypatch, tmp_path: Path) -> None:
    lock = tmp_path / "daily-ingest.lock"
    live_payload = "pid=1234\nrole=ingest\nboot_id=current\n"
    lock.write_text(live_payload, encoding="utf-8")
    stale_checks = iter((True, False))
    monkeypatch.setattr(operation_lock, "_existing_lock_is_stale", lambda _path: next(stale_checks))
    with pytest.raises(RuntimeError, match="changed during stale recovery"):
        with operation_lock.production_lock(lock, "backup"):
            pass
    assert lock.read_text(encoding="utf-8") == live_payload


def _git_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(("git", "init", "-q", "-b", "main"), cwd=path, check=True)
    subprocess.run(("git", "config", "user.email", "backup-test@example.invalid"), cwd=path, check=True)
    subprocess.run(("git", "config", "user.name", "Backup Test"), cwd=path, check=True)
    (path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    (path / ".gitignore").write_text("state/\n", encoding="utf-8")
    subprocess.run(("git", "add", "tracked.txt", ".gitignore"), cwd=path, check=True)
    subprocess.run(("git", "commit", "-q", "-m", "fixture"), cwd=path, check=True)


def test_snapshot_is_create_once_and_contains_code_data_and_online_macro(monkeypatch, tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    repo = tmp_path / "repo"
    site = tmp_path / "site"
    _git_repo(repo)
    _git_repo(site)
    data = tmp_path / "data"
    (data / "runs/2026-08-24/_exports").mkdir(parents=True)
    (data / "runs/2026-08-24/_exports/evidence.json").write_text("{}\n", encoding="utf-8")
    (data / "state").mkdir()
    (data / ".daily-export-stage").mkdir()
    (data / "netdata/lib/bearer_tokens").mkdir(parents=True)
    netdata_secret = data / "netdata/lib/mcp_dev_preview_api_key"
    netdata_secret.write_text("never copy this secret", encoding="utf-8")
    macro = repo / "state/local-macro.sqlite"
    macro.parent.mkdir()
    with sqlite3.connect(macro) as connection:
        connection.execute("CREATE TABLE series_observations(id INTEGER)")
        connection.execute("CREATE TABLE ingest_runs(id INTEGER)")
        connection.execute("INSERT INTO series_observations VALUES (1)")
    monkeypatch.setattr(backup, "mount_preflight", lambda *_args, **_kwargs: {"ok": True, "findings": [], "mount": {}})
    monkeypatch.setattr(backup, "verify_plan_document", lambda *_args: {"ok": True, "findings": []})
    config = tmp_path / "backup.env"
    config.write_text("AR_BACKUP_EXPECTED_SOURCE=/dev/test-backup\n", encoding="utf-8")
    receipt = backup.create_snapshot(
        policy, repo, site, data, macro, "pytest", config_path=config
    )
    snapshot = policy.backup_dir / "snapshots" / str(receipt["snapshot_id"])
    assert backup.verify_snapshot(snapshot)["ok"]
    schema = json.loads((ROOT / "contracts/pi-preservation-snapshot-v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        json.loads((snapshot / "manifest.json").read_text())
    )
    assert (snapshot / "code/AR-local.bundle").is_file()
    assert (snapshot / "data/runs/2026-08-24/_exports/evidence.json").is_file()
    assert (snapshot / "macro/local-macro.sqlite").is_file()
    assert not (snapshot / "data/state/daily-ingest.lock").exists()
    assert not (snapshot / "data/state/.daily-ingest.lock.recovery-lock").exists()
    assert not (snapshot / "data/netdata").exists()
    assert not (snapshot / "data/.daily-export-stage").exists()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_scope"]["included"] == ["runs", "state"]
    assert next(
        item for item in manifest["data_scope"]["excluded"] if item["path"] == "netdata"
    )["contents_copied"] is False
    secret_record = next(
        item for item in manifest["secret_locations"] if item["path"] == str(netdata_secret)
    )
    assert "sha256" not in secret_record
    assert secret_record["metadata_status"] == "AVAILABLE"
    assert manifest["capacity_plan"]["remaining_slots"] == policy.retention_count
    policy_entry = next(
        item for item in manifest["system_configuration"] if item["path"] == str(config)
    )
    policy_copy = snapshot / policy_entry["snapshot_path"]
    assert policy_copy.read_bytes() == config.read_bytes()
    assert policy_entry["sha256"] == policy_module.sha256_file(policy_copy)
    latest_before = (policy.backup_dir / "latest-backup.json").read_bytes()
    mount_checks = 0

    def disappearing_mount(*_args, **_kwargs):
        nonlocal mount_checks
        mount_checks += 1
        return {
            "ok": mount_checks == 1,
            "findings": [] if mount_checks == 1 else ["backup_mount_missing"],
            "mount": {},
        }

    monkeypatch.setattr(backup, "mount_preflight", disappearing_mount)
    with pytest.raises(RuntimeError, match="mount changed before publication"):
        backup.create_snapshot(
            policy, repo, site, data, macro, "pytest", config_path=config
        )
    assert (policy.backup_dir / "latest-backup.json").read_bytes() == latest_before
    assert len(list((policy.backup_dir / "snapshots").iterdir())) == 1
    assert not list(policy.backup_dir.glob(".partial-*"))


def test_snapshot_reserves_capacity_for_every_remaining_retention_slot(monkeypatch, tmp_path: Path) -> None:
    policy = replace(make_policy(tmp_path), retention_count=3, min_free_bytes=1)
    repo = tmp_path / "repo"
    site = tmp_path / "site"
    _git_repo(repo)
    _git_repo(site)
    data = tmp_path / "data"
    (data / "runs").mkdir(parents=True)
    (data / "runs/evidence.bin").write_bytes(b"x" * 1024)
    (data / "state").mkdir()
    macro = repo / "state/local-macro.sqlite"
    macro.parent.mkdir()
    with sqlite3.connect(macro) as connection:
        connection.execute("CREATE TABLE series_observations(id INTEGER)")
        connection.execute("CREATE TABLE ingest_runs(id INTEGER)")
    monkeypatch.setattr(
        backup,
        "mount_preflight",
        lambda *_args, **_kwargs: {"ok": True, "findings": [], "mount": {}},
    )
    monkeypatch.setattr(backup, "verify_plan_document", lambda *_args: {"ok": True, "findings": []})
    one_generation_only = type("Usage", (), {"free": 1024**3 + 1024 + macro.stat().st_size})()
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _path: one_generation_only)
    with pytest.raises(RuntimeError, match="retention reserve"):
        backup.create_snapshot(policy, repo, site, data, macro, "pytest")
    assert not list(policy.backup_dir.glob(".partial-*"))


def test_snapshot_reserve_includes_complete_staged_code_payload(monkeypatch, tmp_path: Path) -> None:
    policy = replace(make_policy(tmp_path), retention_count=2, min_free_bytes=1)
    repo = tmp_path / "repo"
    site = tmp_path / "site"
    _git_repo(repo)
    _git_repo(site)
    for source in (repo, site):
        (source / "bundle-payload.bin").write_bytes(os.urandom(256 * 1024))
        subprocess.run(("git", "add", "bundle-payload.bin"), cwd=source, check=True)
        subprocess.run(("git", "commit", "-q", "-m", "payload"), cwd=source, check=True)
    data = tmp_path / "data"
    (data / "runs").mkdir(parents=True)
    (data / "runs/evidence.bin").write_bytes(b"x")
    (data / "state").mkdir()
    macro = repo / "state/local-macro.sqlite"
    macro.parent.mkdir()
    with sqlite3.connect(macro) as connection:
        connection.execute("CREATE TABLE series_observations(id INTEGER)")
        connection.execute("CREATE TABLE ingest_runs(id INTEGER)")
    monkeypatch.setattr(
        backup,
        "mount_preflight",
        lambda *_args, **_kwargs: {"ok": True, "findings": [], "mount": {}},
    )
    monkeypatch.setattr(backup, "verify_plan_document", lambda *_args: {"ok": True, "findings": []})
    incomplete_only = type("Usage", (), {"free": 1024**3 + 64 * 1024})()
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _path: incomplete_only)
    with pytest.raises(RuntimeError, match="complete-snapshot retention reserve"):
        backup.create_snapshot(policy, repo, site, data, macro, "pytest")
    assert not list(policy.backup_dir.glob(".partial-*"))


def test_daily_export_reconciliation_binds_json_database_and_dashboard(tmp_path: Path) -> None:
    run_date = "2026-08-24"
    exports = tmp_path / "runs" / run_date / "_exports"
    exports.mkdir(parents=True)
    banks = {
        "products": [], "rates": [], "fees": [], "features": [],
        "eligibility": [], "constraints": [], "product_facts": [],
        "product_changes": [], "failures": [],
    }
    cdr_outputs.rebuild_run_db(exports / "local-cdr.sqlite", run_date, banks)
    (exports / f"banks-{run_date}.json").write_text(json.dumps(banks), encoding="utf-8")
    cache = exports / "dashboard-cache"
    cache.mkdir()
    expected = {key: len(value) for key, value in banks.items()}
    (cache / "latest.json").write_text(
        json.dumps({"run_date": run_date, "banks_counts": expected}), encoding="utf-8"
    )
    report = backup._daily_export_reconciliation(exports / "local-cdr.sqlite")
    assert report["run_date"] == run_date
    banks["products"].append({"product_id": "missing-from-db"})
    (exports / f"banks-{run_date}.json").write_text(json.dumps(banks), encoding="utf-8")
    with pytest.raises(ValueError, match="runs metadata"):
        backup._daily_export_reconciliation(exports / "local-cdr.sqlite")


def _write_finalized_observation(data_root: Path, run_date: str = "2026-08-24") -> None:
    exports = data_root / "runs" / run_date / "_exports"
    exports.mkdir(parents=True)
    product = {
        "dataset": "banking",
        "provider": "provider-a",
        "product_id": "product-a",
        "product_key": "provider-a:product-a",
        "product_name": "Product A",
        "source_file": "fixture.json",
        "details_json": "{}",
    }
    rate = {
        **product,
        "rate_family": "variable",
        "rate": "5.00",
        "comparison_rate": "5.10",
    }
    banks = {
        "products": [product],
        "rates": [rate],
        "fees": [],
        "features": [],
        "eligibility": [],
        "constraints": [],
        "product_facts": [],
        "product_changes": [],
        "failures": [],
    }
    cdr_outputs.rebuild_run_db(exports / "local-cdr.sqlite", run_date, banks)
    (exports / f"banks-{run_date}.json").write_text(
        json.dumps(banks), encoding="utf-8"
    )
    counts = {key: len(value) for key, value in banks.items()}
    dashboard = exports / "dashboard-cache"
    dashboard.mkdir()
    (dashboard / "latest.json").write_text(
        json.dumps({"run_date": run_date, "banks_counts": counts}),
        encoding="utf-8",
    )
    (exports / "ingest-status.json").write_text(
        json.dumps(
            {
                "total": 0,
                "corrupt_records": 0,
                "failure_provenance_complete": True,
                "incomplete": False,
                "by_phase": {},
                "by_status": {},
                "by_provider": {},
                "register_provenance_complete": True,
                "register_attempts": [
                    {
                        "source_url": "https://register.example/holders",
                        "mode": "plain",
                        "ok": True,
                        "status": 200,
                        "bytes": 2,
                        "sha256": "a" * 64,
                    }
                ],
                "providers_registered": 1,
                "providers_attempted": 1,
                "provider_states": [
                    {
                        "provider_uid": "provider-a",
                        "state": "complete",
                        "failure_records": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    state = data_root / "state"
    cdr_finalization.finalize_observation(
        exports,
        state,
        state / f"{run_date}.done.json",
        observation_date=run_date,
        result={"run_date": run_date, "banks_counts": counts},
    )


def write_acceptance_snapshot(
    snapshot: Path, snapshot_id: str, candidate_code_sha: str = COMMIT
) -> tuple[dict[str, object], dict[str, object]]:
    artifacts = {
        "data/runs/2026-08-24/_exports/local-cdr.sqlite": b"database",
        "data/state/2026-08-24.done.json": b"marker",
        "data/state/export-contracts-v2/2026-08-24/fixture.json": b"contract",
        "data/state/ledger-v2/events/2026-08-24/obs-2026-08-24-fixture.json": b"event",
        "macro/local-macro.sqlite": b"macro",
    }
    for relative, content in artifacts.items():
        path = snapshot / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    entries = [
        {
            "path": relative,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for relative, content in sorted(artifacts.items())
    ]
    hashes = {relative: hashlib.sha256(content).hexdigest() for relative, content in artifacts.items()}
    manifest = valid_snapshot_manifest(entries)
    manifest["snapshot_id"] = snapshot_id
    manifest["candidate_code_sha"] = candidate_code_sha
    file_set_sha256 = hashlib.sha256(
        policy_module.canonical_json_bytes(entries)
    ).hexdigest()
    checks = {
        "ok": True,
        "findings": [],
        "selected_observation": {
            "observation_date": "2026-08-24",
            "generation_id": "obs-2026-08-24-fixture",
            "observation_state": "complete",
            "ledger_event_digest": "1" * 64,
            "export_contract_digest": "2" * 64,
            "export_contract_path": "export-contracts-v2/2026-08-24/fixture.json",
            "export_contract_sha256": hashes[
                "data/state/export-contracts-v2/2026-08-24/fixture.json"
            ],
            "marker_path": "2026-08-24.done.json",
            "marker_sha256": hashes["data/state/2026-08-24.done.json"],
            "export_path": "runs/2026-08-24/_exports",
            "database_path": "runs/2026-08-24/_exports/local-cdr.sqlite",
            "database_sha256": hashes[
                "data/runs/2026-08-24/_exports/local-cdr.sqlite"
            ],
            "ledger_event_path": "ledger-v2/events/2026-08-24/obs-2026-08-24-fixture.json",
            "ledger_event_sha256": hashes[
                "data/state/ledger-v2/events/2026-08-24/obs-2026-08-24-fixture.json"
            ],
        },
        "restored_files": {
            "ok": True,
            "findings": [],
            "file_count": len(entries),
            "total_bytes": sum(int(entry["size"]) for entry in entries),
            "source_file_set_sha256": file_set_sha256,
            "restored_file_set_sha256": file_set_sha256,
        },
        "macro": {
            "quick_check": "ok",
            "tables": ["ingest_runs", "series_observations"],
            "counts": {"ingest_runs": 1, "series_observations": 2},
        },
    }
    return manifest, checks


def test_restored_state_rejects_empty_observation_store(tmp_path: Path) -> None:
    (tmp_path / "runs").mkdir()
    (tmp_path / "state/ledger-v2").mkdir(parents=True)
    report = backup._verify_restored_state(tmp_path)
    assert not report["ok"]
    assert "daily_database_missing" in report["findings"]
    assert "export_contract_missing" in report["findings"]
    assert "observation_pointer_missing" in report["findings"]
    assert "latest_observation_pointer_missing" in report["findings"]


def test_restored_state_accepts_fully_bound_latest_observation(tmp_path: Path) -> None:
    _write_finalized_observation(tmp_path)
    report = backup._verify_restored_state(tmp_path)
    assert report["ok"], report["findings"]
    assert report["selected_observation"]["observation_date"] == "2026-08-24"
    assert report["selected_observation"]["database_path"].endswith(
        "_exports/local-cdr.sqlite"
    )


def test_restored_state_preserves_older_schema_without_current_reconciliation(
    tmp_path: Path,
) -> None:
    historical = tmp_path / "runs/2026-08-23/_exports"
    historical.mkdir(parents=True)
    with sqlite3.connect(historical / "local-cdr.sqlite") as connection:
        connection.execute("CREATE TABLE schema_meta(key TEXT, value TEXT)")
        connection.execute("INSERT INTO schema_meta VALUES ('version', '7')")
        connection.commit()
    _write_finalized_observation(tmp_path)
    report = backup._verify_restored_state(tmp_path)
    assert report["ok"], report["findings"]
    historical_record = next(
        item
        for item in report["sqlite"]
        if item["path"].startswith("runs/2026-08-23/")
    )
    assert historical_record["schema_version"] == "7"
    assert "export_reconciliation" not in historical_record


def test_restored_state_rejects_contract_marker_rebinding(tmp_path: Path) -> None:
    _write_finalized_observation(tmp_path)
    pointer_path = tmp_path / "state/observation-pointers-v2/latest-observation.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    original_marker = tmp_path / "state" / pointer["marker_path"]
    rebound_marker = tmp_path / "state/rebound.done.json"
    rebound_marker.write_bytes(original_marker.read_bytes())
    pointer["marker_path"] = "rebound.done.json"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    report = backup._verify_restored_state(tmp_path)
    assert not report["ok"]
    assert "pointer_marker_invalid:latest-observation.json" in report["findings"]


def test_restored_manifest_files_detect_same_size_corruption_and_extra(tmp_path: Path) -> None:
    destination = tmp_path / "restore"
    (destination / "data/runs").mkdir(parents=True)
    restored = destination / "data/runs/evidence.bin"
    restored.write_bytes(b"bad!")
    (destination / "data/extra.bin").write_bytes(b"extra")
    expected_sha = hashlib.sha256(b"good").hexdigest()
    manifest = {
        "files": [
            {"path": "data/runs/evidence.bin", "size": 4, "sha256": expected_sha}
        ]
    }
    report = backup._verify_restored_manifest_files(manifest, destination)
    assert not report["ok"]
    assert "restored_file_changed:data/runs/evidence.bin" in report["findings"]
    assert "restored_file_extra:data/extra.bin" in report["findings"]


@pytest.mark.parametrize(
    ("relative", "finding"),
    (
        ("state/2026-08-24.done.json", "pointer_target_missing:latest-observation.json"),
        ("state/observation-pointers-v2/latest-observation.json", "latest_observation_pointer_missing"),
    ),
)
def test_restored_state_rejects_missing_selected_evidence(
    tmp_path: Path, relative: str, finding: str
) -> None:
    _write_finalized_observation(tmp_path)
    (tmp_path / relative).unlink()
    report = backup._verify_restored_state(tmp_path)
    assert not report["ok"]
    assert finding in report["findings"]


def test_restore_drill_rejects_post_copy_data_corruption(
    monkeypatch, tmp_path: Path
) -> None:
    policy = make_policy(tmp_path)
    snapshot_id = "snapshot-corrupt-copy"
    snapshot = policy.backup_dir / "snapshots" / snapshot_id
    (snapshot / "data").mkdir(parents=True)
    (snapshot / "data/evidence.bin").write_bytes(b"good")
    macro = snapshot / "macro/local-macro.sqlite"
    macro.parent.mkdir()
    with sqlite3.connect(macro) as connection:
        connection.execute("CREATE TABLE series_observations(id INTEGER)")
        connection.execute("CREATE TABLE ingest_runs(id INTEGER)")
    files = [
        {
            "path": path.relative_to(snapshot).as_posix(),
            "size": path.stat().st_size,
            "sha256": policy_module.sha256_file(path),
        }
        for path in sorted(snapshot.rglob("*"))
        if path.is_file()
    ]
    (snapshot / "manifest.json").write_text(
        json.dumps(valid_snapshot_manifest(files)), encoding="utf-8"
    )
    original_copytree = backup.shutil.copytree

    def corrupt_copy(source, destination, *args, **kwargs):
        result = original_copytree(source, destination, *args, **kwargs)
        (Path(destination) / "evidence.bin").write_bytes(b"bad!")
        return result

    monkeypatch.setattr(backup.shutil, "copytree", corrupt_copy)
    monkeypatch.setattr(
        backup, "_verify_restored_state", lambda _root: {"ok": True, "findings": []}
    )
    receipt = backup.restore_drill(
        policy, snapshot_id, tmp_path / "scratch", "pytest", ["restore-drill"]
    )
    assert receipt["result"] == "FAIL"
    assert (
        "restored_file_changed:data/evidence.bin"
        in receipt["checks"]["findings"]
    )


def boot_proof(policy: policy_module.BackupPolicy, created_at: str) -> dict[str, object]:
    evidence = policy.backup_dir / "boot-proof.log"
    evidence.write_text("boot proof\n", encoding="utf-8")
    return {
        "schema_version": 1,
        "created_at": created_at,
        **policy.plan_identity(),
        "candidate_code_sha": COMMIT,
        "operator": "pytest",
        "exact_commands": ["boot-clone-verify"],
        "deviations": [],
        "boot_id": "boot-1",
        "backup_device_id": policy.expected_source,
        "network": {"ok": True},
        "dashboard": {"ok": True},
        "ingest_timers": {"ok": True},
        "storage_identity": {
            "ok": True,
            "source": policy.expected_source,
            "mountpoint": str(policy.mountpoint),
            "fstype": policy.expected_fstype,
        },
        "evidence": [{"path": str(evidence.resolve()), "sha256": policy_module.sha256_file(evidence)}],
        "result": "PASS",
    }


def test_boot_proof_rejects_future_timestamp(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    path = tmp_path / "boot.json"
    path.write_text(json.dumps(boot_proof(policy, future)), encoding="utf-8")
    report = backup.validate_boot_proof(path, policy, datetime.now(timezone.utc))
    assert not report["ok"]
    assert "boot_proof_stale_or_future" in report["findings"]


def test_boot_proof_contract_accepts_complete_record(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    proof = boot_proof(policy, datetime.now(timezone.utc).isoformat())
    schema = json.loads((ROOT / "contracts/pi-backup-boot-proof-v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(proof)


def test_boot_archive_rejects_proof_changed_after_gate(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    path = tmp_path / "boot.json"
    path.write_text(
        json.dumps(boot_proof(policy, datetime.now(timezone.utc).isoformat())),
        encoding="utf-8",
    )
    validated_digest = policy_module.sha256_file(path)
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after deployment gate"):
        backup.archive_boot_evidence(path, tmp_path / "archive", validated_digest)
    assert not (tmp_path / "archive/boot-proof.original.json").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    (("schema_version", None), ("boot_id", ""), ("operator", "")),
)
def test_boot_proof_validator_enforces_checked_in_schema(tmp_path: Path, field: str, value: object) -> None:
    policy = make_policy(tmp_path)
    proof = boot_proof(policy, datetime.now(timezone.utc).isoformat())
    if value is None:
        proof.pop(field)
    else:
        proof[field] = value
    path = tmp_path / f"invalid-{field}.json"
    path.write_text(json.dumps(proof), encoding="utf-8")
    report = backup.validate_boot_proof(path, policy, datetime.now(timezone.utc))
    assert not report["ok"]
    assert any(item.startswith("boot_schema_invalid:") for item in report["findings"])


def test_boot_proof_rejects_wrong_device_identity(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    proof = boot_proof(policy, datetime.now(timezone.utc).isoformat())
    proof["backup_device_id"] = "/dev/wrong"
    path = tmp_path / "boot.json"
    path.write_text(json.dumps(proof), encoding="utf-8")
    report = backup.validate_boot_proof(path, policy, datetime.now(timezone.utc))
    assert "boot_device_id_mismatch" in report["findings"]


def test_internal_runner_rejects_non_git_commands(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only internal git"):
        ar_local_checkout.git_command(("powershell", "Get-ChildItem"), tmp_path)


def test_restore_drill_removes_unique_scratch_copy(monkeypatch, tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    snapshot_id = "snapshot-cleanup"
    snapshot = policy.backup_dir / "snapshots" / snapshot_id
    (snapshot / "data").mkdir(parents=True)
    (snapshot / "data/evidence.txt").write_text("evidence\n", encoding="utf-8")
    macro = snapshot / "macro/local-macro.sqlite"
    macro.parent.mkdir()
    with sqlite3.connect(macro) as connection:
        connection.execute("CREATE TABLE series_observations(id INTEGER)")
        connection.execute("CREATE TABLE ingest_runs(id INTEGER)")
    files = []
    for path in sorted(snapshot.rglob("*")):
        if path.is_file():
            files.append({"path": path.relative_to(snapshot).as_posix(), "size": path.stat().st_size, "sha256": policy_module.sha256_file(path)})
    (snapshot / "manifest.json").write_text(
        json.dumps(valid_snapshot_manifest(files)), encoding="utf-8"
    )
    monkeypatch.setattr(backup, "_verify_restored_state", lambda _root: {"ok": True, "findings": []})
    scratch = tmp_path / "missing-parent/scratch"
    receipt = backup.restore_drill(
        policy, snapshot_id, scratch, "pytest", ["restore-drill"]
    )
    assert receipt["result"] == "PASS", receipt["checks"]
    assert receipt["scratch_retained"] is False
    assert list(scratch.iterdir()) == []


def test_restore_drill_requires_exact_command_evidence(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    with pytest.raises(ValueError, match="requires at least one exact command"):
        backup.restore_drill(
            policy, "snapshot", tmp_path / "scratch", "pytest"
        )


def test_restore_drill_records_exception_without_replacing_last_pass(monkeypatch, tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    snapshot_id = "snapshot-failure"
    snapshot = policy.backup_dir / "snapshots" / snapshot_id
    (snapshot / "data").mkdir(parents=True)
    (snapshot / "data/evidence.txt").write_text("evidence\n", encoding="utf-8")
    macro = snapshot / "macro/local-macro.sqlite"
    macro.parent.mkdir()
    with sqlite3.connect(macro) as connection:
        connection.execute("CREATE TABLE series_observations(id INTEGER)")
        connection.execute("CREATE TABLE ingest_runs(id INTEGER)")
    files = [
        {"path": path.relative_to(snapshot).as_posix(), "size": path.stat().st_size, "sha256": policy_module.sha256_file(path)}
        for path in sorted(snapshot.rglob("*"))
        if path.is_file()
    ]
    (snapshot / "manifest.json").write_text(
        json.dumps(valid_snapshot_manifest(files)), encoding="utf-8"
    )
    latest = policy.backup_dir / "latest-restore.json"
    latest.write_text('{"result":"PASS","receipt_path":"receipts/previous.json"}\n', encoding="utf-8")
    previous = latest.read_bytes()

    def fail_copy(*_args, **_kwargs):
        raise OSError("simulated restore I/O failure")

    monkeypatch.setattr(backup.shutil, "copytree", fail_copy)
    with pytest.raises(RuntimeError, match="receipt="):
        backup.restore_drill(policy, snapshot_id, tmp_path / "scratch", "pytest", ["restore"])
    failure_receipts = list((policy.backup_dir / "receipts").glob("*.restore.*.json"))
    assert len(failure_receipts) == 1
    failed = json.loads(failure_receipts[0].read_text(encoding="utf-8"))
    assert failed["result"] == "FAIL"
    assert failed["checks"]["findings"] == ["restore_exception:OSError"]
    assert latest.read_bytes() == previous


def test_snapshot_creation_stops_at_retention_ceiling(monkeypatch, tmp_path: Path) -> None:
    policy = replace(make_policy(tmp_path), retention_count=2)
    snapshots = policy.backup_dir / "snapshots"
    (snapshots / "one").mkdir(parents=True)
    (snapshots / "two").mkdir()
    monkeypatch.setattr(backup, "preflight", lambda *_args: {"ok": True, "findings": []})
    monkeypatch.setattr(
        backup,
        "git_state",
        lambda path: {"path": str(path), "commit": COMMIT, "clean": True, "status": []},
    )
    roots = [tmp_path / name for name in ("repo", "site", "data")]
    for root in roots:
        root.mkdir()
    with pytest.raises(RuntimeError, match="retention ceiling"):
        backup.create_snapshot(policy, *roots, tmp_path / "macro.sqlite", "pytest")


def test_snapshot_rechecks_retention_after_taking_production_lock(monkeypatch, tmp_path: Path) -> None:
    policy = replace(make_policy(tmp_path), retention_count=2)
    snapshots = policy.backup_dir / "snapshots"
    (snapshots / "one").mkdir(parents=True)
    monkeypatch.setattr(backup, "preflight", lambda *_args: {"ok": True, "findings": []})
    monkeypatch.setattr(
        backup,
        "git_state",
        lambda path: {"path": str(path), "commit": COMMIT, "clean": True, "status": []},
    )

    lock_entries = 0
    lock_active = False

    class AddSnapshotWhileAcquiring:
        def __enter__(self):
            nonlocal lock_active, lock_entries
            lock_entries += 1
            lock_active = True
            if lock_entries == 2:
                (snapshots / "two").mkdir()

        def __exit__(self, *_args):
            nonlocal lock_active
            lock_active = False
            return None

    monkeypatch.setattr(backup, "production_lock", lambda *_args: AddSnapshotWhileAcquiring())
    monkeypatch.setattr(
        backup,
        "git_state",
        lambda path: (
            {"path": str(path), "commit": COMMIT, "clean": True, "status": []}
            if lock_active
            else pytest.fail("repository identity sampled outside production lock")
        ),
    )
    monkeypatch.setattr(
        backup, "mount_preflight", lambda *_args, **_kwargs: {"ok": True, "findings": [], "mount": {}}
    )
    repo, site, data = (tmp_path / name for name in ("repo", "site", "data"))
    _git_repo(repo)
    _git_repo(site)
    (data / "runs").mkdir(parents=True)
    (data / "state").mkdir()
    macro = tmp_path / "macro.sqlite"
    with sqlite3.connect(macro) as connection:
        connection.execute("CREATE TABLE series_observations(id INTEGER)")
        connection.execute("CREATE TABLE ingest_runs(id INTEGER)")
    with pytest.raises(RuntimeError, match="retention ceiling reached before publication"):
        backup.create_snapshot(policy, repo, site, data, macro, "pytest")
    assert lock_entries == 2


def test_verified_rollback_writes_immutable_record_and_evidence(monkeypatch, tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    monkeypatch.setattr(
        rollback_record,
        "mount_preflight",
        lambda *_args, **_kwargs: {"ok": True, "findings": [], "mount": {}},
    )
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    _git_repo(repo)
    data.mkdir()
    protected = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    record = rollback_record.record_rollback_acceptance(
        policy,
        repo,
        repo,
        data,
        protected,
        "b" * 40,
        "pytest",
        ["deploy candidate", "rollback checkout"],
        services_verified=True,
        dashboard_verified=True,
    )
    record_path = Path(record["record_path"])
    stored = json.loads(record_path.read_text(encoding="utf-8"))
    assert stored["result"] == "ROLLED_BACK"
    assert stored["candidate_code_sha"] == "b" * 40
    assert stored["protected_code_sha"] == protected
    evidence = Path(stored["evidence"][0]["path"])
    assert policy_module.sha256_file(evidence) == stored["evidence"][0]["sha256"]
    schema = json.loads((ROOT / "contracts/pi-rollback-acceptance-v1.schema.json").read_text())
    assert not list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(stored))


def test_pointer_fields_are_bound_to_marker_and_contract(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state"
    contract_path = state / "export-contracts-v2/2026-08-24/generation.json"
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text("{}\n", encoding="utf-8")
    marker = {
        "run_date": "2026-08-24",
        "generation_id": "generation",
        "observation_state": "complete",
        "ledger_event_digest": "d" * 64,
        "export_contract_path": contract_path.relative_to(state).as_posix(),
    }
    monkeypatch.setattr(
        __import__("cdr_export_contract"),
        "load_contract",
        lambda _path: {"source_path": "runs/2026-08-24/_exports"},
    )
    pointer = {
        "schema_version": 2,
        "observation_date": "2026-08-24",
        "generation_id": "generation",
        "observation_state": "complete",
        "ledger_event_digest": "d" * 64,
        "marker_path": "2026-08-24.done.json",
        "export_path": "runs/2026-08-24/_exports",
    }
    assert backup._pointer_matches_marker(pointer, marker, state)
    assert not backup._pointer_matches_marker({**pointer, "export_path": "runs/wrong"}, marker, state)


def test_boot_proof_rejects_any_deviation(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    created_at = datetime.now(timezone.utc).isoformat()
    proof = boot_proof(policy, created_at)
    proof["deviations"] = ["skipped storage identity"]
    proof["deviation_authorization"] = {"decision": "conversation"}
    path = tmp_path / "boot-deviation.json"
    path.write_text(json.dumps(proof), encoding="utf-8")
    report = backup.validate_boot_proof(path, policy, datetime.now(timezone.utc))
    assert not report["ok"]
    assert "boot_deviation_not_authorized_by_gate" in report["findings"]


def test_gate_binds_candidate_snapshot_restore_and_boot_proof(monkeypatch, tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    monkeypatch.setattr(backup, "mount_preflight", lambda *_args, **_kwargs: {"ok": True, "findings": [], "mount": {}})
    monkeypatch.setattr(backup, "verify_plan_document", lambda *_args: {"ok": True, "findings": []})
    snapshot_id = "snapshot-1"
    snapshot = policy.backup_dir / "snapshots" / snapshot_id
    snapshot.mkdir(parents=True)
    manifest = snapshot / "manifest.json"
    manifest_payload, restore_checks = write_acceptance_snapshot(
        snapshot, snapshot_id
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    manifest_archive = policy.backup_dir / "manifests" / f"{snapshot_id}.json"
    manifest_archive.parent.mkdir()
    manifest_archive.write_bytes(manifest.read_bytes())
    created_at = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        **policy.plan_identity(),
        "candidate_code_sha": COMMIT,
        "manifest_sha256": policy_module.sha256_file(manifest),
        "result": "PASS",
    }
    receipts = policy.backup_dir / "receipts"
    receipts.mkdir()
    (policy.backup_dir / "latest-backup.json").write_text(json.dumps(receipt), encoding="utf-8")
    (receipts / f"{snapshot_id}.backup.json").write_text(json.dumps(receipt), encoding="utf-8")
    restore = {
        **receipt,
        "restore_acceptance_version": 1,
        "started_at": created_at,
        "completed_at": created_at,
        "operator": "pytest",
        "exact_commands": ["restore-drill"],
        "deviations": [],
        "deviation_authorization": None,
        "checks": restore_checks,
    }
    restore_name = f"{snapshot_id}.restore.attempt.json"
    (receipts / restore_name).write_text(json.dumps(restore), encoding="utf-8")
    (policy.backup_dir / "latest-restore.json").write_text(
        json.dumps({**restore, "receipt_path": f"receipts/{restore_name}"}), encoding="utf-8"
    )
    proof = tmp_path / "boot.json"
    proof.write_text(json.dumps(boot_proof(policy, created_at)), encoding="utf-8")
    monkeypatch.setattr(
        backup,
        "_verify_restored_state",
        lambda _root: {
            "ok": True,
            "findings": [],
            "selected_observation": restore_checks["selected_observation"],
        },
    )
    roots = [tmp_path / name for name in ("repo", "site", "data")]
    for root in roots:
        root.mkdir()
    report = backup.gate(policy, *roots, COMMIT, COMMIT, proof)
    assert report["ok"], report["findings"]
    assert report["result"] == "PASS"


def test_gate_rejects_legacy_restore_receipt_without_acceptance_proof(
    monkeypatch, tmp_path: Path
) -> None:
    policy = make_policy(tmp_path)
    monkeypatch.setattr(
        backup,
        "mount_preflight",
        lambda *_args, **_kwargs: {"ok": True, "findings": [], "mount": {}},
    )
    monkeypatch.setattr(
        backup, "verify_plan_document", lambda *_args: {"ok": True, "findings": []}
    )
    snapshot_id = "legacy-restore"
    snapshot = policy.backup_dir / "snapshots" / snapshot_id
    snapshot.mkdir(parents=True)
    manifest = snapshot / "manifest.json"
    manifest_payload, restore_checks = write_acceptance_snapshot(
        snapshot, snapshot_id
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    manifests = policy.backup_dir / "manifests"
    manifests.mkdir()
    (manifests / f"{snapshot_id}.json").write_bytes(manifest.read_bytes())
    created_at = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        **policy.plan_identity(),
        "candidate_code_sha": COMMIT,
        "manifest_sha256": policy_module.sha256_file(manifest),
        "result": "PASS",
    }
    receipts = policy.backup_dir / "receipts"
    receipts.mkdir()
    (receipts / f"{snapshot_id}.backup.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    (policy.backup_dir / "latest-backup.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    restore_name = f"{snapshot_id}.restore.legacy.json"
    legacy_restore = {**receipt, "checks": {"ok": True}}
    (receipts / restore_name).write_text(
        json.dumps(legacy_restore), encoding="utf-8"
    )
    (policy.backup_dir / "latest-restore.json").write_text(
        json.dumps(
            {**legacy_restore, "receipt_path": f"receipts/{restore_name}"}
        ),
        encoding="utf-8",
    )
    proof = tmp_path / "boot.json"
    proof.write_text(json.dumps(boot_proof(policy, created_at)), encoding="utf-8")
    monkeypatch.setattr(
        backup,
        "_verify_restored_state",
        lambda _root: {
            "ok": True,
            "findings": [],
            "selected_observation": restore_checks["selected_observation"],
        },
    )
    roots = [tmp_path / name for name in ("repo", "site", "data")]
    for root in roots:
        root.mkdir()
    report = backup.gate(policy, *roots, COMMIT, COMMIT, proof)
    assert not report["ok"]
    assert any(
        finding.startswith("restore_schema_invalid:")
        for finding in report["findings"]
    )


def test_gate_blocks_candidate_not_named_by_receipt(monkeypatch, tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    monkeypatch.setattr(backup, "mount_preflight", lambda *_args, **_kwargs: {"ok": True, "findings": [], "mount": {}})
    monkeypatch.setattr(backup, "verify_plan_document", lambda *_args: {"ok": True, "findings": []})
    proof = tmp_path / "boot.json"
    proof.write_text(json.dumps(boot_proof(policy, datetime.now(timezone.utc).isoformat())), encoding="utf-8")
    roots = [tmp_path / name for name in ("repo", "site", "data")]
    for root in roots:
        root.mkdir()
    report = backup.gate(policy, *roots, COMMIT, "d" * 40, proof)
    assert not report["ok"]
    assert "backup_or_restore_receipt_missing_or_invalid" in report["findings"]


def test_deployment_acceptance_is_immutable_schema_valid_and_chained(monkeypatch, tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    snapshot_id = "snapshot-deploy"
    manifest = policy.backup_dir / "snapshots" / snapshot_id / "manifest.json"
    manifest.parent.mkdir(parents=True)
    protected_code_sha = "d" * 40
    manifest_payload, restore_checks = write_acceptance_snapshot(
        manifest.parent, snapshot_id, protected_code_sha
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    manifests = policy.backup_dir / "manifests"
    manifests.mkdir()
    (manifests / f"{snapshot_id}.json").write_bytes(manifest.read_bytes())
    receipts = policy.backup_dir / "receipts"
    receipts.mkdir()
    backup_receipt = {
        "snapshot_id": snapshot_id,
        "manifest_sha256": policy_module.sha256_file(manifest),
        **policy.plan_identity(),
        "result": "PASS",
    }
    (receipts / f"{snapshot_id}.backup.json").write_text(
        json.dumps(backup_receipt), encoding="utf-8"
    )
    (policy.backup_dir / "latest-backup.json").write_text(
        json.dumps(backup_receipt), encoding="utf-8"
    )
    restore_name = f"{snapshot_id}.restore.test.json"
    restore_receipt = {
        "schema_version": 1,
        "restore_acceptance_version": 1,
        "snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "operator": "pytest",
        "manifest_sha256": backup_receipt["manifest_sha256"],
        **policy.plan_identity(),
        "candidate_code_sha": protected_code_sha,
        "exact_commands": ["restore-drill"],
        "deviations": [],
        "deviation_authorization": None,
        "checks": restore_checks,
        "result": "PASS",
    }
    restore_path = receipts / restore_name
    restore_path.write_text(json.dumps(restore_receipt), encoding="utf-8")
    (policy.backup_dir / "latest-restore.json").write_text(
        json.dumps({"receipt_path": f"receipts/{restore_name}"}), encoding="utf-8"
    )
    proof = policy.backup_dir / "boot.json"
    proof.write_text(
        json.dumps(boot_proof(policy, datetime.now(timezone.utc).isoformat())),
        encoding="utf-8",
    )
    binding = {
        "snapshot_id": snapshot_id,
        "backup_receipt_path": f"receipts/{snapshot_id}.backup.json",
        "restore_receipt_path": f"receipts/{restore_name}",
        "manifest_archive_path": f"manifests/{snapshot_id}.json",
        "manifest_sha256": backup_receipt["manifest_sha256"],
        "restore_receipt_sha256": policy_module.sha256_file(restore_path),
        "boot_proof_sha256": policy_module.sha256_file(proof),
    }
    monkeypatch.setattr(
        backup,
        "gate",
        lambda *_args, **_kwargs: {
            "ok": True,
            "findings": [],
            "evidence_binding": binding,
        },
    )
    monkeypatch.setattr(
        backup,
        "git_state",
        lambda _repo: {"clean": True, "commit": COMMIT, "status": []},
    )
    roots = [tmp_path / name for name in ("repo", "site", "data")]
    for root in roots:
        root.mkdir()
    first = backup.record_deployment_acceptance(
        policy, *roots, protected_code_sha, COMMIT, proof, "pytest", ["deploy command"],
        dashboard_verified=True, services_verified=True,
    )
    first_path = Path(str(first["record_path"]))
    schema = json.loads((ROOT / "contracts/pi-deployment-acceptance-v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        json.loads(first_path.read_text())
    )
    (policy.backup_dir / "deployment-records/head.json").unlink()
    (policy.backup_dir / "latest-backup.json").write_text(
        json.dumps({"snapshot_id": "newer-snapshot"}), encoding="utf-8"
    )
    second = backup.record_deployment_acceptance(
        policy, *roots, protected_code_sha, COMMIT, proof, "pytest", ["deploy command"],
        dashboard_verified=True, services_verified=True,
    )
    second_record = json.loads(Path(str(second["record_path"])).read_text())
    assert second_record["previous_record_sha256"] == policy_module.sha256_file(first_path)
    assert second_record["sequence"] == 2
    assert len(list((policy.backup_dir / "deployment-records").glob("*.record.json"))) == 2
    assert all(
        "latest-" not in item["path"]
        for item in second_record["evidence"]
    )
    artifact_paths = [
        Path(item["path"])
        for item in second_record["evidence"]
        if "deployment-evidence" in item["path"] and "artifacts" in item["path"]
    ]
    assert len(artifact_paths) == 1
    original_boot_evidence = policy.backup_dir / "boot-proof.log"
    original_boot_evidence.unlink()
    assert artifact_paths[0].read_text(encoding="utf-8") == "boot proof\n"
    (policy.backup_dir / "deployment-records/head.json").unlink()
    corrupted_evidence = Path(second_record["evidence"][0]["path"])
    os.chmod(corrupted_evidence, 0o644)
    corrupted_evidence.write_text("corrupt\n", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence digest mismatch"):
        deployment_chain.reconcile_deployment_chain(
            policy.backup_dir / "deployment-records", policy
        )


def test_deployment_chain_rejects_dangling_head_symlink(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    records = policy.backup_dir / "deployment-records"
    records.mkdir()
    try:
        (records / "head.json").symlink_to(records / "missing.json")
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")
    with pytest.raises(ValueError, match="head is a symlink"):
        deployment_chain.reconcile_deployment_chain(records, policy)


def test_trusted_rollback_checkout_owns_the_shared_production_lock(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    protected = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()
    (repo / "tracked.txt").write_text("newer\n", encoding="utf-8")
    subprocess.run(("git", "commit", "-qam", "newer"), cwd=repo, check=True)
    data = tmp_path / "data"
    (data / "state").mkdir(parents=True)
    report = ar_local_checkout.rollback_candidate(repo, data, protected)
    assert report["result"] == "ROLLED_BACK"
    assert not (data / "state/daily-ingest.lock").exists()
    assert subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip() == protected


def test_trusted_install_checkout_fetches_only_exact_origin_main(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _git_repo(source)
    origin = tmp_path / "origin.git"
    subprocess.run(("git", "clone", "-q", "--bare", str(source), str(origin)), check=True)
    target = tmp_path / "target"
    subprocess.run(("git", "clone", "-q", str(origin), str(target)), check=True)
    (source / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    subprocess.run(("git", "commit", "-qam", "candidate"), cwd=source, check=True)
    candidate = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=source, text=True, capture_output=True, check=True
    ).stdout.strip()
    subprocess.run(("git", "push", "-q", str(origin), "main"), cwd=source, check=True)
    data = tmp_path / "data"
    (data / "state").mkdir(parents=True)
    report = ar_local_checkout.install_candidate(target, data, candidate)
    assert report["result"] == "PASS"
    assert subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=target, text=True, capture_output=True, check=True
    ).stdout.strip() == candidate
    assert not (data / "state/daily-ingest.lock").exists()


def test_checked_in_runbook_matches_its_controlled_identity(tmp_path: Path) -> None:
    repo = tmp_path / "plan-repo"
    _git_repo(repo)
    document = repo / "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md"
    document.parent.mkdir()
    shutil.copy2(ROOT / "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md", document)
    subprocess.run(("git", "add", "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md"), cwd=repo, check=True)
    subprocess.run(("git", "commit", "-q", "-m", "controlled plan"), cwd=repo, check=True)
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()
    policy = replace(
        make_policy(tmp_path),
        plan_git_commit=commit,
        plan_sha256="510937fc4d09d0e9066c5830fedd80053c9d3c40a062c34c8acce764f1fa8adc",
        plan_raw_sha256=policy_module.sha256_file(document),
    )
    report = backup.verify_plan_document(policy, repo)
    assert report["ok"], report["findings"]
