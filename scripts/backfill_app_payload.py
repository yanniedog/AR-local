#!/usr/bin/env python3
"""Backfill per-date app-payload GitHub releases from Pi run exports.

For each ``runs/<YYYY-MM-DD>/_exports`` with valid dashboard data, builds and publishes
an immutable dated release ``app-payload-<date>``. After all dates, refreshes the rolling
``app-payload-latest`` manifest to the newest run_date on disk (without downgrading a
newer live manifest).

Typical Pi invocation (from repo root, with GH_TOKEN in app-payload.env)::

    sudo -E bash scripts/backfill-app-payload.sh

Operator dry-run (no uploads)::

    python3 scripts/backfill_app_payload.py --dry-run

Default ``--from-date`` is ``2026-05-13`` (mobile history ribbon floor); ``--to-date`` is open.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TO = ""
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_payload  # noqa: E402
from ar_local_pi_runtime import data_runs_root  # noqa: E402

DEFAULT_FROM = app_payload.HISTORY_MIN_DATE


iter_valid_export_dates = app_payload.iter_valid_export_dates


def dated_release_already_published(repo: str, run_date: str) -> bool:
    """True when the dated tag already has a live manifest for this run_date."""
    tag = app_payload.dated_tag(run_date)
    status, live = app_payload._live_manifest_status(repo, tag)
    if status != "present" or not live:
        return False
    return str(live.get("run_date") or "") == run_date


def refresh_rolling_latest(
    runs_root: Path,
    *,
    repo: str = app_payload.DEFAULT_REPO,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    """Publish ``app-payload-latest`` for the newest valid export on disk."""
    dates = list(iter_valid_export_dates(runs_root))
    if not dates:
        print("[backfill_app_payload] rolling latest skipped: no valid exports")
        return False
    run_date, exports = dates[-1]
    print(
        f"[backfill_app_payload] rolling latest refresh run_date={run_date} "
        f"exports={exports} dry_run={dry_run}"
    )
    if dry_run:
        return False
    out_dir = exports / "app-payload-latest"
    manifest = app_payload.build_payload(exports, out_dir, repo=repo, tag=app_payload.DEFAULT_TAG)
    our_gen = str(manifest.get("generated_at") or "")
    published = app_payload.publish_payload(out_dir, repo=repo, tag=app_payload.DEFAULT_TAG, force=force)
    print(
        f"[backfill_app_payload] rolling latest finished run_date={run_date} "
        f"published={published}"
    )
    if published:
        return True
    status, live = app_payload._live_manifest_status(repo, app_payload.DEFAULT_TAG)
    if status == "present" and live:
        live_run = str(live.get("run_date") or "")
        live_gen = str(live.get("generated_at") or "")
        if live_run and live_run > run_date:
            print(
                f"[backfill_app_payload] rolling latest no-op: live run_date={live_run} "
                f"> newest export {run_date}"
            )
            return True
        if live_run == run_date and live_gen and our_gen and live_gen >= our_gen:
            print(
                f"[backfill_app_payload] rolling latest no-op: live run_date={live_run} "
                f"generated_at={live_gen} >= built {our_gen}"
            )
            return True
    return False


def backfill(
    runs_root: Path,
    *,
    from_date: str = "",
    to_date: str = "",
    repo: str = app_payload.DEFAULT_REPO,
    dry_run: bool = False,
    force: bool = False,
    skip_latest: bool = False,
) -> Tuple[List[dict], Optional[bool]]:
    """Publish dated releases for each export date; optionally refresh rolling latest."""
    results: List[dict] = []
    dates = list(iter_valid_export_dates(runs_root, from_date=from_date, to_date=to_date))
    print(
        f"[backfill_app_payload] starting runs_root={runs_root} "
        f"from={from_date or '*'} to={to_date or '*'} dates={len(dates)} "
        f"dry_run={dry_run} force={force}"
    )
    for run_date, exports in dates:
        tag = app_payload.dated_tag(run_date)
        out_dir = exports / "app-payload"
        row = {
            "run_date": run_date,
            "tag": tag,
            "exports": str(exports),
            "published": False,
            "skipped": False,
            "error": None,
        }
        try:
            if not force and not dry_run and dated_release_already_published(repo, run_date):
                row["skipped"] = True
                print(f"[backfill_app_payload] run_date={run_date} tag={tag} skipped=already_published")
                results.append(row)
                continue
            if dry_run:
                manifest_path = out_dir / "manifest.json"
                if manifest_path.exists():
                    manifest = app_payload._load_json(manifest_path)
                else:
                    manifest = app_payload.build_payload(exports, out_dir, repo=repo, tag=tag)
                row["core"] = manifest["files"]["core"]["name"]
                row["details"] = manifest["files"]["details"]["name"]
                print(
                    f"[backfill_app_payload] dry-run run_date={run_date} tag={tag} "
                    f"core={row['core']} details={row['details']}"
                )
            else:
                manifest = app_payload.build_payload(exports, out_dir, repo=repo, tag=tag)
                row["core"] = manifest["files"]["core"]["name"]
                row["details"] = manifest["files"]["details"]["name"]
                row["published"] = app_payload.publish_payload(
                    out_dir, repo=repo, tag=tag, force=force
                )
                if not row["published"] and not force and dated_release_already_published(repo, run_date):
                    row["skipped"] = True
                    print(
                        f"[backfill_app_payload] run_date={run_date} tag={tag} "
                        "skipped=already_published_after_publish"
                    )
                print(
                    f"[backfill_app_payload] run_date={run_date} tag={tag} "
                    f"published={row['published']} core={row['core']} details={row['details']}"
                )
        except Exception as exc:  # noqa: BLE001 - continue other dates
            row["error"] = repr(exc)
            print(f"[backfill_app_payload] run_date={run_date} tag={tag} failed error={exc!r}")
        results.append(row)

    published = [r["run_date"] for r in results if r.get("published")]
    skipped = [r["run_date"] for r in results if r.get("skipped")]
    failed = [r["run_date"] for r in results if r.get("error")]
    print(
        f"[backfill_app_payload] dated finished published={len(published)} "
        f"skipped={len(skipped)} failed={len(failed)} "
        f"dates_published={published}"
    )
    rolling_ok: Optional[bool] = None
    if not skip_latest:
        rolling_ok = refresh_rolling_latest(runs_root, repo=repo, dry_run=dry_run, force=force)
    if not dry_run and (published or rolling_ok):
        try:
            app_payload.refresh_dates_index(runs_root, repo=repo, min_date=from_date or DEFAULT_FROM)
        except Exception as exc:  # noqa: BLE001 - index refresh must not fail backfill
            print(f"[backfill_app_payload] dates-index refresh failed (non-fatal) error={exc!r}")
    return results, rolling_ok


def resolve_runs_root(explicit: Optional[Path]) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    data_root = os.environ.get("AR_LOCAL_DATA_ROOT", "").strip()
    if data_root:
        return (Path(data_root).expanduser() / "runs").resolve()
    return data_runs_root(ROOT)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill per-date app-payload GitHub releases from run exports.",
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=None,
        help="Runs root (default: AR_LOCAL_DATA_ROOT/runs or <repo>/data/runs).",
    )
    parser.add_argument("--from-date", default=DEFAULT_FROM, help="Optional first run_date (YYYY-MM-DD) (default: %(default)s).")
    parser.add_argument("--to-date", default=DEFAULT_TO, help="Optional last run_date (YYYY-MM-DD) (default: %(default)s).")
    parser.add_argument("--repo", default=app_payload.DEFAULT_REPO, help="GitHub repo.")
    parser.add_argument("--dry-run", action="store_true", help="Build/list only; no gh uploads.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-publish dated releases even when already present; may override rolling latest.",
    )
    parser.add_argument(
        "--skip-latest",
        action="store_true",
        help="Only publish dated tags; do not refresh app-payload-latest at the end.",
    )
    parser.add_argument(
        "--latest-only",
        action="store_true",
        help="Only refresh app-payload-latest from the newest valid export.",
    )
    parser.add_argument(
        "--retitle-only",
        action="store_true",
        help="Only refresh GitHub release titles from manifest run_date (no uploads).",
    )
    args = parser.parse_args(argv)
    runs_root = resolve_runs_root(args.runs_root)

    if args.retitle_only:
        updated, skipped = app_payload.retitle_payload_releases(
            repo=args.repo,
            from_date=args.from_date,
            to_date=args.to_date,
            dry_run=args.dry_run,
        )
        return 0

    if args.latest_only:
        ok = refresh_rolling_latest(runs_root, repo=args.repo, dry_run=args.dry_run, force=args.force)
        return 0 if args.dry_run or ok else 1

    results, rolling_ok = backfill(
        runs_root,
        from_date=args.from_date,
        to_date=args.to_date,
        repo=args.repo,
        dry_run=args.dry_run,
        force=args.force,
        skip_latest=args.skip_latest,
    )
    if args.dry_run:
        return 0
    attempted = [r for r in results if not r.get("skipped")]
    if attempted and not any(r.get("published") for r in results):
        print("[backfill_app_payload] failed: no dated releases published")
        return 1
    unpublished = [r["run_date"] for r in attempted if not r.get("published") and not r.get("error")]
    if unpublished:
        print(
            f"[backfill_app_payload] failed: dated publish returned false for run_dates={unpublished}"
        )
        return 1
    if any(r.get("error") for r in results):
        print("[backfill_app_payload] failed: one or more dates errored")
        return 1
    if rolling_ok is False:
        print("[backfill_app_payload] failed: rolling latest refresh failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
