"""Explicit Linux drop-behind hashing; never fall back inside required scopes."""
from __future__ import annotations

import hashlib
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar

# Linux UAPI include/uapi/linux/fs.h. Python 3.11 accepts preadv2 flags but
# need not export the constant introduced with Linux 6.14.
RWF_DONTCACHE = 0x80
READ_BYTES = 1024 * 1024
_REQUIRED: ContextVar[bool] = ContextVar("quality_dropbehind_required", default=False)


@contextmanager
def require_dropbehind_reads():
    """Require the read flag in this context, including nested digest calls.

    No environment/CLI toggle or fallback exists. Child Python processes start
    with their own default context. Unsupported platforms fail on the first
    actual read; setting this scope alone is not a capability/acceptance probe.
    """
    token = _REQUIRED.set(True)
    try:
        yield
    finally:
        _REQUIRED.reset(token)


def dropbehind_required() -> bool:
    return _REQUIRED.get()


def _require_reader():
    if sys.platform != "linux" or not callable(getattr(os, "preadv", None)):
        raise RuntimeError("required drop-behind hashing needs Linux preadv2/RWF_DONTCACHE")


def _views_dropbehind(descriptor: int, size: int, *, captured=None, budget=None):
    _require_reader()
    offset = 0
    view = memoryview(captured if captured is not None else bytearray(min(READ_BYTES, max(size, 1))))
    while offset < size:
        requested = min(READ_BYTES, size - offset)
        target = view[offset:offset + requested] if captured is not None else view[:requested]
        if budget is not None:
            budget(reserve_bytes=requested)
        count = os.preadv(descriptor, [target], offset, RWF_DONTCACHE)
        if budget is not None:
            budget(size=count)
        if not 0 < count <= requested:
            raise ValueError("evidence size changed during read")
        offset += count
        yield target[:count]
    # A separate one-byte probe also covers an empty capture buffer.
    if budget is not None:
        budget()
    if os.preadv(descriptor, [bytearray(1)], offset, RWF_DONTCACHE):
        raise ValueError("evidence size changed during read")


def chunks_dropbehind(descriptor: int, size: int, *, budget=None):
    """Read a complete file through the caller's identity-bound descriptor.

    RWF_DONTCACHE is best-effort cache advice, not a memory limit. Missing API,
    unsupported filesystem and I/O errors propagate; resource guards still apply.
    The caller retains all before/open/after file and ancestor identity checks.
    """
    for block in _views_dropbehind(descriptor, size, budget=budget):
        yield bytes(block)


def hash_dropbehind(descriptor: int, size: int, capture: bool, *, budget=None) -> tuple[str, bytearray | None]:
    """Capture into one allocation; callers must not mutate it before validation."""
    _require_reader()
    if capture and budget is not None:
        budget(reserve_bytes=size)
    digest = hashlib.sha256()
    captured = bytearray(size) if capture else None
    for block in _views_dropbehind(descriptor, size, captured=captured, budget=budget):
        digest.update(block)
    return digest.hexdigest(), captured
