from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

import laptop_backup_scheduled as scheduled
import laptop_backup_scheduled_lineage as lineage
import laptop_backup_transition_contract as contract
import laptop_pull_backup as receiver
from test_laptop_backup_transition_flow import config, execution_record


def _args() -> Namespace:
    return Namespace(
        plan_git_commit=receiver.PLAN_GIT_COMMIT,
        candidate_code_sha="c" * 40,
        protected_code_sha="9" * 40,
        operator="pytest",
        allowed_predecessor_candidate_sha=[],
    )


def test_pointed_forged_predecessor_is_rejected_before_lineage_preparation(tmp_path: Path) -> None:
    target = tmp_path / "backup"
    root = target / "catalog/scheduled-runs"
    root.mkdir(parents=True)
    forged = execution_record("NO_BACKUP_DATA_WRITE")
    forged["operator"] = "attacker"
    path = root / "forged.json"
    path.write_bytes(receiver.canonical_json_bytes(forged))
    (target / "catalog/latest-scheduled.json").write_bytes(receiver.canonical_json_bytes({
        "record_path": path.relative_to(target).as_posix(),
        "record_sha256": receiver.sha256_file(path),
        "result": "PASS",
    }))

    with pytest.raises(ValueError, match="identity is invalid"):
        scheduled.prepare_execution_lineage(target, _args())


def test_authenticated_transition_may_accept_exact_old_candidate_predecessor(tmp_path: Path) -> None:
    target = tmp_path / "backup"
    root = target / "catalog/scheduled-runs"
    root.mkdir(parents=True)
    old = execution_record("NO_BACKUP_DATA_WRITE")
    old["candidate_code_sha"] = "d" * 40
    path = root / "old.json"
    path.write_bytes(receiver.canonical_json_bytes(old))
    (target / "catalog/latest-scheduled.json").write_bytes(receiver.canonical_json_bytes({
        "record_path": path.relative_to(target).as_posix(),
        "record_sha256": receiver.sha256_file(path),
        "result": "PASS",
    }))
    args = _args()
    args.operator = "jkoka"
    args.allowed_predecessor_candidate_sha = ["d" * 40]

    scheduled.prepare_execution_lineage(target, args)


def test_dangling_mutex_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "backup"
    catalog = target / "catalog"
    catalog.mkdir(parents=True)
    mutex = catalog / ".scheduled-record.mutex"
    try:
        mutex.symlink_to(tmp_path / "missing-lock-target")
    except OSError:
        pytest.skip("host cannot create an unprivileged symlink")

    with pytest.raises(ValueError, match="link or reparse"):
        with lineage.scheduled_record_mutex(target):
            pass
    assert not (tmp_path / "missing-lock-target").exists()


def test_reconciliation_accepts_legacy_anchor_with_live_linked_child(tmp_path: Path) -> None:
    value = config(tmp_path)
    baseline = (value.target / "catalog/latest-scheduled.json").read_bytes()
    root = value.target / "catalog/scheduled-runs"
    legacy_value = execution_record("NO_BACKUP_DATA_WRITE")
    legacy_value["candidate_code_sha"] = value.old_candidate_code_sha
    legacy = root / "legacy.json"
    legacy.write_bytes(contract.canonical_json(legacy_value))
    child_value = execution_record("BACKUP-LATEST")
    child_value["previous_execution"] = {
        "record_path": legacy.relative_to(value.target).as_posix(),
        "record_sha256": contract.sha256_file(legacy),
    }
    child = root / "child.json"
    child.write_bytes(contract.canonical_json(child_value))
    live = contract.canonical_json({
        "record_path": child.relative_to(value.target).as_posix(),
        "record_sha256": contract.sha256_file(child),
        "result": "PASS",
    })
    records = {
        path.relative_to(value.target).as_posix(): contract.sha256_file(path)
        for path in (legacy, child)
    }

    result = contract.reconcile_scheduled_pointer(
        value.target, baseline, live, records,
        old_candidate_sha=value.old_candidate_code_sha, apply=False,
    )

    assert result["ordered_appended_records"] == [
        legacy.relative_to(value.target).as_posix(),
        child.relative_to(value.target).as_posix(),
    ]
    assert result["latest_record"] == child.relative_to(value.target).as_posix()


def test_reconciliation_rejects_live_pointer_digest_mismatch(tmp_path: Path) -> None:
    value = config(tmp_path)
    baseline = (value.target / "catalog/latest-scheduled.json").read_bytes()
    root = value.target / "catalog/scheduled-runs"
    legacy_value = execution_record("NO_BACKUP_DATA_WRITE")
    legacy_value["candidate_code_sha"] = value.old_candidate_code_sha
    legacy = root / "legacy.json"
    legacy.write_bytes(contract.canonical_json(legacy_value))
    child_value = execution_record("BACKUP-LATEST")
    child_value["previous_execution"] = {
        "record_path": legacy.relative_to(value.target).as_posix(),
        "record_sha256": contract.sha256_file(legacy),
    }
    child = root / "child.json"
    child.write_bytes(contract.canonical_json(child_value))
    live = contract.canonical_json({
        "record_path": child.relative_to(value.target).as_posix(),
        "record_sha256": "f" * 64,
        "result": "PASS",
    })
    records = {
        path.relative_to(value.target).as_posix(): contract.sha256_file(path)
        for path in (legacy, child)
    }

    with pytest.raises(
        ValueError,
        match="scheduled execution pointer hash is invalid|not bound to the live pointer",
    ):
        contract.reconcile_scheduled_pointer(
            value.target, baseline, live, records,
            old_candidate_sha=value.old_candidate_code_sha, apply=False,
        )
