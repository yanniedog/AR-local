from pathlib import Path
from types import SimpleNamespace

import pytest

from app_payload_secure_upload import (
    decode_public_bytes, publication_key, secure_upload, resolve_release_key,
)
from release_transport import MAGIC, TransportError, encrypt_transport, transport_key_id

KEY = bytes(range(32))


@pytest.fixture
def key_file(tmp_path, monkeypatch):
    path = tmp_path / "private.key"
    path.write_text(KEY.hex())
    monkeypatch.setenv("AR_LOCAL_PAYLOAD_KEY_FILE", str(path))
    monkeypatch.setenv("AR_LOCAL_PAYLOAD_ENC", "0")  # no plaintext opt-out
    return path


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
