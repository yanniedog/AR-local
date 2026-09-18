import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import publication_status as status
from app_payload_revisions_github import GitHubRevisionStore
from app_payload_revisions_state import RevisionError
from app_payload_secure_upload import secure_upload
from release_transport import encrypt_transport
from tests.test_app_payload_revisions import DAY, REPO, MemoryStore, build_payload, publish

KEY = bytes(range(32))


class WireStore(GitHubRevisionStore):
    def __init__(self, objects):
        super().__init__(REPO, gh='technical-gh')
        self.objects = objects
        self.writes = []

    def read_wire_url(self, url, limit=status.LIMIT):
        raw = self.objects.get(url)
        if raw is not None and len(raw) > limit + 72:
            raise ValueError('oversized public response')
        return raw

    def _run(self, args, **kwargs):
        def runner(command, **kwargs):
            path = Path(command[4]);raw = path.read_bytes()
            self.objects[self.url(command[3], path.name)] = raw
            self.writes.append(path.name)
            return SimpleNamespace(returncode=0)
        return secure_upload([self.gh, *args], runner=runner)


@pytest.fixture
def publication(tmp_path, monkeypatch):
    key = tmp_path / 'key';key.write_text(KEY.hex())
    monkeypatch.setenv('AR_LOCAL_PAYLOAD_KEY_FILE', str(key))
    build_payload(tmp_path / 'payload')
    private = MemoryStore();revision = publish(tmp_path, private)
    raw = (revision.archive_dir / 'manifest.json').read_bytes()
    private.objects[(status.TAG, 'manifest.json')] = raw
    store = WireStore({private.url(tag, name): encrypt_transport(body, KEY)
                       for (tag, name), body in private.objects.items()})
    return store, raw


def test_publisher_authenticates_then_hosted_check_requires_no_key(publication, monkeypatch):
    store, manifest = publication
    receipt = status.publish(store, manifest)
    assert set(receipt) == {'schema_version', 'run_date', 'revision', 'assets'}
    assert store.writes == [status.NAME]
    monkeypatch.delenv('AR_LOCAL_PAYLOAD_KEY_FILE')
    monkeypatch.setattr('app_payload_secure_upload.publication_key', lambda: pytest.fail('host accessed key'))
    monkeypatch.setattr('app_payload_revisions_github.GitHubRevisionStore', lambda *a, **kw: store)
    assert status.check(DAY)['publication_current']
    assert not status.check('2026-05-20')['publication_current']


@pytest.mark.parametrize('asset', ['manifest', 'index', 'selected'])
@pytest.mark.parametrize('fault', ['missing', 'tampered', 'plaintext', 'oversized'])
def test_host_rejects_interrupted_or_changed_publication(publication, monkeypatch, asset, fault):
    store, manifest = publication;receipt = status.publish(store, manifest)
    url = status.urls(store, receipt)[asset];raw = store.objects[url]
    if fault == 'missing':store.objects.pop(url)
    elif fault == 'tampered':store.objects[url] = raw[:-1] + bytes([raw[-1] ^ 1])
    elif fault == 'plaintext':store.objects[url] = manifest
    else:store.objects[url] = raw + b'x' * (status.LIMIT + 73)
    monkeypatch.setattr('app_payload_revisions_github.GitHubRevisionStore', lambda *a, **kw: store)
    result = status.check(DAY)
    assert not result['publication_current'] and result['publication_issues']


@pytest.mark.parametrize('fault', ['wrong_key', 'mismatched_alias', 'mismatched_index'])
def test_publisher_never_emits_success_for_unauthenticated_or_inconsistent_inputs(publication, fault):
    store, manifest = publication
    if fault == 'wrong_key':store.objects[store.url(status.TAG, 'manifest.json')] = encrypt_transport(manifest, bytes(reversed(KEY)))
    elif fault == 'mismatched_alias':store.objects[store.url(status.TAG, 'manifest.json')] = encrypt_transport(manifest + b' ', KEY)
    else:store.objects[store.url(status.TAG, 'dates-index.json')] = encrypt_transport(b'{}', KEY)
    with pytest.raises((ValueError, RevisionError)):status.publish(store, manifest)
    assert store.writes == []


@pytest.mark.parametrize('fault', ['extra_root', 'extra_asset', 'bool_revision', 'bad_date', 'bad_hash', 'huge_size'])
def test_egress_refuses_unclassified_or_nonoperational_receipt_fields(publication, tmp_path, fault):
    store, manifest = publication;value = copy.deepcopy(status.publish(store, manifest))
    if fault == 'extra_root':value['products'] = ['must not publish']
    elif fault == 'extra_asset':value['assets']['index']['secret'] = 'must not publish'
    elif fault == 'bool_revision':value['revision'] = True
    elif fault == 'bad_date':value['run_date'] = '2026-02-30'
    elif fault == 'bad_hash':value['assets']['index']['sha256'] = 'private/key'
    else:value['assets']['index']['bytes'] = status.LIMIT + 73
    path = tmp_path / status.NAME;path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        secure_upload(['gh', 'release', 'upload', status.TAG, str(path)],
                      runner=lambda *a, **kw: pytest.fail('invalid receipt escaped'))


def test_duplicate_receipt_fields_and_wrong_release_refused(publication, tmp_path):
    store, manifest = publication;value = status.publish(store, manifest)
    raw = json.dumps(value).replace('"schema_version": 1', '"schema_version": 1,"schema_version": 1')
    with pytest.raises(ValueError, match='duplicate'):status.validate(raw.encode())
    path = tmp_path / status.NAME;path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='rolling'):
        secure_upload(['gh', 'release', 'upload', 'wrong-tag', str(path)],
                      runner=lambda *a, **kw: pytest.fail('wrong release accepted'))


def test_configured_rolling_tag_binds_reads_writes_and_keyless_check(publication, monkeypatch, tmp_path):
    store, manifest = publication
    original = status.TAG
    monkeypatch.setattr(status, 'TAG', 'configured-app-feed')
    for name in ('manifest.json', 'dates-index.json'):
        store.objects[store.url(status.TAG, name)] = store.objects.pop(store.url(original, name))
    receipt = status.publish(store, manifest)
    assert store.url(status.TAG, status.NAME) in store.objects
    assert store.url(original, status.NAME) not in store.objects
    monkeypatch.setattr('app_payload_revisions_github.GitHubRevisionStore', lambda *a, **kw: store)
    assert status.check(DAY)['publication_current']
    path = tmp_path / status.NAME;path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='rolling'):
        secure_upload(['gh', 'release', 'upload', original, str(path)],
                      runner=lambda *a, **kw: pytest.fail('unconfigured release accepted'))


@pytest.mark.parametrize('fault', ['upload', 'readback'])
def test_same_revision_retries_receipt_after_transient_failure(publication, monkeypatch, fault):
    from app_payload_publish import _manifest_should_replace
    store, manifest = publication;live = json.loads(manifest)
    original_run, original_read = store._run, store.read_wire_url
    if fault == 'upload':
        monkeypatch.setattr(store, '_run', lambda *a, **kw: (_ for _ in ()).throw(OSError('interrupted upload')))
    else:
        monkeypatch.setattr(store, 'read_wire_url', lambda url, limit=status.LIMIT:
                            None if url.endswith('/' + status.NAME) else original_read(url, limit))
    with pytest.raises((OSError, ValueError)):
        status.publish(store, manifest)
    assert _manifest_should_replace('present', live, our_run_date=live['run_date'],
                                   our_gen=live['generated_at'], tag=status.TAG, force=False,
                                   our_revision=live['payload_revision']) == (True, 'revision')
    monkeypatch.setattr(store, '_run', original_run)
    monkeypatch.setattr(store, 'read_wire_url', original_read)
    status.verify(store, status.publish(store, manifest))


def test_receipt_cli_honors_configured_repository_and_rejects_conflicting_urls():
    code = '''
from publication_status import check, TAG
from scripts.pi_ingest_manifest_check import parse_args
assert check.__defaults__ == ('example/private-feed',)
assert TAG == 'custom-feed'
assert parse_args(['--public-receipt']).manifest_url == 'https://github.com/example/private-feed/releases/download/custom-feed/manifest.json'
for flag in ('--manifest-url', '--dates-index-url'):
    try:parse_args(['--public-receipt', flag, 'https://github.com/other/repo/releases/download/other/manifest.json'])
    except SystemExit as error:assert error.code == 2
    else:raise AssertionError('conflicting target accepted')
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'AR_LOCAL_REPO': 'example/private-feed',
                                 'AR_LOCAL_APP_PAYLOAD_TAG': 'custom-feed'})
    assert result.returncode == 0, result.stderr
