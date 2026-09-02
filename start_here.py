"""Small operator launcher for ingest, rebuild, and Pi verification."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ar_local_pi_runtime import PI_PUBLIC_BASE_URL, data_runs_root, data_state_root


ROOT = Path(__file__).resolve().parent
RUNS = data_runs_root(ROOT)
STATE = data_state_root(ROOT)


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True, shell=False)


def latest_run() -> Path:
    candidates = sorted(
        path for path in RUNS.glob("????-??-??") if path.is_dir()
    )
    if not candidates:
        raise SystemExit("No run exists; ingest first.")
    return candidates[-1]


def dispatch(action: str) -> None:
    if action in {"daily", "force"}:
        args = ["cdr_daily.py", "--runs", str(RUNS), "--state", str(STATE)]
        if action == "force":
            args.append("--force")
        run(*args)
    elif action == "rebuild":
        run("cdr_outputs.py", str(latest_run()))
    elif action == "verify":
        run("verify_local.py", "--base-url", PI_PUBLIC_BASE_URL)


def menu() -> None:
    actions = {"1": "daily", "2": "force", "3": "rebuild", "4": "verify"}
    while True:
        print("\nAR-local\n1. Ingest today\n2. Force ingest\n3. Rebuild latest\n4. Verify Pi\n0. Exit")
        choice = input("Choose: ").strip()
        if choice == "0":
            return
        action = actions.get(choice)
        if action:
            dispatch(action)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=("menu", "daily", "force", "rebuild", "verify"), default="menu"
    )
    args = parser.parse_args(argv)
    menu() if args.action == "menu" else dispatch(args.action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
