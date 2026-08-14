"""Append-only per-generation run journal for ingest and publication stages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

from cdr_atomic import atomic_write_json
from cdr_file_lock import FileLock


class RunStage(str, Enum):
    REGISTER = "register_discovery"
    HOLDERS = "holders"
    NORMALIZATION = "normalization"
    EXPORT = "export"
    LEDGER = "ledger"
    DATED_PUBLICATION = "dated_publication"
    ROLLING_PUBLICATION = "rolling_publication"
    HISTORY = "history"
    ECONOMY = "economic_snapshot"
    RBA = "rba"
    DATES_INDEX = "dates_index"


class StageState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    RETRYABLE_ERROR = "retryable_error"
    PERMANENT_ERROR = "permanent_error"


_ALLOWED = {
    StageState.PENDING: {StageState.RUNNING},
    StageState.RUNNING: {
        StageState.COMPLETE,
        StageState.RETRYABLE_ERROR,
        StageState.PERMANENT_ERROR,
    },
    StageState.RETRYABLE_ERROR: {StageState.RUNNING, StageState.PERMANENT_ERROR},
    StageState.COMPLETE: set(),
    StageState.PERMANENT_ERROR: set(),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class InvalidJournalTransition(RuntimeError):
    pass


class RunJournal:
    def __init__(self, root: Path, generation_id: str) -> None:
        if not generation_id or Path(generation_id).name != generation_id:
            raise ValueError("generation_id must be one safe path segment")
        self.root = root.expanduser().resolve() / generation_id
        self.generation_id = generation_id
        self.events = self.root / "events"
        self.current_path = self.root / "current.json"
        self.lock_path = self.root / ".lock"

    def _initial(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generation_id": self.generation_id,
            "updated_at": utc_now(),
            "sequence": 0,
            "stages": {
                stage.value: {
                    "state": StageState.PENDING.value,
                    "attempts": 0,
                    "error": None,
                    "remote_digest": None,
                    "retry_at": None,
                    "updated_at": None,
                }
                for stage in RunStage
            },
        }

    def read(self) -> dict[str, Any]:
        if not self.current_path.is_file():
            return self._initial()
        payload = json.loads(self.current_path.read_text(encoding="utf-8"))
        if payload.get("generation_id") != self.generation_id:
            raise ValueError("journal generation_id mismatch")
        return payload

    def transition(
        self,
        stage: RunStage,
        state: StageState,
        *,
        error: Optional[Mapping[str, Any]] = None,
        remote_digest: Optional[str] = None,
        retry_at: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        with FileLock(self.lock_path):
            current = self.read()
            stage_record = dict(current["stages"][stage.value])
            previous = StageState(stage_record["state"])
            if state not in _ALLOWED[previous]:
                raise InvalidJournalTransition(
                    f"invalid {stage.value} transition {previous.value} -> {state.value}"
                )
            if state is StageState.RUNNING:
                stage_record["attempts"] = int(stage_record.get("attempts") or 0) + 1
            when = utc_now()
            stage_record.update(
                {
                    "state": state.value,
                    "error": dict(error) if error is not None else None,
                    "remote_digest": remote_digest,
                    "retry_at": retry_at,
                    "updated_at": when,
                }
            )
            sequence = int(current.get("sequence") or 0) + 1
            event = {
                "schema_version": 1,
                "generation_id": self.generation_id,
                "sequence": sequence,
                "stage": stage.value,
                "previous_state": previous.value,
                "state": state.value,
                "attempt": stage_record["attempts"],
                "at": when,
                "error": stage_record["error"],
                "remote_digest": remote_digest,
                "retry_at": retry_at,
                "metadata": dict(metadata or {}),
            }
            event_path = self.events / f"{sequence:06d}-{stage.value}-{state.value}.json"
            atomic_write_json(event_path, event, create_once=True)
            current["stages"][stage.value] = stage_record
            current["sequence"] = sequence
            current["updated_at"] = when
            atomic_write_json(self.current_path, current)
            return event
