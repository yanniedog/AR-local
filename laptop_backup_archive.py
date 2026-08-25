"""Lossless zstd-tar inspection and extraction for laptop restore drills."""

from __future__ import annotations

import hashlib
import os
import tarfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Mapping

import zstandard


CHUNK = 4 * 1024**2
PathValidator = Callable[[str, dict[str, str]], None]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@contextmanager
def open_tar_stream(archive: Path) -> Iterator[tarfile.TarFile]:
    """Open plain or zstd-compressed tar bytes without recoding member names."""
    with archive.open("rb") as source:
        magic = source.read(4)
        source.seek(0)
        if magic == b"\x28\xb5\x2f\xfd":
            with zstandard.ZstdDecompressor().stream_reader(source) as decoded:
                with tarfile.open(
                    fileobj=decoded,
                    mode="r|*",
                    encoding="utf-8",
                    errors="surrogateescape",
                ) as stream:
                    yield stream
        else:
            with tarfile.open(
                fileobj=source,
                mode="r:*",
                encoding="utf-8",
                errors="surrogateescape",
            ) as stream:
                yield stream


def _read_metadata(stream: tarfile.TarFile) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for member in stream:
        relative = member.name.removeprefix("./")
        if member.isdir():
            continue
        if not member.isfile():
            raise ValueError(f"archive contains a non-regular member: {relative}")
        entries.append({
            "path": relative,
            "type": "file",
            "size": member.size,
            "mode": oct(member.mode),
            "mtime_ns": int(member.mtime * 1_000_000_000),
            "uid": member.uid,
            "gid": member.gid,
        })
    return entries


def tar_metadata(archive: Path) -> list[dict[str, object]]:
    """Read raw tar headers without Windows libarchive filename recoding."""
    try:
        with open_tar_stream(archive) as stream:
            return _read_metadata(stream)
    except (tarfile.TarError, zstandard.ZstdError) as exc:
        raise RuntimeError(f"compressed archive is unreadable: {exc}") from exc


def verify_tar_metadata(manifest: Mapping[str, object], archive: Path) -> None:
    expected = [
        {key: item[key] for key in ("path", "type", "size", "mode", "mtime_ns", "uid", "gid")}
        for item in manifest["files"]
    ]
    actual = tar_metadata(archive)
    if actual == expected:
        return
    for index in range(max(len(expected), len(actual))):
        wanted = expected[index] if index < len(expected) else None
        found = actual[index] if index < len(actual) else None
        if wanted != found:
            raise ValueError(
                "tar member metadata mismatch "
                f"at index {index}: expected={wanted!r}; actual={found!r}"
            )
    raise ValueError("tar member metadata mismatch without a differentiating entry")


def extract_archive(archive: Path, destination: Path, validate_path: PathValidator) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    seen: dict[str, str] = {}
    try:
        with open_tar_stream(archive) as stream:
            for member in stream:
                relative = member.name.removeprefix("./")
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError(f"archive contains a non-regular member: {relative}")
                validate_path(relative, seen)
                target = destination.joinpath(*PurePosixPath(relative).parts)
                if not _is_within(target, destination) or target.exists():
                    raise ValueError(f"unsafe or duplicate archive member: {relative}")
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = stream.extractfile(member)
                if payload is None:
                    raise ValueError(f"archive member has no readable bytes: {relative}")
                written = 0
                with payload, target.open("xb") as output:
                    for block in iter(lambda: payload.read(CHUNK), b""):
                        output.write(block)
                        written += len(block)
                    output.flush()
                    os.fsync(output.fileno())
                if written != member.size:
                    raise ValueError(f"archive member size mismatch: {relative}")
                os.chmod(target, member.mode)
                mtime_ns = int(member.mtime * 1_000_000_000)
                os.utime(target, ns=(mtime_ns, mtime_ns))
    except (tarfile.TarError, zstandard.ZstdError) as exc:
        raise RuntimeError(f"archive extraction failed: {exc}") from exc


def extracted_entries(root: Path) -> list[dict[str, object]]:
    entries = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().encode("utf-8")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"extracted archive contains symlink: {relative}")
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(CHUNK), b""):
                    digest.update(block)
            entries.append({"path": relative, "size": path.stat().st_size, "sha256": digest.hexdigest()})
        elif not path.is_dir():
            raise ValueError(f"extracted archive contains special file: {relative}")
    return entries
