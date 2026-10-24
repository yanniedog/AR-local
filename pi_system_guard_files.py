"""Small root custody primitives; never repair unexpected existing permissions."""
import hashlib
import json
import os
from pathlib import Path
import stat


def protected(path, maximum=16 * 1024 ** 2, *, readonly=True):
    path = Path(path)
    if path.resolve(strict=True) != path:
        raise RuntimeError("canonical protected input required")
    for node in (path, *path.parents):
        item = node.lstat()
        if item.st_uid != 0 or stat.S_ISLNK(item.st_mode) or item.st_mode & 0o022:
            raise RuntimeError("input ancestry is not exclusively root controlled")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        item = os.fstat(descriptor)
        if (not stat.S_ISREG(item.st_mode) or item.st_nlink != 1 or item.st_size > maximum
                or readonly and item.st_mode & 0o222):
            raise RuntimeError("bounded immutable root input required")
        body = os.read(descriptor, maximum + 1)
        if len(body) != item.st_size:
            raise RuntimeError("protected input changed during read")
        return body
    finally:
        os.close(descriptor)


def directory(path, mode, gid=0):
    path = Path(path)
    if not path.exists():
        path.mkdir(mode=mode)
        descriptor = os.open(path, os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fchown(descriptor, 0, gid)
            os.fchmod(descriptor, mode)  # Native service UMask0077 must not remove Pi traversal.
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    item = path.lstat()
    if (path.resolve() != path or not stat.S_ISDIR(item.st_mode) or item.st_uid != 0
            or item.st_gid != gid or stat.S_IMODE(item.st_mode) != mode):
        raise RuntimeError("existing fixed directory custody differs")


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def sha(body):
    return hashlib.sha256(body).hexdigest()


def publish(path, body, mode=0o400, gid=0):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        view = memoryview(body)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise RuntimeError("short protected publication")
            view = view[count:]
        os.fchown(descriptor, 0, gid)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    descriptor = os.open(Path(path).parent, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
