"""Sync GitHub main and run the Raspberry Pi daily CDR ingest."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from ar_local_launcher_constants import DAILY_WORKER_COUNT
from ar_local_pi_runtime import data_state_root, ensure_runtime_data_writable
from ar_local_subprocess import run_checked

REPO_ROOT = Path(__file__).resolve().parent
AR_SITE_REPO = REPO_ROOT.parent / "australianrates"
AR_SITE_URL = "https://github.com/yanniedog/australianrates.git"
LOCK_STALE_SECONDS = 6 * 60 * 60
GIT_TIMEOUT_SEC = 30


class DailyIngestLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None

    def _owner_pid(self) -> int | None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return None
        for line in text.splitlines():
            if not line.startswith("pid="):
                continue
            try:
                return int(line.removeprefix("pid=").strip())
            except ValueError:
                return None
        return None

    def _pid_is_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def __enter__(self) -> "DailyIngestLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                age = 0
            owner_pid = self._owner_pid()
            owner_alive = bool(owner_pid and self._pid_is_alive(owner_pid))
            if (owner_pid and not owner_alive) or (age > LOCK_STALE_SECONDS and not owner_alive):
                self.path.unlink(missing_ok=True)
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            else:
                raise RuntimeError(f"daily ingest already running: {self.path}")
        os.write(self.fd, f"pid={os.getpid()}\n".encode("utf-8"))
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.path.unlink(missing_ok=True)


def run_git(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, check=True, shell=False)


def _app_payload_enabled() -> bool:
    return os.environ.get("AR_LOCAL_APP_PAYLOAD", "").strip().lower() in ("1", "true", "yes", "on")


def maybe_publish_app_payload(repo_root: Path) -> None:
    """Build + publish the mobile-app payload after a successful ingest.

    Opt-in (AR_LOCAL_APP_PAYLOAD=1) and strictly non-fatal: a publish failure must
    never fail the daily ingest. Publishing itself is token-gated inside
    app_payload (no GH_TOKEN -> builds locally and skips the upload).
    """
    if not _app_payload_enabled():
        return
    try:
        from ar_local_pi_runtime import data_runs_root, latest_exports_root
        import app_payload

        exports = latest_exports_root(data_runs_root(repo_root))
        if exports is None:
            print("[pi_daily_sync] app_payload skipped reason=no_valid_exports")
            return
        print(f"[pi_daily_sync] app_payload publish starting exports={exports}")
        manifest, published_dated, published_latest = app_payload.build_and_publish_dual(exports)
        run_date = str(manifest.get("run_date") or "")
        dated_tag = app_payload.dated_tag(run_date)
        core_name = manifest.get("files", {}).get("core", {}).get("name", "")
        details_name = manifest.get("files", {}).get("details", {}).get("name", "")
        state = "published" if (published_dated or published_latest) else "built_or_skipped"
        print(
            f"[pi_daily_sync] app_payload publish finished run_date={run_date} "
            f"dated_tag={dated_tag} published_dated={published_dated} "
            f"published_latest={published_latest} state={state} "
            f"core={core_name} details={details_name} exit=0"
        )
        if published_dated or published_latest:
            try:
                runs_root = data_runs_root(repo_root)
                app_payload.refresh_dates_index(runs_root)
            except Exception as idx_exc:  # noqa: BLE001 - index is informational
                print(
                    f"[pi_daily_sync] app_payload dates-index refresh failed "
                    f"(non-fatal) error={idx_exc!r}"
                )
    except Exception as exc:  # noqa: BLE001 - never fail the ingest on payload errors
        print(f"[pi_daily_sync] app_payload publish failed (non-fatal) error={exc!r} exit=0")


def sync_existing_repo(repo: Path, remote_url: str) -> None:
    if not (repo / ".git").is_dir():
        run_git(["clone", remote_url, str(repo)])
    run_git(["fetch", "origin"], cwd=repo)
    run_git(["checkout", "main"], cwd=repo)
    run_git(["pull", "--ff-only", "origin", "main"], cwd=repo)


def discard_eol_only_changes(repo: Path) -> bool:
    """Reset tracked files that differ only by CRLF vs LF (common after Windows edits on Pi)."""
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        shell=False,
        timeout=GIT_TIMEOUT_SEC,
    ).stdout.strip()
    if not status:
        return False
    for line in status.splitlines():
        if len(line) < 2:
            continue
        staged, unstaged = line[0], line[1]
        if staged == "?" and unstaged == "?":
            return False
        if staged not in (" ", "?"):
            return False
    has_unstaged_tracked = subprocess.run(
        ["git", "diff", "--quiet"],
        cwd=str(repo),
        check=False,
        shell=False,
        timeout=GIT_TIMEOUT_SEC,
    ).returncode != 0
    if not has_unstaged_tracked:
        return False
    eol_only = subprocess.run(
        ["git", "diff", "--ignore-cr-at-eol", "--quiet"],
        cwd=str(repo),
        check=False,
        shell=False,
        timeout=GIT_TIMEOUT_SEC,
    ).returncode == 0
    if not eol_only:
        return False
    subprocess.run(
        ["git", "checkout", "--", "."],
        cwd=str(repo),
        check=True,
        shell=False,
        timeout=GIT_TIMEOUT_SEC,
    )
    remaining = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        shell=False,
        timeout=GIT_TIMEOUT_SEC,
    ).stdout.strip()
    if remaining:
        return False

    print(f"[pi_daily_sync] discarded line-ending-only local changes in {repo}")
    return True


def assert_clean(repo: Path) -> None:
    if discard_eol_only_changes(repo):
        return
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


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync GitHub main and run Pi daily ingest.")
    parser.add_argument(
        "--skip-git-sync",
        action="store_true",
        help="Run ingest without pulling AR-local or AustralianRates first.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Forward --force to cdr_daily.py, ignoring today's completion marker.",
    )
    parser.add_argument("--date", default="", help="Run date YYYY-MM-DD; defaults to cdr_daily.py local date.")
    parser.add_argument("--banks-only", action="store_true", help="Run the daily banking ingest only.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    ensure_runtime_data_writable(REPO_ROOT)
    lock_path = data_state_root(REPO_ROOT) / "daily-ingest.lock"
    try:
        lock_context = DailyIngestLock(lock_path)
        with lock_context:
            if not args.skip_git_sync:
                assert_clean(REPO_ROOT)
                if (AR_SITE_REPO / ".git").is_dir():
                    assert_clean(AR_SITE_REPO)
                sync_existing_repo(REPO_ROOT, "https://github.com/yanniedog/AR-local.git")
                sync_existing_repo(AR_SITE_REPO, AR_SITE_URL)
            sector_args: list[str] = []
            if args.banks_only:
                sector_args = ["--banks-only"]
            force_args = ["--force"] if args.force else []
            date_args = ["--date", args.date] if args.date else []
            run_checked(
                [
                    sys.executable,
                    str(REPO_ROOT / "cdr_daily.py"),
                    "--workers",
                    str(DAILY_WORKER_COUNT),
                    *sector_args,
                    *force_args,
                    *date_args,
                ],
                cwd=REPO_ROOT,
            )
            maybe_publish_app_payload(REPO_ROOT)
    except RuntimeError as exc:
        if "daily ingest already running" in str(exc):
            print(f"pi_daily_sync: {exc}")
            return 0
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
