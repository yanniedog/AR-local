"""Sync GitHub main and run the Raspberry Pi daily CDR ingest."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ar_local_launcher_constants import DAILY_WORKER_COUNT

REPO_ROOT = Path(__file__).resolve().parent
AR_SITE_REPO = REPO_ROOT.parent / "australianrates"
AR_SITE_URL = "https://github.com/yanniedog/australianrates.git"


def run(argv: list[str], cwd: Path | None = None) -> None:
    subprocess.run(argv, cwd=str(cwd) if cwd else None, check=True, shell=False)


def sync_existing_repo(repo: Path, remote_url: str) -> None:
    if not (repo / ".git").is_dir():
        run(["git", "clone", remote_url, str(repo)])
    run(["git", "fetch", "origin"], cwd=repo)
    run(["git", "checkout", "main"], cwd=repo)
    run(["git", "pull", "--ff-only", "origin", "main"], cwd=repo)


def assert_clean(repo: Path) -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    ).stdout.strip()
    if status:
        raise RuntimeError(f"{repo} has local changes; refusing automated pull")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync GitHub main and run Pi daily ingest.")
    parser.add_argument(
        "--skip-git-sync",
        action="store_true",
        help="Run ingest without pulling AR-local or AustralianRates first.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.skip_git_sync:
        assert_clean(REPO_ROOT)
        sync_existing_repo(REPO_ROOT, "https://github.com/yanniedog/AR-local.git")
        sync_existing_repo(AR_SITE_REPO, AR_SITE_URL)
    run(
        [
            sys.executable,
            str(REPO_ROOT / "cdr_daily.py"),
            "--workers",
            str(DAILY_WORKER_COUNT),
        ],
        cwd=REPO_ROOT,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
