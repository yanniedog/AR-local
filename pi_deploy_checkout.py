"""Read-only raw Git-tree binding; never run checkout filters or external diff."""
from __future__ import annotations

import hashlib
import base64
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


def _blob(repo, name, mode):
    path = repo.joinpath(*os.fsdecode(name).split("/"))
    # A replaced parent directory must not redirect the observer out of checkout.
    parent = path.parent
    while parent != repo:
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError("unsafe tracked parent")
        parent = parent.parent
    before = path.lstat()
    if mode == b"120000" and stat.S_ISLNK(before.st_mode):
        body = os.fsencode(os.readlink(path))
        return hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest().encode()
    if mode not in {b"100644", b"100755"} or not stat.S_ISREG(before.st_mode):
        raise ValueError("unsupported tracked file mode")
    if bool(before.st_mode & stat.S_IXUSR) != (mode == b"100755"):
        raise ValueError("tracked executable mode differs")
    digest = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("tracked file changed while opening")
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("tracked file changed while hashing")
    return digest.hexdigest().encode()


def checkout_binding(repo):
    repo = Path(repo).resolve(strict=True)
    head = _git(repo, "rev-parse", "HEAD").decode().strip()
    tree = _git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
    tracked = _entries(_git(repo, "ls-tree", "-rz", "--full-tree", "HEAD"))
    if not tracked or _entries(_git(repo, "ls-files", "--stage", "-z"), index=True) != tracked:
        raise ValueError("index differs from deployed tree")
    if any(row and not row.startswith(b"H ") for row in _git(repo, "ls-files", "-v", "-z").split(b"\0")):
        raise ValueError("masked index entry")
    if _git(repo, "ls-files", "--others", "--exclude-standard", "-z"):
        raise ValueError("untracked checkout files")
    for name, (mode, oid) in tracked.items():
        if _blob(repo, name, mode) != oid:
            raise ValueError("tracked bytes differ from deployed tree")
    if _git(repo, "rev-parse", "HEAD").decode().strip() != head:
        raise ValueError("checkout moved during observation")
    return {"head": head, "tree": tree, "clean": True}


if __name__ == "__main__":
    try:
        print(json.dumps(checkout_binding(sys.argv[1]), separators=(",", ":")))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        print('{"clean":false}')
        raise SystemExit(1)
