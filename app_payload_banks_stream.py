"""Read a complete banks artifact with bounded JSON tokens and streamed arrays.

Projection discards only in-memory copies; every original byte is hashed and the
complete JSON document is validated before any result is returned.
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    source_bytes: int = 512 * 1024**2
    value_bytes: int = 8 * 1024**2
    retained_bytes: int = 256 * 1024**2
    array_rows: int = 1000000
    chunk_bytes: int = 64 * 1024

    def validate(self):
        for key, value in self.__dict__.items():
            if type(value) is not int or not 0 < value <= getattr(Limits(), key):
                raise ValueError("Invalid streamed banks reader budget")


def signature(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate banks JSON field")
        result[key] = value
    return result


class Reader:
    def __init__(self, stream, limits):
        self.stream, self.limits = stream, limits
        self.buffer, self.eof, self.count, self.retained = "", False, 0, 0
        self.hash = hashlib.sha256()
        self.utf8 = codecs.getincrementaldecoder("utf-8")()
        self.json = json.JSONDecoder(object_pairs_hook=pairs)

    def more(self):
        raw = self.stream.read(min(self.limits.chunk_bytes, self.limits.source_bytes - self.count + 1))
        self.count += len(raw)
        if self.count > self.limits.source_bytes:
            raise ValueError("Streamed banks source exceeds byte budget")
        self.hash.update(raw)
        self.eof = not raw
        self.buffer += self.utf8.decode(raw, final=self.eof)

    def peek(self):
        while True:
            self.buffer = self.buffer.lstrip(" \r\n\t")
            if self.buffer or self.eof:
                return self.buffer[:1]
            self.more()

    def token(self, expected):
        if self.peek() != expected:
            raise ValueError("Malformed banks JSON delimiter")
        self.buffer = self.buffer[1:]

    def value(self):
        self.peek()
        while True:
            try:
                value, end = self.json.raw_decode(self.buffer)
            except json.JSONDecodeError:
                if self.eof or len(self.buffer) > self.limits.value_bytes:
                    raise ValueError("Malformed or oversized banks JSON value") from None
                self.more()
                continue
            # A number may continue in the next chunk (e.g. 1 then 2e-3).
            if end == len(self.buffer) or self.buffer[end] not in " \r\n\t,:]}":
                if not self.eof and len(self.buffer) <= self.limits.value_bytes:
                    self.more()
                    continue
                if end != len(self.buffer):
                    raise ValueError("Malformed banks JSON value boundary")
            size = len(self.buffer[:end].encode("utf-8"))
            if size > self.limits.value_bytes:
                raise ValueError("Banks JSON value exceeds byte budget")
            self.buffer = self.buffer[end:]
            return value, size

    def keep(self, size):
        self.retained += size
        if self.retained > self.limits.retained_bytes:
            raise ValueError("Banks projection exceeds retained byte budget")

    def array(self, *, retain, consume=None):
        self.token("[")
        result, count = [], 0
        if self.peek() == "]":
            self.token("]")
            return result
        while True:
            value, size = self.value()
            count += 1
            if count > self.limits.array_rows:
                raise ValueError("Banks array exceeds row budget")
            if consume is not None:
                consume(value)
            if retain:
                self.keep(size)
                result.append(value)
            if self.peek() == "]":
                self.token("]")
                return result
            self.token(",")

    def document(self, *, retain_fields, product_consumer):
        self.token("{")
        result, seen = {}, set()
        if self.peek() != "}":
            while True:
                key, _ = self.value()
                if not isinstance(key, str) or key in seen or len(seen) >= 128:
                    raise ValueError("Invalid or duplicate banks JSON field")
                seen.add(key)
                self.token(":")
                retain = retain_fields is None or key in retain_fields
                consume = product_consumer if key == "products" else None
                if self.peek() == "[":
                    value = self.array(retain=retain and consume is None, consume=consume)
                else:
                    value, size = self.value()
                    if retain:
                        self.keep(size)
                if retain:
                    result[key] = value
                if self.peek() == "}":
                    break
                self.token(",")
        self.token("}")
        if self.peek():
            raise ValueError("Trailing banks JSON content")
        return result


def read_banks(path, *, retain_fields=None, product_consumer=None, expected=None, limits=Limits()):
    """Return (projection, original SHA256, original bytes); expected is an artifact record."""
    limits.validate()
    path = Path(path).absolute()
    if path.resolve() != path or not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Selected bank-rate history source is missing or unsafe")
    before = signature(path.stat())
    if not 0 < before[2] <= limits.source_bytes:
        raise ValueError("Bank-rate history source exceeds byte budget")
    with path.open("rb") as stream:
        if signature(os.fstat(stream.fileno())) != before:
            raise ValueError("Bank-rate history source changed before read")
        reader = Reader(stream, limits)
        value = reader.document(retain_fields=retain_fields, product_consumer=product_consumer)
        if signature(os.fstat(stream.fileno())) != before or signature(path.stat()) != before or reader.count != before[2]:
            raise ValueError("Bank-rate history source changed during read")
    sha = reader.hash.hexdigest()
    if expected is not None and (expected["bytes"] != reader.count or expected["sha256"] != sha):
        raise ValueError("Selected bank-rate history source differs from its contract")
    return value, sha, reader.count
