"""Crash-recoverable, mixed-version-safe CAS for local bot-wait state.

The persistent sidecar is kernel-locked, never unlinked. Its hardlink at the
legacy .lock name excludes old wx writers. An abandoned hardlink is reusable
only after acquiring the kernel lock and verifying its filesystem identity.
An unrelated legacy lock requires verified manual migration, never a TTL/PID
guess. Requires Python 3 and a filesystem supporting locks and hardlinks.
"""

import contextlib
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

MAX_INPUT = 1024 * 1024


def file_identity(info):
    if (not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not info.st_ino):
        raise RuntimeError("Wait state lock must be a regular file with a stable identity")
    return info.st_dev, info.st_ino


def require_identity(filename, expected):
    if file_identity(os.lstat(filename)) != expected:
        raise RuntimeError("Wait state lock identity changed; refusing update")


def acquire_kernel_lock(descriptor):
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(descriptor, 0, os.SEEK_SET)
            # Byte-range locks may extend beyond EOF, including an empty file.
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        raise RuntimeError("Wait state update is locked or locking is unavailable; retry after the writer exits") from error


@contextlib.contextmanager
def state_write_lock(destination):
    sidecar = str(destination) + ".writer-lock"
    legacy = str(destination) + ".lock"
    descriptor = os.open(sidecar, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        identity = file_identity(os.fstat(descriptor))
        require_identity(sidecar, identity)
        acquire_kernel_lock(descriptor)
        require_identity(sidecar, identity)
        try:
            os.link(sidecar, legacy, follow_symlinks=False)
        except FileExistsError:
            try:
                require_identity(legacy, identity)
            except (OSError, RuntimeError) as error:
                raise RuntimeError("Wait state update is locked by a legacy or unknown writer; verified migration is required") from error
        try:
            require_identity(sidecar, identity)
            require_identity(legacy, identity)
            yield
        finally:
            # Never delete another writer's lock, including a replaced alias.
            require_identity(legacy, identity)
            os.unlink(legacy)
    finally:
        # Closing the descriptor (also on process death) releases the kernel lock.
        os.close(descriptor)


def current_fingerprint(destination):
    try:
        descriptor = os.open(destination, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as current:
        require_identity(destination, file_identity(os.fstat(current.fileno())))
        content = current.read(MAX_INPUT + 1)
    if len(content) > MAX_INPUT:
        raise RuntimeError("Wait state exceeds the supported size")
    return hashlib.sha256(content).hexdigest()


def sync_directory(directory):
    if os.name == "nt":
        return  # Windows does not support opening directory descriptors this way.
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    except OSError as error:
        if error.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
            raise RuntimeError("Wait state was replaced, but its directory could not be synced") from error
        print("Wait state replaced; this filesystem does not support directory fsync.", file=sys.stderr)
    finally:
        os.close(descriptor)


def write_state(destination, content, expected):
    with state_write_lock(destination):
        if current_fingerprint(destination) != expected:
            raise RuntimeError("Wait state changed since read; reread before updating")
        descriptor, temporary = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            sync_directory(destination.parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return hashlib.sha256(content).hexdigest()


def main():
    request_bytes = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(request_bytes) > MAX_INPUT:
        raise RuntimeError("Wait state request exceeds the supported size")
    request = json.loads(request_bytes)
    destination = Path(request["destination"])
    content = request["content"].encode("utf-8")
    expected = request["expected"]
    if not destination.is_absolute() or not isinstance(json.loads(content), dict):
        raise RuntimeError("Invalid wait state request")
    if expected is not None and (not isinstance(expected, str) or len(expected) != 64
                                 or any(char not in "0123456789abcdef" for char in expected)):
        raise RuntimeError("Invalid wait state snapshot")
    print(json.dumps({"fingerprint": write_state(destination, content, expected)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
