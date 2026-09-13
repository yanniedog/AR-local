"""Advised bounded writes confined to a newly created private backup output."""
from __future__ import annotations

import errno
import os
import warnings
from typing import BinaryIO, Callable

from pi_drive_backup_read import CHUNK_BYTES, LINUX, RWF_DONTCACHE, UNSUPPORTED, created_identity


class CreatedWriter:
    def __init__(self, stream: BinaryIO):
        self.identity = created_identity(stream)
        if stream.tell() != 0 or os.fstat(stream.fileno()).st_size != 0:
            raise ValueError("private write adapter requires a new empty destination")
        self.stream, self.offset = stream, 0
        self.writev = getattr(os, "pwritev", None) if LINUX else None

    def write(self, block: bytes, guard: Callable[[], None]) -> None:
        if not 0 < len(block) <= CHUNK_BYTES:
            raise ValueError("private write block must be bounded and nonempty")
        pending = memoryview(block)
        while pending:
            guard()
            if created_identity(self.stream) != self.identity:
                raise ValueError("private destination identity changed during copy")
            if self.writev is not None:
                try:
                    count = self.writev(self.stream.fileno(), [pending], self.offset, RWF_DONTCACHE)
                except (OSError, NotImplementedError) as error:
                    if isinstance(error, OSError) and error.errno not in UNSUPPORTED:
                        raise
                    warnings.warn("Backup RWF_DONTCACHE writes unavailable; using buffered writes with unchanged resource guards",
                                  RuntimeWarning, stacklevel=2)
                    self.writev = None
                    self.stream.seek(self.offset)
                    continue
            else:
                count = self.stream.write(pending)
            if type(count) is not int or not 0 < count <= len(pending):
                raise OSError(errno.EIO, "private backup write made invalid progress")
            self.offset += count
            pending = pending[count:]
        # Native positional writes do not advance the stream offset. Keep it
        # aligned for unsupported fallbacks and the caller's final flush/fsync.
        if self.writev is not None:
            self.stream.seek(self.offset)
