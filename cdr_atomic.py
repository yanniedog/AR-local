"""Durable, create-once filesystem primitives for irreplaceable CDR state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


class ImmutablePathError(RuntimeError):
    """Raised when a create-once path already contains different bytes."""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return stable UTF-8 JSON and reject NaN/Infinity financial values."""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, payload: bytes, *, create_once: bool = False) -> bool:
    """Install fully flushed bytes atomically.

    Returns ``True`` when bytes were installed and ``False`` for an idempotent
    create-once replay. A create-once collision with different bytes is fatal.
    """
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if create_once and path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return False
        raise ImmutablePathError(f"immutable path already exists with different bytes: {path}")

    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}-{os.urandom(8).hex()}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if create_once:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_file() and path.read_bytes() == payload:
                    return False
                raise ImmutablePathError(
                    f"immutable path appeared with different bytes: {path}"
                )
            finally:
                temporary.unlink(missing_ok=True)
        else:
            os.replace(temporary, path)
        _fsync_directory(path.parent)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(
    path: Path,
    value: Mapping[str, Any],
    *,
    create_once: bool = False,
) -> bool:
    return atomic_write_bytes(path, canonical_json_bytes(value), create_once=create_once)
