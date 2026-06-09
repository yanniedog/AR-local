#!/usr/bin/env python3
"""Backfill historical app-payload assets onto the rolling GitHub release.

Iterates Pi run folders under ``<runs-root>/<date>/_exports`` for dates that were
ingested but never published. For each date with a valid dashboard export it builds
(or reuses) ``app-payload`` and calls ``app_payload.publish_payload`` **without**
``--force``, so older run_dates upload missing core/details assets but never
downgrade the live manifest when a newer one is already published.

Typical Pi invocation (from repo root, with GH_TOKEN in app-payload.env)::

    sudo -E bash scripts/backfill-app-payload.sh

Operator dry-run (no uploads)::

    python3 scripts/backfill_app_payload.py --dry-run

Bounds default to the audit window (2026-05-20 .. 2026-06-06); override with
``--from-date`` / ``--to-date``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_payload  # noqa: E402
from ar_local_pi_runtime import export_manifest_is_valid, load_exports_manifest  # noqa: E402

DEFAULT_FROM = "2026-05-20"
DEFAULT_TO = "2026-06-06"


def iter_backfill_dates(
    runs_root: Path,
    from_date: str,
    to_date: str,
) -> Iterable[Tuple[str, Path]]:
    """Yield (run_date, exports_dir) for valid exports in the inclusive date range."""
    runs_root = runs_root.expanduser().resolve()
    if not runs_root.is_dir():
        return
    for child in sorted(runs_root.iterdir()):
        if not child.is_dir():
            continue
        run_date = child.name
        if run_date < from_date or run_date > to_date:
            continue
        exports = child / "_exports"
        manifest = load_exports_manifest(exports)
        if manifest is not None and export_manifest_is_valid(manifest):
            yield run_date, exports


def sync_release_title_from_live(
    *,
    repo: str = app_payload.DEFAULT_REPO,
    tag: str = app_payload.DEFAULT_TAG,
) -> bool:
    """Set the rolling release title from the live manifest's run_date (best-effort)."""
    gh = app_payload._gh_available()
    if not gh or not app_payload._gh_authed(gh):
        print("[backfill_app_payload] title sync skipped: no gh auth")
        return False
    status, live = app_payload._live_manifest_status(repo, tag)
    if status != "present" or not live:
        print(f"[backfill_app_payload] title sync skipped: live manifest status={status}")
        return False
    run_date = str(live.get("run_date") or "")
    return app_payload._update_release_title(gh, repo, tag, run_date)


def backfill(
    runs_root: Path,
    *,
    from_date: str = DEFAULT_FROM,
    to_date: str = DEFAULT_TO,
    repo: str = app_payload.DEFAULT_REPO,
    tag: str = app_payload.DEFAULT_TAG,
    dry_run: bool = False,
    sync_title: bool = True,
) -> List[dict]:
    """Build + publish payloads for each date; return per-date result rows."""
    results: List[dict] = []
    dates = list(iter_backfill_dates(runs_root, from_date, to_date))
    print(
        f"[backfill_app_payload] starting runs_root={runs_root} "
        f"from={from_date} to={to_date} dates={len(dates)} dry_run={dry_run}"
    )
    for run_date, exports in dates:
        out_dir = exports / "app-payload"
        row = {"run_date": run_date, "exports": str(exports), "published": False, "error": None}
        try:
            if dry_run:
                manifest_path = out_dir / "manifest.json"
                if manifest_path.exists():
                    manifest = app_payload._load_json(manifest_path)
                else:
                    manifest = app_payload.build_payload(exports, out_dir, repo=repo, tag=tag)
                row["core"] = manifest["files"]["core"]["name"]
                row["details"] = manifest["files"]["details"]["name"]
                print(
                    f"[backfill_app_payload] dry-run run_date={run_date} "
                    f"core={row['core']} details={row['details']}"
                )
            else:
                manifest = app_payload.build_payload(exports, out_dir, repo=repo, tag=tag)
                row["core"] = manifest["files"]["core"]["name"]
                row["details"] = manifest["files"]["details"]["name"]
                row["published"] = app_payload.publish_payload(
                    out_dir, repo=repo, tag=tag, force=False
                )
                print(
                    f"[backfill_app_payload] run_date={run_date} published={row['published']} "
                    f"core={row['core']} details={row['details']}"
                )
        except Exception as exc:  # noqa: BLE001 - continue other dates
            row["error"] = repr(exc)
            print(f"[backfill_app_payload] run_date={run_date} failed error={exc!r}")
        results.append(row)

    uploaded = [r["run_date"] for r in results if r.get("published")]
    built = [r["run_date"] for r in results if not r.get("error")]
    failed = [r["run_date"] for r in results if r.get("error")]
    print(
        f"[backfill_app_payload] finished built={len(built)} manifest_replaced={len(uploaded)} "
        f"failed={len(failed)} dates={built}"
    )
    if sync_title and not dry_run:
        sync_release_title_from_live(repo=repo, tag=tag)
    return results


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill app-payload assets for historical run dates.")
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=None,
        help="Pi runs root (default: AR_LOCAL_DATA_ROOT/runs or <repo>/data/runs).",
    )
    parser.add_argument("--from-date", default=DEFAULT_FROM, help=f"First run_date (default: {DEFAULT_FROM}).")
    parser.add_argument("--to-date", default=DEFAULT_TO, help=f"Last run_date (default: {DEFAULT_TO}).")
    parser.add_argument("--repo", default=app_payload.DEFAULT_REPO, help="GitHub repo (default: %(default)s).")
    parser.add_argument("--tag", default=app_payload.DEFAULT_TAG, help="Rolling release tag (default: %(default)s).")
    parser.add_argument("--dry-run", action="store_true", help="Build/list only; no gh uploads.")
    parser.add_argument(
        "--no-sync-title",
        action="store_true",
        help="Skip gh release edit to match live manifest run_date after backfill.",
    )
    parser.add_argument(
        "--sync-title-only",
        action="store_true",
        help="Only refresh the rolling release title from the live manifest.",
    )
    args = parser.parse_args(argv)

    if args.sync_title_only:
        ok = sync_release_title_from_live(repo=args.repo, tag=args.tag)
        return 0 if ok else 1

    runs_root = args.runs_root
    if runs_root is None:
        import os
        from ar_local_pi_runtime import data_runs_root, repo_root as resolve_repo_root

        data_root = os.environ.get("AR_LOCAL_DATA_ROOT", "").strip()
        if data_root:
            runs_root = Path(data_root).expanduser() / "runs"
        else:
            runs_root = data_runs_root(resolve_repo_root(ROOT))

    backfill(
        runs_root,
        from_date=args.from_date,
        to_date=args.to_date,
        repo=args.repo,
        tag=args.tag,
        dry_run=args.dry_run,
        sync_title=not args.no_sync_title,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
