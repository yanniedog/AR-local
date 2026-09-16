"""Transport unit controls use technical bytes, not fabricated business evidence."""
import pytest

from release_transport import (
    MAX_ENCODED_BYTES, OVERHEAD, TransportError, decrypt_transport,
    encrypt_transport, transport_header, transport_key_id,
)

KEY = bytes(range(32))


@pytest.mark.parametrize("plain", [b"", b"opaque domain bytes", bytes(range(256)) * 100], ids=["empty", "small", "binary"])
def test_roundtrip_preserves_exact_domain_bytes(plain):
    wire = encrypt_transport(plain, KEY)
    assert len(wire) == len(plain) + OVERHEAD
    assert transport_header(wire) == (transport_key_id(KEY), len(plain))
    assert decrypt_transport(wire, lambda _: KEY, limit=len(plain)) == plain
    assert wire != encrypt_transport(plain, KEY)  # fresh nonce for every encoding


@pytest.mark.parametrize("position", [4, 36, 44, 56, -1])
def test_tampered_header_nonce_or_ciphertext_fails(position):
    wire = bytearray(encrypt_transport(b"technical-vector", KEY))
    wire[position] ^= 1
    with pytest.raises(TransportError):
        decrypt_transport(bytes(wire), lambda _: KEY)


def test_oversize_refused_before_resolving_private_key():
    wire = encrypt_transport(b"abcd", KEY)
    def forbidden(_):
        pytest.fail("oversize must fail before key access")
    with pytest.raises(TransportError, match="limit"):
        decrypt_transport(wire, forbidden, limit=3)


@pytest.mark.parametrize("blob", [b"{}", b"ARE1" + bytes(80), b"ARE2", b"ARE2" + bytes(68)])
def test_plaintext_truncated_and_unsupported_headers_fail(blob):
    with pytest.raises(TransportError):
        decrypt_transport(blob, lambda _: KEY)


def test_missing_wrong_keys_and_private_errors_are_sanitized():
    wire = encrypt_transport(b"technical-vector", KEY)
    for resolver in [lambda _: bytes(32), lambda _: b"short"]:
        with pytest.raises(TransportError, match="^encrypted release authentication failed$"):
            decrypt_transport(wire, resolver)
    def missing(_):
        raise RuntimeError("private-key-material")
    with pytest.raises(TransportError, match="^encrypted release authentication failed$"):
        decrypt_transport(wire, missing)


def test_nested_transport_and_bad_limits_fail():
    wire = encrypt_transport(b"technical-vector", KEY)
    with pytest.raises(TransportError, match="nested"):
        encrypt_transport(wire, KEY)
    for limit in [-1, True, MAX_ENCODED_BYTES + 1]:
        with pytest.raises(TransportError, match="invalid"):
            decrypt_transport(wire, lambda _: KEY, limit=limit)


@pytest.mark.parametrize("inner", [b"ARE1" + bytes(80), b"ARE2" + bytes(80)])
def test_authenticated_nested_or_legacy_domain_refused(inner):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from release_transport import MAGIC
    # Construct a valid adversarial envelope independently of the guarded encoder.
    header = MAGIC + transport_key_id(KEY).encode("ascii") + len(inner).to_bytes(8, "big")
    nonce = bytes(range(12))
    wire = header + nonce + AESGCM(KEY).encrypt(nonce, inner, header)
    with pytest.raises(TransportError, match="nested or legacy"):
        decrypt_transport(wire, lambda _: KEY)
    with pytest.raises(TransportError, match="nested or legacy"):
        encrypt_transport(inner, KEY)
