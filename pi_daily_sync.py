"""Run the Raspberry Pi daily CDR ingest without changing deployed code."""

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
from ar_local_pi_runtime import (
    data_runs_root,
    data_state_root,
    ensure_runtime_data_writable,
    is_raspberry_pi,
)
from ar_local_subprocess import run_checked
from cdr_finalization import verify_completion_marker
from cdr_macro_ingest import DEFAULT_STORE_PATH as DEFAULT_MACRO_STORE_PATH

REPO_ROOT = Path(__file__).resolve().parent
LOCK_STALE_SECONDS = 6 * 60 * 60
PENDING_PAYLOAD_FILENAME = "app-payload-publication-pending.json"
DASHBOARD_UNIT = "ar-local-dashboard.service"
DASHBOARD_CONTROL_TIMEOUT_SEC = 120

# Outcomes of maybe_publish_app_payload. "withheld" is a deliberate policy no-op
# (nothing was eligible to publish), so it neither raises a pending retry nor
# clears one an earlier day left behind; only a confirmed upload clears it.
PUBLISH_PUBLISHED = "published"
PUBLISH_WITHHELD = "withheld"
PUBLISH_FAILED = "failed"


def pause_dashboard_for_ingest() -> bool:
    """Reserve dashboard preload memory for the mandatory Pi ingest."""
    if not is_raspberry_pi():
        return False
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "stop", DASHBOARD_UNIT],
            check=False,
            shell=False,
            timeout=DASHBOARD_CONTROL_TIMEOUT_SEC,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        print(f"[pi_daily_sync] dashboard pause failed (non-fatal): {exc}", file=sys.stderr)
        return False
    if result.returncode != 0:
        print(
            f"[pi_daily_sync] dashboard pause failed (non-fatal) exit={result.returncode}",
            file=sys.stderr,
        )
        return False
    print("[pi_daily_sync] dashboard paused for daily ingest")
    return True


def resume_dashboard_after_ingest() -> None:
    """Best-effort dashboard recovery without changing ingest outcome."""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "start", DASHBOARD_UNIT],
            check=False,
            shell=False,
            timeout=DASHBOARD_CONTROL_TIMEOUT_SEC,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        print(f"[pi_daily_sync] dashboard resume failed (non-fatal): {exc}", file=sys.stderr)
        return
    if result.returncode != 0:
        print(
            f"[pi_daily_sync] dashboard resume failed (non-fatal) exit={result.returncode}",
            file=sys.stderr,
        )
        return
    print("[pi_daily_sync] dashboard resumed after daily ingest")


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


def maybe_publish_app_payload(repo_root: Path) -> str:
    """Build + publish the mobile-app payload after a successful ingest.

    Opt-in (AR_LOCAL_APP_PAYLOAD=1) and strictly non-fatal: a publish failure must
    never fail the daily ingest. Publishing itself is token-gated inside
    app_payload (no GH_TOKEN -> builds locally and skips the upload).

    Returns one of PUBLISH_PUBLISHED / PUBLISH_WITHHELD / PUBLISH_FAILED. A build
    that never reached the release (no gh auth, a swallowed upload error, a live
    manifest that still does not match this revision) is PUBLISH_FAILED so the
    pending marker survives and the watchdog retries it, rather than being
    reported as success because no exception escaped.
    """
    if not _app_payload_enabled():
        return PUBLISH_WITHHELD
    try:
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
            return PUBLISH_WITHHELD
        latest_complete = _read_observation_pointer(runtime_state, "latest-complete.json")
        exports = _exports_from_pointer(runtime_state, latest_complete)
        if exports is None:
            print(
                "[pi_daily_sync] app_payload promotion withheld "
                "reason=missing_or_invalid_latest_complete_pointer"
            )
            return PUBLISH_WITHHELD
        observation_date = str(latest_complete.get("observation_date") or "")
        marker_relative = str(latest_complete.get("marker_path") or "")
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
            return PUBLISH_WITHHELD
        completion_marker = runtime_state / marker_part
        try:
            completion = json.loads(completion_marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            completion = {}
        if not verify_completion_marker(completion, runtime_state, observation_date):
            print(
                "[pi_daily_sync] app_payload promotion withheld "
                f"run_date={observation_date or 'unknown'} "
                "reason=unverified_completion_marker"
            )
            return PUBLISH_WITHHELD
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
            return PUBLISH_WITHHELD
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
        # Neither published_dated nor published_latest is a reliable success signal on
        # its own: publish_payload returns False (never raises) when gh auth is
        # missing or the live manifest check errors, and build_and_publish_dual
        # swallows a failed dated upload. The rolling app-payload-latest manifest is
        # what the mobile app actually polls, so confirm against it.
        v2_eligible = published_latest
        rolling_superseded = False
        rolling_confirmed = published_latest
        if not v2_eligible:
            try:
                live_status, live_v1 = app_payload._live_manifest_status(
                    app_payload.DEFAULT_REPO, app_payload.DEFAULT_TAG
                )
                if live_status == "present" and live_v1 is not None:
                    v2_eligible = _same_payload_revision(manifest, live_v1)
                    rolling_confirmed = v2_eligible
                    # A backfill may legitimately hold a newer run_date on the
                    # rolling tag; that is a correct skip, not a lost upload.
                    rolling_superseded = not v2_eligible and (
                        str(live_v1.get("run_date") or "") > run_date
                    )
            except Exception as live_exc:  # noqa: BLE001 - optional sidecar check
                print(
                    "[pi_daily_sync] app_payload v2 skipped "
                    f"reason=v1_revision_check_failed error={live_exc!r}"
                )
        outcome = (
            PUBLISH_PUBLISHED
            if (rolling_confirmed or rolling_superseded)
            else PUBLISH_FAILED
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
        if outcome != PUBLISH_PUBLISHED:
            print(
                "[pi_daily_sync] app_payload publication incomplete "
                f"run_date={run_date} published_dated={published_dated} "
                f"published_latest={published_latest} "
                "reason=rolling_manifest_not_confirmed (retry pending)",
                file=sys.stderr,
            )
        return outcome
    except Exception as exc:  # noqa: BLE001 - never fail the ingest on payload errors
        print(f"[pi_daily_sync] app_payload publish failed (non-fatal) error={exc!r} exit=0")
        return PUBLISH_FAILED


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Pi daily ingest without changing either production checkout."
    )
    parser.add_argument(
        "--skip-git-sync",
        action="store_true",
        help="Compatibility no-op; ingest never changes production checkouts.",
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
    try:
        lock_context = DailyIngestLock(lock_path)
        with lock_context:
            if args.publish_existing_payload:
                if not payload_publication_pending(REPO_ROOT):
                    print("[pi_daily_sync] app_payload retry skipped reason=no_pending_marker")
                elif not _app_payload_enabled():
                    print(
                        "[pi_daily_sync] app_payload retry remains pending "
                        "reason=publication_disabled",
                        file=sys.stderr,
                    )
                else:
                    outcome = maybe_publish_app_payload(REPO_ROOT)
                    if outcome == PUBLISH_PUBLISHED:
                        clear_payload_publication_pending(REPO_ROOT)
                        print("[pi_daily_sync] app_payload retry completed")
                    else:
                        # Withheld keeps the marker too: nothing reached the release,
                        # so the upload is still outstanding for the next attempt.
                        print(
                            "[pi_daily_sync] app_payload retry remains pending "
                            f"reason={outcome}",
                            file=sys.stderr,
                        )
                return 0
            sector_args: list[str] = []
            if args.banks_only:
                sector_args = ["--banks-only"]
            force_args = ["--force"] if args.force else []
            date_args = ["--date", args.date] if args.date else []
            dashboard_paused = pause_dashboard_for_ingest()
            try:
                run_checked(
                    [
                        sys.executable,
                        str(REPO_ROOT / "cdr_daily.py"),
                        "--workers",
                        str(DAILY_WORKER_COUNT),
                        "--archive-failed-ram-stage",
                        *sector_args,
                        *force_args,
                        *date_args,
                    ],
                    cwd=REPO_ROOT,
                )
            finally:
                if dashboard_paused:
                    resume_dashboard_after_ingest()
            if _app_payload_enabled():
                outcome = maybe_publish_app_payload(REPO_ROOT)
                if outcome == PUBLISH_PUBLISHED:
                    clear_payload_publication_pending(REPO_ROOT)
                elif outcome == PUBLISH_FAILED:
                    mark_payload_publication_pending(REPO_ROOT, "publish_failed")
                elif payload_publication_pending(REPO_ROOT):
                    # Today withheld by policy, but an earlier day's upload never
                    # landed. Keep that marker so the watchdog keeps retrying.
                    print(
                        "[pi_daily_sync] app_payload remains pending "
                        "reason=withheld_this_run",
                        file=sys.stderr,
                    )
            elif payload_publication_pending(REPO_ROOT):
                print(
                    "[pi_daily_sync] app_payload remains pending "
                    "reason=publication_disabled",
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
