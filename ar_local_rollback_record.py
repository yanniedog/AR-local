"""Append-only acceptance evidence for a verified production rollback."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ar_local_backup_policy import (
    BackupPolicy,
    COMMIT_RE,
    atomic_create_json,
    mount_preflight,
    sha256_file,
    utc_now,
)
from ar_local_checkout import git_state
from ar_local_operation_lock import production_lock

ROLLBACK_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "contracts/pi-rollback-acceptance-v1.schema.json"
)


def _confined_directory(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.resolve() != path or not path.resolve().is_relative_to(root):
        raise ValueError(f"rollback {name} directory is not confined to backup storage")
    return path


def record_rollback_acceptance(
    policy: BackupPolicy,
    repo: Path,
    site_repo: Path,
    data_root: Path,
    protected_code_sha: str,
    candidate_sha: str,
    operator: str,
    exact_commands: list[str],
    *,
    services_verified: bool,
    dashboard_verified: bool,
) -> dict[str, object]:
    """Persist a create-once rollback record only after runtime verification."""

    if not COMMIT_RE.fullmatch(protected_code_sha) or not COMMIT_RE.fullmatch(candidate_sha):
        raise ValueError("rollback code SHA is invalid")
    if not operator or not exact_commands:
        raise ValueError("rollback operator and exact commands are required")
    if not services_verified or not dashboard_verified:
        raise ValueError("rollback services and dashboard must be verified")
    started_at = utc_now()
    repo = repo.resolve(strict=True)
    site_repo = site_repo.resolve(strict=True)
    data_root = data_root.resolve(strict=True)
    with production_lock(data_root / "state/daily-ingest.lock", "rollback-record"):
        mount = mount_preflight(policy, (repo, site_repo, data_root), perform_probe=False)
        if not mount["ok"]:
            raise ValueError(f"backup mount failed before rollback acceptance: {mount['findings']}")
        root = policy.backup_dir.resolve(strict=True)
        records = _confined_directory(root, "rollback-records")
        evidence_root = _confined_directory(root, "rollback-evidence")
        repository = git_state(repo)
        if not repository["clean"] or repository["commit"] != protected_code_sha:
            raise ValueError("rollback checkout is not the exact clean protected commit")
        if not mount_preflight(policy, (repo, site_repo, data_root), perform_probe=False)["ok"]:
            raise ValueError("backup mount changed before rollback acceptance")
        record, record_path = _write_record(
            policy, records, evidence_root, repository, protected_code_sha,
            candidate_sha, operator, exact_commands, started_at, (repo, site_repo, data_root),
        )
    return {**record, "record_path": str(record_path), "record_sha256": sha256_file(record_path)}


def _write_record(
    policy: BackupPolicy,
    records: Path,
    evidence_root: Path,
    repository: dict[str, object],
    protected_code_sha: str,
    candidate_sha: str,
    operator: str,
    exact_commands: list[str],
    started_at: str,
    mount_roots: tuple[Path, Path, Path],
) -> tuple[dict[str, object], Path]:
    with production_lock(records / ".record.lock", "rollback-record-chain"):
        if not mount_preflight(policy, mount_roots, perform_probe=False)["ok"]:
            raise ValueError("backup mount changed before rollback evidence write")
        record_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
            + uuid.uuid4().hex
            + f"-{candidate_sha}-to-{protected_code_sha}"
        )
        checks = {
            "clean_protected_checkout": "PASS",
            "services": "PASS",
            "dashboard": "PASS",
        }
        evidence_path = evidence_root / f"{record_id}.json"
        atomic_create_json(
            evidence_path,
            {
                **policy.plan_identity(),
                "protected_code_sha": protected_code_sha,
                "candidate_code_sha": candidate_sha,
                "operator": operator,
                "created_at": utc_now(),
                "exact_commands": exact_commands,
                "repository": repository,
                "checks": checks,
                "result": "ROLLED_BACK",
            },
        )
        record: dict[str, object] = {
            "schema_version": 1,
            **policy.plan_identity(),
            "protected_code_sha": protected_code_sha,
            "candidate_code_sha": candidate_sha,
            "operator": operator,
            "started_at": started_at,
            "completed_at": utc_now(),
            "exact_commands": exact_commands,
            "evidence": [{"path": str(evidence_path), "sha256": sha256_file(evidence_path)}],
            "checks": checks,
            "deviations": [],
            "deviation_authorization": None,
            "result": "ROLLED_BACK",
        }
        schema = json.loads(ROLLBACK_SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            raise ValueError(f"rollback record schema is invalid: {errors[0].message}")
        if not mount_preflight(policy, mount_roots, perform_probe=False)["ok"]:
            raise ValueError("backup mount changed before rollback record write")
        record_path = records / f"{record_id}.record.json"
        atomic_create_json(record_path, record)
    return record, record_path
