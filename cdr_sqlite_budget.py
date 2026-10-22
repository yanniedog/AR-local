"""Cooperative deadlines for SQLite verification, inactive outside an audit scope."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar


# Reserve fifteen minutes of the restore unit's four-hour limit for cleanup
# and its failure receipt. Blocking filesystem I/O is not a hard timed bound.
RESTORE_BUDGET_SECONDS = 4 * 60 * 60 - 15 * 60
SQLITE_BUDGET_SECONDS = 5 * 60
_deadline: ContextVar[float | None] = ContextVar("sqlite_audit_deadline", default=None)


def current_deadline() -> float | None:
    return _deadline.get()


def check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("SQLite restore verification deadline exceeded")


@contextmanager
def audit_budget(deadline: float):
    """Nested verification and newly opened connections share the earlier limit."""
    previous = current_deadline()
    deadline = min(deadline, previous) if previous is not None else deadline
    check_deadline(deadline)
    token = _deadline.set(deadline)
    try:
        try:
            yield
            check_deadline(deadline)
        except sqlite3.OperationalError:
            check_deadline(deadline)
            raise
    finally:
        _deadline.reset(token)


def install_progress_deadline(connection: sqlite3.Connection) -> None:
    """Install only on an owned audit connection; ordinary callers are unchanged."""
    deadline = current_deadline()
    if deadline is not None:
        check_deadline(deadline)
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)


@contextmanager
def sqlite_budget(connection: sqlite3.Connection):
    previous = current_deadline()
    try:
        with audit_budget(time.monotonic() + SQLITE_BUDGET_SECONDS):
            install_progress_deadline(connection)
            yield
    finally:
        # Keep an enclosing audit's guard for subsequent reconciliation SQL.
        callback = None if previous is None else lambda: int(time.monotonic() >= previous)
        connection.set_progress_handler(callback, 0 if previous is None else 1000)
