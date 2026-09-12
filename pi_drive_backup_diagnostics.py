"""Private bounded Restic stderr, with safe immutable command receipts.

Raw provider text can contain credentials. It never enters errors or receipts.
The head and latest complete tail survive process termination independently of
the final receipt; no final receipt means command completion is unverified.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

HEAD_BYTES = 32 * 1024
TAIL_BYTES = 96 * 1024
CHUNK_BYTES = 16 * 1024
COMMANDS = {"init", "cat", "snapshots", "check", "backup", "stats", "restore"}
_OPERATION = ContextVar("drive_diagnostic_operation", default=None)


def classify(raw: bytes, exit_code: int | None, *, interrupted=False) -> str:
    """Fixed pattern labels, not a claim that one pattern proves root cause."""
    if interrupted:
        return "INTERRUPTED"
    if exit_code == 0:
        return "NONE"
    if exit_code == 11:
        return "REPOSITORY_LOCK"
    text = raw.decode("utf-8", errors="replace").lower()
    rules = (
        ("AUTHORIZATION", ("invalid_grant", "invalid_client", "access_denied", "unauthorized", "invalid credentials")),
        ("REMOTE_STORAGE_QUOTA", ("storagequotaexceeded", "storage quota exceeded")),
        ("API_RATE_LIMIT", ("userratelimitexceeded", "ratelimitexceeded", "dailylimitexceeded", "rate limit exceeded")),
        ("PERMISSION", ("permission denied", "insufficient permissions", "forbidden")),
        ("NETWORK", ("timeout", "timed out", "no such host", "network is unreachable", "connection reset", "unexpected eof")),
        ("REPOSITORY_LOCK", ("repository is already locked", "unable to create lock", "repository is locked")),
        ("DISK_SPACE", ("no space left on device",)),
        ("MEMORY", ("out of memory", "cannot allocate memory")),
        ("REPOSITORY_INTEGRITY", ("invalid data returned", "ciphertext verification failed", "pack file is corrupted")),
    )
    return next((name for name, terms in rules if any(term in text for term in terms)), "UNCLASSIFIED")


def _private_file(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags, 0o600), "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _json(path: Path, value: dict) -> None:
    _private_file(path, (json.dumps(value, sort_keys=True) + "\n").encode("utf-8"))


def _directory(path: Path) -> None:
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    if path.resolve() != path or path.is_symlink() or not path.is_dir():
        raise ValueError("unsafe diagnostic directory")
    if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError("diagnostic directory is not private")


@contextmanager
def operation_scope(operation: Path):
    """Called only after the controller validates its private worker request."""
    token = _OPERATION.set(operation)
    try:
        yield
    finally:
        _OPERATION.reset(token)


class StderrCapture:
    def __init__(self, spool: Path, command: str):
        if command not in COMMANDS or not spool.is_absolute() or spool.resolve() != spool or not spool.is_dir():
            raise ValueError("invalid diagnostic scope or command")
        operation = _OPERATION.get()
        request_hash = None
        if operation is not None:
            if (operation.resolve() != operation or operation.parent != spool / "resource-runs"
                    or re.fullmatch(r"[0-9a-f]{32}", operation.name) is None):
                raise ValueError("diagnostics leave the protected operation")
            request = operation / "request.json"
            if request.is_symlink() or request.stat().st_size > 64 * 1024:
                raise ValueError("unsafe diagnostic request binding")
            with request.open("rb") as stream:
                raw = stream.read(64 * 1024 + 1)
            if len(raw) > 64 * 1024:
                raise ValueError("diagnostic request exceeds bound")
            request_hash = hashlib.sha256(raw).hexdigest()
        base = (operation if operation is not None else spool) / "diagnostics"
        _directory(base)
        self.path = base / uuid.uuid4().hex
        self.path.mkdir(mode=0o700)
        self.reference = self.path.relative_to(spool).as_posix()
        self.command, self.thread, self.process_pid = command, None, None
        self.total, self.head, self.tail = 0, bytearray(), bytearray()
        self.reader_error, self.finished = False, False
        self.started = {"schema": "ar-local-drive-command-diagnostic-v1", "command": command,
            "worker_pid": os.getpid(), "supervisor_pid": os.getppid(),
            "operation_id": operation.name if operation else None, "request_sha256": request_hash,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "stderr_head_limit": HEAD_BYTES, "stderr_tail_limit": TAIL_BYTES,
            "raw_text_private": True, "result": "STARTED"}
        _json(self.path / "started.json", self.started)
        _private_file(self.path / "stderr.head", b"")
        _private_file(self.path / "stderr.tail", b"")

    def __enter__(self):
        return self

    def __exit__(self, kind, _error, _traceback):
        if not self.finished:
            self.finish(None, interrupted=kind is not None)

    def attach(self, pipe, process_pid: int) -> None:
        if self.thread is not None:
            raise ValueError("stderr reader already attached")
        self.process_pid = process_pid
        _json(self.path / "process.json", {"process_pid": process_pid})
        self.thread = threading.Thread(target=self._read, args=(pipe,), daemon=True)
        self.thread.start()

    def _read(self, pipe) -> None:
        try:
            with pipe, (self.path / "stderr.head").open("ab", buffering=0) as head:
                while chunk := os.read(pipe.fileno(), CHUNK_BYTES):
                    kept = chunk[:max(0, HEAD_BYTES - len(self.head))]
                    head.write(kept)
                    self.head.extend(kept)
                    self.total += len(chunk)
                    self.tail.extend(chunk)
                    del self.tail[:-TAIL_BYTES]
                    # At most one bounded pending tail exists. Atomic replacement
                    # leaves a complete earlier tail if this process is killed.
                    pending = self.path / "stderr.tail.pending"
                    _private_file(pending, self.tail)
                    pending.replace(self.path / "stderr.tail")
        except Exception:
            self.reader_error = True

    def finish(self, exit_code: int | None, *, interrupted=False) -> dict:
        if self.finished:
            return self.summary
        if self.thread is not None:
            self.thread.join(timeout=5)
        complete = self.thread is not None and not self.thread.is_alive() and not self.reader_error
        category = classify(bytes(self.head + self.tail), exit_code, interrupted=interrupted)
        if not complete:
            category = "DIAGNOSTIC_CAPTURE_INCOMPLETE"
        self.summary = {"path": self.reference, "command": self.command, "exit_code": exit_code,
                        "category": category}
        result = {**self.started, **self.summary, "process_pid": self.process_pid,
            "result": "EXITED" if exit_code is not None and complete else "INCOMPLETE",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "stderr_bytes_observed": self.total, "stderr_truncated": self.total > HEAD_BYTES + TAIL_BYTES,
            "reader_complete": complete, "reader_error": self.reader_error,
            "stderr_head_sha256": hashlib.sha256(self.head).hexdigest(),
            "stderr_tail_sha256": hashlib.sha256(self.tail).hexdigest()}
        _json(self.path / "result.json", result)
        self.finished = True
        if not complete and self.process_pid is not None:
            raise RuntimeError("Restic diagnostic capture incomplete; diagnostic=" + self.reference)
        return self.summary
