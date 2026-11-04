"""Rejoin exact-source raw records into an already owned, newly built image.

The committed SQLite views from the raw restore tool are never inputs here.
This module receives only the new image mount and a read-only restore workspace.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from pathlib import Path

from pi_system_capture import DATA_PREFIX, fingerprint, relative


def external_files(mapping):
    with Path(mapping).open(encoding="ascii") as stream:
        for line in stream:
            item = json.loads(line)
            row = item.get("external")
            if not row:
                continue  # Volatile sockets are explicitly separate exclusions.
            name = relative(item["path"])
            source = relative(row["source_relative"])
            if (item["tree"] != "root" or name != DATA_PREFIX + source
                    or row["representation"] != "exact_source_bytes"):
                raise ValueError("external map is not an exact-source raw file")
            yield name, row


def expected_row(name, row):
    mode = int(row["mode"], 0) if isinstance(row["mode"], str) else row["mode"]
    return {"path": name, "type": stat.S_IFREG, "mode": mode,
            "uid": row["uid"], "gid": row["gid"], "mtime_ns": row["mtime_ns"],
            "size": row["size"], "sha256": row["sha256"], "xattrs": row["restore_xattrs"]}


def safe_leaf(root, name):
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root or not root.is_dir() or root.is_symlink():
        raise ValueError("raw restore root must be an existing canonical directory")
    path = root / relative(name)
    for parent in path.parents:
        if parent == root:
            break
        if not parent.is_dir() or parent.is_symlink():
            raise ValueError("raw restore path has an absent or symlinked ancestor")
    return path


def restore_raw(image_root, restored_workspace, mapping, catalog_sha256, manifest, full_manifest):
    restored_workspace = Path(restored_workspace)
    result = json.loads((restored_workspace / "restore-result.json").read_text())
    if result.get("result") != "FILES_RESTORED_VERIFIED" or result.get("catalog_sha256") != catalog_sha256:
        raise ValueError("raw restore result differs from accepted cloud catalog")
    copied, total = 0, 0
    with Path(full_manifest).open("x", encoding="ascii") as output:
        with Path(manifest).open(encoding="ascii") as existing:
            for line in existing:
                output.write(line)
        for name, row in external_files(mapping):
            source = safe_leaf(restored_workspace / "data", row["source_relative"])
            target = safe_leaf(image_root, name)
            source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0))
            try:
                before = os.fstat(source_fd)
                if not stat.S_ISREG(before.st_mode) or before.st_size != row["size"]:
                    raise ValueError("raw restored source is not the expected regular file")
                target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                digest = hashlib.sha256()
                with os.fdopen(target_fd, "wb") as destination:
                    while True:
                        block = os.read(source_fd, 1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                        destination.write(block)
                    destination.flush()
                    os.fsync(destination.fileno())
                if digest.hexdigest() != row["sha256"] or fingerprint(os.fstat(source_fd)) != fingerprint(before):
                    raise ValueError("raw restored bytes changed or do not match external map")
            finally:
                os.close(source_fd)
            expected = expected_row(name, row)
            os.chown(target, expected["uid"], expected["gid"], follow_symlinks=False)
            os.chmod(target, expected["mode"], follow_symlinks=False)
            for key, value in expected["xattrs"].items():
                os.setxattr(target, key, base64.b64decode(value, validate=True), follow_symlinks=False)
            os.utime(target, ns=(before.st_atime_ns, expected["mtime_ns"]), follow_symlinks=False)
            output.write(json.dumps(expected, sort_keys=True) + "\n")
            copied += 1
            total += row["size"]
        output.flush()
        os.fsync(output.fileno())
    return {"result": "EXACT_RAW_FILES_REJOINED", "files": copied, "bytes": total,
            "catalog_sha256": catalog_sha256, "committed_views_used": False}
