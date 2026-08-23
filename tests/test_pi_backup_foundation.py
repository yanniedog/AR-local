"""Fail-closed tests for the Pi backup and restoration foundation."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ar_local_backup_policy as policy_module  # noqa: E402
import pi_backup_foundation as backup  # noqa: E402
import cdr_outputs  # noqa: E402

COMMIT = "a" * 40
DIGEST = "b" * 64


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


def test_immutable_json_record_cannot_be_rewritten(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    policy_module.atomic_create_json(target, {"result": "PASS"})
    with pytest.raises(FileExistsError):
        policy_module.atomic_create_json(target, {"result": "FAIL"})
    assert json.loads(target.read_text())["result"] == "PASS"


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
    manifest = {
        "files": [{"path": "artifact.bin", "size": 4, "sha256": policy_module.sha256_file(artifact)}]
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert backup.verify_snapshot(snapshot)["ok"]
    artifact.write_bytes(b"evil")
    report = backup.verify_snapshot(snapshot)
    assert not report["ok"]
    assert report["findings"] == ["changed:artifact.bin"]


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
    assert report["findings"] == ["invalid_entry:0"]


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
    macro = repo / "state/local-macro.sqlite"
    macro.parent.mkdir()
    with sqlite3.connect(macro) as connection:
        connection.execute("CREATE TABLE series_observations(id INTEGER)")
        connection.execute("CREATE TABLE ingest_runs(id INTEGER)")
        connection.execute("INSERT INTO series_observations VALUES (1)")
    monkeypatch.setattr(backup, "mount_preflight", lambda *_args, **_kwargs: {"ok": True, "findings": [], "mount": {}})
    monkeypatch.setattr(backup, "verify_plan_document", lambda *_args: {"ok": True, "findings": []})
    receipt = backup.create_snapshot(policy, repo, site, data, macro, "pytest")
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
        backup._run(("powershell", "Get-ChildItem"), tmp_path)


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
        json.dumps({"candidate_code_sha": COMMIT, "files": files}), encoding="utf-8"
    )
    monkeypatch.setattr(backup, "_verify_restored_state", lambda _root: {"ok": True, "findings": []})
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    receipt = backup.restore_drill(policy, snapshot_id, scratch, "pytest")
    assert receipt["result"] == "PASS", receipt["checks"]
    assert receipt["scratch_retained"] is False
    assert list(scratch.iterdir()) == []


def test_gate_binds_candidate_snapshot_restore_and_boot_proof(monkeypatch, tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    monkeypatch.setattr(backup, "mount_preflight", lambda *_args, **_kwargs: {"ok": True, "findings": [], "mount": {}})
    monkeypatch.setattr(backup, "verify_plan_document", lambda *_args: {"ok": True, "findings": []})
    snapshot_id = "snapshot-1"
    snapshot = policy.backup_dir / "snapshots" / snapshot_id
    snapshot.mkdir(parents=True)
    manifest = snapshot / "manifest.json"
    manifest.write_text('{"files":[]}\n', encoding="utf-8")
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
    restore = {**receipt, "checks": {"ok": True}}
    restore_name = f"{snapshot_id}.restore.attempt.json"
    (receipts / restore_name).write_text(json.dumps(restore), encoding="utf-8")
    (policy.backup_dir / "latest-restore.json").write_text(
        json.dumps({**restore, "receipt_path": f"receipts/{restore_name}"}), encoding="utf-8"
    )
    proof = tmp_path / "boot.json"
    proof.write_text(json.dumps(boot_proof(policy, created_at)), encoding="utf-8")
    roots = [tmp_path / name for name in ("repo", "site", "data")]
    for root in roots:
        root.mkdir()
    report = backup.gate(policy, *roots, COMMIT, COMMIT, proof)
    assert report["ok"], report["findings"]
    assert report["result"] == "PASS"


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
    manifest.write_text("{}\n", encoding="utf-8")
    (policy.backup_dir / "latest-backup.json").write_text(
        json.dumps({"snapshot_id": snapshot_id}), encoding="utf-8"
    )
    (policy.backup_dir / "latest-restore.json").write_text("{}\n", encoding="utf-8")
    proof = policy.backup_dir / "boot.json"
    proof.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(backup, "gate", lambda *_args, **_kwargs: {"ok": True, "findings": []})
    monkeypatch.setattr(
        backup,
        "git_state",
        lambda _repo: {"clean": True, "commit": COMMIT, "status": []},
    )
    roots = [tmp_path / name for name in ("repo", "site", "data")]
    for root in roots:
        root.mkdir()
    first = backup.record_deployment_acceptance(
        policy, *roots, "d" * 40, COMMIT, proof, "pytest", ["deploy command"],
        dashboard_verified=True, services_verified=True,
    )
    first_path = Path(str(first["record_path"]))
    schema = json.loads((ROOT / "contracts/pi-deployment-acceptance-v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        json.loads(first_path.read_text())
    )
    second = backup.record_deployment_acceptance(
        policy, *roots, "d" * 40, COMMIT, proof, "pytest", ["deploy command"],
        dashboard_verified=True, services_verified=True,
    )
    second_record = json.loads(Path(str(second["record_path"])).read_text())
    assert second_record["previous_record_sha256"] == policy_module.sha256_file(first_path)
    assert len(list((policy.backup_dir / "deployment-records").glob("*.json"))) == 2


def test_checked_in_runbook_matches_its_controlled_identity(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    object.__setattr__(policy, "plan_git_commit", "4a3af1ccbdc24deefe3d12da2f7152946984f459")
    object.__setattr__(policy, "plan_sha256", "510937fc4d09d0e9066c5830fedd80053c9d3c40a062c34c8acce764f1fa8adc")
    object.__setattr__(
        policy,
        "plan_raw_sha256",
        policy_module.sha256_file(ROOT / "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md"),
    )
    report = backup.verify_plan_document(policy, ROOT)
    assert report["ok"], report["findings"]
