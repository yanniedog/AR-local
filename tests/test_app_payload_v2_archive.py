"""Transport/retention controls, with no invented financial acceptance rows."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import subprocess

import pytest

import app_payload_v2 as v2
import app_payload_v2_archive as archive
from app_payload_revisions_github import GitHubRevisionStore
from app_payload_revisions_state import RevisionError, canonical, digest, bundle_sha256

TAG = 'app-payload-latest'
DAY = '2026-09-13'


class Store(GitHubRevisionStore):
    def __init__(self, repo='owner/repository'):
        self.repo, self.gh = repo, 'gh'
        self.objects, self.actions = {}, []
        self.fail_name = self.fail_alias = None

    def read(self, tag, name, limit=8 * 1024 * 1024):
        raw = self.objects.get((tag, name))
        if raw is not None and len(raw) > limit:
            raise RevisionError('read budget exceeded')
        return raw

    def read_url(self, url, limit):
        prefix = f'https://github.com/{self.repo}/releases/download/'
        assert url.startswith(prefix)
        tag, name = url[len(prefix):].split('/')
        return self.read(tag, name, limit)

    def ensure_release(self, tag):
        self.actions.append(('ensure', tag))

    def _run(self, args, **_kwargs):
        assert args[:2] == ['release', 'upload']
        tag = args[2]
        for value in args[3:args.index('--repo')]:
            path = Path(value)
            key = tag, path.name
            if path.name == self.fail_name:
                self.fail_name = None
                raise RevisionError('controlled archive interruption')
            if tag == TAG and path.name == archive.MANIFEST and self.fail_alias:
                behavior, self.fail_alias = self.fail_alias, None
                if behavior == 'deleted':
                    self.objects.pop(key, None)
                if behavior == 'completed':
                    self.objects[key] = path.read_bytes()
                raise subprocess.TimeoutExpired('gh', 1)
            if key in self.objects and '--clobber' not in args:
                raise RevisionError('existing object cannot be clobbered')
            self.objects[key] = path.read_bytes()
            self.actions.append(('upload', tag, path.name))
        return subprocess.CompletedProcess(args, 0, '', '')


def base(store, marker='first'):
    files = {}
    for kind in ('core', 'details'):
        raw = gzip.compress(canonical({'transport_marker': marker, 'kind': kind}), mtime=0)
        name = f'{kind}-{digest(raw)[:12]}.json.gz'
        files[kind] = {'name': name, 'bytes': len(raw), 'sha256': digest(raw), 'url': store.url(TAG, name)}
        store.objects[TAG, name] = raw
    value = {'schema_version': 1, 'run_date': DAY, 'generated_at': DAY + 'T01:00:00Z', 'files': files}
    store.objects[TAG, 'manifest.json'] = canonical(value)
    return value


def sidecar(store, v1, marker='first', out=None):
    files = {}
    for kind in ('product_history', 'economic_outlook'):
        plain = canonical({'transport_marker': marker, 'kind': kind})
        raw = gzip.compress(plain, mtime=0)
        name = f'v2-{kind.replace("_", "-")}-{DAY}-{digest(raw)[:12]}.json.gz'
        files[kind] = {'name': name, 'bytes': len(raw), 'sha256': digest(raw),
            'url': store.url(TAG, name), 'encoding': 'gzip', 'uncompressed_bytes': len(plain)}
        if out:
            out.mkdir(exist_ok=True)
            (out / name).write_bytes(raw)
        else:
            store.objects[TAG, name] = raw
    value = {'schema_version': 2, 'run_date': DAY, 'generated_at': DAY + 'T02:00:00Z',
        'base': {f'{kind}_sha': v1['files'][kind]['sha256'] for kind in ('core', 'details')},
        'capabilities': sorted(files), 'files': files}
    raw = (json.dumps(value, indent=3) + '\n').encode()
    if out:
        (out / archive.MANIFEST).write_bytes(raw)
    else:
        store.objects[TAG, archive.MANIFEST] = raw
    return raw, value


def test_all_exact_predecessor_bytes_survive_alias_replacement_and_pruning(tmp_path):
    store = Store()
    v1 = base(store)
    raw, v2_manifest = sidecar(store, v1)
    originals = dict(store.objects)
    assert archive.preserve_current_v2(tmp_path, repo=store.repo, tag=TAG, store=store) == raw
    tag = archive.archive_tag(raw)
    store.objects = {key: value for key, value in store.objects.items() if key[0] != TAG}
    assert store.read(tag, archive.MANIFEST) == raw
    assert store.read(tag, archive.BASE_MANIFEST) == originals[TAG, 'manifest.json']
    for entry in [*v2_manifest['files'].values(), *v1['files'].values()]:
        assert store.read(tag, entry['name']) == originals[TAG, entry['name']]
    receipt = json.loads(store.read(tag, archive.RECEIPT))
    assert receipt['manifest_sha256'] == digest(raw) and len(receipt['files']) == 4
    # Retry verifies the existing archive even after the mutable source vanished.
    archive.archive_v2(raw, tmp_path, store=store, source_tag=TAG)


def test_partial_archive_retry_completes_without_overwriting_prior_evidence(tmp_path):
    store = Store()
    raw, _ = sidecar(store, base(store))
    store.fail_name = archive.BASE_MANIFEST
    with pytest.raises(RevisionError, match='interruption'):
        archive.preserve_current_v2(tmp_path, repo=store.repo, tag=TAG, store=store)
    preserved = dict(store.objects)
    tag = archive.archive_tag(raw)
    assert store.read(tag, archive.RECEIPT) is None
    archive.preserve_current_v2(tmp_path, repo=store.repo, tag=TAG, store=store)
    assert all(store.objects[key] == value for key, value in preserved.items())
    assert store.read(tag, archive.RECEIPT)


@pytest.mark.parametrize('fault', ['asset_hash', 'asset_missing', 'base_mismatch', 'archive_tamper',
                                 'archive_receipt_tamper', 'archive_base_tamper', 'malformed_selector'])
def test_invalid_predecessor_or_archive_cannot_claim_preservation(tmp_path, fault):
    store = Store()
    raw, manifest = sidecar(store, base(store))
    name = manifest['files']['product_history']['name']
    if fault.startswith('archive_'):
        archive.preserve_current_v2(tmp_path, repo=store.repo, tag=TAG, store=store)
        changed = {'archive_tamper': name, 'archive_receipt_tamper': archive.RECEIPT,
                   'archive_base_tamper': archive.BASE_MANIFEST}[fault]
        store.objects[archive.archive_tag(raw), changed] = b'tampered'
    elif fault == 'asset_hash':
        store.objects[TAG, name] = b'tampered'
    elif fault == 'asset_missing':
        del store.objects[TAG, name]
    elif fault == 'base_mismatch':
        base(store, 'different')
    else:
        store.objects[TAG, archive.MANIFEST] = b'{'
    before = dict(store.objects)
    with pytest.raises((RevisionError, ValueError)):
        archive.preserve_current_v2(tmp_path, repo=store.repo, tag=TAG, store=store)
    assert store.objects == before


def test_v2_only_difference_gets_distinct_archive_without_changing_v1_identity(tmp_path):
    store = Store('another/valid-repository')
    v1 = base(store)
    identity = bundle_sha256(v1)
    first, _ = sidecar(store, v1)
    tag1 = archive.archive_v2(first, tmp_path, store=store, source_tag=TAG)
    second, _ = sidecar(store, v1, 'changed-insight')
    tag2 = archive.archive_v2(second, tmp_path, store=store, source_tag=TAG)
    assert tag1 != tag2 and bundle_sha256(v1) == identity
    assert store.read(tag1, archive.MANIFEST) == first
    assert store.read(tag2, archive.MANIFEST) == second


@pytest.mark.parametrize('failure', ['deleted', 'completed'])
def test_uncertain_selector_upload_retains_exact_archives_and_restores_only_missing_predecessor(tmp_path, monkeypatch, failure):
    store = Store()
    v1 = base(store)
    old, _ = sidecar(store, v1)
    archive.archive_v2(old, tmp_path, store=store, source_tag=TAG)
    new, _ = sidecar(store, v1, 'updated', tmp_path / 'new')
    archive.archive_v2(new, tmp_path, store=store, source_tag=TAG, payload_dir=tmp_path / 'new')
    monkeypatch.setattr(v2.subprocess, 'run', lambda args, **kwargs: store._run(args[1:], **kwargs))
    store.fail_alias = failure
    if failure == 'deleted':
        with pytest.raises(subprocess.TimeoutExpired):
            v2._replace_v2_manifest('gh', store.repo, TAG, tmp_path / 'new' / archive.MANIFEST, old, store)
        assert store.read(TAG, archive.MANIFEST) == old
    else:
        v2._replace_v2_manifest('gh', store.repo, TAG, tmp_path / 'new' / archive.MANIFEST, old, store)
        assert store.read(TAG, archive.MANIFEST) == new
    for raw in (old, new):
        assert store.read(archive.archive_tag(raw), archive.MANIFEST) == raw


def test_changed_predecessor_prevents_selector_clobber(tmp_path):
    store = Store()
    old, _ = sidecar(store, base(store))
    path = tmp_path / archive.MANIFEST
    path.write_bytes(old)
    store.objects[TAG, archive.MANIFEST] = b'other-writer'
    with pytest.raises(RevisionError, match='predecessor changed'):
        v2._replace_v2_manifest('gh', store.repo, TAG, path, old, store)
    assert store.read(TAG, archive.MANIFEST) == b'other-writer'


def test_immutable_archive_cannot_be_mutated_or_pruned(tmp_path):
    store = Store()
    raw, _ = sidecar(store, base(store))
    tag = archive.archive_tag(raw)
    with pytest.raises(RevisionError, match='immutable'):
        v2.publish_v2_sidecar(tmp_path, repo=store.repo, tag=tag)
    assert v2._prune_v2_assets('gh', store.repo, tag, set()) == 0


def transport(monkeypatch, store, before_alias=None):
    def run(command, **kwargs):
        args = command[1:]
        if args[:2] == ['release', 'view']:
            return subprocess.CompletedProcess(command, 0,
                '\n'.join(name for tag, name in store.objects if tag == args[2]), '')
        if args[:2] == ['release', 'upload']:
            if args[2] == TAG and Path(args[3]).name in {'manifest.json', archive.MANIFEST} and before_alias:
                before_alias(Path(args[3]).name)
            return store._run(args, **kwargs)
        raise AssertionError(command)
    monkeypatch.setattr(v2.subprocess, 'run', run)
    monkeypatch.setattr(v2, '_gh_available', lambda: 'gh')
    monkeypatch.setattr(v2, '_gh_authed', lambda _: True)
    monkeypatch.setattr(v2, 'GitHubRevisionStore', lambda *_a, **_k: store)
    monkeypatch.setattr(archive, 'GitHubRevisionStore', lambda *_a, **_k: store)
    monkeypatch.setattr(v2, '_live_manifest_status', lambda *_: ('present', json.loads(store.read(TAG, 'manifest.json'))))


def test_publisher_archives_both_bundles_before_alias_and_prune(tmp_path, monkeypatch):
    store = Store()
    v1 = base(store)
    old, _ = sidecar(store, v1)
    new, _ = sidecar(store, v1, 'new-insight', tmp_path)
    observed = []
    def before_alias(name):
        assert name == archive.MANIFEST
        for raw in (old, new):
            tag = archive.archive_tag(raw)
            assert store.read(tag, archive.MANIFEST) == raw and store.read(tag, archive.RECEIPT)
        observed.append(name)
    transport(monkeypatch, store, before_alias)
    def prune(*_args):
        assert observed == [archive.MANIFEST]
        observed.append('prune')
        return 0
    monkeypatch.setattr(v2, '_prune_v2_assets', prune)
    assert v2.publish_v2_sidecar(tmp_path, repo=store.repo)
    assert observed == [archive.MANIFEST, 'prune']
    assert store.read(TAG, archive.MANIFEST) == new


@pytest.mark.parametrize('broken', [False, True])
def test_v1_direct_publisher_preserves_old_v2_base_before_replacement(tmp_path, monkeypatch, broken):
    import app_payload
    store = Store()
    old_v1 = base(store)
    old_v2, old_manifest = sidecar(store, old_v1)
    incoming = Store()
    new_v1 = base(incoming, 'new-base')
    new_v1['generated_at'] = DAY + 'T04:00:00Z'
    (tmp_path / 'manifest.json').write_bytes(canonical(new_v1))
    for entry in new_v1['files'].values():
        (tmp_path / entry['name']).write_bytes(incoming.read(TAG, entry['name']))
    if broken:
        del store.objects[TAG, old_manifest['files']['product_history']['name']]
    seen = []
    def before_alias(name):
        assert name == 'manifest.json'
        archive_root = archive.archive_tag(old_v2)
        assert store.read(archive_root, archive.RECEIPT)
        assert store.read(archive_root, archive.BASE_MANIFEST) == canonical(old_v1)
        seen.append(name)
    transport(monkeypatch, store, before_alias)
    monkeypatch.delenv('AR_LOCAL_PAYLOAD_REVISIONS', raising=False)
    monkeypatch.setattr(app_payload, '_gh_available', lambda: 'gh')
    monkeypatch.setattr(app_payload, '_gh_authed', lambda _: True)
    monkeypatch.setattr(app_payload, '_live_manifest_status', lambda *_: ('present', old_v1))
    monkeypatch.setattr(app_payload, '_update_release_title', lambda *_: None)
    monkeypatch.setattr(app_payload, '_prune_release_assets', lambda *_: seen.append('prune') or 0)
    if broken:
        with pytest.raises(RevisionError, match='hash/size'):
            app_payload.publish_payload(tmp_path, repo=store.repo)
        assert seen == [] and store.read(TAG, 'manifest.json') == canonical(old_v1)
    else:
        assert app_payload.publish_payload(tmp_path, repo=store.repo)
        assert seen == ['manifest.json', 'prune']
        # V2 retry can preserve its former base after v1 has already advanced.
        archive.preserve_current_v2(tmp_path / 'retry', repo=store.repo, tag=TAG, store=store)
        assert store.read(TAG, 'manifest.json') == canonical(new_v1)


def test_bad_public_insight_blocks_selector_even_after_incoming_archive(tmp_path, monkeypatch):
    store = Store()
    v1 = base(store)
    old, _ = sidecar(store, v1)
    new, manifest = sidecar(store, v1, 'new-insight', tmp_path)
    entry = manifest['files']['product_history']
    store.objects[TAG, entry['name']] = b'wrong existing bytes'
    transport(monkeypatch, store)
    monkeypatch.setattr(v2, '_prune_v2_assets', lambda *_: pytest.fail('must not prune'))
    with pytest.raises(RevisionError, match='public insight'):
        v2.publish_v2_sidecar(tmp_path, repo=store.repo)
    assert store.read(TAG, archive.MANIFEST) == old
    assert store.read(archive.archive_tag(new), archive.MANIFEST) == new


def test_incoming_archive_failure_never_replaces_a_preserved_predecessor(tmp_path, monkeypatch):
    store = Store()
    v1 = base(store)
    old, _ = sidecar(store, v1)
    archive.archive_v2(old, tmp_path / 'prior', store=store, source_tag=TAG)
    new, _ = sidecar(store, v1, 'new-insight', tmp_path)
    store.fail_name = archive.RECEIPT
    transport(monkeypatch, store)
    monkeypatch.setattr(v2, '_prune_v2_assets', lambda *_: pytest.fail('must not prune'))
    with pytest.raises(RevisionError, match='interruption'):
        v2.publish_v2_sidecar(tmp_path, repo=store.repo)
    assert store.read(TAG, archive.MANIFEST) == old
    assert store.read(archive.archive_tag(old), archive.RECEIPT)
    assert store.read(archive.archive_tag(new), archive.RECEIPT) is None
    monkeypatch.setattr(v2, '_prune_v2_assets', lambda *_: 0)
    assert v2.publish_v2_sidecar(tmp_path, repo=store.repo) is True
