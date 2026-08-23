"""Trusted exact-commit checkout operations protected by the production ingest lock."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from ar_local_backup_policy import COMMIT_RE, utc_now
from ar_local_operation_lock import production_lock


def _git(repo: Path, arguments: Sequence[str]) -> str:
    # The executable is fixed, shell use is disabled, and every commit argument is validated.
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    result = subprocess.run(
        ("git", *arguments),
        cwd=repo,
        text=True,
        capture_output=True,
        timeout=300,
        shell=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "trusted Git operation failed")
    return result.stdout.strip()


def _assert_clean(repo: Path) -> None:
    if _git(repo, ("status", "--porcelain")):
        raise RuntimeError("production checkout is dirty")


def install_candidate(repo: Path, data_root: Path, candidate_sha: str) -> dict[str, object]:
    """Fetch and fast-forward production main to one exact origin/main commit."""

    if not COMMIT_RE.fullmatch(candidate_sha):
        raise ValueError("candidate SHA is invalid")
    repo = repo.resolve(strict=True)
    lock = data_root.resolve(strict=True) / "state/daily-ingest.lock"
    with production_lock(lock, "deploy"):
        _assert_clean(repo)
        _git(repo, ("fetch", "origin", "main"))
        if _git(repo, ("rev-parse", "origin/main")) != candidate_sha:
            raise RuntimeError("fetched origin/main does not match the approved candidate")
        _git(repo, ("checkout", "main"))
        _git(repo, ("merge", "--ff-only", candidate_sha))
        _assert_clean(repo)
        if _git(repo, ("rev-parse", "HEAD")) != candidate_sha:
            raise RuntimeError("production checkout did not reach the approved candidate")
    return {"ok": True, "result": "PASS", "candidate_code_sha": candidate_sha, "completed_at": utc_now()}


def rollback_candidate(repo: Path, data_root: Path, protected_sha: str) -> dict[str, object]:
    """Detach production at the verified pre-deployment commit under the same lock."""

    if not COMMIT_RE.fullmatch(protected_sha):
        raise ValueError("protected SHA is invalid")
    repo = repo.resolve(strict=True)
    lock = data_root.resolve(strict=True) / "state/daily-ingest.lock"
    with production_lock(lock, "rollback"):
        _assert_clean(repo)
        _git(repo, ("cat-file", "-e", f"{protected_sha}^{{commit}}"))
        _git(repo, ("checkout", "--detach", protected_sha))
        _assert_clean(repo)
        if _git(repo, ("rev-parse", "HEAD")) != protected_sha:
            raise RuntimeError("rollback checkout did not reach the protected commit")
    return {"ok": True, "result": "ROLLED_BACK", "candidate_code_sha": protected_sha, "completed_at": utc_now()}
