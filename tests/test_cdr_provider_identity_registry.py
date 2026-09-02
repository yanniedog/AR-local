from __future__ import annotations

import json

import pytest

from cdr_contracts import provider_uid
from cdr_provider_identity_registry import (
    ProviderIdentityRegistryError,
    authorize_alias,
    resolve_provider_rows,
    validate_registry_snapshot_bytes,
)


def _row(*, name: str = "Example Bank", endpoint: str = "https://bank.example/products"):
    uid, status = provider_uid(
        data_holder_id=None,
        data_holder_brand_id="brand-1",
        interim_id="interim-1",
        endpoint_urls=(endpoint,),
        display_name=name,
    )
    return {
        "provider_uid": uid,
        "provider_identity_status": status,
        "data_holder_id": "",
        "data_holder_brand_id": "brand-1",
        "interim_id": "interim-1",
        "brand_name": name,
        "legal_entity_name": "Example Bank Limited",
        "endpoint_url": endpoint,
        "identity_authority": endpoint.split("/")[2],
    }


def test_fallback_registry_reuses_identity_and_holds_unapproved_change(tmp_path):
    path = tmp_path / "provider-identity-registry-v1.json"
    first, snapshot = resolve_provider_rows([_row()], path)
    assert first[0]["provider_identity_status"] == "fallback"
    validate_registry_snapshot_bytes(snapshot)

    replay, replay_snapshot = resolve_provider_rows([_row()], path)
    assert replay[0]["provider_uid"] == first[0]["provider_uid"]
    assert replay_snapshot == snapshot

    changed, unchanged_snapshot = resolve_provider_rows(
        [_row(name="Renamed Bank", endpoint="https://new.bank.example/products")], path
    )
    assert changed[0]["provider_uid"] == first[0]["provider_uid"]
    assert changed[0]["provider_identity_status"] == "fallback_conflict"
    assert changed[0]["provider_identity_held"] is True
    assert unchanged_snapshot == snapshot


def test_operator_authorized_alias_reuses_registered_uid(tmp_path):
    path = tmp_path / "provider-identity-registry-v1.json"
    first, _ = resolve_provider_rows([_row()], path)
    authorize_alias(
        path,
        first[0]["provider_uid"],
        endpoint_urls=("https://new.bank.example/products",),
        display_name="Renamed Bank",
        authorized_by="operator-change-1",
    )
    changed, _ = resolve_provider_rows(
        [_row(name="Renamed Bank", endpoint="https://new.bank.example/products")], path
    )
    assert changed[0]["provider_uid"] == first[0]["provider_uid"]
    assert changed[0]["provider_identity_status"] == "fallback"
    assert "provider_identity_held" not in changed[0]


def test_registry_rejects_noncanonical_or_mutually_ambiguous_content(tmp_path):
    path = tmp_path / "provider-identity-registry-v1.json"
    _, snapshot = resolve_provider_rows([_row()], path)
    path.write_text(json.dumps(json.loads(snapshot), indent=2), encoding="utf-8")
    with pytest.raises(ProviderIdentityRegistryError, match="not canonical"):
        resolve_provider_rows([_row()], path)
