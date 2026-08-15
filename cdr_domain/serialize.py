"""Deterministic, float-free serialization for content-addressed assets."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any


class FrozenMapping(Mapping[str, Any]):
    """A genuinely immutable mapping for identity derivation material."""

    __slots__ = ("_data",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_data", MappingProxyType(dict(values)))

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise TypeError("canonical semantic mapping storage is immutable")

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenMapping({dict(self._data)!r})"

    def __deepcopy__(self, _memo: dict[int, Any]) -> "FrozenMapping":
        return self


def freeze_semantics(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenMapping(
            {str(key): freeze_semantics(child) for key, child in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_semantics(item) for item in value)
    return value


def semantics_are_frozen(value: Any) -> bool:
    if not isinstance(value, FrozenMapping) or not isinstance(
        value._data, MappingProxyType
    ):
        return False
    return all(
        semantics_are_frozen(child)
        if isinstance(child, Mapping)
        else all(
            semantics_are_frozen(item) if isinstance(item, Mapping) else not isinstance(item, list)
            for item in child
        )
        if isinstance(child, tuple)
        else not isinstance(child, list)
        for child in value.values()
    )


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
    if isinstance(value, Mapping):
        return {str(key): to_primitive(child) for key, child in value.items()}
    if isinstance(value, float):
        raise TypeError("canonical payloads cannot contain binary floating-point values")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    # A dataclass can be replaced into an invalid state even when all nested identity
    # material is immutable. Recheck products at any aggregate nesting depth.
    from .models import CanonicalProduct
    from .validate import validate_canonical_product

    def validate_nested(child: Any) -> None:
        if isinstance(child, CanonicalProduct):
            validate_canonical_product(child)
            return
        if dataclasses.is_dataclass(child):
            for field in dataclasses.fields(child):
                validate_nested(getattr(child, field.name))
            return
        if isinstance(child, Mapping):
            for item in child.values():
                validate_nested(item)
            return
        if isinstance(child, (list, tuple)):
            for item in child:
                validate_nested(item)

    validate_nested(value)
    return json.dumps(
        to_primitive(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
