"""Immutable, sanitized evidence for every bounded CDR HTTP attempt."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from cdr_atomic import atomic_write_bytes, atomic_write_json, canonical_json_bytes
from cdr_file_lock import FileLock
from cdr_http_policy import DEFAULT_HTTP_POLICY, RedirectEvidence, sanitize_url


SCHEMA_VERSION = 1
MAX_EVIDENCE_BODY_BYTES = 32 * 1024 * 1024
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|cookie|credential|password|secret|signature|token|api[_-]?key)",
    re.IGNORECASE,
)
_REQUEST_HEADER_ALLOWLIST = frozenset(
    {"accept", "accept-encoding", "user-agent", "x-v", "x-min-v"}
)
_RESPONSE_HEADER_ALLOWLIST = frozenset(
    {"content-encoding", "content-length", "content-type", "date", "retry-after", "x-v"}
)


class AttemptJournalError(RuntimeError):
    """Raised when immutable attempt evidence is invalid or inconsistent."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise AttemptJournalError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AttemptJournalError(f"{label} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AttemptJournalError(f"{label} lacks a timezone")
    return parsed.astimezone(timezone.utc)


def new_session_id(prefix: str = "ingest") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}-{stamp}-{os.urandom(6).hex()}"


def _digest_json(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _bounded_text(value: Any, limit: int = 512) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _sanitize_error(value: Any) -> Optional[str]:
    text = _bounded_text(value, 512)
    if not text:
        return None
    return re.sub(r"https?://[^\s]+", lambda match: sanitize_url(match.group(0)), text)


def _sanitize_headers(
    headers: Optional[Mapping[str, Any]],
    allowlist: frozenset[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_name, raw_value in (headers or {}).items():
        name = str(raw_name).strip().lower()
        if name in allowlist:
            result[name] = _bounded_text(raw_value, 512)
    return dict(sorted(result.items()))


def _sanitize_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if _SENSITIVE_KEY_RE.search(key):
        return "[REDACTED]"
    if depth >= 4:
        return "[TRUNCATED]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _bounded_text(value, 512)
    if isinstance(value, Mapping):
        items = sorted(value.items(), key=lambda item: str(item[0]))[:64]
        return {
            _bounded_text(name, 128): _sanitize_value(item, key=str(name), depth=depth + 1)
            for name, item in items
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item, depth=depth + 1) for item in value[:128]]
    return _bounded_text(value, 512)


def _sanitize_redirects(redirects: Iterable[Any]) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(redirects):
        if index >= DEFAULT_HTTP_POLICY.max_redirects:
            raise AttemptJournalError("redirect evidence exceeds the policy limit")
        if isinstance(item, RedirectEvidence):
            status, source, target = item.status, item.source_url, item.target_url
        elif isinstance(item, Mapping):
            status = item.get("status")
            source = item.get("source_url")
            target = item.get("target_url")
        else:
            raise AttemptJournalError("redirect evidence must be a mapping")
        result.append(
            {
                "status": int(status),
                "source_url": sanitize_url(str(source or "")),
                "target_url": sanitize_url(str(target or "")),
            }
        )
    return result


class RawAttemptJournal:
    """Create-once response bodies plus a hash-chained attempt event sequence."""

    def __init__(
        self,
        root: Path,
        session_id: str,
        *,
        fault_injector: Optional[Callable[[str], None]] = None,
    ) -> None:
        safe_session_id = str(session_id or "")
        session_stem = safe_session_id.upper().split(".", 1)[0]
        if (
            not _SESSION_RE.fullmatch(safe_session_id)
            or safe_session_id.endswith((".", " "))
            or session_stem in _WINDOWS_RESERVED_STEMS
        ):
            raise ValueError("session_id must be one safe path segment")
        self.base_root = root.expanduser().resolve()
        self.session_id = safe_session_id
        self.root = self.base_root / safe_session_id
        self.events = self.root / "events"
        self.keys = self.root / "keys"
        self.bodies = self.root / "bodies"
        self.current_path = self.root / "current.json"
        self.lock_path = self.root / ".lock"
        self._fault_injector = fault_injector
        self._thread_lock = threading.Lock()

    def _fault(self, stage: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(stage)

    def _initial(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "sequence": 0,
            "head_digest": None,
            "updated_at": None,
        }

    def _read_current(self) -> dict[str, Any]:
        if not self.current_path.is_file():
            return self._initial()
        try:
            current = json.loads(self.current_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AttemptJournalError("attempt journal current pointer is unreadable") from error
        if not isinstance(current, dict):
            raise AttemptJournalError("attempt journal current pointer must be an object")
        if current.get("schema_version") != SCHEMA_VERSION:
            raise AttemptJournalError("attempt journal schema version mismatch")
        if current.get("session_id") != self.session_id:
            raise AttemptJournalError("attempt journal session mismatch")
        sequence = current.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise AttemptJournalError("attempt journal sequence is invalid")
        return current

    @staticmethod
    def _event_digest(event: Mapping[str, Any]) -> str:
        payload = dict(event)
        payload.pop("event_digest", None)
        return _digest_json(payload)

    def _validate_event(
        self,
        path: Path,
        *,
        sequence: int,
        previous_digest: Optional[str],
    ) -> dict[str, Any]:
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AttemptJournalError(f"attempt event {path.name} is unreadable") from error
        if not isinstance(event, dict):
            raise AttemptJournalError(f"attempt event {path.name} must be an object")
        expected = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "sequence": sequence,
            "previous_event_digest": previous_digest,
        }
        if any(event.get(name) != value for name, value in expected.items()):
            raise AttemptJournalError(f"attempt event {path.name} breaks sequence continuity")
        key_hash = event.get("attempt_key_hash")
        identity_digest = event.get("attempt_identity_digest")
        if not isinstance(key_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", key_hash):
            raise AttemptJournalError(f"attempt event {path.name} key digest is invalid")
        if path.name != f"{sequence:08d}-{key_hash[:16]}.json":
            raise AttemptJournalError(f"attempt event {path.name} filename is invalid")
        if not isinstance(identity_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", identity_digest
        ):
            raise AttemptJournalError(f"attempt event {path.name} identity digest is invalid")
        identity_names = ("request", "response", "redirects", "context", "body_path")
        if any(name not in event for name in identity_names):
            raise AttemptJournalError(f"attempt event {path.name} identity is incomplete")
        identity = {name: event[name] for name in identity_names}
        if identity_digest != _digest_json(identity):
            raise AttemptJournalError(f"attempt event {path.name} identity digest mismatch")
        digest = event.get("event_digest")
        if not isinstance(digest, str) or digest != self._event_digest(event):
            raise AttemptJournalError(f"attempt event {path.name} digest mismatch")
        return event

    def _pointer_for(self, event: Mapping[str, Any], event_name: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "attempt_key_hash": event["attempt_key_hash"],
            "attempt_identity_digest": event["attempt_identity_digest"],
            "sequence": event["sequence"],
            "event_path": event_name,
            "event_digest": event["event_digest"],
        }

    def _install_pointer(self, event: Mapping[str, Any], event_name: str) -> None:
        key_path = self.keys / f"{event['attempt_key_hash']}.json"
        atomic_write_json(key_path, self._pointer_for(event, event_name), create_once=True)

    def _advance_current(self, event: Mapping[str, Any]) -> dict[str, Any]:
        current = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "sequence": event["sequence"],
            "head_digest": event["event_digest"],
            "updated_at": event["response"]["completed_at"],
        }
        atomic_write_json(self.current_path, current)
        return current

    def _recover(self, current: dict[str, Any]) -> dict[str, Any]:
        """Complete event -> key -> current suffixes left by an interrupted writer."""
        while True:
            sequence = int(current["sequence"]) + 1
            candidates = sorted(self.events.glob(f"{sequence:08d}-*.json"))
            if not candidates:
                return current
            if len(candidates) != 1:
                raise AttemptJournalError(f"ambiguous attempt events at sequence {sequence}")
            event_path = candidates[0]
            event = self._validate_event(
                event_path,
                sequence=sequence,
                previous_digest=current.get("head_digest"),
            )
            self._install_pointer(event, event_path.name)
            current = self._advance_current(event)

    def _existing_event(self, key_hash: str) -> Optional[dict[str, Any]]:
        key_path = self.keys / f"{key_hash}.json"
        if not key_path.is_file():
            return None
        try:
            pointer = json.loads(key_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AttemptJournalError("attempt key pointer is unreadable") from error
        if not isinstance(pointer, dict) or pointer.get("attempt_key_hash") != key_hash:
            raise AttemptJournalError("attempt key pointer is invalid")
        event_name = str(pointer.get("event_path") or "")
        if not event_name or Path(event_name).name != event_name:
            raise AttemptJournalError("attempt key event path is invalid")
        sequence = pointer.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise AttemptJournalError("attempt key sequence is invalid")
        event = self._validate_event(
            self.events / event_name,
            sequence=sequence,
            previous_digest=None if sequence == 1 else self._previous_digest(sequence),
        )
        if pointer.get("event_digest") != event.get("event_digest"):
            raise AttemptJournalError("attempt key pointer digest mismatch")
        return event

    def _previous_digest(self, sequence: int) -> Optional[str]:
        candidates = sorted(self.events.glob(f"{sequence - 1:08d}-*.json"))
        if len(candidates) != 1:
            raise AttemptJournalError(f"attempt event predecessor {sequence - 1} is missing or ambiguous")
        try:
            previous = json.loads(candidates[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AttemptJournalError("attempt predecessor is unreadable") from error
        digest = previous.get("event_digest") if isinstance(previous, dict) else None
        if not isinstance(digest, str):
            raise AttemptJournalError("attempt predecessor digest is invalid")
        return digest

    def _verify_committed(self, current: Mapping[str, Any]) -> Optional[str]:
        previous_digest: Optional[str] = None
        head_completed_at: Optional[str] = None
        observed_at: Optional[datetime] = None
        sequence_count = int(current["sequence"])
        for sequence in range(1, sequence_count + 1):
            candidates = sorted(self.events.glob(f"{sequence:08d}-*.json"))
            if len(candidates) != 1:
                raise AttemptJournalError(f"attempt sequence {sequence} is missing or ambiguous")
            event = self._validate_event(
                candidates[0],
                sequence=sequence,
                previous_digest=previous_digest,
            )
            key_path = self.keys / f"{event['attempt_key_hash']}.json"
            try:
                pointer = json.loads(key_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise AttemptJournalError(f"attempt key for sequence {sequence} is unreadable") from error
            if pointer != self._pointer_for(event, candidates[0].name):
                raise AttemptJournalError(f"attempt key for sequence {sequence} does not match its event")
            request = event.get("request")
            response = event.get("response")
            body_path_text = event.get("body_path")
            if (
                not isinstance(request, dict)
                or not isinstance(response, dict)
                or not isinstance(body_path_text, str)
            ):
                raise AttemptJournalError(f"attempt body metadata for sequence {sequence} is invalid")
            started = _timestamp(
                request.get("started_at"),
                f"attempt request timestamp for sequence {sequence}",
            )
            completed_text = response.get("completed_at")
            completed = _timestamp(
                completed_text,
                f"attempt response timestamp for sequence {sequence}",
            )
            if completed < started:
                raise AttemptJournalError(
                    f"attempt timestamps for sequence {sequence} are reversed"
                )
            head_completed_at = str(completed_text)
            observed_at = max(observed_at, completed) if observed_at is not None else completed
            body_name = str(response.get("body_sha256") or "")
            if body_path_text != f"bodies/{body_name}.body" or not re.fullmatch(r"[0-9a-f]{64}", body_name):
                raise AttemptJournalError(f"attempt body path for sequence {sequence} is invalid")
            body_path = self.root / "bodies" / f"{body_name}.body"
            try:
                body = body_path.read_bytes()
            except OSError as error:
                raise AttemptJournalError(f"attempt body for sequence {sequence} is unreadable") from error
            if len(body) != response.get("body_bytes") or hashlib.sha256(body).hexdigest() != body_name:
                raise AttemptJournalError(f"attempt body for sequence {sequence} does not match its event")
            previous_digest = str(event["event_digest"])
        if current.get("head_digest") != previous_digest:
            raise AttemptJournalError("attempt journal head does not match the committed event chain")
        if current.get("updated_at") != head_completed_at:
            raise AttemptJournalError("attempt journal timestamp does not match its head event")
        if len(list(self.events.glob("*.json"))) != sequence_count:
            raise AttemptJournalError("attempt journal contains uncommitted event files")
        if len(list(self.keys.glob("*.json"))) != sequence_count:
            raise AttemptJournalError("attempt journal contains unbound key pointers")
        if observed_at is None:
            return None
        return observed_at.isoformat().replace("+00:00", "Z")

    def _identity(
        self,
        *,
        request_url: str,
        request_headers: Optional[Mapping[str, Any]],
        started_at: str,
        completed_at: str,
        status: int,
        outcome: str,
        response_headers: Optional[Mapping[str, Any]],
        body: bytes,
        wire_bytes: int,
        inflated_bytes: int,
        wire_sha256: str,
        peer_ip: Optional[str],
        redirects: Iterable[Any],
        retry_after_seconds: Optional[float],
        error_code: Optional[str],
        error_message: Optional[str],
        context: Optional[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(body, bytes) or len(body) > MAX_EVIDENCE_BODY_BYTES:
            raise AttemptJournalError("attempt response body exceeds the evidence limit")
        started = _timestamp(started_at, "attempt request timestamp")
        completed = _timestamp(completed_at, "attempt response timestamp")
        if completed < started:
            raise AttemptJournalError("attempt timestamps are reversed")
        if isinstance(status, bool) or not isinstance(status, int) or not 0 <= status <= 999:
            raise AttemptJournalError("attempt status must be an integer")
        if (
            isinstance(wire_bytes, bool)
            or not isinstance(wire_bytes, int)
            or isinstance(inflated_bytes, bool)
            or not isinstance(inflated_bytes, int)
            or wire_bytes < 0
            or inflated_bytes < 0
        ):
            raise AttemptJournalError("attempt byte counts must be non-negative")
        if inflated_bytes != len(body):
            raise AttemptJournalError("attempt inflated byte count must match the evidence body")
        if not re.fullmatch(r"[0-9a-f]{64}", str(wire_sha256 or "")):
            raise AttemptJournalError("attempt wire digest must be lowercase SHA-256")
        if retry_after_seconds is not None:
            retry_after_seconds = float(retry_after_seconds)
            if (
                not math.isfinite(retry_after_seconds)
                or retry_after_seconds < 0
                or retry_after_seconds > DEFAULT_HTTP_POLICY.max_retry_after_seconds
            ):
                raise AttemptJournalError("attempt Retry-After is outside the policy limit")
        if peer_ip:
            try:
                peer_ip = ipaddress.ip_address(peer_ip).compressed
            except ValueError as error:
                raise AttemptJournalError("attempt peer address is invalid") from error
        body_digest = hashlib.sha256(body).hexdigest()
        return {
            "request": {
                "method": "GET",
                "url": sanitize_url(request_url),
                "headers": _sanitize_headers(request_headers, _REQUEST_HEADER_ALLOWLIST),
                "started_at": _bounded_text(started_at, 64),
            },
            "response": {
                "status": status,
                "outcome": _bounded_text(outcome, 64),
                "headers": _sanitize_headers(response_headers, _RESPONSE_HEADER_ALLOWLIST),
                "completed_at": _bounded_text(completed_at, 64),
                "body_bytes": len(body),
                "body_sha256": body_digest,
                "wire_bytes": int(wire_bytes),
                "inflated_bytes": int(inflated_bytes),
                "wire_sha256": _bounded_text(wire_sha256, 64),
                "peer_ip": peer_ip,
                "retry_after_seconds": retry_after_seconds,
                "error_code": _bounded_text(error_code, 128) or None,
                "error_message": _sanitize_error(error_message),
            },
            "redirects": _sanitize_redirects(redirects),
            "context": _sanitize_value(dict(context or {})),
            "body_path": f"bodies/{body_digest}.body",
        }

    def record(
        self,
        attempt_key: str,
        *,
        request_url: str,
        status: int,
        outcome: str,
        body: bytes = b"",
        request_headers: Optional[Mapping[str, Any]] = None,
        response_headers: Optional[Mapping[str, Any]] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        wire_bytes: Optional[int] = None,
        inflated_bytes: Optional[int] = None,
        wire_sha256: Optional[str] = None,
        peer_ip: Optional[str] = None,
        redirects: Iterable[Any] = (),
        retry_after_seconds: Optional[float] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        if not attempt_key:
            raise ValueError("attempt_key is required")
        started = started_at or utc_now()
        completed = completed_at or utc_now()
        wire_count = len(body) if wire_bytes is None else int(wire_bytes)
        inflated_count = len(body) if inflated_bytes is None else int(inflated_bytes)
        wire_digest = wire_sha256 or hashlib.sha256(body).hexdigest()
        identity = self._identity(
            request_url=request_url,
            request_headers=request_headers,
            started_at=started,
            completed_at=completed,
            status=status,
            outcome=outcome,
            response_headers=response_headers,
            body=body,
            wire_bytes=wire_count,
            inflated_bytes=inflated_count,
            wire_sha256=wire_digest,
            peer_ip=peer_ip,
            redirects=redirects,
            retry_after_seconds=retry_after_seconds,
            error_code=error_code,
            error_message=error_message,
            context=context,
        )
        key_hash = hashlib.sha256(
            f"{self.session_id}\0{attempt_key}".encode("utf-8")
        ).hexdigest()
        identity_digest = _digest_json(identity)
        body_path = self.root / identity["body_path"]
        atomic_write_bytes(body_path, body, create_once=True)
        self._fault("after_body")

        with self._thread_lock, FileLock(self.lock_path):
            current = self._recover(self._read_current())
            existing = self._existing_event(key_hash)
            if existing is not None:
                if existing.get("attempt_identity_digest") != identity_digest:
                    raise AttemptJournalError("attempt key already records different evidence")
                return existing

            sequence = int(current["sequence"]) + 1
            base_event = {
                "schema_version": SCHEMA_VERSION,
                "session_id": self.session_id,
                "sequence": sequence,
                "previous_event_digest": current.get("head_digest"),
                "attempt_key_hash": key_hash,
                "attempt_identity_digest": identity_digest,
                **identity,
            }
            event = {**base_event, "event_digest": _digest_json(base_event)}
            event_name = f"{sequence:08d}-{key_hash[:16]}.json"
            atomic_write_json(self.events / event_name, event, create_once=True)
            self._fault("after_event")
            self._install_pointer(event, event_name)
            self._fault("after_key")
            self._advance_current(event)
            self._fault("after_current")
            return event

    def summary(self, *, recover: bool = True) -> dict[str, Any]:
        with self._thread_lock, FileLock(self.lock_path):
            current = self._read_current()
            if recover:
                current = self._recover(current)
            observed_at = self._verify_committed(current)
            return {
                "schema_version": SCHEMA_VERSION,
                "session_id": self.session_id,
                "attempts": current["sequence"],
                "head_digest": current.get("head_digest"),
                "observed_at": observed_at,
                "verified": True,
            }

    def evidence_records(self, *, recover: bool = False) -> tuple[dict[str, Any], ...]:
        """Return body digests and sanitized contexts after full chain verification."""

        with self._thread_lock, FileLock(self.lock_path):
            current = self._read_current()
            if recover:
                current = self._recover(current)
            self._verify_committed(current)
            previous: Optional[str] = None
            records = []
            for sequence in range(1, int(current["sequence"]) + 1):
                candidates = sorted(self.events.glob(f"{sequence:08d}-*.json"))
                if len(candidates) != 1:
                    raise AttemptJournalError(
                        f"attempt sequence {sequence} is missing or ambiguous"
                    )
                event = self._validate_event(
                    candidates[0], sequence=sequence, previous_digest=previous
                )
                records.append(
                    {
                        "body_sha256": event["response"]["body_sha256"],
                        "body_path": event["body_path"],
                        "status": event["response"]["status"],
                        "outcome": event["response"]["outcome"],
                        "context": dict(event["context"]),
                    }
                )
                previous = event["event_digest"]
            return tuple(records)
