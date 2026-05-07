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
    is_raspberry_pi,
    prepare_empty_dir,
)
from cdr_outputs import build_outputs


def local_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def next_midnight_sleep_seconds() -> int:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).date()
    return max(60, int((datetime.combine(tomorrow, datetime.min.time()) - now).total_seconds()))


def marker_path(state_dir: Path, date: str) -> Path:
    return state_dir / f"{date}.done.json"


def run_ingest(script_dir: Path, out_dir: Path, date: str, extra: List[str], energy_full_detail: bool) -> None:
    cmd_extra = [a for a in extra if a not in ("--energy-lite",)]
    if energy_full_detail and "--energy-full-detail" not in cmd_extra:
        cmd_extra.append("--energy-full-detail")
    cmd = [
        sys.executable,
        str(script_dir / "cdr_full_ingest.py"),
        "--out",
        str(out_dir),
        "--date",
        date,
        "--resume",
        *cmd_extra,
    ]
    # Intentionally pass a list with shell=False; extra args are local CLI passthrough.
    subprocess.run(cmd, cwd=script_dir, check=True, shell=False)


def sector_ingest_args(args: argparse.Namespace) -> List[str]:
    if args.banks_only:
        return ["--no-energy"]
    return []


def run_once(args: argparse.Namespace) -> bool:
    script_dir = Path(__file__).resolve().parent
    persistent_runs_root = args.runs.expanduser().resolve()
    date = args.date or local_date()
    state_dir = (args.state.expanduser().resolve() if args.state else data_state_root(script_dir))
    state_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_path(state_dir, date)
    if marker.exists() and not args.force:
        print(f"Already completed local CDR daily run for {date}: {marker}")
        return False

    want_full_energy = bool(getattr(args, "energy_full_detail", False)) or "--energy-full-detail" in args.ingest_arg
    extra_args = [*sector_ingest_args(args), *args.ingest_arg]
    use_ram_stage = args.ram_stage or (is_raspberry_pi() and not args.no_ram_stage)
    if use_ram_stage:
        ram_root = args.ram_root.expanduser().resolve()
        staged_runs = ram_root / "runs"
        staged_exports = ram_root / "exports" / date / "_exports"
        prepare_empty_dir(ram_root / "runs" / date)
        prepare_empty_dir(staged_exports)
        run_ingest(script_dir, staged_runs, date, extra_args, energy_full_detail=want_full_energy)
        result = build_outputs(staged_runs / date, staged_exports, args.db, energy_slim=not want_full_energy)
        persistent_export_root = (
            args.exports.expanduser().resolve()
            if args.exports
            else persistent_runs_root / date / "_exports"
        )
        copytree_atomic(staged_exports, persistent_export_root)
        result["out_dir"] = str(persistent_export_root)
        result["ram_staged"] = True
        result["ram_root"] = str(ram_root)
        if args.clean_ram_stage:
            shutil.rmtree(ram_root / "runs" / date, ignore_errors=True)
            shutil.rmtree(ram_root / "exports" / date, ignore_errors=True)
    else:
        run_ingest(script_dir, persistent_runs_root, date, extra_args, energy_full_detail=want_full_energy)
        export_root = (
            args.exports.expanduser().resolve()
            if args.exports
            else persistent_runs_root / date / "_exports"
        )
        result = build_outputs(persistent_runs_root / date, export_root, args.db, energy_slim=not want_full_energy)
        result["ram_staged"] = False

    marker.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return True


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local CDR ingest once per local day.")
    repo_root = Path(__file__).resolve().parent
    parser.add_argument("--runs", type=Path, default=data_runs_root(repo_root))
    parser.add_argument("--exports", type=Path, default=None, help="Export folder; default <run>/_exports")
    parser.add_argument("--db", type=Path, default=None, help="SQLite path; default <exports>/local-cdr.sqlite")
    parser.add_argument("--state", type=Path, default=None, help="Daily completion marker folder")
    parser.add_argument("--date", default=None, help="Override run date YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Ignore daily completion marker")
    parser.add_argument("--banks-only", action="store_true", help="Ingest banking products only.")
    parser.add_argument("--daemon", action="store_true", help="Keep running and execute after each local midnight")
    parser.add_argument(
        "--energy-full-detail",
        action="store_true",
        help="Energy: per-plan GET and full granular exports (default is index-only + slim).",
    )
    parser.add_argument("--energy-lite", action="store_true", help=argparse.SUPPRESS)
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
        run_once(args)
        if not args.daemon:
            return 0
        sleep_for = next_midnight_sleep_seconds()
        print(f"Sleeping {sleep_for}s until next local-day check.")
        time.sleep(sleep_for)
        args.date = None
        args.force = False


if __name__ == "__main__":
    raise SystemExit(main())
