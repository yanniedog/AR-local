"""Run the local manual CDR ingest at most once per local day."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from ar_local_pi_runtime import (
    copytree_atomic,
    data_runs_root,
    data_state_root,
    default_ram_root,
    export_manifest_is_valid,
    ensure_runtime_data_writable,
    is_raspberry_pi,
    load_exports_manifest,
    manifest_banks_rate_count,
    prepare_empty_dir,
)
import cdr_ledger_integrity
from cdr_outputs import build_outputs
from cdr_ingest_sanity import write_sanity_report


def local_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def next_midnight_sleep_seconds() -> int:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).date()
    return max(60, int((datetime.combine(tomorrow, datetime.min.time()) - now).total_seconds()))


def marker_path(state_dir: Path, date: str) -> Path:
    return state_dir / f"{date}.done.json"


def banks_result_rate_count(result: dict) -> int:
    return manifest_banks_rate_count(result)


def persistent_export_root(persistent_runs_root: Path, date: str, exports: Optional[Path]) -> Path:
    if exports is not None:
        return exports.expanduser().resolve()
    return (persistent_runs_root / date / "_exports").resolve()


def marker_is_trustworthy(marker: Path, export_root: Path, date: str) -> bool:
    try:
        recorded = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(recorded, dict) or banks_result_rate_count(recorded) <= 0:
        return False
    manifest = load_exports_manifest(export_root)
    if manifest is None:
        return False
    if str(manifest.get("run_date") or "") != date:
        return False
    return export_manifest_is_valid(manifest)


class LedgerImmutabilityError(RuntimeError):
    """Raised when an ingest would mutate or fabricate append-only ledger history."""


def _export_root_has_content(root: Path) -> bool:
    return root.is_dir() and any(root.iterdir())


def revision_root_for(primary_root: Path, when: datetime) -> Path:
    """Append-only revision target beside a finalized day's primary _exports.

    The stamp carries microseconds so two forced ingests in the same second get
    distinct revision dirs instead of colliding (Sourcery).
    """
    stamp = when.strftime("%Y%m%dT%H%M%S_%f")
    return primary_root.parent / "_revisions" / stamp / primary_root.name


def resolve_ledger_target(
    primary_root: Path,
    date: str,
    today: str,
    force: bool,
    now: Optional[datetime] = None,
) -> tuple[Path, bool]:
    """Enforce append-only history; return ``(target_root, is_revision)``.

    Today's partition is still being assembled, so it writes its primary
    ``_exports`` as before. PAST days are immutable, append-only ledger data:

    - An already-finalized partition is NEVER overwritten. ``--force`` appends a
      timestamped revision beside it, preserving the original bytes (corrections
      are appended, never destructive).
    - A MISSING past day is NEVER created by the live ingest: live CDR endpoints
      return only current data, so writing it under a historical date would
      fabricate the ledger (e.g. the 2026-05-14 gap must remain a gap).

    Dates are ``YYYY-MM-DD`` so lexical comparison is chronological.
    """
    if date >= today:
        return primary_root, False
    if _export_root_has_content(primary_root):
        if not force:
            raise LedgerImmutabilityError(
                f"Refusing to overwrite finalized ledger day {date} at {primary_root}; "
                f"re-run with --force to append a revision instead of mutating it."
            )
        return revision_root_for(primary_root, now or datetime.now()), True
    raise LedgerImmutabilityError(
        f"Refusing to ingest past date {date}: live CDR endpoints return only "
        f"current data, so writing it under a historical date would fabricate the "
        f"ledger (the {date} gap must remain a gap). Past days are append-only."
    )


def run_ingest(script_dir: Path, out_dir: Path, date: str, extra: List[str]) -> None:
    cmd = [
        sys.executable,
        str(script_dir / "cdr_full_ingest.py"),
        "--out",
        str(out_dir),
        "--date",
        date,
        "--resume",
        *extra,
    ]
    # Intentionally pass a list with shell=False; extra args are local CLI passthrough.
    subprocess.run(cmd, cwd=script_dir, check=True, shell=False)


def sector_ingest_args(args: argparse.Namespace) -> List[str]:
    return []


def _emit_day_manifest(persistent_runs_root: Path, state_dir: Path, date: str, exports: Optional[Path]) -> None:
    """Best-effort: emit/refresh the day's ledger integrity manifest.

    Non-fatal and primary-only (a revision doesn't change the hashed _exports);
    skipped for a custom --exports layout, since the manifest assumes the default
    <runs>/<date>/_exports paths. Catches broadly on purpose: this runs after the
    completion marker is written, so it must never turn a successful ingest into a
    failure.
    """
    if exports is not None:
        return
    try:
        cdr_ledger_integrity.append_day_manifest(persistent_runs_root, state_dir, date)
    except Exception as exc:  # never let integrity bookkeeping fail the ingest
        print(
            f"ledger-integrity: failed to write manifest for {date}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def run_once(args: argparse.Namespace) -> int:
    """Return 0 when skipped, 1 on success, 2 when banking export is empty."""
    script_dir = Path(__file__).resolve().parent
    ensure_runtime_data_writable(script_dir)
    persistent_runs_root = args.runs.expanduser().resolve()
    date = args.date or local_date()
    state_dir = (args.state.expanduser().resolve() if args.state else data_state_root(script_dir))
    state_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_path(state_dir, date)
    export_root = persistent_export_root(persistent_runs_root, date, args.exports)
    if marker.exists() and not args.force:
        if marker_is_trustworthy(marker, export_root, date):
            print(f"Already completed local CDR daily run for {date}: {marker}")
            # Self-heal a finalized day whose integrity manifest never landed
            # (e.g. a prior best-effort write failed): the trusted-marker path is
            # otherwise the only return point, so emit it here if missing (Codex
            # P2). Cheap no-op when the manifest already exists.
            if args.exports is None and not cdr_ledger_integrity.manifest_path(state_dir, date).is_file():
                _emit_day_manifest(persistent_runs_root, state_dir, date, args.exports)
            return 0
        print(
            f"Stale or empty daily marker for {date} ({marker}); re-running ingest.",
            file=sys.stderr,
        )

    # Append-only ledger guard: decide where this ingest may write before touching
    # any persistent bytes. Today writes its primary _exports; past days are
    # immutable (force => revision; missing gap => refuse).
    try:
        target_export_root, is_revision = resolve_ledger_target(
            export_root, date, local_date(), args.force
        )
    except LedgerImmutabilityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if is_revision:
        print(
            f"Ledger append-only: {date} is already finalized; appending a revision at "
            f"{target_export_root} (original _exports preserved).",
            file=sys.stderr,
        )

    extra_args = [*sector_ingest_args(args), *args.ingest_arg]
    use_ram_stage = args.ram_stage or (is_raspberry_pi() and not args.no_ram_stage)
    if use_ram_stage:
        ram_root = args.ram_root.expanduser().resolve()
        staged_runs = ram_root / "runs"
        staged_exports = ram_root / "exports" / date / "_exports"
        prepare_empty_dir(ram_root / "runs" / date)
        prepare_empty_dir(staged_exports)
        run_ingest(script_dir, staged_runs, date, extra_args)
        result = build_outputs(staged_runs / date, staged_exports, args.db)
        copytree_atomic(staged_exports, target_export_root)
        result["out_dir"] = str(target_export_root)
        result["ram_staged"] = True
        result["ram_root"] = str(ram_root)
        if args.clean_ram_stage:
            shutil.rmtree(ram_root / "runs" / date, ignore_errors=True)
            shutil.rmtree(ram_root / "exports" / date, ignore_errors=True)
    else:
        # A revision must not mutate the original day's raw run files either, so
        # isolate the revision's raw ingest under the revision dir (Gemini). The
        # Pi path is RAM-staged (raw files never persist), so this guards the
        # --no-ram-stage / dev path.
        run_root = target_export_root.parent if is_revision else persistent_runs_root
        run_ingest(script_dir, run_root, date, extra_args)
        result = build_outputs(run_root / date, target_export_root, args.db)
        result["ram_staged"] = False

    if banks_result_rate_count(result) <= 0:
        print(
            f"ERROR: banking export for {date} has zero rates; refusing to write completion marker.",
            file=sys.stderr,
        )
        return 2

    # Post-ingest sanity check (non-blocking). Flags per-product rate
    # ladders that moved >= LOW_BP vs the previous day's export. See
    # cdr_ingest_sanity.py module docstring for the 2026-05-20/26
    # CommBank repricing-window incident that motivated this guard.
    try:
        report_path = write_sanity_report(target_export_root, date, persistent_runs_root)
    except Exception as exc:  # never let the guard fail the ingest
        print(f"sanity-check: error writing report: {type(exc).__name__}: {exc}", file=sys.stderr)
    else:
        if report_path is not None:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            counts = report.get("counts", {})
            high = counts.get("HIGH", 0)
            structural = counts.get("STRUCTURAL", 0)
            low = counts.get("LOW", 0)
            print(
                f"sanity-check vs {report.get('compared_against')}: "
                f"HIGH={high} STRUCTURAL={structural} LOW={low}  ({report_path})"
            )
            for finding in report.get("findings", [])[:10]:
                if finding["severity"] in ("HIGH", "STRUCTURAL"):
                    print(
                        f"  {finding['severity']}: {finding['provider']} "
                        f"{finding.get('product_name','')[:50]} "
                        f"worst_delta={finding.get('worst_delta_bp', '-')}bp",
                        file=sys.stderr,
                    )

    if is_revision:
        # Preserve the primary day marker; record the revision under its own marker
        # so the day's original finalization stays authoritative and auditable.
        revision_marker = state_dir / f"{date}.revision.{target_export_root.parent.name}.json"
        revision_marker.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        marker.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        # Emit this day's ledger integrity manifest (hash-chain link to the prior
        # day) so the partition is tamper-evident from finalization.
        _emit_day_manifest(persistent_runs_root, state_dir, date, args.exports)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local CDR ingest once per local day.")
    repo_root = Path(__file__).resolve().parent
    parser.add_argument("--runs", type=Path, default=data_runs_root(repo_root))
    parser.add_argument("--exports", type=Path, default=None, help="Export folder; default <run>/_exports")
    parser.add_argument("--db", type=Path, default=None, help="SQLite path; default <exports>/local-cdr.sqlite")
    parser.add_argument("--state", type=Path, default=None, help="Daily completion marker folder")
    parser.add_argument("--date", default=None, help="Override run date YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Ignore daily completion marker")
    parser.add_argument("--banks-only", action="store_true", help="Accepted for compatibility; banking is the only sector.")
    parser.add_argument("--daemon", action="store_true", help="Keep running and execute after each local midnight")
    parser.add_argument(
        "--ram-stage",
        action="store_true",
        help="Stage ingest and export build files in RAM before copying completed exports to --runs.",
    )
    parser.add_argument(
        "--no-ram-stage",
        action="store_true",
        help="Disable automatic RAM staging on Raspberry Pi.",
    )
    parser.add_argument("--ram-root", type=Path, default=default_ram_root())
    parser.add_argument(
        "--keep-ram-stage",
        dest="clean_ram_stage",
        action="store_false",
        help="Keep RAM-staged raw files for debugging after a successful run.",
    )
    parser.set_defaults(clean_ram_stage=True)
    args, extra = parser.parse_known_args(argv)
    args.ingest_arg = extra
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    while True:
        status = run_once(args)
        if status == 2:
            return 1
        if not args.daemon:
            return 0
        sleep_for = next_midnight_sleep_seconds()
        print(f"Sleeping {sleep_for}s until next local-day check.")
        time.sleep(sleep_for)
        args.date = None
        args.force = False


if __name__ == "__main__":
    raise SystemExit(main())
