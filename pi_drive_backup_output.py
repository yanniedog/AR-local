"""Bounded-memory reading of completed Restic command output.

Backup JSON progress can grow throughout a multi-hour upload. Read one bounded
record at a time and retain only its unique final snapshot summary. Other
commands keep their existing whole-output limit. Child exit and private stderr
validation remain the caller's responsibility, before using this reader.
"""
from __future__ import annotations

import json
import re
import time
from typing import BinaryIO, Callable

MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_BACKUP_RECORD_BYTES = 1024 * 1024


def _invalid_constant(_value):
    raise ValueError("non-finite JSON number")


def backup_summary(stream: BinaryIO, *, guard: Callable[[], None]) -> str:
    """Consume bounded JSON lines, never accumulate discarded progress."""
    summary = None
    deadline = time.monotonic() + 60
    while True:
        guard()
        if time.monotonic() >= deadline:
            raise RuntimeError("restic backup output processing deadline exceeded")
        raw = stream.readline(MAX_BACKUP_RECORD_BYTES + 1)
        if not raw:
            break
        if len(raw) > MAX_BACKUP_RECORD_BYTES:
            raise RuntimeError("restic backup JSON record exceeded bounded receipt limit")
        if not raw.strip():
            continue
        try:
            text = raw.decode("utf-8")
            row = json.loads(text, parse_constant=_invalid_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise RuntimeError("restic backup output contains invalid JSON") from None
        if not isinstance(row, dict) or not isinstance(row.get("message_type"), str):
            raise RuntimeError("restic backup output contains an invalid message")
        if summary is not None:
            raise RuntimeError("restic backup summary was not the unique final message")
        if row["message_type"] == "summary":
            if (not isinstance(row.get("snapshot_id"), str)
                    or not re.fullmatch(r"[0-9a-f]{8,64}", row["snapshot_id"])
                    or row.get("dry_run", False) is not False):
                raise RuntimeError("restic backup did not return a real snapshot identity")
            summary = text
    if summary is None:
        raise RuntimeError("restic backup did not return exactly one snapshot identity")
    return summary


def command_output(stream: BinaryIO, arguments: tuple[str, ...], *, guard: Callable[[], None]) -> str:
    stream.seek(0)
    if arguments[0] == "backup" and "--json" in arguments:
        return backup_summary(stream, guard=guard)
    output = stream.read(MAX_OUTPUT_BYTES + 1)
    if len(output) > MAX_OUTPUT_BYTES:
        raise RuntimeError("restic command output exceeded bounded receipt limit")
    return output.decode("utf-8")
