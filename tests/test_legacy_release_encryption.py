"""Historical JSON/log/archive egress uses the same authenticated transport."""
from pathlib import Path

import pytest

from app_payload_secure_upload import decode_public_bytes, secure_upload
from release_transport import MAGIC, TransportError, encrypt_transport

NAMES = (
    'changelog-summary.json', 'execution.jsonl',
    'september6-evidence-addendum-20260906T140341Z.zip',
    'september6-finalization-closeout-20260906T135034Z.zip',
    'september6-recovery-evidence.zip',
)
KEY = bytes(range(32))


@pytest.fixture
def configured_key(tmp_path, monkeypatch):
    path = tmp_path / 'private.key'
    path.write_text(KEY.hex())
    monkeypatch.setenv('AR_LOCAL_PAYLOAD_KEY_FILE', str(path))
    monkeypatch.setenv('AR_LOCAL_PAYLOAD_ENC', '0')
    return path


@pytest.mark.parametrize('name', NAMES)
@pytest.mark.parametrize('prepared', [False, True])
def test_historical_asset_only_leaves_as_authenticated_ciphertext(tmp_path, configured_key, name, prepared):
    domain = b'technical encryption control\x00\xff\n'
    source = tmp_path / name
    original = encrypt_transport(domain, KEY) if prepared else domain
    source.write_bytes(original)
    uploads = []

    def upload(args):
        path = Path(args[4])
        uploads.append(path)
        wire = path.read_bytes()
        assert path.name == name and path != source
        assert wire.startswith(MAGIC) and domain not in wire
        assert decode_public_bytes(wire, len(domain), require_encrypted=True) == domain
        if prepared:
            assert wire == original

    secure_upload(['gh', 'release', 'upload', 'historical', str(source)], runner=upload)
    assert len(uploads) == 1 and not uploads[0].exists()
    assert source.read_bytes() == original


@pytest.mark.parametrize('name', NAMES)
def test_historical_asset_missing_key_never_reaches_cli(tmp_path, monkeypatch, name):
    monkeypatch.setenv('AR_LOCAL_PAYLOAD_KEY_FILE', str(tmp_path / 'absent.key'))
    source = tmp_path / name
    source.write_bytes(b'technical control')
    with pytest.raises(TransportError, match='private encryption key'):
        secure_upload(['gh', 'release', 'upload', 'historical', str(source)],
                      runner=lambda *a: pytest.fail('plaintext fallback'))


@pytest.mark.parametrize('name', ['unknown.jsonl', 'archive.zip', 'september6-other.zip',
                                 'september6-recovery-evidence.zip.bak', 'Changelog-summary.json'])
def test_registry_does_not_allow_other_log_or_archive_names(tmp_path, configured_key, name):
    source = tmp_path / name
    source.write_bytes(b'technical control')
    with pytest.raises(TransportError, match='classification'):
        secure_upload(['gh', 'release', 'upload', 'historical', str(source)],
                      runner=lambda *a: pytest.fail('unknown classification reached CLI'))


@pytest.mark.parametrize('fault', ['tamper', 'wrong-key'])
def test_prepared_historical_archive_requires_authentication(tmp_path, configured_key, fault):
    wire = bytearray(encrypt_transport(b'technical control', KEY))
    if fault == 'tamper':
        wire[-1] ^= 1
    else:
        configured_key.write_text(bytes(reversed(KEY)).hex())
    source = tmp_path / 'september6-recovery-evidence.zip'
    source.write_bytes(wire)
    with pytest.raises(TransportError):
        secure_upload(['gh', 'release', 'upload', 'historical', str(source)],
                      runner=lambda *a: pytest.fail('unauthenticated archive reached CLI'))
