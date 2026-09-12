"""Disk-indexed backup manifests with the original portable JSON wire format.

Only one file record is decoded at a time. Historical manifests remain ordinary
JSON objects with files/excluded arrays, so existing receipts and restores work.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from pi_laptop_backup_source import validate_archive_path

CHUNK_BYTES = 64 * 1024
MAX_VALUE_CHARS = 16 * 1024 * 1024


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


class ManifestIndex:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA cache_size=-2048")
        self.db.execute("PRAGMA temp_store=FILE")
        self.db.execute("CREATE TABLE IF NOT EXISTS files (logical_path TEXT PRIMARY KEY, folded TEXT UNIQUE NOT NULL, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS excluded (path TEXT PRIMARY KEY)")
        self.pending = 0

    def append(self, row: dict) -> None:
        if not isinstance(row, dict) or not isinstance(row.get("logical_path"), str):
            raise ValueError("backup manifest row requires a logical path")
        logical = row["logical_path"]
        validate_archive_path(logical, {})
        try:
            self.db.execute("INSERT INTO files VALUES(?,?,?)", (logical, logical.casefold(), encoded(row).decode("utf-8")))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"duplicate or case-insensitive manifest path: {logical}") from exc
        self._flush_batch()

    def exclude(self, path: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO excluded VALUES(?)", (path,))
        self._flush_batch()

    def _flush_batch(self) -> None:
        self.pending += 1
        if self.pending >= 256:
            self.db.commit()
            self.pending = 0

    def rows(self, table: str = "files"):
        self.db.commit()
        return DiskRows(self, table)

    def close(self) -> None:
        if self.db is not None:
            self.db.commit()
            self.db.close()
            self.db = None

    def __del__(self):
        if getattr(self, "db", None) is not None:
            self.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, _error, _traceback):
        if kind is not None:
            self.close()


class DiskRows:
    def __init__(self, index: ManifestIndex, table: str = "files"):
        if table not in {"files", "excluded"}:
            raise ValueError("invalid manifest table")
        self.index, self.table = index, table

    def __iter__(self):
        sql = "SELECT value FROM files ORDER BY logical_path" if self.table == "files" else "SELECT path FROM excluded ORDER BY path"
        cursor = self.index.db.execute(sql)
        try:
            for row in cursor:
                yield json.loads(row[0]) if self.table == "files" else row[0]
        finally:
            cursor.close()

    def __len__(self):
        return self.index.db.execute(f"SELECT count(*) FROM {self.table}").fetchone()[0]

    def __getitem__(self, offset: int):
        if offset < 0:
            offset += len(self)
        if offset < 0:
            raise IndexError(offset)
        sql = "SELECT value FROM files ORDER BY logical_path LIMIT 1 OFFSET ?" if self.table == "files" else "SELECT path FROM excluded ORDER BY path LIMIT 1 OFFSET ?"
        row = self.index.db.execute(sql, (offset,)).fetchone()
        if row is None:
            raise IndexError(offset)
        return json.loads(row[0]) if self.table == "files" else row[0]

    def get(self, logical: str, default=None):
        row = self.index.db.execute("SELECT value FROM files WHERE logical_path=?", (logical,)).fetchone()
        return json.loads(row[0]) if row else default


class SelectedRows:
    """Reusable streaming view for multi-pass size/include/restore checks."""
    def __init__(self, rows: Iterable, predicate=lambda _: True, extra: Iterable = ()):
        self.rows, self.predicate, self.extra = rows, predicate, tuple(extra)

    def __iter__(self):
        yield from (row for row in self.rows if self.predicate(row))
        yield from self.extra

    def __len__(self):
        return sum(1 for _ in self)


def json_chunks(value):
    if isinstance(value, dict):
        yield b"{"
        for offset, key in enumerate(sorted(value)):
            if offset:
                yield b","
            yield encoded(key)
            yield b":"
            yield from json_chunks(value[key])
        yield b"}"
    elif isinstance(value, (list, tuple, DiskRows, SelectedRows)):
        yield b"["
        for offset, item in enumerate(value):
            if offset:
                yield b","
            # File records are deliberately encoded one at a time.
            if isinstance(value, DiskRows):
                yield encoded(item)
            else:
                yield from json_chunks(item)
        yield b"]"
    else:
        yield encoded(value)


def content_digest(rows) -> str:
    value = hashlib.sha256()
    value.update(b"[")
    for offset, row in enumerate(rows):
        if offset:
            value.update(b",")
        value.update(encoded({key: row[key] for key in ("logical_path", "sha256", "size", "mode", "uid", "gid")}))
    value.update(b"]\n")
    return value.hexdigest()


class _Reader:
    def __init__(self, stream):
        self.stream, self.buffer, self.offset, self.eof = stream, "", 0, False
        self.decoder = json.JSONDecoder()

    def fill(self):
        self.buffer = self.buffer[self.offset:]
        self.offset = 0
        chunk = self.stream.read(CHUNK_BYTES)
        self.eof = not chunk
        self.buffer += chunk
        if len(self.buffer) > MAX_VALUE_CHARS:
            raise ValueError("backup manifest record exceeds bounded decode limit")

    def peek(self):
        while True:
            while self.offset < len(self.buffer) and self.buffer[self.offset].isspace():
                self.offset += 1
            if self.offset < len(self.buffer):
                return self.buffer[self.offset]
            if self.eof:
                return ""
            self.fill()

    def expect(self, character):
        if self.peek() != character:
            raise ValueError("malformed backup manifest structure")
        self.offset += 1

    def value(self):
        self.peek()
        while True:
            try:
                result, end = self.decoder.raw_decode(self.buffer, self.offset)
                if end == len(self.buffer) and not self.eof:
                    self.fill()
                    continue
                self.offset = end
                return result
            except json.JSONDecodeError:
                if self.eof:
                    raise ValueError("truncated backup manifest")
                self.fill()


def load_manifest(path: Path, index_path: Path) -> dict:
    index = ManifestIndex(index_path)
    document = {}
    try:
        with path.open(encoding="utf-8") as stream:
            reader = _Reader(stream)
            reader.expect("{")
            while reader.peek() != "}":
                key = reader.value()
                if not isinstance(key, str) or key in document:
                    raise ValueError("duplicate or invalid backup manifest field")
                reader.expect(":")
                if key in {"files", "excluded"}:
                    reader.expect("[")
                    while reader.peek() != "]":
                        row = reader.value()
                        index.append(row) if key == "files" else index.exclude(row)
                        if reader.peek() != "]":
                            reader.expect(",")
                    reader.expect("]")
                    document[key] = index.rows(key)
                else:
                    document[key] = reader.value()
                if reader.peek() != "}":
                    reader.expect(",")
            reader.expect("}")
            if reader.peek():
                raise ValueError("trailing content after backup manifest")
        if "files" not in document:
            raise ValueError("backup manifest requires files")
        return document
    except BaseException:
        index.close()
        raise


def close_manifest(document: dict) -> None:
    rows = document.get("files")
    if isinstance(rows, DiskRows):
        rows.index.close()
