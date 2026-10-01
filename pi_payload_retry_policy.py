"""Bound low-priority publication retries around the mandatory natural ingest."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import nullcontext
from datetime import datetime, time as daytime, timedelta, timezone
from pathlib import Path

from ar_local_ingest_schedule import DAILY_INGEST_TZ
from ar_local_pi_runtime import data_state_root
from cdr_atomic import atomic_write_json, canonical_json_bytes
from cdr_file_lock import FileLock

PAYLOAD_TIMEOUT_SECONDS = 30 * 60
CLEANUP_SECONDS = 45
RETRY_BASE_SECONDS = 60 * 60
RETRY_MAX_SECONDS = 6 * 60 * 60
RETRY_STATE_DIRECTORY = "app-payload-retries"


def payload_retry_window_reason(now_utc: datetime | None = None) -> str:
    now = now_utc or datetime.now(timezone.utc)
    local = now.astimezone(DAILY_INGEST_TZ)
    if not daytime(3, 30) <= local.time() < daytime(22):
        return "protected_natural_ingest_window"
    closing = local.replace(hour=22, minute=0, second=0, microsecond=0)
    if (closing - local).total_seconds() < PAYLOAD_TIMEOUT_SECONDS + CLEANUP_SECONDS:
        return "insufficient_publication_window"
    return ""


def publication_source_key(pending: dict) -> str:
    # Failure reason/time can change while retrying the same immutable source.
    pointer = pending.get("pointer")
    source = pointer if isinstance(pointer, dict) and pointer else pending
    return hashlib.sha256(canonical_json_bytes(source)).hexdigest()


def publication_retry_candidates(pending: dict) -> list[dict]:
    """Keep the legacy head and every queued immutable pointer eligible to retry."""
    if not pending:
        return []
    result = [pending]
    seen = {publication_source_key(pending)}
    queued = pending.get("queued_pointers")
    for pointer in queued if isinstance(queued, list) else []:
        if not isinstance(pointer, dict) or not pointer:
            continue
        candidate = {"pointer": pointer}
        key = publication_source_key(candidate)
        if key not in seen:
            result.append(candidate)
            seen.add(key)
    return result


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("retry timestamp requires a timezone")
    return parsed.astimezone(timezone.utc)


def retry_state_path(repo_root: Path, source_key: str) -> Path:
    if len(source_key) != 64 or any(char not in "0123456789abcdef" for char in source_key):
        raise ValueError("invalid publication source key")
    return data_state_root(repo_root) / RETRY_STATE_DIRECTORY / f"{source_key}.json"


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or not isinstance(value.get("source_key"), str)
            or not isinstance(value.get("attempts"), int) or value["attempts"] < 1):
        raise ValueError("invalid publication retry state")
    _timestamp(value["next_attempt_at"])
    return value


def retry_admission(repo_root: Path, pending: dict, *, now_utc: datetime | None = None,
                    reserve: bool = False) -> dict:
    """Reserve before spawning so a killed watchdog also observes a cooldown."""
    now = now_utc or datetime.now(timezone.utc)
    reason = payload_retry_window_reason(now)
    if reason:
        return {"status": "deferred", "reason": reason}
    source_key = publication_source_key(pending)
    path = retry_state_path(repo_root, source_key)
    with FileLock(path.with_suffix(".lock")) if reserve else nullcontext():
        try:
            previous = _read_state(path)
        except (OSError, ValueError, KeyError, TypeError):
            return {"status": "deferred", "reason": "publication_retry_state_unreadable"}
        if previous and previous.get("source_key") != source_key:
            return {"status": "deferred", "reason": "publication_retry_source_mismatch"}
        if previous and now < _timestamp(previous["next_attempt_at"]):
            return {"status": "deferred", "reason": "publication_retry_cooldown",
                    "next_attempt_at": previous["next_attempt_at"]}
        attempt = int(previous.get("attempts", 0)) + 1
        delay = min(RETRY_BASE_SECONDS * 2 ** min(attempt - 1, 3), RETRY_MAX_SECONDS)
        record = {"schema_version": 1, "source_key": source_key, "attempts": attempt,
                  "attempt_id": uuid.uuid4().hex, "status": "running",
                  "started_at": now.isoformat(), "cooldown_seconds": delay,
                  "next_attempt_at": (now + timedelta(
                      seconds=PAYLOAD_TIMEOUT_SECONDS + CLEANUP_SECONDS + delay)).isoformat()}
        if reserve:
            atomic_write_json(path, record)
        return {**record, "status": "ready"}


def finish_retry(repo_root: Path, reservation: dict, *, succeeded: bool,
                 reason: str = "", now_utc: datetime | None = None) -> None:
    """Preserve a concurrent newer source reservation and back off from completion."""
    now = now_utc or datetime.now(timezone.utc)
    path = retry_state_path(repo_root, reservation["source_key"])
    with FileLock(path.with_suffix(".lock")):
        previous = _read_state(path)
        if previous.get("attempt_id") != reservation.get("attempt_id"):
            return
        previous.update(status="published" if succeeded else "failed", reason=reason,
                        finished_at=now.isoformat(),
                        next_attempt_at=(now + timedelta(
                            seconds=previous["cooldown_seconds"])).isoformat())
        atomic_write_json(path, previous)
