"""Scheduled macro refresh with a hard process deadline and persistent cooldown."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import errno
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cdr_macro_freshness import parse_timestamp

REFRESH_TIMEOUT_SECONDS = 180
MIN_ATTEMPT_INTERVAL_SECONDS = 3600


def _save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _refresh_lock(path: Path):
    """Nonblocking OS ownership; never remove another caller's lock file."""
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            yield False
            return
        # Closing the descriptor releases ownership on normal exit and crash.
        yield True


def refresh_macro_store(store_path: Path, *, repo_root: Path) -> dict:
    """Refresh without delaying banking publication indefinitely or retry storms.

    The attempt is written before launch so process interruption still enforces
    cooldown. Individual source transactions preserve completed work on timeout.
    A nonblocking OS lock rejects concurrent refreshes and is released on
    process exit. Its persistent file is never unlinked or reclaimed by age.
    """
    store_path = Path(store_path).resolve()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = store_path.with_name("macro-refresh-status.json")
    lock = receipt.with_suffix(".lock")
    with _refresh_lock(lock) as acquired:
        if not acquired:
            return {"status": "busy"}
        now = datetime.now(timezone.utc)
        try:
            latest = json.loads(receipt.read_text(encoding="utf-8"))
            recent = parse_timestamp(latest.get("last_attempt_at")) if isinstance(latest, dict) else None
        except (OSError, ValueError):
            latest, recent = {}, None
        if recent and 0 <= (now - recent).total_seconds() < MIN_ATTEMPT_INTERVAL_SECONDS:
            return {"status": "cooldown", "last_attempt_at": latest["last_attempt_at"], "previous_status": latest.get("status")}
        report = {"status": "running", "last_attempt_at": now.isoformat().replace("+00:00", "Z")}
        _save(receipt, report)
        try:
            result = subprocess.run(
                [sys.executable, "-B", str(Path(repo_root) / "cdr_macro_ingest.py"),
                 "--store", str(store_path)], cwd=repo_root, capture_output=True,
                text=True, timeout=REFRESH_TIMEOUT_SECONDS, check=False,
            )
            try:
                sources = json.loads(result.stdout)
            except (TypeError, ValueError):
                sources = {}
            report.update(status="ok" if result.returncode == 0 and sources else "partial",
                          returncode=result.returncode, sources=sources,
                          message=result.stderr[-2000:] if result.returncode else "")
        except subprocess.TimeoutExpired:
            report.update(status="timeout", message="Macro refresh exceeded its time budget; completed sources were retained.")
        except OSError as exc:
            report.update(status="error", message=f"Macro refresh could not start: {type(exc).__name__}")
        report["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _save(receipt, report)
        return report
