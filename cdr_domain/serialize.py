"""Deterministic, float-free serialization for content-addressed assets."""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from typing import Any


def to_primitive(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {
            field.name: to_primitive(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [to_primitive(item) for item in value]
    if isinstance(value, list):
        return [to_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_primitive(child) for key, child in value.items()}
    if isinstance(value, float):
        raise TypeError("canonical payloads cannot contain binary floating-point values")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        to_primitive(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
