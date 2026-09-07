"""Read authenticated runtime ancestry without rewriting backup evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Mapping

import laptop_backup_scheduled_lineage as lineage
import laptop_pull_backup as receiver

MAX_RECORDS = 4096
MAX_RECORD_BYTES = 1024 * 1024


def _successful_inventory(record: Mapping[str, object]) -> bool:
    detail = record.get("detail")
    status = detail.get("after", detail) if isinstance(detail, Mapping) else None
    return (record.get("result") == "PASS" and isinstance(status, Mapping)
            and status.get("status") == "UP_TO_DATE")


def _pair(record: Mapping[str, object]) -> tuple[str, str]:
    pair = record.get("protected_code_sha"), record.get("candidate_code_sha")
    if any(not isinstance(value, str) or not receiver.COMMIT_RE.fullmatch(value) for value in pair):
        raise ValueError("runtime ancestry contains an invalid runtime identity")
    return pair


class _Records:
    def __init__(self, target: Path, expected: Mapping[str, object]) -> None:
        self.target = target.resolve(strict=True)
        self.expected = expected
        self.cache: dict[str, tuple[str, dict]] = {}
        self.by_digest: dict[str, dict[str, str]] | None = None

    def read(self, pointer: Mapping[str, object]) -> dict:
        if not isinstance(pointer, Mapping) or set(pointer) != {"record_path", "record_sha256"}:
            raise ValueError("runtime ancestry link is incomplete")
        relative, digest = pointer["record_path"], pointer["record_sha256"]
        parts = PurePosixPath(relative).parts if isinstance(relative, str) else ()
        if (len(parts) != 3 or parts[:2] != ("catalog", "scheduled-runs")
                or not parts[-1].endswith(".json") or not isinstance(digest, str)
                or not lineage.SHA256.fullmatch(digest)):
            raise ValueError("runtime ancestry link is invalid")
        if relative not in self.cache:
            if len(self.cache) >= MAX_RECORDS:
                raise ValueError("runtime ancestry exceeds its record bound")
            path = lineage.safe_path(self.target, relative)
            if not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
                raise ValueError("runtime ancestry record exceeds its size bound")
            payload = path.read_bytes()
            if len(payload) > MAX_RECORD_BYTES:
                raise ValueError("runtime ancestry record exceeds its size bound")
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("runtime ancestry record is not an object")
            self.cache[relative] = hashlib.sha256(payload).hexdigest(), value
        actual, value = self.cache[relative]
        if actual != digest:
            raise ValueError("runtime ancestry record digest mismatch")
        if "previous_execution" not in value:
            raise ValueError("runtime ancestry predecessor link is missing")
        production, candidate = _pair(value)
        # The hash-bound link authenticates the runtime pair. Retain the existing
        # strict operator, controlled-plan, timestamp and outcome envelope checks.
        lineage._validate_owned_record(value, {
            **self.expected, "protected_code_sha": production,
            "candidate_code_sha": candidate, "runtime_predecessor": {},
        })
        return value

    def find(self, digest: str) -> dict[str, str]:
        if self.by_digest is None:
            self.by_digest = {}
            root = lineage.safe_path(self.target, "catalog/scheduled-runs")
            paths = sorted(root.glob("*.json"))
            if len(paths) > MAX_RECORDS:
                raise ValueError("runtime ancestry exceeds its record bound")
            for path in paths:
                relative = path.relative_to(self.target).as_posix()
                safe = lineage.safe_path(self.target, relative)
                if not safe.is_file() or safe.stat().st_size > MAX_RECORD_BYTES:
                    raise ValueError("runtime ancestry record exceeds its size bound")
                payload = safe.read_bytes()
                if len(payload) > MAX_RECORD_BYTES:
                    raise ValueError("runtime ancestry record exceeds its size bound")
                actual = hashlib.sha256(payload).hexdigest()
                if actual in self.by_digest:
                    raise ValueError("runtime ancestry receipt is ambiguous")
                self.by_digest[actual] = {"record_path": relative, "record_sha256": actual}
        if digest not in self.by_digest:
            raise ValueError("runtime ancestry differs from the pinned receipt")
        return self.by_digest[digest]

    def pinned(self, runtime: Mapping[str, object]) -> dict[str, str]:
        from laptop_backup_runtime_transition import validate_previous

        value = validate_previous(runtime)
        pointer = self.find(value["record_sha256"])
        record = self.read(pointer)
        if (_pair(record) != (value["production_sha"], value["receiver_sha"])
                or not _successful_inventory(record)):
            raise ValueError("runtime ancestry pin is not the exact successful predecessor")
        return pointer


def authenticated_runtime_pairs(
    target: Path, runtime: Mapping[str, object], expected: Mapping[str, object]
) -> frozenset[tuple[str, str]]:
    """Only successful pairs reachable from the config-pinned PASS grant coverage."""
    records = _Records(target, expected)
    root = records.pinned(runtime)
    stack = [(root, False)]
    active: set[str] = set()
    finished: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    while stack:
        pointer, leaving = stack.pop()
        key = pointer.get("record_path") if isinstance(pointer, Mapping) else None
        if not isinstance(key, str):
            raise ValueError("runtime ancestry link is incomplete")
        if leaving:
            active.remove(key)
            finished.add(key)
            continue
        if key in active:
            raise ValueError("runtime ancestry contains a cycle")
        value = records.read(pointer)  # Validate even a repeated link's digest.
        if key in finished:
            continue
        active.add(key)
        stack.append((pointer, True))
        if _successful_inventory(value):
            pairs.add(_pair(value))
        if value.get("runtime_predecessor") is not None:
            stack.append((records.pinned(value["runtime_predecessor"]), False))
        previous = value.get("previous_execution")
        if previous is not None:
            stack.append((previous, False))
    return frozenset(pairs)


def authenticate_pointer_descendant(
    target: Path, pointer: Mapping[str, str], expected: Mapping[str, object]
) -> None:
    """Allow a failed attempt to remain lineage, without promoting it to a PASS."""
    runtime = expected["runtime_predecessor"]
    authenticated_runtime_pairs(target, runtime, expected)
    records = _Records(target, expected)
    anchor = records.pinned(runtime)
    current = {key: pointer[key] for key in ("record_path", "record_sha256")}
    allowed = {
        (expected["protected_code_sha"], expected["candidate_code_sha"]),
        (runtime["production_sha"], runtime["receiver_sha"]),
        # A receiver update may follow a failed attempt on the now-authorized
        # production release using the receiver authenticated by the PASS pin.
        (expected["protected_code_sha"], runtime["receiver_sha"]),
    }
    seen: set[str] = set()
    while True:
        if current["record_path"] in seen:
            raise ValueError("runtime descendant lineage contains a cycle")
        seen.add(current["record_path"])
        value = records.read(current)
        if _pair(value) not in allowed:
            raise ValueError("runtime descendant contains a foreign runtime identity")
        if current == anchor:
            return
        if value.get("runtime_predecessor") is not None:
            if value["runtime_predecessor"] != runtime:
                raise ValueError("runtime descendant changed the pinned predecessor")
        previous = value.get("previous_execution")
        if previous is None:
            raise ValueError("runtime descendant is not bound to the pinned receipt")
        records.read(previous)
        current = previous
