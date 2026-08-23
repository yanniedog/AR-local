"""Fail-closed source scoping for AR-local preservation snapshots."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

REQUIRED_DATA_DIRS = ("runs", "state")
OPTIONAL_DATA_DIRS = ("logs", "predeploy", "runs-archive")
TRANSIENT_EMPTY_DIRS = (".daily-export-stage",)
METADATA_ONLY_DIRS = {
    "netdata": "live telemetry databases and credential-bearing state are not CDR recovery data",
}
NETDATA_SECRET_RELATIVES = (
    "netdata/lib/bearer_tokens",
    "netdata/lib/mcp_dev_preview_api_key",
    "netdata/lib/config",
    "netdata/lib/cloud.d",
)


@dataclass(frozen=True)
class DataSnapshotScope:
    root: Path
    included: tuple[Path, ...]
    excluded: tuple[dict[str, object], ...]
    secret_locations: tuple[Path, ...]

    def manifest(self) -> dict[str, object]:
        return {
            "policy_version": 1,
            "included": [path.relative_to(self.root).as_posix() for path in self.included],
            "excluded": list(self.excluded),
            "unknown_roots_allowed": False,
        }


def _top_level_metadata(path: Path, reason: str, *, contents_copied: bool) -> dict[str, object]:
    if path.is_symlink():
        raise ValueError(f"data-root scoped path is a symlink: {path}")
    if not path.exists():
        return {
            "path": path.name,
            "exists": False,
            "contents_copied": contents_copied,
            "reason": reason,
        }
    if not path.is_dir():
        raise ValueError(f"data-root scoped path is not a real directory: {path}")
    info = path.stat()
    return {
        "path": path.name,
        "exists": True,
        "contents_copied": contents_copied,
        "reason": reason,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": oct(stat.S_IMODE(info.st_mode)),
    }


def build_data_scope(data_root: Path) -> DataSnapshotScope:
    configured = data_root.expanduser()
    if not configured.is_absolute():
        raise ValueError("production data root must be absolute")
    root = configured.resolve(strict=True)
    if configured != root or configured.is_symlink() or not root.is_dir():
        raise ValueError("production data root must be a canonical real directory")
    known = set(REQUIRED_DATA_DIRS + OPTIONAL_DATA_DIRS + TRANSIENT_EMPTY_DIRS) | set(METADATA_ONLY_DIRS)
    children = {path.name: path for path in root.iterdir()}
    unknown = sorted(children.keys() - known)
    if unknown:
        raise ValueError(f"production data root contains unclassified paths: {', '.join(unknown)}")
    missing = sorted(set(REQUIRED_DATA_DIRS) - children.keys())
    if missing:
        raise ValueError(f"production data root is missing required paths: {', '.join(missing)}")
    included: list[Path] = []
    for name in (*REQUIRED_DATA_DIRS, *OPTIONAL_DATA_DIRS):
        if name not in children:
            continue
        path = children[name]
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"included data path is not a real directory: {path}")
        included.append(path)
    excluded: list[dict[str, object]] = []
    for name in TRANSIENT_EMPTY_DIRS:
        path = root / name
        metadata = _top_level_metadata(
            path,
            "transient ingest/export staging must be empty before preservation",
            contents_copied=False,
        )
        if path.exists() and next(path.iterdir(), None) is not None:
            raise ValueError(f"transient data path is not empty: {path}")
        excluded.append(metadata)
    for name, reason in METADATA_ONLY_DIRS.items():
        excluded.append(
            _top_level_metadata(root / name, reason, contents_copied=False)
        )
    return DataSnapshotScope(
        root=root,
        included=tuple(included),
        excluded=tuple(excluded),
        secret_locations=tuple(root / relative for relative in NETDATA_SECRET_RELATIVES),
    )


def copy_regular_tree(source: Path, destination: Path, *, exclude: set[Path] | None = None) -> None:
    excluded = {path.resolve() for path in (exclude or set())}
    destination.mkdir(parents=True, exist_ok=False)
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"snapshot source contains symlink: {item}")
        if item.is_dir():
            (destination / item.relative_to(source)).mkdir(parents=True, exist_ok=True)
            continue
        if not item.is_file():
            raise ValueError(f"snapshot source contains non-regular file: {item}")
        if item.stat().st_nlink != 1:
            raise ValueError(f"snapshot source contains hardlink: {item}")
        if item.resolve() in excluded:
            continue
        before = item.stat()
        target = destination / item.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        after = item.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"snapshot source changed during copy: {item}")
        if _sha256(item) != _sha256(target):
            raise RuntimeError(f"snapshot copy hash mismatch: {item}")


def tree_metadata(source: Path, exclude: set[Path]) -> dict[str, tuple[int, int]]:
    excluded = {path.resolve() for path in exclude}
    result: dict[str, tuple[int, int]] = {}
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"snapshot source contains symlink: {item}")
        if item.is_dir() or item.resolve() in excluded:
            continue
        if not item.is_file() or item.stat().st_nlink != 1:
            raise ValueError(f"snapshot source is not a unique regular file: {item}")
        info = item.stat()
        result[item.relative_to(source).as_posix()] = (info.st_size, info.st_mtime_ns)
    return result


def scoped_tree_metadata(scope: DataSnapshotScope, exclude: set[Path]) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for source in scope.included:
        prefix = source.relative_to(scope.root).as_posix()
        for relative, metadata in tree_metadata(source, exclude).items():
            result[f"{prefix}/{relative}"] = metadata
    return result


def copy_scoped_data(scope: DataSnapshotScope, destination: Path, *, exclude: set[Path]) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for source in scope.included:
        copy_regular_tree(source, destination / source.relative_to(scope.root), exclude=exclude)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
