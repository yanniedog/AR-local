#!/usr/bin/env python3
"""Remove retired non-banking CDR artifacts from the configured Pi data root."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Iterable

from ar_local_pi_runtime import data_root

REPO_ROOT = Path(__file__).resolve().parent
REMOVED = "en" + "ergy"
REMOVED_TABLES = (REMOVED + "_plans", REMOVED + "_items")
REMOVED_MANIFEST_KEYS = (REMOVED + "_counts",)
REMOVED_FILE_KEYS = (REMOVED + "_json", REMOVED + "_xlsx")


def iter_run_dirs(runs_root: Path) -> Iterable[Path]:
    if not runs_root.is_dir():
        return []
    return (
        path
        for path in sorted(runs_root.iterdir())
        if path.is_dir() and len(path.name) == 10 and path.name[4] == "-" and path.name[7] == "-"
    )


def remove_path(path: Path, *, apply: bool, actions: list[str]) -> None:
    if not path.exists():
        return
    actions.append(f"remove {path}")
    if not apply:
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def rewrite_manifest(path: Path, *, apply: bool, actions: list[str]) -> None:
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    changed = False
    for key in REMOVED_MANIFEST_KEYS:
        if key in payload:
            payload.pop(key, None)
            changed = True
    files = payload.get("files")
    if isinstance(files, dict):
        for key in REMOVED_FILE_KEYS:
            if key in files:
                files.pop(key, None)
                changed = True
    if not changed:
        return
    actions.append(f"rewrite manifest {path}")
    if apply:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def migrate_db(path: Path, *, apply: bool, actions: list[str]) -> None:
    if not path.is_file():
        return
    with sqlite3.connect(path) as con:
        old_runs = False
        if table_exists(con, "runs"):
            cols = {str(row[1]) for row in con.execute("PRAGMA table_info(runs)").fetchall()}
            old_runs = REMOVED + "_counts_json" in cols
        old_tables = [table for table in REMOVED_TABLES if table_exists(con, table)]
        if not old_runs and not old_tables:
            return
        actions.append(f"migrate sqlite {path}")
        if not apply:
            return
        con.execute("BEGIN")
        try:
            if old_runs:
                con.execute(
                    """
                    CREATE TABLE runs_new (
                      run_date TEXT PRIMARY KEY,
                      generated_at TEXT NOT NULL,
                      banks_counts_json TEXT NOT NULL
                    )
                    """,
                )
                con.execute(
                    "INSERT OR REPLACE INTO runs_new (run_date, generated_at, banks_counts_json) "
                    "SELECT run_date, generated_at, banks_counts_json FROM runs",
                )
                con.execute("DROP TABLE runs")
                con.execute("ALTER TABLE runs_new RENAME TO runs")
            for table in old_tables:
                con.execute(f'DROP TABLE IF EXISTS "{table}"')
            con.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', '6')")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("VACUUM")


def cleanup_run(run_dir: Path, *, apply: bool, actions: list[str]) -> None:
    run_date = run_dir.name
    remove_path(run_dir / REMOVED, apply=apply, actions=actions)
    exports = run_dir / "_exports"
    remove_path(exports / f"{REMOVED}-{run_date}.json", apply=apply, actions=actions)
    remove_path(exports / f"{REMOVED}-{run_date}.xlsx", apply=apply, actions=actions)
    remove_path(exports / "dashboard-cache" / run_date / f"{REMOVED}.json", apply=apply, actions=actions)
    rewrite_manifest(exports / "dashboard-cache" / run_date / "manifest.json", apply=apply, actions=actions)
    rewrite_manifest(exports / "dashboard-cache" / "latest.json", apply=apply, actions=actions)
    migrate_db(exports / "local-cdr.sqlite", apply=apply, actions=actions)


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove retired non-banking CDR artifacts from AR-local data.")
    parser.add_argument("--data-root", type=Path, default=data_root(REPO_ROOT))
    parser.add_argument("--apply", action="store_true", help="Apply changes. Without this, only reports actions.")
    args = parser.parse_args()

    root = args.data_root.expanduser().resolve()
    configured = data_root(REPO_ROOT).resolve()
    if root != configured:
        print(f"cleanup_removed_cdr_sector: explicit data root {root}")
    actions: list[str] = []
    for run_dir in iter_run_dirs((root / "runs") if root.name != "runs" else root):
        cleanup_run(run_dir, apply=args.apply, actions=actions)
    for action in actions:
        print(action)
    print(f"cleanup_removed_cdr_sector: {'applied' if args.apply else 'dry-run'} {len(actions)} actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
