"""Bounded child execution with whole-tree cleanup for Pi watchdog workers."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

TERMINATE_GRACE_SECONDS = 30
KILL_WAIT_SECONDS = 10
FORCE_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)


def _terminate_tree(process: subprocess.Popen, grouped: bool, grace: float,
                    kill_wait: float) -> None:
    if not grouped and os.name == "nt":
        # Do not signal a Windows console; terminate only this child and its tree.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       check=False, capture_output=True, shell=False, timeout=kill_wait,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        process.wait(timeout=kill_wait)
        return
    try:
        if grouped:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    # The parent exiting does not prove its children exited. Always finish the
    # process group, even when SIGTERM already reaped the direct child.
    try:
        if grouped:
            os.killpg(process.pid, FORCE_KILL_SIGNAL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    process.wait(timeout=kill_wait)


def run_process_group(cmd: list[str], *, cwd: Path, timeout_seconds: float,
                      env: dict[str, str] | None = None,
                      process_groups_supported: bool | None = None,
                      terminate_grace_seconds: float = TERMINATE_GRACE_SECONDS,
                      kill_wait_seconds: float = KILL_WAIT_SECONDS) -> None:
    grouped = os.name != "nt" if process_groups_supported is None else process_groups_supported
    process = subprocess.Popen(cmd, cwd=cwd, shell=False, start_new_session=grouped,
                               **({"env": env} if env is not None else {}))
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except BaseException:
        _terminate_tree(process, grouped, terminate_grace_seconds, kill_wait_seconds)
        raise
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, cmd)
