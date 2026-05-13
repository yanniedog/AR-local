"""Raspberry Pi runtime defaults and low-write helpers for AR-local."""

from __future__ import annotations

import filecmp
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from ar_local_platform import HostKind, host_kind

PI_REPO_ROOT = Path("/home/pi/AR-local")
PI_SITE_ROOT = Path("/home/pi/australianrates/site")
_UID_SUFFIX = os.getuid() if hasattr(os, "getuid") else "shared"
PI_RAM_ROOT = Path(os.environ.get("AR_LOCAL_RAM_ROOT", f"/dev/shm/ar-local-{_UID_SUFFIX}"))
PI_DASHBOARD_HOST = "0.0.0.0"
PI_DASHBOARD_PORT = 8808


def is_raspberry_pi() -> bool:
    return host_kind() == HostKind.RASPBERRY_PI


def default_ram_root() -> Path:
    return Path(os.environ.get("AR_LOCAL_RAM_ROOT", str(PI_RAM_ROOT))).expanduser().resolve()


def prepare_empty_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copytree_atomic(src: Path, dst: Path) -> None:
    """Copy a completed tree into place with a same-parent final rename."""
    src = src.resolve()
    dst = dst.resolve()
    if dst.exists() and tree_contents_equal(src, dst):
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.tmp-{os.getpid()}-{int(time.time())}"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp)
    if dst.exists():
        backup = dst.parent / f".{dst.name}.previous-{int(time.time())}"
        if backup.exists():
            shutil.rmtree(backup)
        dst.replace(backup)
        tmp.replace(dst)
        shutil.rmtree(backup)
        return
    tmp.replace(dst)


def tree_contents_equal(left: Path, right: Path) -> bool:
    if not left.is_dir() or not right.is_dir():
        return False
    left_files = sorted(p.relative_to(left) for p in left.rglob("*") if p.is_file())
    right_files = sorted(p.relative_to(right) for p in right.rglob("*") if p.is_file())
    if left_files != right_files:
        return False
    for rel in left_files:
        if not filecmp.cmp(left / rel, right / rel, shallow=False):
            return False
    return True


def latest_exports_root(runs_root: Path) -> Optional[Path]:
    runs_root = runs_root.expanduser().resolve()
    if not runs_root.is_dir():
        return None
    candidates = []
    for child in runs_root.iterdir():
        if not child.is_dir():
            continue
        exports = child / "_exports"
        if (exports / "dashboard-cache" / "latest.json").is_file():
            candidates.append((child.name, exports))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[-1][1].resolve()
