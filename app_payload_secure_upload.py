"""Fail-closed release egress: classify, encrypt, then invoke the supplied CLI.

Private builders and immutable domain contracts remain unchanged. Every allowed
asset, including manifests and indexes, uses the independently versioned ARE2
transport. Unknown asset names have no plaintext or encryption fallback.
"""
from __future__ import annotations

import os
import json
import re
import tempfile
from pathlib import Path

from payload_crypto import DEFAULT_KEY_FILE, ENV_KEY_FILE, load_key
from release_transport import (
    MAGIC, MAX_ENCODED_BYTES, TransportError, PlaintextTransportError, decrypt_transport, encrypt_transport,
    transport_key_id,
)

DOCUMENTS = frozenset({
    "manifest.json", "manifest-v2.json", "dates-index.json", "source-manifest.json",
    "base-manifest.json", "preservation.json", "publication-provenance.json",
    "revision-delta.json",
})
# Retained releases also contain these inventoried CDR-bearing artifacts. Treat
# the whole archive/log as opaque domain bytes; never publish its members or
# infer that a changelog is operational metadata. Unknown names still fail closed.
LEGACY_CDR_ARTIFACTS = frozenset({
    "changelog-summary.json", "execution.jsonl",
    "september6-evidence-addendum-20260906T140341Z.zip",
    "september6-finalization-closeout-20260906T135034Z.zip",
    "september6-recovery-evidence.zip",
})
ASSET = re.compile(
    r"(?:core|details|search-index|history-banks|bank-history|bank-spread-history|rba-calendar|"
    r"v2-product-history|v2-economic-outlook|terms-index|terms_shard_\d{3}|"
    r"executable-index|executable_shard_\d{3}|executable_v2_(?:index|shard_\d{3})|"
    r"monetary_v[34]_[a-z_]+_(?:index|shard_\d{3}))"
    r"-\d{4}-\d{2}-\d{2}-[a-f0-9]{12}\.json\.gz(?:\.enc)?"
)


def classify_asset(name: str) -> str:
    if (name in DOCUMENTS or name in LEGACY_CDR_ARTIFACTS or ASSET.fullmatch(name)
            or re.fullmatch(r"[a-f0-9]{64}\.json(?:\.gz)?", name)):
        return "cdr_domain"
    raise TransportError("unknown release asset classification")


def publication_key() -> bytes:
    """Publication cannot opt out by dropping the legacy build-encryption flag."""
    try:
        return load_key(Path(os.environ.get(ENV_KEY_FILE) or DEFAULT_KEY_FILE))
    except Exception:
        raise TransportError("publication requires a valid private encryption key") from None


def resolve_release_key(key_id: str) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{32}", key_id):
        raise TransportError("invalid release key ID")
    try:
        current = publication_key()
        if transport_key_id(current) == key_id:
            return current
    except TransportError:
        pass
    try:
        root = Path(os.environ.get("AR_LOCAL_PAYLOAD_KEYRING_DIR") or "/etc/ar-local/payload-keys")
        retained = load_key(root / f"{key_id}.key")
        if transport_key_id(retained) == key_id:
            return retained
    except Exception:
        pass
    raise TransportError("matching private release key unavailable")


def decode_public_bytes(raw: bytes, limit: int, *, require_encrypted: bool = False) -> bytes:
    """Legacy reads support migration; new publication readback requires ARE2."""
    if raw.startswith(MAGIC):
        return decrypt_transport(raw, resolve_release_key, limit=limit)
    if raw.startswith((b"ARE2", b"ARE1")) or len(raw) > limit:
        raise TransportError("encrypted publication readback missing or oversized")
    if require_encrypted:
        raise PlaintextTransportError("encrypted publication readback missing or oversized")
    return raw


def validate_upload_paths(paths: list[Path]) -> None:
    if not paths or len({p.name for p in paths}) != len(paths):
        raise TransportError("release asset inventory is empty or duplicated")
    for path in paths:
        classify_asset(path.name)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ENCODED_BYTES:
            raise TransportError("unsafe or oversized release asset")


def validate_publication_contract(name: str, raw: bytes) -> None:
    """Keep private integration admission separate from public release egress."""
    if name.startswith('monetary_v4_') or (name in DOCUMENTS and 'manifest' in name
            and isinstance(value := json.loads(raw), dict) and 'executable_v4' in value):
        from cdr_terms.executable_v4_contract import require_publication_ready
        require_publication_ready()


def secure_upload(args: list[str], *, runner, **kwargs):
    """Only this exact CLI upload shape is accepted; caller options are retained."""
    if len(args) < 5 or args[1:3] != ["release", "upload"]:
        raise TransportError("invalid encrypted upload invocation")
    indices = []
    index = 4
    while index < len(args):
        value = args[index]
        if value == "--repo" and index + 1 < len(args):
            index += 2
        elif value == "--clobber":
            index += 1
        elif value.startswith("-"):
            raise TransportError("unsupported release upload option")
        else:
            indices.append(index)
            index += 1
    paths = [Path(args[i]) for i in indices]
    validate_upload_paths(paths)
    key = publication_key()
    with tempfile.TemporaryDirectory(prefix="ar-encrypted-upload-") as temporary:
        command = list(args)
        for position, path in zip(indices, paths):
            raw = path.read_bytes()
            if len(raw) > MAX_ENCODED_BYTES:
                raise TransportError("asset changed beyond transport byte limit")
            # Retrying a prepared ciphertext is allowed only after authentication.
            if raw.startswith(MAGIC):
                domain = decrypt_transport(raw, resolve_release_key)
                validate_publication_contract(path.name, domain)
                wire = raw
            else:
                if raw.startswith(b"ARE1"):
                    raise TransportError("rebuild legacy encrypted assets before transport publication")
                validate_publication_contract(path.name, raw)
                wire = encrypt_transport(raw, key)
            target = Path(temporary) / path.name
            target.write_bytes(wire)
            command[position] = str(target)
        return runner(command, **kwargs)
