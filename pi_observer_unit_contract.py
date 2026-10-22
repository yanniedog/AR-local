"""Strict native readback contract for the unprivileged observation services."""
from __future__ import annotations

import json
from pathlib import PurePosixPath
import re

COMMAND_TYPE = "a(sasasttttuii)"
USERNAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")


def native_property(raw, signature):
    if not isinstance(raw, str) or len(raw) > 16384:
        raise ValueError("missing or oversized native property")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("type") != signature or "data" not in value:
        raise ValueError("unknown native property signature")
    return value["data"]


def unprivileged_user(user, uid):
    return (isinstance(user, str) and USERNAME.fullmatch(user) is not None
            and user != "root" and isinstance(uid, str) and uid.isascii()
            and uid.isdecimal() and 0 < int(uid) < 2**32 - 1)


def canonical_remote_repo(path):
    """Validate a Pi pwd -P result; never resolve a remote path on Windows."""
    if (not isinstance(path, str) or not path.startswith("/") or path.startswith("//")
            or path == "/" or any(char in path for char in "\x00\r\n")
            or ".." in PurePosixPath(path).parts or str(PurePosixPath(path)) != path):
        raise ValueError("missing or noncanonical remote repository readback")
    return path


def command_matches(commands, expected):
    if not isinstance(commands, list) or len(commands) != 1:
        return False
    row = commands[0]
    if (not isinstance(row, list) or len(row) != 10 or row[0] != expected[0]
            or row[1] != expected or row[2] != []):
        return False
    # ExecStartEx retains all modifiers, including +/!/!! privilege bypasses.
    # Reject every modifier; a legacy ExecStart boolean is insufficient proof.
    bounds = [(0, 2**64)] * 4 + [(0, 2**32)] + [(-2**31, 2**31)] * 2
    return all(type(value) is int and low <= value < high
               for value, (low, high) in zip(row[3:], bounds))


def watchdog_snapshot_ok(snap):
    try:
        repo = canonical_remote_repo(snap.get("AR_REPO_PHYSICAL"))
        user, uid = snap.get("DAILY_USER"), snap.get("DAILY_USER_UID")
        return (unprivileged_user(user, uid)
                and native_property(snap.get("WATCHDOG_USER_JSON"), "s") == user
                and command_matches(native_property(snap.get("WATCHDOG_EXEC_JSON"), COMMAND_TYPE),
                                    ["/usr/bin/python3", "-B", repo + "/pi_ingest_observe.py"])
                and snap.get("WATCHDOG_ACTIVE_STATE") in {"inactive", "failed"}
                and snap.get("WATCHDOG_SUB_STATE") in {"dead", "failed"}
                and snap.get("WATCHDOG_MAIN_PID") == "0" and snap.get("WATCHDOG_CONTROL_PID") == "0")
    except (ValueError, TypeError):
        return False
