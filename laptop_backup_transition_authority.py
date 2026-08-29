"""Immutable authority and lexical path gates for the A3 transition harness."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Protocol, Sequence

import laptop_backup_transition_contract as contract
import laptop_pull_backup as receiver


SOURCE_IDENTITY_BASE = "46e2aeba55fe3f97ace4143ba08fc00e36225dc1"


class AuthorityConfig(Protocol):
    target: Path
    recovery_image: Path
    receiver: Path
    old_receiver: Path
    old_task_xml: Path
    candidate_code_sha: str
    old_candidate_code_sha: str
    protected_code_sha: str
    plan_git_commit: str
    plan_sha256: str
    authority_repo: Path
    authority_commit: str
    handoff_sha256: str
    expected_observation_date: str
    operator: str
    principal: str
    python_path: Path
    old_python_path: Path
    task_name: str
    deadline: datetime
    host: str
    accepted_old_xml_sha256: str


def _run(
    command: Sequence[str],
    *,
    binary: bool = False,
    command_log: list[str] | None = None,
) -> str | bytes:
    if command_log is not None:
        command_log.append(subprocess.list2cmdline(tuple(command)))
    completed = subprocess.run(tuple(command), capture_output=True, check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace")
        raise RuntimeError(
            f"native command failed ({completed.returncode}): {subprocess.list2cmdline(tuple(command))}\n{detail}"
        )
    return completed.stdout if binary else completed.stdout.decode("utf-8", errors="strict")


def validate_config(config: AuthorityConfig) -> None:
    for value, label in (
        (config.candidate_code_sha, "candidate code SHA"),
        (config.old_candidate_code_sha, "old candidate code SHA"),
        (config.protected_code_sha, "protected code SHA"),
        (config.plan_git_commit, "plan commit"),
        (config.authority_commit, "authority commit"),
    ):
        contract.require_sha(value, 40, label)
    for value, label in (
        (config.plan_sha256, "plan SHA-256"),
        (config.handoff_sha256, "handoff SHA-256"),
        (config.accepted_old_xml_sha256, "accepted task XML SHA-256"),
    ):
        contract.require_sha(value, 64, label)
    datetime.strptime(config.expected_observation_date, "%Y-%m-%d")
    if config.operator != "jkoka" or config.principal.lower() != r"yanniedog\jkoka":
        raise ValueError("transition operator identity is invalid")
    if config.task_name != "AR-local laptop backup":
        raise ValueError("transition task name is invalid")
    if config.host != "ar-local-pi5-lan":
        raise ValueError("transition host must be the installed task's exact Pi host")
    if config.plan_git_commit != receiver.PLAN_GIT_COMMIT or config.plan_sha256 != receiver.PLAN_SHA256:
        raise ValueError("transition plan identity is not current")
    for path, label in (
        (config.target, "backup target"),
        (config.recovery_image, "recovery image"),
        (config.receiver, "receiver"),
        (config.old_receiver, "old receiver"),
        (config.old_task_xml, "old task XML"),
        (config.authority_repo, "authority checkout"),
        (config.python_path, "Python executable"),
        (config.old_python_path, "old Python executable"),
    ):
        if not path.is_absolute():
            raise ValueError(f"{label} path is unsafe")
        contract.reject_linked_components(path, label)


def validate_evidence_target(config: AuthorityConfig) -> None:
    expected = Path(r"C:\code\backups\AR-local-pi5")
    if os.path.normcase(str(config.target)) != os.path.normcase(str(expected)):
        raise ValueError("transition evidence target is not the controlled backup target")
    contract.reject_linked_components(config.target, "backup target")
    if receiver.canonical_target(config.target) != config.target.resolve(strict=True):
        raise ValueError("backup target identity changed")


def static_preflight(
    config: AuthorityConfig,
    *,
    executing_root: Path,
    require_current_main: bool = True,
    verify_external_old_xml: bool = True,
    command_log: list[str] | None = None,
) -> dict[str, str]:
    validate_config(config)
    if executing_root.resolve(strict=True) != config.receiver.resolve(strict=True):
        raise ValueError("executing transition harness is not the exact receiver checkout")
    authority = verify_git_authority(
        config,
        require_current_main=require_current_main,
        command_log=command_log,
    )
    if receiver.canonical_target(config.target) != config.target.resolve(strict=True):
        raise ValueError("backup target identity changed")
    if config.recovery_image.is_symlink() or not config.recovery_image.resolve(strict=True).is_file():
        raise ValueError("recovery image is unsafe")
    if verify_external_old_xml and (
        contract.sha256_file(config.old_task_xml) != config.accepted_old_xml_sha256
    ):
        raise ValueError("accepted old task XML hash is invalid")
    return authority


def verify_git_authority(
    config: AuthorityConfig,
    *,
    require_current_main: bool,
    command_log: list[str] | None = None,
) -> dict[str, str]:
    if config.authority_repo.is_symlink() or config.receiver.is_symlink():
        raise ValueError("transition checkout path is linked")
    run = lambda command, **kwargs: _run(command, command_log=command_log, **kwargs)
    run(("git", "-C", str(config.authority_repo), "fetch", "origin", "main"))
    origin_main = str(run(("git", "-C", str(config.authority_repo), "rev-parse", "origin/main"))).strip()
    if require_current_main and origin_main != config.authority_commit:
        raise ValueError("origin/main does not match the authorised handoff commit")
    run(("git", "-C", str(config.authority_repo), "cat-file", "-e", f"{config.authority_commit}^{{commit}}"))
    run(("git", "-C", str(config.authority_repo), "merge-base", "--is-ancestor", config.authority_commit, origin_main))
    if str(run(("git", "-C", str(config.authority_repo), "status", "--porcelain=v1"))):
        raise ValueError("authority checkout is dirty")
    handoff = run((
        "git", "-C", str(config.authority_repo), "show",
        f"{config.authority_commit}:docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md",
    ), binary=True)
    assert isinstance(handoff, bytes)
    if contract.sha256_bytes(handoff) != config.handoff_sha256:
        raise ValueError("authorised handoff bytes do not match")
    expected_authorization = {
        "schema_version": 1,
        "plan_document_id": receiver.PLAN_DOCUMENT_ID,
        "plan_version": receiver.PLAN_VERSION,
        "plan_git_commit": config.plan_git_commit,
        "plan_sha256": config.plan_sha256,
        "source_identity_base": SOURCE_IDENTITY_BASE,
        "candidate_code_sha": config.candidate_code_sha,
        "new_receiver": str(config.receiver),
        "old_candidate_code_sha": config.old_candidate_code_sha,
        "old_receiver": str(config.old_receiver),
        "protected_code_sha": config.protected_code_sha,
        "target": str(config.target),
        "recovery_image": str(config.recovery_image),
        "accepted_old_xml_sha256": config.accepted_old_xml_sha256,
        "expected_observation_date": config.expected_observation_date,
        "operator": config.operator,
        "principal": config.principal,
        "task_name": config.task_name,
        "host": config.host,
        "deadline": config.deadline.isoformat(),
    }
    if dict(contract.parse_transition_authorization(handoff)) != expected_authorization:
        raise ValueError("handoff transition authorization does not exactly match the invocation")
    run(("git", "-C", str(config.authority_repo), "merge-base", "--is-ancestor", config.candidate_code_sha, config.authority_commit))
    for root, expected, label in (
        (config.receiver, config.candidate_code_sha, "receiver"),
        (config.old_receiver, config.old_candidate_code_sha, "old receiver"),
    ):
        head = str(run(("git", "-C", str(root), "rev-parse", "HEAD"))).strip()
        if head != expected:
            raise ValueError(f"{label} is not at the exact candidate")
        if str(run(("git", "-C", str(root), "status", "--porcelain=v1"))):
            raise ValueError(f"{label} checkout is dirty")
    return {
        "authority_commit": config.authority_commit,
        "origin_main": origin_main,
        "handoff_sha256": config.handoff_sha256,
    }
