"""Narrow provider identity bindings for same-day retained CDR captures."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from cdr_atomic import canonical_json_bytes

IDENTITY_FIELDS = ("provider_dir", "provider_uid", "identity_status", "brand_name",
                   "legal_entity_name", "endpoint_url")


def provider_identity(value: Mapping[str, Any]) -> dict:
    return {key: value.get(key) for key in IDENTITY_FIELDS}


def _names(value: Mapping[str, Any]) -> tuple[str, str]:
    return tuple(" ".join(str(value.get(key) or "").split()).casefold()
                 for key in ("brand_name", "legal_entity_name"))


def _legacy(value: Mapping[str, Any]) -> bool:
    material = "\x1f".join(str(value.get(key) or "").strip().lower()
                          for key in ("endpoint_url", "legal_entity_name", "brand_name"))
    return (value.get("identity_status") == "derived_legacy"
            and value.get("provider_uid") == "legacy-prd:" + hashlib.sha256(material.encode()).hexdigest())


def endpoint_transition(previous: dict[str, dict], current: dict[str, dict], provider: str) -> dict | None:
    """Allow only unique, unchanged legal/brand identity with a new endpoint."""
    before, after = previous.get(provider), current.get(provider)
    if not before or not after or not _legacy(before) or not _legacy(after):
        return None
    names = _names(before)
    if (not all(names) or names != _names(after)
            or before.get("provider_dir") != after.get("provider_dir")
            or before.get("endpoint_url") == after.get("endpoint_url")
            or sum(_names(value) == names for value in previous.values()) != 1
            or sum(_names(value) == names for value in current.values()) != 1):
        return None
    return {"provider_dir": provider, "from": provider_identity(before), "to": provider_identity(after)}


def captured_provider_directories(status: Mapping[str, Any], fresh: dict[str, dict]) -> dict[str, dict]:
    """Merge proven retained identities without changing fresh register counts."""
    retained = status.get("retained_provider_states") or []
    if not retained:
        return dict(fresh)
    reuse = status.get("same_day_reuse") or {}
    material = {key: value for key, value in reuse.items() if key != "manifest_sha256"}
    if (reuse.get("schema_version") != 1 or reuse.get("reconciled") is not True
            or reuse.get("manifest_sha256") != hashlib.sha256(canonical_json_bytes(material)).hexdigest()):
        raise ValueError("retained provider identity lacks bound reuse provenance")
    result, seen = dict(fresh), set()
    blocks = reuse.get("identity_blocks") or {}
    for row in retained:
        if not isinstance(row, dict):
            raise ValueError("retained provider identity is invalid")
        provider = str(row.get("provider_dir") or "")
        expected = (reuse.get("providers") or {}).get(provider)
        if (not provider or provider in seen or not expected
                or provider_identity(row) != provider_identity(expected)):
            raise ValueError("retained provider does not match its source identity")
        if provider in fresh and provider not in blocks:
            raise ValueError("retained provider conflicts with the fresh register")
        seen.add(provider)
        result[provider] = dict(row)
    return result
