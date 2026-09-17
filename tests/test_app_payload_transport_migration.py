"""Transport state controls around the existing retained-real-source fixtures."""
import pytest

from app_payload_common import DEFAULT_TAG
from app_payload_revisions import publish_revision_bundle, _preserve_alias
from app_payload_revisions_state import RevisionError, bundle_sha256, canonical, decode_document
from app_payload_secure_upload import decode_public_bytes
from release_transport import PlaintextTransportError, TransportError
from tests.test_app_payload_revisions import MemoryStore, build_payload, publish, CONSUMER, REPO, DAY


class TransportStore(MemoryStore):
    repo = REPO

    def __init__(self):
        super().__init__()
        self.encrypted = set()
        self.encrypt_uploads = False
        self.faults = {}

    def read_url(self, url, limit=64*1024*1024, *, require_encrypted=False):
        raw = super().read_url(url, limit)
        if require_encrypted:
            if url in self.faults:
                fault = self.faults[url]
                if isinstance(fault, Exception):
                    raise fault
                return fault
            if raw is not None and url not in self.encrypted:
                raise PlaintextTransportError('legacy plaintext')
        return raw

    def archive(self, tag, paths):
        for path in paths:
            url = self.url(tag, path.name)
            if self.encrypt_uploads and (tag, path.name) in self.objects and url not in self.encrypted:
                raise PlaintextTransportError('immutable plaintext collision')
            super().archive(tag, [path])
            if self.encrypt_uploads:
                self.encrypted.add(url)

    def replace_index(self, tag, path, expected):
        super().replace_index(tag, path, expected)
        if self.encrypt_uploads:
            self.encrypted.add(self.url(tag, path.name))


def migrate(root, store):
    return publish_revision_bundle(root/'payload', state_dir=root/'state', repo=REPO,
        enabled=True, consumer_commit=CONSUMER, store=store, migrate_encryption=True)


def initial(root):
    store = TransportStore()
    manifest = build_payload(root/'payload')
    first = publish(root, store)
    store.encrypt_uploads = True
    return store, manifest, first


def test_same_domain_gets_higher_encrypted_revision_then_is_idempotent(tmp_path):
    store, original, first = initial(tmp_path)
    old_objects = dict(store.objects)
    migrated = migrate(tmp_path, store)
    assert migrated.head['revision'] == 2
    assert migrated.head['bundle_sha256'] == first.head['bundle_sha256'] == bundle_sha256(original)
    for key, raw in old_objects.items():
        if key != (DEFAULT_TAG, 'dates-index.json'):
            assert store.objects[key] == raw
    for key, entry in original['files'].items():
        assert (migrated.archive_dir/entry['name']).read_bytes() == (tmp_path/'payload'/entry['name']).read_bytes()
    again = migrate(tmp_path, store)
    assert again.head == migrated.head and not again.index_changed
    assert store.promotions == 2


def test_plaintext_index_cannot_count_as_finished_migration(tmp_path):
    store, _, first = initial(tmp_path)
    store.encrypted.update(store.url(*key) for key in store.objects if key != (DEFAULT_TAG,'dates-index.json'))
    assert migrate(tmp_path,store).head['revision'] == 2


@pytest.mark.parametrize('name', ['revision-delta.json', 'publication-provenance.json'])
def test_plaintext_control_document_cannot_count_as_finished(tmp_path, name):
    store, _, first = initial(tmp_path)
    store.encrypted.update(store.url(*key) for key in store.objects)
    store.encrypted.remove(store.url(first.manifest['tag'], name))
    assert migrate(tmp_path, store).head['revision'] == 2


@pytest.mark.parametrize('fault', [TransportError('authentication failed'), None, b'wrong-domain-bytes'])
def test_authentication_missing_or_changed_readback_never_advances(tmp_path, fault):
    store, original, first = initial(tmp_path)
    # Manifest and index are plaintext; a later asset error must still be fatal.
    entry = original['files']['details']
    store.faults[store.url(first.manifest['tag'],entry['name'])] = fault
    before = dict(store.objects)
    with pytest.raises((TransportError,RevisionError)):
        migrate(tmp_path,store)
    assert store.objects == before and store.promotions == 1


def test_interrupted_migration_reuses_reserved_revision(tmp_path):
    store, _, _ = initial(tmp_path)
    store.fail_asset='manifest.json'
    with pytest.raises(RevisionError,match='interrupted'):
        migrate(tmp_path,store)
    assert store.promotions == 1
    store.fail_asset=None
    assert migrate(tmp_path,store).head['revision'] == 2
    assert len(list((tmp_path/'state/revisions'/DAY).glob('r*/reservation.json'))) == 2


def test_historical_migration_preserves_newer_date_and_rolling_manifest(tmp_path):
    store, _, _ = initial(tmp_path)
    index = decode_document(store.objects[(DEFAULT_TAG,'dates-index.json')])
    index.update(dates=[DAY,'2026-05-20'],count=2,latest_date='2026-05-20')
    store.objects[(DEFAULT_TAG,'dates-index.json')] = canonical(index)
    store.objects[(DEFAULT_TAG,'manifest.json')] = b'retained-current-alias-control'
    migrate(tmp_path,store)
    updated = decode_document(store.objects[(DEFAULT_TAG,'dates-index.json')])
    assert updated['latest_date'] == '2026-05-20'
    assert updated['dates'] == [DAY,'2026-05-20']
    assert store.objects[(DEFAULT_TAG,'manifest.json')] == b'retained-current-alias-control'


def test_plaintext_signal_never_includes_bad_legacy_or_oversized_transport():
    with pytest.raises(PlaintextTransportError):
        decode_public_bytes(b'{}', 2, require_encrypted=True)
    for raw,limit in [(b'{}',1),(b'ARE1invalid',100),(b'ARE2invalid',100)]:
        with pytest.raises(TransportError) as caught:
            decode_public_bytes(raw,limit,require_encrypted=True)
        assert not isinstance(caught.value,PlaintextTransportError)


def test_existing_plaintext_legacy_preservation_is_not_overwritten(tmp_path):
    store = TransportStore()
    original = build_payload(tmp_path/'payload')
    store.objects[(DEFAULT_TAG, 'manifest.json')] = canonical(original)
    for entry in original['files'].values():
        store.objects[(DEFAULT_TAG, entry['name'])] = (tmp_path/'payload'/entry['name']).read_bytes()
    _preserve_alias(store, DEFAULT_TAG, tmp_path/'state')
    retained = dict(store.objects)
    store.encrypt_uploads = True
    with pytest.raises(PlaintextTransportError, match='collision'):
        _preserve_alias(store, DEFAULT_TAG, tmp_path/'state')
    migrated = migrate(tmp_path, store)
    assert migrated.head['revision'] == 1
    assert all(store.objects[key] == raw for key, raw in retained.items())
    legacy_tags = [tag for tag in store.tags() if '-legacy-' in tag]
    assert len(legacy_tags) == 2
    encrypted_tags = [tag for tag in legacy_tags if store.url(tag, 'manifest.json') in store.encrypted]
    assert len(encrypted_tags) == 1
    assert store.read(encrypted_tags[0], 'source-manifest.json') == canonical(original)
    assert migrate(tmp_path, store).head == migrated.head
