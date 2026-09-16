"""Wire-level publication safety; technical bytes only, no financial evidence."""
import hashlib
import io
from types import SimpleNamespace

import pytest

from app_payload_revisions_github import GitHubRevisionStore
from app_payload_publish import _manifest_should_replace
from app_payload_revisions_state import RevisionError
from app_payload_v3_github import GitHubPromotionBackend
from app_payload_v3_state import CONTROL_BRANCH, POINTER_FILENAME, PromotionError
from app_payload_secure_upload import decode_public_bytes
from release_transport import MAGIC, OVERHEAD, TransportError, encrypt_transport


@pytest.fixture
def private_key(tmp_path, monkeypatch):
    key = bytes(range(32))
    path = tmp_path / 'technical.key'
    path.write_text(key.hex())
    monkeypatch.setenv('AR_LOCAL_PAYLOAD_KEY_FILE', str(path))
    return key


def serve(monkeypatch, wire):
    def opened(*args, **kwargs):
        result = io.BytesIO(wire)
        result.headers = {'Content-Length': str(len(wire))}
        return result
    monkeypatch.setattr('urllib.request.build_opener', lambda *args: SimpleNamespace(open=opened))


def test_revision_readback_rejects_legacy_plaintext_even_with_exact_domain_hash(monkeypatch, private_key):
    plain = b'original immutable domain bytes'
    store = GitHubRevisionStore('owner/repo', gh='gh')
    serve(monkeypatch, plain)
    assert store.read('tag', 'manifest.json', len(plain)) == plain  # preservation only
    with pytest.raises(TransportError):
        store.read('tag', 'manifest.json', len(plain), require_encrypted=True)
    serve(monkeypatch, encrypt_transport(plain, private_key))
    assert store.read('tag', 'manifest.json', len(plain), require_encrypted=True) == plain


def test_revision_ciphertext_tampering_and_domain_size_are_checked(monkeypatch, private_key):
    wire = encrypt_transport(b'original', private_key)
    store = GitHubRevisionStore('owner/repo', gh='gh')
    serve(monkeypatch, wire[:-1] + bytes([wire[-1] ^ 1]))
    with pytest.raises(TransportError):
        store.read('tag', 'manifest.json', 8, require_encrypted=True)
    serve(monkeypatch, wire)
    with pytest.raises(RevisionError):
        store.read('tag', 'manifest.json', 7, require_encrypted=True)


@pytest.mark.parametrize('status,live', [
    ('error', None), ('present', {'run_date': '2026-09-17'}),
])
def test_force_cannot_bypass_unknown_head_or_roll_back_day(status, live):
    assert not _manifest_should_replace(status, live, our_run_date='2026-09-16',
        our_gen='2026-09-16T00:00:00Z', tag='app-payload-latest', force=True)[0]


def test_v3_draft_authenticates_ciphertext_before_normalizing_domain_census(monkeypatch, private_key):
    backend = GitHubPromotionBackend()
    monkeypatch.setattr(backend, '_validate_candidate_release', lambda *args: None)
    plain = b'candidate domain'
    wire = encrypt_transport(plain, private_key)
    release = {'draft': True, 'assets': [{'name': 'manifest.json', 'size': len(wire),
        'digest': 'sha256:' + hashlib.sha256(wire).hexdigest()}]}
    monkeypatch.setattr(backend, '_download_draft_asset', lambda *args: wire)
    args = (release, 'tag', 'title', 'notes', 'a'*40, {'manifest.json': plain})
    assert backend._candidate_draft_missing(*args) == ()
    release['assets'][0]['size'] = len(plain)
    with pytest.raises(PromotionError, match='encrypted asset metadata'):
        backend._candidate_draft_missing(*args)


def test_v3_control_commit_never_sends_plaintext_and_unknown_paths_fail(monkeypatch, private_key):
    backend = GitHubPromotionBackend()
    observed = []
    def api(method, endpoint, body):
        if endpoint.endswith('/blobs'):
            import base64
            wire = base64.b64decode(body['content'])
            assert wire.startswith(MAGIC)
            assert decode_public_bytes(wire, 2, require_encrypted=True) == b'{}'
        observed.append(endpoint)
        return {'sha': 'a'*40}
    monkeypatch.setattr(backend, '_api', api)
    backend._prepare_commit(CONTROL_BRANCH, None, {POINTER_FILENAME: b'{}'}, 'test')
    assert len(observed) == 3
    with pytest.raises(PromotionError, match='classification'):
        backend._prepare_commit(CONTROL_BRANCH, None, {'unknown.json': b'{}'}, 'test')
    assert len(observed) == 3


def test_v3_public_readback_requires_encryption(private_key):
    wire = encrypt_transport(b'{}', private_key)
    seen = []
    def fetcher(url, limit):
        seen.append(limit)
        return wire
    backend = GitHubPromotionBackend(fetcher=fetcher, sleeper=lambda _: None)
    assert backend.fetch_url('https://github.com/owner/repo/releases/download/tag/manifest.json', 2) == b'{}'
    assert seen == [2 + OVERHEAD]
    backend._fetcher = lambda *args: b'{}'
    with pytest.raises(TransportError):
        backend.fetch_url('https://github.com/owner/repo/releases/download/tag/manifest.json', 2)
