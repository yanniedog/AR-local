#!/usr/bin/env python3
"""Shared Pi queue claim wrapping for protected deploy mutations."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Optional

SHARED_QUEUE_WAIT_TIMEOUT_SEC = 45
SHARED_QUEUE_MAX_RUNTIME_SEC = 90
SHARED_QUEUE_SSH_TIMEOUT_SEC = (
    SHARED_QUEUE_WAIT_TIMEOUT_SEC + 60 + SHARED_QUEUE_MAX_RUNTIME_SEC + 30
)
SHARED_QUEUE_STATE = Path("/var/lib/shared-pi-queue/state.json")
SHARED_QUEUE_UNIT_RE = re.compile(
    r"((?:ar-local-queue-task-|shared-pi-task-)[0-9a-f]{32})\.service"
)
EXIT_CONFIG = 2


def _read_self_cgroup() -> str:
    try:
        return Path("/proc/self/cgroup").read_text(encoding="utf-8")
    except OSError:
        return ""


def already_under_shared_queue() -> bool:
    """True when this process runs under a transient shared-queue unit name."""

    return SHARED_QUEUE_UNIT_RE.search(_read_self_cgroup()) is not None


def _queue_job_for_unit(unit: str) -> Optional[dict]:
    path = SHARED_QUEUE_STATE
    try:
        if path.is_symlink() or path.parent.is_symlink():
            return None
        raw = path.read_text(encoding="utf-8")
        if len(raw.encode("utf-8")) > 1024 * 1024:
            return None
        state = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return None
    jobs = state.get("jobs") if isinstance(state, dict) else None
    if not isinstance(jobs, list):
        return None
    matches = [j for j in jobs if isinstance(j, dict) and j.get("unit") == unit]
    return matches[0] if len(matches) == 1 else None


def inherited_queue_admission(*, require_host: bool = False) -> str:
    """Classify reuse of an inherited queue claim: reuse | admit | refuse."""

    match = SHARED_QUEUE_UNIT_RE.search(_read_self_cgroup())
    if match is None:
        return "admit"
    job = _queue_job_for_unit(f"{match.group(1)}.service")
    resources = job.get("resources") if isinstance(job, dict) else None
    if (
        not isinstance(job, dict)
        or job.get("project") != "ar-local"
        or job.get("mode") != "exclusive"
        or not isinstance(resources, list)
        or "ar-local" not in resources
        or (require_host and "host" not in resources)
    ):
        return "refuse"
    return "reuse"


def wrap_shared_queue(
    shell_cmd: str,
    *,
    require_host: bool = False,
    max_runtime: int = SHARED_QUEUE_MAX_RUNTIME_SEC,
    wait_timeout: int = SHARED_QUEUE_WAIT_TIMEOUT_SEC,
) -> str:
    """Wrap a shell command so it acquires the required shared Pi queue claim.

    Fail-closed when ``pi-shared-task`` is missing or an inherited queue unit
    lacks exclusive ``ar-local`` (and ``host`` when required). Skip wrapping only
    when those exclusive resources are already proven held.
    """

    decision = inherited_queue_admission(require_host=require_host)
    if decision == "reuse":
        return shell_cmd
    needed = "ar-local+host" if require_host else "ar-local"
    if decision == "refuse":
        return (
            "echo 'pi_deploy_verify: inherited queue claim insufficient "
            f"(need exclusive {needed}); refusing deploy mutation' >&2; "
            f"exit {EXIT_CONFIG}"
        )
    resources = "--resource ar-local"
    if require_host:
        resources += " --resource host"
    inner = shlex.quote(shell_cmd)
    return (
        "if ! command -v pi-shared-task >/dev/null 2>&1; then "
        "echo 'pi_deploy_verify: pi-shared-task required for deploy mutations; "
        "refusing unqueued production change' >&2; "
        f"exit {EXIT_CONFIG}; "
        "fi; "
        f"pi-shared-task --project ar-local {resources} --cpu-slots 1 "
        f"--max-runtime {int(max_runtime)} --wait-timeout {int(wait_timeout)} -- "
        f"/bin/bash -lc {inner}"
    )
