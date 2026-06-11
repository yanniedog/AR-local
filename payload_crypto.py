"""AES-256-GCM encryption for app payload assets.

Phase A of docs/SECURITY_CDR_PIPELINE.md: the Pi encrypts CDR-bearing assets
before uploading them to the public GitHub Release, so the release exposes
ciphertext only. Disabled unless AR_LOCAL_PAYLOAD_ENC=1 (the app must ship
decrypt support — Phase B — before this is switched on).

Requires the `cryptography` package, which Raspberry Pi OS ships system-wide
(Debian: python3-cryptography). Imported lazily so unencrypted builds keep the
repo's stdlib-only footprint.

Asset format (``.json.gz.enc``)::

    ARE1 | 12-byte nonce | AES-256-GCM ciphertext+tag (AAD = b"ARE1")

The nonce is derived as HMAC-SHA256(key, sha256(plaintext))[:12]. Identical
(key, plaintext) pairs therefore produce identical bytes — required because
same-day rebuilds must stay content-addressable (the app skips re-download on
unchanged sha256). A nonce can only repeat for an identical plaintext, which
yields the identical ciphertext, so GCM nonce-reuse leakage cannot occur.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Optional

MAGIC = b"ARE1"
NONCE_LEN = 12
KEY_LEN = 32
ALG = "aes-256-gcm"

ENV_FLAG = "AR_LOCAL_PAYLOAD_ENC"
ENV_KEY_FILE = "AR_LOCAL_PAYLOAD_KEY_FILE"
DEFAULT_KEY_FILE = "/etc/ar-local/payload.key"


def _aesgcm_cls():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(
            "payload encryption requires the 'cryptography' package "
            "(Debian/Raspberry Pi OS: apt install python3-cryptography)"
        ) from exc
    return AESGCM


def load_key(path: Path) -> bytes:
    """Read a 32-byte key stored as 64 hex chars (whitespace tolerated)."""
    key = bytes.fromhex(path.read_text(encoding="utf-8").strip())
    if len(key) != KEY_LEN:
        raise ValueError(
            f"payload key must be {KEY_LEN} bytes (64 hex chars), got {len(key)} bytes"
        )
    return key


def key_id(key: bytes) -> str:
    """Short non-secret identifier so clients can confirm they hold the right key."""
    return hashlib.sha256(b"ar-local-payload-key:" + key).hexdigest()[:8]


def resolve_key_from_env() -> Optional[bytes]:
    """Key when AR_LOCAL_PAYLOAD_ENC is truthy, else None (encryption off)."""
    if (os.environ.get(ENV_FLAG) or "").strip().lower() not in {"1", "true", "yes"}:
        return None
    return load_key(Path(os.environ.get(ENV_KEY_FILE) or DEFAULT_KEY_FILE))


def _derive_nonce(key: bytes, plain: bytes) -> bytes:
    return hmac.new(key, b"nonce:" + hashlib.sha256(plain).digest(), hashlib.sha256).digest()[
        :NONCE_LEN
    ]


def encrypt_asset(plain: bytes, key: bytes) -> bytes:
    nonce = _derive_nonce(key, plain)
    return MAGIC + nonce + _aesgcm_cls()(key).encrypt(nonce, plain, MAGIC)


def decrypt_asset(blob: bytes, key: bytes) -> bytes:
    if blob[: len(MAGIC)] != MAGIC:
        raise ValueError("not an ARE1 encrypted asset")
    nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_LEN]
    return _aesgcm_cls()(key).decrypt(nonce, blob[len(MAGIC) + NONCE_LEN :], MAGIC)
