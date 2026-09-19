from pathlib import Path
from types import SimpleNamespace

import pytest

from app_payload_secure_upload import (
    classify_asset, decode_public_bytes, publication_key, secure_upload, resolve_release_key,
)
from release_transport import MAGIC, TransportError, encrypt_transport, transport_key_id

KEY = bytes(range(32))


@pytest.mark.parametrize('name', [
    'core-\u0662\u0660\u0662\u0666-09-19-abcdef012345.json.gz',
    'terms_shard_\u0660\u0660\u0661-2026-09-19-abcdef012345.json.gz',
])
def test_non_ascii_digits_cannot_enter_the_published_filename_contract(name):
    with pytest.raises(TransportError, match='unknown release asset classification'):
        classify_asset(name)


@pytest.mark.parametrize("kind", ["index", "shard_000"])
def test_savings_activity_v4_is_classified_but_unfrozen_publication_refused(tmp_path, key_file, kind):
    path = tmp_path / f"monetary_v4_savings_activity_calculation_{kind}-2026-09-16-abcdef012345.json.gz"
    path.write_bytes(b"technical-domain-vector")
    assert classify_asset(path.name) == "cdr_domain"
    def runner(args, **kwargs):
        pytest.fail('unfrozen activity asset reached publication')
    with pytest.raises(ValueError, match='approved publication freeze'):
        secure_upload(["gh", "release", "upload", "technical", str(path)], runner=runner)


@pytest.mark.parametrize('encrypted', [False, True])
def test_unfrozen_manifest_refused_even_when_transport_authenticated(tmp_path, key_file, encrypted):
    path = tmp_path / 'manifest.json'
    raw = b'{"files":{},"executable_v4":{}}'
    path.write_bytes(encrypt_transport(raw, KEY) if encrypted else raw)
    with pytest.raises(ValueError, match='approved publication freeze'):
        secure_upload(['gh', 'release', 'upload', 'technical', str(path)],
                      runner=lambda *args, **kwargs: pytest.fail('unfrozen manifest published'))


@pytest.fixture
def key_file(tmp_path, monkeypatch):
    path = tmp_path / "private.key"
    path.write_text(KEY.hex())
    monkeypatch.setenv("AR_LOCAL_PAYLOAD_KEY_FILE", str(path))
    monkeypatch.setenv("AR_LOCAL_PAYLOAD_ENC", "0")  # no plaintext opt-out
    return path


def test_malformed_manifest_is_refused_before_upload(tmp_path, key_file):
    path = tmp_path / 'manifest.json'
    path.write_bytes(b'not a JSON manifest')
    with pytest.raises(ValueError):
        secure_upload(['gh', 'release', 'upload', 'technical', str(path)],
                      runner=lambda *args, **kwargs: pytest.fail('malformed manifest published'))


def test_upload_encrypts_manifest_and_preserves_local_domain_bytes(tmp_path, key_file):
    source = tmp_path / "manifest.json"
    original = b'{"technical_transport_fixture":true}'
    source.write_bytes(original)
    observed = []
    def runner(args, **kwargs):
        path = Path(args[4]);observed.append(path)
        assert path != source and path.name == source.name
        assert path.read_bytes().startswith(MAGIC)
        assert decode_public_bytes(path.read_bytes(), len(original), require_encrypted=True) == original
        assert kwargs == {"check": True, "timeout": 10}
        return SimpleNamespace(returncode=0)
    secure_upload(["gh", "release", "upload", "test", str(source), "--repo", "owner/repo"],
                  runner=runner, check=True, timeout=10)
    assert source.read_bytes() == original
    assert not observed[0].exists()


@pytest.mark.parametrize("name", ["unknown.json", "archive.zip", "app-preview.apk", "private.key"])
def test_unknown_assets_never_reach_cli(tmp_path, key_file, name):
    source=tmp_path/name;source.write_bytes(b"technical bytes")
    with pytest.raises(TransportError, match="classification"):
        secure_upload(["gh", "release", "upload", "test", str(source)],
                      runner=lambda *a, **k: pytest.fail("CLI must not execute"))


def test_missing_key_never_falls_back_to_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("AR_LOCAL_PAYLOAD_KEY_FILE", str(tmp_path / "absent"))
    monkeypatch.delenv("AR_LOCAL_PAYLOAD_ENC", raising=False)
    source=tmp_path/'manifest.json';source.write_bytes(b"{}")
    with pytest.raises(TransportError, match="private encryption key"):
        secure_upload(["gh", "release", "upload", "test", str(source)],
                      runner=lambda *a, **k: pytest.fail("CLI must not execute"))


def test_retained_key_id_and_encrypted_readback(tmp_path, key_file, monkeypatch):
    old = bytes(reversed(KEY));key_id=transport_key_id(old)
    (tmp_path/f'{key_id}.key').write_text(old.hex())
    monkeypatch.setenv('AR_LOCAL_PAYLOAD_KEYRING_DIR',str(tmp_path))
    assert resolve_release_key(key_id)==old
    assert decode_public_bytes(encrypt_transport(b'old-domain',old),10,require_encrypted=True)==b'old-domain'
    with pytest.raises(TransportError):decode_public_bytes(b'old-domain',10,require_encrypted=True)
    assert decode_public_bytes(b'old-domain',10)==b'old-domain'  # explicit migration reads only


def test_cleanup_after_failed_cli_and_no_nested_legacy_encryption(tmp_path, key_file):
    source=tmp_path/'manifest.json';source.write_bytes(b'{}');observed=[]
    def failure(args,**kwargs):
        observed.append(Path(args[4]));raise RuntimeError('upload interrupted')
    with pytest.raises(RuntimeError):secure_upload(['gh','release','upload','test',str(source)],runner=failure)
    assert not observed[0].exists()
    source.write_bytes(b'ARE1'+bytes(50))
    with pytest.raises(TransportError,match='legacy'):
        secure_upload(['gh','release','upload','test',str(source)],runner=failure)


def test_key_errors_do_not_disclose_private_path(tmp_path, monkeypatch):
    monkeypatch.setenv('AR_LOCAL_PAYLOAD_KEY_FILE',str(tmp_path/'secret-path'))
    with pytest.raises(TransportError,match='^publication requires a valid private encryption key$'):
        publication_key()


def test_migration_reader_never_returns_legacy_ciphertext_as_domain():
    with pytest.raises(TransportError):
        decode_public_bytes(b"ARE1" + bytes(80), 1024)


@pytest.mark.parametrize("inner", [b"ARE1" + bytes(80), b"ARE2" + bytes(80)])
def test_prepared_nested_ciphertext_never_reaches_publication(tmp_path, key_file, inner):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    header = MAGIC + transport_key_id(KEY).encode("ascii") + len(inner).to_bytes(8, "big")
    nonce = bytes(range(12))
    wire = header + nonce + AESGCM(KEY).encrypt(nonce, inner, header)
    source = tmp_path / "manifest.json"
    source.write_bytes(wire)
    with pytest.raises(TransportError, match="nested or legacy"):
        secure_upload(["gh", "release", "upload", "test", str(source)],
                      runner=lambda *a, **k: pytest.fail("CLI must not execute"))
    with pytest.raises(TransportError, match="nested or legacy"):
        decode_public_bytes(wire, 1024, require_encrypted=True)
