"""Stable identities and exact contract primitives."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

SHA256 = re.compile(r"^[a-f0-9]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def byte_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_sha(value: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError("Expected a lowercase SHA-256 identity")
    return value


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Evidence timestamps require an explicit timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def exact_value(value: Any) -> None:
    """Reject binary float money/rates in interpreted terms (use decimal text)."""
    if isinstance(value, float):
        raise ValueError("Term quantities must use exact decimal strings, not floats")
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 9007199254740991:
        raise ValueError("Public integer exceeds the cross-platform exact range")
    if isinstance(value, dict):
        for child in value.values():
            exact_value(child)
    elif isinstance(value, list):
        for child in value:
            exact_value(child)
    canonical_json(value)
