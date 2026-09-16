"""Versioned encrypted release transport, independent of frozen domain contracts.

ARE2 | 32 ASCII hex key ID | u64be encoded size | 12-byte nonce | ciphertext/tag.
The first 44 bytes are authenticated additional data. The encrypted body is the
original domain asset, including its original compression and immutable hash.
No key or product facts occur in the public header.
"""
from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable

from payload_crypto import KEY_LEN, _aesgcm_cls

MAGIC = b"ARE2"
HEADER_BYTES = 44
NONCE_BYTES = 12
OVERHEAD = HEADER_BYTES + NONCE_BYTES + 16
MAX_ENCODED_BYTES = 256 * 1024 * 1024
KEY_ID = re.compile(r"[0-9a-f]{32}")


class TransportError(ValueError):
    """A bounded, non-secret transport failure."""


def transport_key_id(key: bytes) -> str:
    if len(key) != KEY_LEN:
        raise TransportError("invalid transport key length")
    return hashlib.sha256(b"ar-local-payload-key:" + key).hexdigest()[:32]


def encrypt_transport(plain: bytes, key: bytes) -> bytes:
    """Encrypt exact domain bytes; callers retain the original contract identity."""
    if len(plain) > MAX_ENCODED_BYTES:
        raise TransportError("encoded asset exceeds transport limit")
    if plain.startswith((MAGIC, b"ARE1")):
        raise TransportError("nested or legacy release transport is forbidden")
    header = MAGIC + transport_key_id(key).encode("ascii") + len(plain).to_bytes(8, "big")
    nonce = os.urandom(NONCE_BYTES)
    return header + nonce + _aesgcm_cls()(key).encrypt(nonce, plain, header)


def transport_header(blob: bytes, limit: int = MAX_ENCODED_BYTES) -> tuple[str, int]:
    if type(limit) is not int or not 0 <= limit <= MAX_ENCODED_BYTES:
        raise TransportError("invalid transport byte limit")
    if len(blob) < OVERHEAD or blob[:4] != MAGIC:
        raise TransportError("missing encrypted release transport")
    try:
        key_id = blob[4:36].decode("ascii")
    except UnicodeDecodeError:
        raise TransportError("invalid transport key ID") from None
    size = int.from_bytes(blob[36:44], "big")
    if not KEY_ID.fullmatch(key_id):
        raise TransportError("invalid transport key ID")
    if size > limit or len(blob) != size + OVERHEAD:
        raise TransportError("encrypted asset size mismatch or limit exceeded")
    return key_id, size


def decrypt_transport(
    blob: bytes, resolve_key: Callable[[str], bytes], *, limit: int = MAX_ENCODED_BYTES,
) -> bytes:
    key_id, _ = transport_header(blob, limit)
    try:
        key = resolve_key(key_id)
        if transport_key_id(key) != key_id:
            raise TransportError("transport key ID mismatch")
        nonce = blob[HEADER_BYTES:HEADER_BYTES + NONCE_BYTES]
        plain = _aesgcm_cls()(key).decrypt(nonce, blob[HEADER_BYTES + NONCE_BYTES:], blob[:HEADER_BYTES])
    except Exception:
        # Resolver/native crypto errors can include private paths or key material.
        raise TransportError("encrypted release authentication failed") from None
    if plain.startswith((MAGIC, b"ARE1")):
        raise TransportError("nested or legacy release transport is forbidden")
    return plain
