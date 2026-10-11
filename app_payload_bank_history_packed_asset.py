"""Optional packed history, preserving legacy bytes and URL-independent identity."""
from __future__ import annotations

import re

from app_payload_bank_history_asset import (
    HASH, _decode_document, _encode_document,
    descriptor as legacy_descriptor,
)
from app_payload_history_packed import pack, unpack, PackedBudgetError

NAMESPACE = "bank_rate_history_catalogue_packed"
ASSET_KIND = "bank-rate-history-catalogue-packed"
INNER_JSON_MAX_BYTES = 10 * 1024 * 1024


def encode_envelope(catalogue, *, run_date, core_sha256):
    if not isinstance(catalogue, dict) or catalogue.get("schema_version") != 2:
        raise ValueError("Historical catalogue must use schema 2")
    return _encode_document(pack(catalogue), run_date=run_date, core_sha256=core_sha256,
                            inner_limit=INNER_JSON_MAX_BYTES, budget_error=PackedBudgetError)


def decode_envelope(raw, *, run_date, core_sha256):
    catalogue = unpack(_decode_document(raw, run_date=run_date, core_sha256=core_sha256,
                                        inner_limit=INNER_JSON_MAX_BYTES))
    if not isinstance(catalogue, dict) or catalogue.get("schema_version") != 2:
        raise ValueError("Historical catalogue must use schema 2")
    return catalogue


def descriptor(manifest):
    return url_free_descriptor(manifest, NAMESPACE, ASSET_KIND)


def url_free_descriptor(manifest, namespace_name, asset_kind):
    namespace = manifest[namespace_name]
    if (not isinstance(namespace, dict) or set(namespace) != {"schema_version", "file"}
            or type(namespace["schema_version"]) is not int or namespace["schema_version"] != 1):
        raise ValueError("Packed historical namespace must use schema 1 with one file")
    entry = namespace["file"]
    if (not isinstance(entry, dict) or not {"name", "bytes", "sha256"}.issubset(entry)
            or set(entry) - {"name", "bytes", "sha256", "enc"}
            or not isinstance(entry["sha256"], str) or not HASH.fullmatch(entry["sha256"])):
        raise ValueError("Packed historical descriptor must be URL-free")
    repo, tag = manifest.get("repo"), manifest.get("tag")
    if (not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
            or not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", tag)):
        raise ValueError("Packed historical release identity is invalid")
    expected = f"{asset_kind}-{manifest.get('run_date')}-{entry['sha256'][:12]}.json.gz" + (".enc" if entry.get("enc") else "")
    if entry["name"] != expected:
        raise ValueError("Packed historical asset name/date/hash differs")
    # Reuse all established byte/encryption checks without changing either
    # manifest. The temporary old-kind projection is never published or hashed.
    old_name = expected.replace(asset_kind, "bank-rate-history-catalogue", 1)
    old_file = {**entry, "name": old_name, "url": f"https://github.com/{repo}/releases/download/{tag}/{old_name}"}
    legacy_descriptor({**manifest, "bank_rate_history_catalogue": {"schema_version": 1, "file": old_file}})
    return {**entry, "url": f"https://github.com/{repo}/releases/download/{tag}/{expected}"}


def validate_local_asset(manifest, root):
    entry = descriptor(manifest)
    raw = (root / entry["name"]).read_bytes()
    if entry.get("enc"):
        import payload_crypto
        key = payload_crypto.resolve_key_from_env()
        if key is None or payload_crypto.key_id(key) != entry["enc"]["key_id"]:
            raise ValueError("Packed historical asset requires its private build encryption key")
        raw = payload_crypto.decrypt_asset(raw, key)
    return decode_envelope(raw, run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])


def add_packed_asset(manifest, catalogue, out_dir, release_base, enc_key, write_asset):
    """Add the faster projection only within unchanged total transfer budgets."""
    from app_payload_network_budget import ROLLING_TOTAL_MAX_BYTES
    from app_payload_optional_assets import iter_payload_assets
    try:
        wire = encode_envelope(catalogue, run_date=manifest["run_date"],
                               core_sha256=manifest["files"]["core"]["sha256"])
    except PackedBudgetError as error:
        print(f"[app_payload] optional packed history omitted: {error}")
        return
    # Legacy encryption contributes framing bytes; inspect the exact new asset
    # before adoption. Unreferenced staging files are pruned by normal packaging.
    entry = write_asset(out_dir, ASSET_KIND, manifest["run_date"], wire, release_base, enc_key)
    if sum(asset["bytes"] for _, asset in iter_payload_assets(manifest)) + entry["bytes"] > ROLLING_TOTAL_MAX_BYTES:
        print("[app_payload] optional packed history omitted: combined transfer budget exceeded")
        return
    manifest[NAMESPACE] = {"schema_version": 1, "file": {key: value for key, value in entry.items() if key != "url"}}
