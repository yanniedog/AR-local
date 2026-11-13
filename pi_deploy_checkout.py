"""Read-only raw Git-tree binding; never run checkout filters or external diff."""
from __future__ import annotations

import hashlib
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zlib

MAX_BYTES = 8 * 1024 * 1024


def inline_program():
    """Carry these reviewed stdlib-only bytes to older Pi checkouts without writes."""
    source = Path(__file__).read_bytes()
    if len(source) > 65536:
        raise ValueError("checkout observer source exceeds bound")
    encoded = base64.b64encode(zlib.compress(source)).decode("ascii")
    return ("exec(compile(__import__('zlib').decompress(__import__('base64').b64decode("
            + repr(encoded) + ")), '<ar-local-checkout-observer>', 'exec'))")


def _git(repo, *args):
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), "-c", "core.fsmonitor=false", *args],
                            capture_output=True, check=True, timeout=15, env=env)
    if len(result.stdout) > MAX_BYTES:
        raise ValueError("Git inventory exceeds bound")
    return result.stdout


def _entries(raw, *, index=False):
    result = {}
    for row in raw.split(b"\0"):
        if not row:
            continue
        metadata, path = row.split(b"\t", 1)
        mode, kind, oid = metadata.split(b" ")
        if index:
            kind, oid = oid, kind
            if kind != b"0":
                raise ValueError("unmerged index")
        if path in result or path.startswith(b"/") or any(p in {b"", b".", b".."} for p in path.split(b"/")):
            raise ValueError("unsafe or duplicate tracked path")
        result[path] = (mode, oid)
    return result


def _signature(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


@contextmanager
def _parent(repo, name):
    """Pin POSIX directories without following links; revalidate every parent."""
    parts = os.fsdecode(name).split("/")
    handles, parents, signatures = [], [], []
    anchored = os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW")
    try:
        path, parent_fd = repo, None
        for part in [None, *parts[:-1]]:
            path = path if part is None else path / part
            target = path if parent_fd is None else part
            before = os.stat(target, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400:
                raise ValueError("unsafe tracked parent")
            parents.append((target, parent_fd, _signature(before)))
            signatures.append(_signature(before))
            if anchored:
                handle = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                handles.append(handle)
                if _signature(os.fstat(handle)) != _signature(before):
                    raise ValueError("tracked parent changed while opening")
                parent_fd = handle
        yield (parts[-1] if anchored else path / parts[-1]), parent_fd, tuple(signatures)
        if any(_signature(os.stat(target, dir_fd=fd, follow_symlinks=False)) != before for target, fd, before in parents):
            raise ValueError("tracked parent changed during observation")
    finally:
        for handle in reversed(handles):
            os.close(handle)


def _blob(repo, name, mode):
    with _parent(repo, name) as (path, parent_fd, parents):
        before = os.stat(path, dir_fd=parent_fd, follow_symlinks=False)
        if mode == b"120000" and stat.S_ISLNK(before.st_mode):
            body = os.fsencode(os.readlink(path, dir_fd=parent_fd))
            digest = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body)
        else:
            if mode not in {b"100644", b"100755"} or not stat.S_ISREG(before.st_mode):
                raise ValueError("unsupported tracked file mode")
            if bool(before.st_mode & stat.S_IXUSR) != (mode == b"100755"):
                raise ValueError("tracked executable mode differs")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
            handle = os.open(path, flags, dir_fd=parent_fd)
            with os.fdopen(handle, "rb") as stream:
                if _signature(os.fstat(stream.fileno())) != _signature(before):
                    raise ValueError("tracked file changed while opening")
                digest = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
                for chunk in iter(lambda: stream.read(65536), b""):
                    digest.update(chunk)
                if _signature(os.fstat(stream.fileno())) != _signature(before):
                    raise ValueError("tracked file changed while hashing")
        if _signature(os.stat(path, dir_fd=parent_fd, follow_symlinks=False)) != _signature(before):
            raise ValueError("tracked file changed during observation")
    return digest.hexdigest().encode(), (_signature(before), parents)


def _inventory(repo, tracked):
    if _entries(_git(repo, "ls-files", "--stage", "-z"), index=True) != tracked:
        raise ValueError("index differs from deployed tree")
    if any(row and not row.startswith(b"H ") for row in _git(repo, "ls-files", "-v", "-z").split(b"\0")):
        raise ValueError("masked index entry")
    if _git(repo, "ls-files", "--others", "--exclude-standard", "-z"):
        raise ValueError("untracked checkout files")


def checkout_binding(repo):
    repo = Path(repo).resolve(strict=True)
    head = _git(repo, "rev-parse", "HEAD").decode().strip()
    tree = _git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
    tracked = _entries(_git(repo, "ls-tree", "-rz", "--full-tree", "HEAD"))
    if not tracked:
        raise ValueError("empty deployed tree")
    _inventory(repo, tracked)
    states = {}
    for name, (mode, oid) in tracked.items():
        actual, states[name] = _blob(repo, name, mode)
        if actual != oid:
            raise ValueError("tracked bytes differ from deployed tree")
    _inventory(repo, tracked)
    for name, before in states.items():
        with _parent(repo, name) as (path, parent_fd, parents):
            if (_signature(os.stat(path, dir_fd=parent_fd, follow_symlinks=False)), parents) != before:
                raise ValueError("tracked state changed after hashing")
    if _git(repo, "rev-parse", "HEAD").decode().strip() != head:
        raise ValueError("checkout moved during observation")
    return {"head": head, "tree": tree, "clean": True}


if __name__ == "__main__":
    try:
        print(json.dumps(checkout_binding(sys.argv[1]), separators=(",", ":")))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        print('{"clean":false}')
        raise SystemExit(1)
