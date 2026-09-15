"""Atomic directory admission without overwriting another writer's reservation."""
import ctypes
import errno
import os
import sys


def admit_new_directory(stage, destination):
    if os.name == 'nt':
        # Windows rename already refuses every existing destination.
        os.rename(stage, destination)
        return
    if not sys.platform.startswith('linux'):
        raise OSError(errno.ENOTSUP, 'Atomic no-replace admission requires Windows or Linux')
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise OSError(errno.ENOTSUP, 'Atomic no-replace rename unavailable')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    # AT_FDCWD / RENAME_NOREPLACE: one kernel operation, including empty targets.
    if rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
