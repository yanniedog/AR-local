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


def hash_dropbehind(descriptor: int, size: int, capture: bool, *, budget=None) -> tuple[str, bytes | None]:
    """Read every byte through the caller's identity-bound descriptor.

    RWF_DONTCACHE is best-effort cache advice, not a memory limit. Missing API,
    unsupported filesystem and I/O errors propagate; resource guards still apply.
    The caller retains all before/open/after file and ancestor identity checks.
    """
    if sys.platform != "linux" or not callable(getattr(os, "preadv", None)):
        raise RuntimeError("required drop-behind hashing needs Linux preadv2/RWF_DONTCACHE")
    digest, blocks, offset = hashlib.sha256(), [], 0
    buffer = bytearray(min(READ_BYTES, max(size, 1)))
    view = memoryview(buffer)
    while offset < size:
        requested = min(len(view), size - offset)
        if budget is not None:
            budget(reserve_bytes=requested)
        count = os.preadv(descriptor, [view[:requested]], offset, RWF_DONTCACHE)
        if budget is not None:
            budget(size=count)
        if not 0 < count <= requested:
            raise ValueError("evidence size changed during read")
        digest.update(view[:count])
        if capture:
            blocks.append(bytes(view[:count]))
        offset += count
    # Even an empty file must exercise the required flag and check for growth.
    if budget is not None:
        budget()
    if os.preadv(descriptor, [view[:1]], offset, RWF_DONTCACHE):
        raise ValueError("evidence size changed during read")
    return digest.hexdigest(), b"".join(blocks) if capture else None
