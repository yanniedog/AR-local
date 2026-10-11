"""Pure, fail-closed admission rules for a demand-driven shared Pi queue.

This module starts no processes and has no persistent state. Callers must hold
their queue transaction lock while checking admission and marking a job running.
Resource declarations are a contract: cooperating jobs must declare every
resource they can mutate. The reserved resource ``host`` excludes all jobs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

AR_PROJECT = "ar-local"
AR_PRIORITY_WAIT_SECONDS = 7200
MAX_DURATION_SECONDS = 21600
MAX_OTHER_DURATION_SECONDS = 1800
CPU_SLOT_BUDGET = 3
STOP_GRACE_SECONDS = 60
MAX_QUEUE_JOBS = 1024
_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")


@dataclass(frozen=True)
class _Job:
    id: str
    project: str
    resources: frozenset[str]
    mode: str
    ready_since: datetime
    sequence: int
    max_duration_seconds: int
    state: str
    cpu_slots: int
    unit: str | None


def _aware(value: object) -> datetime:
    if isinstance(value, str) and len(value) <= 64:
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return value


def _name(value: object) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError("invalid job, project or resource name")
    return value


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid bounded integer")
    return value


def _parse(record: Mapping, now: datetime) -> _Job:
    if not isinstance(record, Mapping):
        raise ValueError("job must be an object")
    resources = record["resources"]
    if not isinstance(resources, (list, tuple)) or not 1 <= len(resources) <= 32:
        raise ValueError("resources must be a bounded nonempty list")
    names = frozenset(_name(resource) for resource in resources)
    if len(names) != len(resources):
        raise ValueError("duplicate resources")
    ready = _aware(record["ready_since"])
    if ready > now:
        raise ValueError("job ready time is in the future")
    mode, state = record["mode"], record["state"]
    if mode not in ("shared", "exclusive") or state not in ("waiting", "running"):
        raise ValueError("invalid mode or state")
    project = _name(record["project"])
    duration = _integer(record["max_duration_seconds"], 1,
                        MAX_DURATION_SECONDS if project == AR_PROJECT else MAX_OTHER_DURATION_SECONDS)
    cpu_slots = _integer(record.get("cpu_slots", 1), 1,
                         CPU_SLOT_BUDGET if project == AR_PROJECT else 1)
    unit = _name(record["unit"]) if "unit" in record else None
    return _Job(
        _name(record["id"]), project, names, mode, ready,
        _integer(record["sequence"], 0, 2**63 - 1),
        duration, state, cpu_slots, unit,
    )


def _conflicts(left: _Job, right: _Job) -> bool:
    if "host" in left.resources or "host" in right.resources:
        return True
    return bool(left.resources & right.resources) and (
        left.mode == "exclusive" or right.mode == "exclusive"
    )


def _protected(now: datetime) -> tuple[bool, datetime]:
    """Reserve the pre-ingest quiet window, 00:30 through 02:00 Hobart.

    Ongoing ingest retains its running resource/CPU leases after 02:00, so the
    fixed boundary never authorizes overlap with a still-running ingest job.
    """
    local = now.astimezone(ZoneInfo("Australia/Hobart"))
    start = local.replace(hour=0, minute=30, second=0, microsecond=0)
    end = local.replace(hour=2, minute=0, second=0, microsecond=0)
    critical = start <= local < end
    if local >= start:
        start += timedelta(days=1)
    return critical, start


def _protected_ingest(job: _Job) -> bool:
    # Unit identity must be verified by the caller against systemd. The missing
    # unit case supports pure logical clients; production must supply a unit.
    return job.project == AR_PROJECT and job.unit in (
        None, "ar-local-daily.service", "ar-local-daily-watchdog.service"
    )


def _priority(job: _Job, now: datetime, critical: bool) -> bool:
    if critical:
        return _protected_ingest(job)
    return job.project == AR_PROJECT and (
        (now - job.ready_since).total_seconds() >= AR_PRIORITY_WAIT_SECONDS
    )


def admission(job: Mapping, jobs: Sequence[Mapping], now: datetime) -> tuple[bool, str]:
    """Return eligibility and a stable reason; invalid or ambiguous state denies.

    Running jobs are never preempted. Waiting conflicts are FIFO by sequence,
    except protected daily ingest receives quiet-window priority and AR-local
    receives priority after two hours outside that window. Other work, including
    manual AR-local publication, cannot run into the reserved daily window.
    Every AR-local job must name ``ar-local`` as a resource; host-wide jobs may
    additionally name ``host``. Names do not grant authority to impersonate a
    project: authenticating requests belongs to the queue's caller.
    """
    try:
        now = _aware(now)
        if not isinstance(jobs, (list, tuple)) or len(jobs) > MAX_QUEUE_JOBS:
            raise ValueError("invalid queue size")
        candidate = _parse(job, now)
        records = [_parse(record, now) for record in jobs]
        if len({record.id for record in records}) != len(records):
            raise ValueError("duplicate job ids")
        if len({record.sequence for record in records}) != len(records):
            raise ValueError("duplicate queue sequences")
        for record in [candidate, *records]:
            if record.project == AR_PROJECT and AR_PROJECT not in record.resources:
                raise ValueError("AR-local resource must be declared")
        same = [record for record in records if record.id == candidate.id]
        if same and same[0] != candidate:
            raise ValueError("candidate differs from its queued record")
        if not same and any(record.sequence == candidate.sequence for record in records):
            raise ValueError("candidate sequence already exists")
        critical, next_start = _protected(now)
        if candidate.state != "waiting":
            return False, "already-running"
        others = [record for record in records if record.id != candidate.id]
        running_slots = sum(record.cpu_slots for record in others if record.state == "running")
        if running_slots > CPU_SLOT_BUDGET:
            raise ValueError("running jobs exceed the host budget")
        if any(record.state == "running" and _conflicts(candidate, record) for record in others):
            return False, "running-conflict"
        if running_slots + candidate.cpu_slots > CPU_SLOT_BUDGET:
            return False, "cpu-capacity"
        if not _protected_ingest(candidate):
            # Reserve the ingest budget even before its daily invocation has
            # registered. A disjoint or manual newcomer could consume a core
            # and leave the subsequent three-core ingest blocked for its lease.
            if critical:
                return False, "protected-ingest-window"
            if now + timedelta(seconds=candidate.max_duration_seconds + STOP_GRACE_SECONDS) >= next_start:
                return False, "would-cross-ingest-start"
        promoted = _priority(candidate, now, critical)
        promoted_waiters = []
        for other in others:
            if other.state != "waiting":
                continue
            other_promoted = _priority(other, now, critical)
            precedes = (other_promoted and not promoted) or (
                other_promoted == promoted and other.sequence < candidate.sequence
            )
            if other_promoted and precedes:
                promoted_waiters.append(other)
            if not _conflicts(candidate, other):
                continue
            if precedes:
                return False, "ar-local-priority" if other_promoted and not promoted else "earlier-conflicting-job"
        running = [other for other in others if other.state == "running"]
        reserved = []
        reserved_slots = 0
        for other in sorted(promoted_waiters, key=lambda record: record.sequence):
            if any(_conflicts(other, owner) for owner in [*running, *reserved]):
                continue
            if running_slots + reserved_slots + other.cpu_slots <= CPU_SLOT_BUDGET:
                reserved.append(other)
                reserved_slots += other.cpu_slots
        if running_slots + candidate.cpu_slots + reserved_slots > CPU_SLOT_BUDGET:
            return False, "ar-local-cpu-reservation"
        return True, "admitted"
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return False, "invalid-state"
