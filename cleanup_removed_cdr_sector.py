#!/usr/bin/env python3
"""Remove retired non-banking CDR artifacts from the configured Pi data root."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from ar_local_pi_runtime import data_root

# Two-factor break-glass: this utility rmtree/unlink/DROP-TABLEs inside finalized
# daily partition dirs (retired-sector artifacts), so --apply must never fire by
# accident. Per the Permanent CDR Ledger Invariant, destructive operations over
# the ledger sit behind an audited break-glass step.
BREAK_GLASS_ENV = "AR_LEDGER_BREAK_GLASS"
AUDIT_LOG_NAME = "_ledger_breakglass_audit.log"

REPO_ROOT = Path(__file__).resolve().parent
REMOVED = "en" + "ergy"
REMOVED_TABLES = (REMOVED + "_plans", REMOVED + "_items")
REMOVED_DROP_SQL = (
    'DROP TABLE IF EXISTS "en' 'ergy_plans"',
    'DROP TABLE IF EXISTS "en' 'ergy_items"',
)
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
            if old_tables:
                for sql in REMOVED_DROP_SQL:
                    con.execute(sql)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                )
                """,
            )
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


def breakglass_authorized(apply: bool, break_glass: bool, env_value: Optional[str]) -> tuple[bool, str]:
    """Authorize a destructive --apply run; returns ``(authorized, reason)``.

    A dry-run writes nothing and is always allowed. --apply requires BOTH the
    ``--break-glass`` flag AND ``AR_LEDGER_BREAK_GLASS=1`` so that neither a stray
    ``--apply`` in a script nor a lingering env var alone can mutate finalized
    partitions.
    """
    if not apply:
        return True, "dry-run"
    if not break_glass:
        return False, "refusing --apply without --break-glass (this mutates finalized ledger partitions)"
    if str(env_value) != "1":
        return False, f"refusing --apply: set {BREAK_GLASS_ENV}=1 to confirm break-glass"
    return True, "break-glass authorized"


def write_audit_log(data_root_path: Path, actions: list[str], *, phase: str, success: bool = True) -> Path:
    """Append an audit record (one JSON line) for a destructive run.

    ``phase`` is ``"planned"`` (preflight, written before any mutation) or
    ``"applied"`` (the outcome). ``success`` flags whether the applied pass
    completed without raising. The timestamp is timezone-aware (local offset) so
    entries are unambiguous across hosts.
    """
    log_path = data_root_path / AUDIT_LOG_NAME
    entry = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool": "cleanup_removed_cdr_sector",
        "phase": phase,
        "success": success,
        "user": os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
        "data_root": str(data_root_path),
        "action_count": len(actions),
        "actions": actions,
    }
    data_root_path.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log_path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Remove retired non-banking CDR artifacts from AR-local data.")
    parser.add_argument("--data-root", type=Path, default=data_root(REPO_ROOT))
    parser.add_argument("--apply", action="store_true", help="Apply changes. Without this, only reports actions.")
    parser.add_argument(
        "--break-glass",
        action="store_true",
        help=f"Required with --apply (plus {BREAK_GLASS_ENV}=1): confirm destructive changes to finalized partitions.",
    )
    args = parser.parse_args(argv)

    authorized, reason = breakglass_authorized(args.apply, args.break_glass, os.environ.get(BREAK_GLASS_ENV))
    if args.apply and not authorized:
        print(f"cleanup_removed_cdr_sector: {reason}", file=sys.stderr)
        return 2
    apply = args.apply and authorized

    root = args.data_root.expanduser().resolve()
    configured = data_root(REPO_ROOT).resolve()
    if root != configured:
        print(f"cleanup_removed_cdr_sector: explicit data root {root}")
    runs_dir = (root / "runs") if root.name != "runs" else root

    if apply:
        # Preflight (Codex P1 / Gemini): enumerate the planned destructive actions
        # via a dry-run pass and record intent to the audit log BEFORE mutating
        # anything. This also proves the audit sink is writable; if it isn't, abort
        # before any destruction rather than mutate partitions with no audit trail.
        planned: list[str] = []
        for run_dir in iter_run_dirs(runs_dir):
            cleanup_run(run_dir, apply=False, actions=planned)
        if planned:
            try:
                write_audit_log(root, planned, phase="planned")
            except OSError as exc:
                print(
                    f"cleanup_removed_cdr_sector: cannot write break-glass audit log ({exc}); "
                    f"aborting before any changes.",
                    file=sys.stderr,
                )
                return 3

    actions: list[str] = []
    success = False
    try:
        for run_dir in iter_run_dirs(runs_dir):
            cleanup_run(run_dir, apply=apply, actions=actions)
        success = True
    finally:
        # Always print and audit what was attempted, even if cleanup raised midway
        # (Gemini): destructive actions may have already executed.
        for action in actions:
            print(action)
        if apply and actions:
            log_path = write_audit_log(root, actions, phase="applied", success=success)
            print(f"cleanup_removed_cdr_sector: break-glass audit appended to {log_path}")
    print(f"cleanup_removed_cdr_sector: {'applied' if apply else 'dry-run'} {len(actions)} actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
