"""Persistent, fail-closed provider fallback identity bindings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from cdr_atomic import atomic_write_json, canonical_json_bytes
from cdr_contracts import (
    PROVIDER_UID_RE,
    canonical_authority,
    normalize_provider_display_name,
    provider_uid,
)
from cdr_file_lock import FileLock


SCHEMA_VERSION = 1
REGISTRY_FILENAME = "provider-identity-registry-v1.json"
_ROOT_FIELDS = {"schema_version", "bindings"}
_BINDING_FIELDS = {
    "provider_uid",
    "authority",
    "display_name",
    "anchors",
    "authorized_aliases",
}
_ANCHOR_FIELDS = {"kind", "value"}
_ALIAS_FIELDS = {"authority", "display_name", "authorized_by"}
_ANCHOR_KINDS = {"data_holder_id", "data_holder_brand_id", "interim_id"}


class ProviderIdentityRegistryError(ValueError):
    """The provider registry cannot be trusted or reconciled."""


def _exact(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise ProviderIdentityRegistryError(f"{label} has missing or unexpected fields")


def _safe_text(value: Any, label: str, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise ProviderIdentityRegistryError(f"{label} must be text")
    text = value.strip()
    if not text or len(text) > maximum or any(ord(char) < 32 for char in text):
        raise ProviderIdentityRegistryError(f"{label} is invalid")
    return text


def _signature(authority: Any, display_name: Any) -> tuple[str, str]:
    authority_text = _safe_text(authority, "registry authority", 255)
    name = normalize_provider_display_name(
        _safe_text(display_name, "registry display_name", 256)
    )
    try:
        canonical = canonical_authority((f"https://{authority_text}",))
    except ValueError as error:
        raise ProviderIdentityRegistryError("registry authority is invalid") from error
    if canonical != authority_text:
        raise ProviderIdentityRegistryError("registry authority is not canonical")
    return canonical, name


def _anchors(row: Mapping[str, Any]) -> list[dict[str, str]]:
    result = []
    strong = ("data_holder_brand_id", "interim_id")
    kinds = strong if any(str(row.get(kind) or "").strip() for kind in strong) else ("data_holder_id",)
    for kind in kinds:
        value = str(row.get(kind) or "").strip()
        if value:
            result.append({"kind": kind, "value": value})
    return sorted(result, key=lambda item: (item["kind"], item["value"]))


def _validate(document: Any) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise ProviderIdentityRegistryError("provider registry must be an object")
    _exact(document, _ROOT_FIELDS, "provider registry")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ProviderIdentityRegistryError("provider registry schema version is unsupported")
    raw_bindings = document.get("bindings")
    if not isinstance(raw_bindings, list):
        raise ProviderIdentityRegistryError("provider registry bindings must be an array")
    bindings: list[dict[str, Any]] = []
    seen_uids: set[str] = set()
    seen_signatures: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_bindings):
        if not isinstance(raw, Mapping):
            raise ProviderIdentityRegistryError(f"binding {index} must be an object")
        _exact(raw, _BINDING_FIELDS, f"binding {index}")
        authority, name = _signature(raw["authority"], raw["display_name"])
        uid, status = provider_uid(
            data_holder_id=None,
            data_holder_brand_id=None,
            endpoint_urls=(f"https://{authority}",),
            display_name=name,
        )
        if status != "fallback" or raw.get("provider_uid") != uid or uid in seen_uids:
            raise ProviderIdentityRegistryError("fallback binding identity is invalid or duplicated")
        raw_anchors = raw.get("anchors")
        if not isinstance(raw_anchors, list):
            raise ProviderIdentityRegistryError("binding anchors must be an array")
        anchors: list[dict[str, str]] = []
        for anchor in raw_anchors:
            if not isinstance(anchor, Mapping):
                raise ProviderIdentityRegistryError("binding anchor must be an object")
            _exact(anchor, _ANCHOR_FIELDS, "binding anchor")
            kind = _safe_text(anchor.get("kind"), "anchor kind", 64)
            if kind not in _ANCHOR_KINDS:
                raise ProviderIdentityRegistryError("binding anchor kind is unknown")
            anchors.append({"kind": kind, "value": _safe_text(anchor.get("value"), "anchor value")})
        if anchors != sorted(anchors, key=lambda item: (item["kind"], item["value"])):
            raise ProviderIdentityRegistryError("binding anchors are not canonical")
        if len({(item["kind"], item["value"]) for item in anchors}) != len(anchors):
            raise ProviderIdentityRegistryError("binding anchors are duplicated")
        raw_aliases = raw.get("authorized_aliases")
        if not isinstance(raw_aliases, list):
            raise ProviderIdentityRegistryError("authorized_aliases must be an array")
        aliases: list[dict[str, str]] = []
        for alias in raw_aliases:
            if not isinstance(alias, Mapping):
                raise ProviderIdentityRegistryError("authorized alias must be an object")
            _exact(alias, _ALIAS_FIELDS, "authorized alias")
            alias_authority, alias_name = _signature(alias["authority"], alias["display_name"])
            aliases.append(
                {
                    "authority": alias_authority,
                    "display_name": alias_name,
                    "authorized_by": _safe_text(alias.get("authorized_by"), "authorized_by", 256),
                }
            )
        if aliases != sorted(aliases, key=lambda item: (item["authority"], item["display_name"])):
            raise ProviderIdentityRegistryError("authorized aliases are not canonical")
        signatures = {(authority, name)} | {
            (item["authority"], item["display_name"]) for item in aliases
        }
        if seen_signatures & signatures:
            raise ProviderIdentityRegistryError("fallback signature is bound more than once")
        seen_signatures.update(signatures)
        seen_uids.add(uid)
        bindings.append(
            {
                "provider_uid": uid,
                "authority": authority,
                "display_name": name,
                "anchors": anchors,
                "authorized_aliases": aliases,
            }
        )
    if bindings != sorted(bindings, key=lambda item: item["provider_uid"]):
        raise ProviderIdentityRegistryError("provider registry bindings are not canonical")
    return {"schema_version": SCHEMA_VERSION, "bindings": bindings}


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "bindings": []}
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProviderIdentityRegistryError("provider registry is unreadable") from error
    document = _validate(value)
    if payload != canonical_json_bytes(document):
        raise ProviderIdentityRegistryError("provider registry is not canonical")
    return document


def validate_registry_snapshot_bytes(payload: bytes) -> dict[str, Any]:
    """Validate one immutable per-run registry snapshot."""

    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProviderIdentityRegistryError("provider registry snapshot is unreadable") from error
    document = _validate(value)
    if payload != canonical_json_bytes(document):
        raise ProviderIdentityRegistryError("provider registry snapshot is not canonical")
    return document


def resolve_provider_rows(
    rows: Iterable[Mapping[str, Any]], registry_path: Path
) -> tuple[list[dict[str, Any]], bytes]:
    """Resolve rows under one locked registry update and hold alias conflicts."""

    path = registry_path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(path.with_suffix(path.suffix + ".lock")):
        document = _load(path)
        bindings = list(document["bindings"])
        by_signature: dict[tuple[str, str], str] = {}
        by_anchor: dict[tuple[str, str], set[str]] = {}
        for binding in bindings:
            signatures = [(binding["authority"], binding["display_name"]), *[
                (alias["authority"], alias["display_name"])
                for alias in binding["authorized_aliases"]
            ]]
            for signature in signatures:
                by_signature[signature] = binding["provider_uid"]
            for anchor in binding["anchors"]:
                by_anchor.setdefault((anchor["kind"], anchor["value"]), set()).add(
                    binding["provider_uid"]
                )
        resolved: list[dict[str, Any]] = []
        for source in rows:
            row = dict(source)
            uid = str(row.get("provider_uid") or "")
            if not PROVIDER_UID_RE.fullmatch(uid):
                raise ProviderIdentityRegistryError("register row has invalid provider_uid")
            if row.get("provider_identity_status") == "official":
                resolved.append(row)
                continue
            authority, _ = _signature(
                row.get("identity_authority"),
                row.get("brand_name") or row.get("legal_entity_name"),
            )
            name = normalize_provider_display_name(
                str(row.get("brand_name") or row.get("legal_entity_name") or "")
            )
            signature = (authority, name)
            anchors = _anchors(row)
            mapped = by_signature.get(signature)
            anchor_uids = {
                candidate
                for anchor in anchors
                for candidate in by_anchor.get((anchor["kind"], anchor["value"]), set())
            }
            if mapped is not None and not (anchor_uids - {mapped}):
                row["provider_uid"] = mapped
                row["provider_identity_status"] = "fallback"
            elif anchor_uids:
                row["provider_uid"] = sorted(anchor_uids | ({mapped} if mapped else set()))[0]
                row["provider_identity_status"] = "fallback_conflict"
                row["provider_identity_held"] = True
                row["provider_identity_evidence_digest"] = hashlib.sha256(
                    canonical_json_bytes(
                        {"authority": authority, "display_name": name, "anchors": anchors}
                    )
                ).hexdigest()
            else:
                binding = {
                    "provider_uid": uid,
                    "authority": authority,
                    "display_name": name,
                    "anchors": anchors,
                    "authorized_aliases": [],
                }
                if uid in {item["provider_uid"] for item in bindings}:
                    row["provider_identity_status"] = "fallback_conflict"
                    row["provider_identity_held"] = True
                    row["provider_identity_evidence_digest"] = hashlib.sha256(
                        canonical_json_bytes(
                            {"authority": authority, "display_name": name, "anchors": anchors}
                        )
                    ).hexdigest()
                else:
                    bindings.append(binding)
                    by_signature[signature] = uid
                    for anchor in anchors:
                        by_anchor.setdefault((anchor["kind"], anchor["value"]), set()).add(uid)
            resolved.append(row)
        updated = _validate(
            {"schema_version": SCHEMA_VERSION, "bindings": sorted(bindings, key=lambda item: item["provider_uid"])}
        )
        atomic_write_json(path, updated)
        return resolved, canonical_json_bytes(updated)


def authorize_alias(
    registry_path: Path,
    provider: str,
    *,
    endpoint_urls: Iterable[str],
    display_name: str,
    authorized_by: str,
) -> None:
    """Append one explicit operator-authorized fallback alias."""

    path = registry_path.expanduser().resolve()
    with FileLock(path.with_suffix(path.suffix + ".lock")):
        document = _load(path)
        authority = canonical_authority(endpoint_urls)
        name = normalize_provider_display_name(display_name)
        found = False
        for binding in document["bindings"]:
            if binding["provider_uid"] == provider:
                found = True
                binding["authorized_aliases"].append(
                    {
                        "authority": authority,
                        "display_name": name,
                        "authorized_by": authorized_by,
                    }
                )
                binding["authorized_aliases"].sort(
                    key=lambda item: (item["authority"], item["display_name"])
                )
        if not found:
            raise ProviderIdentityRegistryError("authorized alias provider is unknown")
        atomic_write_json(path, _validate(document))
