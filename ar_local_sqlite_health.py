"""Shared fail-closed SQLite health checks for preservation workflows."""

from __future__ import annotations

import sqlite3
from typing import Any


def check_sqlite_health(connection: sqlite3.Connection) -> dict[str, Any]:
    """Run structural, page-level, and referential checks on one database."""

    quick_rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
    integrity_rows = [
        str(row[0]) for row in connection.execute("PRAGMA integrity_check")
    ]
    foreign_key_violation = connection.execute("PRAGMA foreign_key_check").fetchone()
    return {
        "quick_check": "ok" if quick_rows == ["ok"] else quick_rows,
        "integrity_check": "ok" if integrity_rows == ["ok"] else integrity_rows,
        "foreign_key_check": "ok" if foreign_key_violation is None else "failed",
        **(
            {"foreign_key_violation": list(foreign_key_violation)}
            if foreign_key_violation is not None
            else {}
        ),
    }


def sqlite_health_ok(report: dict[str, Any]) -> bool:
    return all(
        report.get(name) == "ok"
        for name in ("quick_check", "integrity_check", "foreign_key_check")
    )


def require_sqlite_health(
    connection: sqlite3.Connection, *, label: str
) -> dict[str, Any]:
    report = check_sqlite_health(connection)
    if not sqlite_health_ok(report):
        raise ValueError(f"SQLite health check failed for {label}: {report}")
    return report
