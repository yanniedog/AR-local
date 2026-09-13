"""Bounded backup reads that avoid retaining newly read Linux cache pages."""
from __future__ import annotations

import errno
import os
import stat
import sys
import warnings
from typing import BinaryIO, Iterator

CHUNK_BYTES = 1024 * 1024
LINUX = sys.platform.startswith("linux")
# Linux UAPI RWF_DONTCACHE; older supported Python versions lack the name.
RWF_DONTCACHE = getattr(os, "RWF_DONTCACHE", 0x80)
UNSUPPORTED = {errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL}


def chunks(stream: BinaryIO) -> Iterator[bytes]:
    """Consume a private read handle; callers keep their existing per-block guard.

    Linux 6.14+ can discard pages instantiated by this read without discarding
    pre-existing cached pages. This is best-effort, not a memory/swap guarantee.
    Unsupported hosts/filesystems keep the old read path and resource guards.
    """
    readv = getattr(os, "preadv", None) if LINUX else None
    if readv is not None:
        offset = stream.tell()
        buffer = bytearray(CHUNK_BYTES)
        while True:
            try:
                count = readv(stream.fileno(), [buffer], offset, RWF_DONTCACHE)
            except (OSError, NotImplementedError) as error:
                if isinstance(error, OSError) and error.errno not in UNSUPPORTED:
                    raise
                warnings.warn("Backup RWF_DONTCACHE unavailable; using buffered reads with unchanged resource guards",
                              RuntimeWarning, stacklevel=2)
                # preadv does not advance the file offset. Resume exactly after
                # the last yielded bytes, including a mid-file capability error.
                stream.seek(offset)
                break
            if count == 0:
                return
            offset += count
            yield bytes(memoryview(buffer)[:count])
    for block in iter(lambda: stream.read(CHUNK_BYTES), b""):
        yield block


def created_identity(stream: BinaryIO) -> tuple[int, int]:
    """Validate the original exclusive writer, never a source or reopened file."""
    info = os.fstat(stream.fileno())
    if stream.mode != "xb" or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("cache release requires an exclusively created private file")
    named = os.stat(stream.name, follow_symlinks=False)
    if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
        raise ValueError("private destination identity changed before cache release")
    return info.st_dev, info.st_ino


def discard_created_cache(stream: BinaryIO) -> None:
    """Release a verified private file still held by its original xb descriptor."""
    created_identity(stream)
    stream.flush()
    os.fsync(stream.fileno())
    advise = getattr(os, "posix_fadvise", None) if LINUX else None
    if advise is not None:
        try:
            advise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        except OSError as error:
            if error.errno not in UNSUPPORTED:
                raise
            warnings.warn("Private backup cache release unavailable; resource guards remain unchanged",
                          RuntimeWarning, stacklevel=2)
