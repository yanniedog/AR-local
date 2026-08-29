"""Durable atomic file operations and exclusive receiver ownership."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_move(source: Path, destination: Path, *, replace: bool) -> None:
    if destination.exists() and not replace:
        raise FileExistsError(destination)
    if os.name == "nt":
        import ctypes

        flags = 0x8 | (0x1 if replace else 0)
        move = ctypes.windll.kernel32.MoveFileExW
        move.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
        move.restype = ctypes.c_int
        if not move(str(source), str(destination), flags):
            raise ctypes.WinError()
        return
    if replace:
        source.replace(destination)
    else:
        os.link(source, destination)
        fsync_directory(destination.parent)
        source.unlink()
    fsync_directory(destination.parent)


def atomic_create(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
        fsync_directory(path.parent)
        return
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        durable_move(temporary, path, replace=False)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        durable_move(temporary, path, replace=True)
    finally:
        temporary.unlink(missing_ok=True)


class ReceiverLock:
    def __init__(self, target: Path) -> None:
        self.path = target / "catalog/.receiver.lock"
        self.nonce = uuid.uuid4().hex

    def __enter__(self) -> "ReceiverLock":
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        payload = (json.dumps(
            {"pid": os.getpid(), "nonce": self.nonce, "started_at": now},
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n").encode("utf-8")
        atomic_create(self.path, payload)
        return self

    def __exit__(self, *_args: object) -> None:
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("nonce") != self.nonce:
            raise RuntimeError("receiver lock ownership changed; refusing removal")
        self.path.unlink()
