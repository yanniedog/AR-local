"""Run the local manual CDR ingest at most once per local day."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from cdr_outputs import build_outputs


def local_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def next_midnight_sleep_seconds() -> int:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).date()
    return max(60, int((datetime.combine(tomorrow, datetime.min.time()) - now).total_seconds()))


def marker_path(state_dir: Path, date: str) -> Path:
    return state_dir / f"{date}.done.json"


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


def run_once(args: argparse.Namespace) -> bool:
    script_dir = Path(__file__).resolve().parent
    runs_root = args.runs.expanduser().resolve()
    date = args.date or local_date()
    state_dir = (args.state or (script_dir / ".daily-state")).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_path(state_dir, date)
    if marker.exists() and not args.force:
        print(f"Already completed local CDR daily run for {date}: {marker}")
        return False
    run_ingest(script_dir, runs_root, date, args.ingest_arg)
    export_root = args.exports.expanduser().resolve() if args.exports else runs_root / date / "_exports"
    result = build_outputs(runs_root / date, export_root, args.db)
    marker.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return True


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local CDR ingest once per local day.")
    parser.add_argument("--runs", type=Path, default=Path(__file__).resolve().parent / "runs")
    parser.add_argument("--exports", type=Path, default=None, help="Export folder; default <run>/_exports")
    parser.add_argument("--db", type=Path, default=None, help="SQLite path; default <exports>/local-cdr.sqlite")
    parser.add_argument("--state", type=Path, default=None, help="Daily completion marker folder")
    parser.add_argument("--date", default=None, help="Override run date YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Ignore daily completion marker")
    parser.add_argument("--daemon", action="store_true", help="Keep running and execute after each local midnight")
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
