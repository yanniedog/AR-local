"""Bounded one-pass callback for the existing root reconciliation timer."""
import os
import json
from pathlib import Path
import re
import stat
import time


def retained_units():
    path = Path("/var/lib/shared-pi-queue/state.json")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        raw = os.read(descriptor, 1048577)
        if not stat.S_ISREG(info.st_mode) or len(raw) != info.st_size or len(raw) > 1048576:
            raise RuntimeError("bounded retained image queue inventory required")
        return {row["unit"] for row in json.loads(raw).get("jobs", []) if isinstance(row, dict) and isinstance(row.get("unit"), str)}
    finally:
        os.close(descriptor)


def one_pass():
    import fcntl
    from pi_system_guard_host import ImageHost, STATE
    from pi_system_guard_policy import finish
    from pi_shared_queue_post_hooks import root_json
    deadline, considered, failures = time.monotonic() + 4.25, 0, 0
    units = retained_units()
    with os.scandir(STATE) as entries:
        for entry in entries:
            if time.monotonic() >= deadline or considered >= 4:
                break
            if not re.fullmatch(r"[a-f0-9]{32}", entry.name) or not entry.is_dir(follow_symlinks=False):
                continue
            host = ImageHost(entry.name)
            host.deadline = deadline
            intent = host.intent(entry.name)
            completed = host.public / "completion.json"
            terminal = root_json(completed) if completed.exists() else {}
            if not intent and "ar-local-plain-backup-" + entry.name + ".service" not in units:
                continue  # Prepared but never submitted packets own no runtime state.
            if intent and intent["phase"] == "RESTORED" and terminal.get("owned_loop_terminal") is True and terminal.get("writers_restored") is True:
                continue
            considered += 1
            descriptor = os.open(host.private / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                finish(host, entry.name, recovery=True)
            except Exception:
                failures += 1  # Retain ambiguous ownership and original evidence.
            finally:
                os.close(descriptor)
    return 2 if failures else 0
