"""Sync GitHub main and run the Raspberry Pi daily CDR ingest."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from ar_local_launcher_constants import DAILY_WORKER_COUNT
from ar_local_pi_runtime import data_state_root, ensure_runtime_data_writable
from ar_local_subprocess import run_checked
from cdr_finalization import verify_completion_marker
from cdr_macro_ingest import DEFAULT_STORE_PATH as DEFAULT_MACRO_STORE_PATH

REPO_ROOT = Path(__file__).resolve().parent
AR_SITE_REPO = REPO_ROOT.parent / "australianrates"
AR_SITE_URL = "https://github.com/yanniedog/australianrates.git"
LOCK_STALE_SECONDS = 6 * 60 * 60
GIT_TIMEOUT_SEC = 30
PENDING_PAYLOAD_FILENAME = "app-payload-publication-pending.json"


def v2_publication_allowed() -> bool:
    """V2 is plaintext-only today; preserve ciphertext-only mode when enabled."""
    return (os.environ.get("AR_LOCAL_PAYLOAD_ENC") or "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }


def prune_payload_staging(out_dir: Path, manifest_name: str) -> int:
    """Remove stale staged assets while retaining the current manifest contract."""
    manifest_path = out_dir / manifest_name
    if not manifest_path.is_file():
        return 0
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files") or {}
        keep = {manifest_name}
        keep.update(
            str(entry.get("name"))
            for entry in files.values()
            if isinstance(entry, dict) and entry.get("name")
        )
    except (OSError, ValueError, TypeError):
        return 0
    removed = 0
    for path in out_dir.iterdir():
        if path.is_file() and path.name not in keep:
            path.unlink()
            removed += 1
    return removed


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
    subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        shell=False,
        timeout=GIT_TIMEOUT_SEC,
    )


def _app_payload_enabled() -> bool:
    return os.environ.get("AR_LOCAL_APP_PAYLOAD", "").strip().lower() in ("1", "true", "yes", "on")


def _same_payload_revision(left: dict, right: dict) -> bool:
    if str(left.get("run_date") or "") != str(right.get("run_date") or ""):
        return False
    left_files = left.get("files") or {}
    right_files = right.get("files") or {}
    return all(
        str((left_files.get(kind) or {}).get("sha256") or "")
        and str((left_files.get(kind) or {}).get("sha256") or "")
        == str((right_files.get(kind) or {}).get("sha256") or "")
        for kind in ("core", "details")
    )


def payload_publication_pending_path(repo_root: Path) -> Path:
    return data_state_root(repo_root) / PENDING_PAYLOAD_FILENAME


def payload_publication_pending(repo_root: Path) -> bool:
    return payload_publication_pending_path(repo_root).is_file()


def mark_payload_publication_pending(repo_root: Path, reason: str) -> None:
    path = payload_publication_pending_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "reason": str(reason),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def clear_payload_publication_pending(repo_root: Path) -> None:
    payload_publication_pending_path(repo_root).unlink(missing_ok=True)


def _read_observation_pointer(state_dir: Path, name: str) -> dict:
    path = state_dir / "observation-pointers-v2" / name
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _exports_from_pointer(state_dir: Path, pointer: dict) -> Optional[Path]:
    relative = str(pointer.get("export_path") or "")
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        return None
    data_root = state_dir.parent.resolve()
    candidate = (data_root / relative).resolve()
    try:
        candidate.relative_to(data_root)
    except ValueError:
        return None
    return candidate if candidate.is_dir() else None


def maybe_publish_app_payload(repo_root: Path) -> bool:
    """Build + publish the mobile-app payload after a successful ingest.

    Opt-in (AR_LOCAL_APP_PAYLOAD=1) and strictly non-fatal: a publish failure must
    never fail the daily ingest. Publishing itself is token-gated inside
    app_payload (no GH_TOKEN -> builds locally and skips the upload).
    """
    if not _app_payload_enabled():
        return True
    try:
        from ar_local_pi_runtime import data_runs_root, latest_exports_root
        import app_payload

        runtime_state = data_state_root(repo_root)
        latest_observation = _read_observation_pointer(
            runtime_state, "latest-observation.json"
        )
        if latest_observation.get("observation_state") == "partial":
            print(
                "[pi_daily_sync] app_payload promotion withheld "
                f"run_date={latest_observation.get('observation_date', 'unknown')} "
                "observation_state=partial"
            )
            return True
        latest_complete = _read_observation_pointer(runtime_state, "latest-complete.json")
        exports = _exports_from_pointer(runtime_state, latest_complete)
        pointer_selected = exports is not None
        if exports is None:
            exports = latest_exports_root(data_runs_root(repo_root))
        if exports is None:
            print("[pi_daily_sync] app_payload skipped reason=no_valid_exports")
            return False
        observation_date = str(latest_complete.get("observation_date") or "")
        marker_relative = str(latest_complete.get("marker_path") or "")
        if pointer_selected:
            marker_part = Path(marker_relative)
            if (
                latest_complete.get("observation_state") != "complete"
                or not marker_relative
                or marker_part.is_absolute()
                or ".." in marker_part.parts
            ):
                print(
                    "[pi_daily_sync] app_payload promotion withheld "
                    "reason=invalid_latest_complete_pointer"
                )
                return True
            completion_marker = runtime_state / marker_part
        else:
            observation_date = exports.parent.name
            completion_marker = runtime_state / f"{observation_date}.done.json"
        try:
            completion = json.loads(completion_marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            completion = {}
        if pointer_selected and not verify_completion_marker(
            completion, runtime_state, observation_date
        ):
            print(
                "[pi_daily_sync] app_payload promotion withheld "
                f"run_date={observation_date or 'unknown'} "
                "reason=unverified_completion_marker"
            )
            return True
        if (
            completion.get("finalization_schema_version") == 2
            and completion.get("observation_state") != "complete"
        ):
            print(
                "[pi_daily_sync] app_payload promotion withheld "
                f"run_date={observation_date} "
                f"observation_state={completion.get('observation_state', 'unknown')}"
            )
            # Withholding an incomplete candidate is a successful policy outcome,
            # not a publication failure that the watchdog should retry forever.
            return True
        payload_state = runtime_state / "app-payload"
        print(f"[pi_daily_sync] app_payload publish starting exports={exports}")
        manifest, published_dated, published_latest = app_payload.build_and_publish_dual(
            exports, state_dir=payload_state / "v1"
        )
        pruned_v1 = sum(
            prune_payload_staging(payload_state / "v1" / folder, "manifest.json")
            for folder in ("v1-dated", "v1-latest")
        )
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
            f" pruned_local_assets={pruned_v1}"
        )
        v2_eligible = published_latest
        if not v2_eligible:
            try:
                live_status, live_v1 = app_payload._live_manifest_status(
                    app_payload.DEFAULT_REPO, app_payload.DEFAULT_TAG
                )
                v2_eligible = (
                    live_status == "present"
                    and live_v1 is not None
                    and _same_payload_revision(manifest, live_v1)
                )
            except Exception as live_exc:  # noqa: BLE001 - optional sidecar check
                print(
                    "[pi_daily_sync] app_payload v2 skipped "
                    f"reason=v1_revision_check_failed error={live_exc!r}"
                )
        if v2_eligible and not v2_publication_allowed():
            print(
                "[pi_daily_sync] app_payload v2 skipped "
                "reason=payload_encryption_enabled_plaintext_v2_forbidden"
            )
        elif v2_eligible:
            try:
                v2_manifest, published_v2 = app_payload.build_and_publish_v2(
                    exports,
                    v1_manifest=manifest,
                    out_dir=payload_state / "v2",
                    economic_store_path=DEFAULT_MACRO_STORE_PATH,
                )
                pruned_v2 = prune_payload_staging(
                    payload_state / "v2", app_payload.V2_MANIFEST_FILENAME
                )
                print(
                    "[pi_daily_sync] app_payload v2 finished "
                    f"run_date={v2_manifest.get('run_date', '')} "
                    f"capabilities={v2_manifest.get('capabilities', [])} "
                    f"published={published_v2} pruned_local_assets={pruned_v2} exit=0"
                )
            except Exception as v2_exc:  # noqa: BLE001 - v1 is already complete
                print(
                    "[pi_daily_sync] app_payload v2 failed "
                    f"(non-fatal; v1 preserved) error={v2_exc!r} exit=0"
                )
        if published_dated or published_latest:
            try:
                runs_root = data_runs_root(repo_root)
                app_payload.refresh_dates_index(
                    runs_root, out_dir=payload_state / "v1-dates-index"
                )
            except Exception as idx_exc:  # noqa: BLE001 - index is informational
                print(
                    f"[pi_daily_sync] app_payload dates-index refresh failed "
                    f"(non-fatal) error={idx_exc!r}"
                )
        return True
    except Exception as exc:  # noqa: BLE001 - never fail the ingest on payload errors
        print(f"[pi_daily_sync] app_payload publish failed (non-fatal) error={exc!r} exit=0")
        return False


def sync_existing_repo(repo: Path, remote_url: str) -> None:
    if not (repo / ".git").is_dir():
        run_git(["clone", remote_url, str(repo)])
    run_git(["fetch", "origin"], cwd=repo)
    run_git(["checkout", "main"], cwd=repo)
    run_git(["pull", "--ff-only", "origin", "main"], cwd=repo)


def current_branch(repo: Path) -> str:
    result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        shell=False,
        timeout=GIT_TIMEOUT_SEC,
    )
    return result.stdout.strip()


def head_is_contained_by_origin_main(repo: Path) -> bool:
    """Return whether the checkout can safely fall back to tracked origin/main."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
        cwd=str(repo),
        check=False,
        shell=False,
        timeout=GIT_TIMEOUT_SEC,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError(
        f"unable to compare fallback checkout with origin/main: {repo} "
        f"(exit={result.returncode})"
    )


def sync_repo_for_ingest(
    repo: Path,
    remote_url: str,
    *,
    require_main_fallback: bool = True,
) -> bool:
    """Try to update a verified-clean checkout without blocking CDR capture.

    The clean-tree check remains mandatory and happens before this function.
    Once that check succeeds, a transient remote, DNS, or Git fetch failure must
    not discard the day's banking snapshot. AR-local itself may fall back only
    to a clean ``main`` checkout; ancillary site sync can be deferred without
    that constraint. The deploy watchdog restores remote parity.
    """
    try:
        sync_existing_repo(repo, remote_url)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        if require_main_fallback:
            try:
                assert_clean(repo)
                branch = current_branch(repo)
            except (OSError, RuntimeError, subprocess.SubprocessError) as verify_exc:
                raise RuntimeError(
                    f"git sync failed and fallback checkout is not verifiable: {repo}"
                ) from verify_exc
            if branch != "main":
                raise RuntimeError(
                    f"git sync failed and fallback checkout is not main: {repo} ({branch!r})"
                ) from exc
            try:
                contained = head_is_contained_by_origin_main(repo)
            except (OSError, RuntimeError, subprocess.SubprocessError) as verify_exc:
                raise RuntimeError(
                    f"git sync failed and fallback checkout ancestry is not verifiable: {repo}"
                ) from verify_exc
            if not contained:
                raise RuntimeError(
                    f"git sync failed and fallback checkout diverges from origin/main: {repo}"
                ) from exc
        print(
            f"[pi_daily_sync] git sync deferred repo={repo} error={exc!r}",
            file=sys.stderr,
        )
        return False
    return True


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
    parser.add_argument(
        "--publish-existing-payload",
        action="store_true",
        help="Retry a pending app-payload publication from existing exports without ingesting.",
    )
    args = parser.parse_args(argv)
    if args.publish_existing_payload and (args.force or args.date or args.banks_only):
        parser.error("--publish-existing-payload cannot be combined with ingest options")
    return args


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    ensure_runtime_data_writable(REPO_ROOT)
    lock_path = data_state_root(REPO_ROOT) / "daily-ingest.lock"
    code_sync_ok = True
    try:
        lock_context = DailyIngestLock(lock_path)
        with lock_context:
            if not args.skip_git_sync:
                assert_clean(REPO_ROOT)
                if (AR_SITE_REPO / ".git").is_dir():
                    assert_clean(AR_SITE_REPO)
                code_sync_ok = sync_repo_for_ingest(
                    REPO_ROOT, "https://github.com/yanniedog/AR-local.git"
                )
                sync_repo_for_ingest(
                    AR_SITE_REPO,
                    AR_SITE_URL,
                    require_main_fallback=False,
                )
            if args.publish_existing_payload:
                if not payload_publication_pending(REPO_ROOT):
                    print("[pi_daily_sync] app_payload retry skipped reason=no_pending_marker")
                elif not code_sync_ok:
                    print(
                        "[pi_daily_sync] app_payload retry deferred reason=code_sync_deferred",
                        file=sys.stderr,
                    )
                elif maybe_publish_app_payload(REPO_ROOT):
                    clear_payload_publication_pending(REPO_ROOT)
                    print("[pi_daily_sync] app_payload retry completed")
                else:
                    print(
                        "[pi_daily_sync] app_payload retry remains pending reason=publish_failed",
                        file=sys.stderr,
                    )
                return 0
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
            if code_sync_ok:
                if maybe_publish_app_payload(REPO_ROOT):
                    clear_payload_publication_pending(REPO_ROOT)
                elif _app_payload_enabled():
                    mark_payload_publication_pending(REPO_ROOT, "publish_failed")
            else:
                if _app_payload_enabled():
                    mark_payload_publication_pending(REPO_ROOT, "code_sync_deferred")
                print(
                    "[pi_daily_sync] app_payload skipped reason=code_sync_deferred",
                    file=sys.stderr,
                )
    except RuntimeError as exc:
        if "daily ingest already running" in str(exc):
            print(f"pi_daily_sync: {exc}")
            return 0
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
