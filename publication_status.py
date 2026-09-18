"""Public operational receipt binding verified encrypted publication documents.

The hosted watchdog checks ciphertext identity, not private product semantics.
Only the Pi publisher authenticates and reconciles the three domain documents.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import date
from pathlib import Path

NAME = 'publication-status.json'
TAG = 'app-payload-latest'
LIMIT = 8 * 1024 * 1024
ASSETS = frozenset({'manifest', 'index', 'selected'})


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate operational receipt field')
        result[key] = value
    return result


def validate(raw: bytes) -> dict:
    if len(raw) > 4096:
        raise ValueError('operational receipt exceeds byte limit')
    value = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(value, dict) or set(value) != {'schema_version', 'run_date', 'revision', 'assets'}:
        raise ValueError('unknown operational receipt fields')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('unsupported operational receipt version')
    day = value['run_date']
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError('invalid operational publication date')
    if type(value['revision']) is not int or not 1 <= value['revision'] <= 999999:
        raise ValueError('invalid operational revision')
    assets = value['assets']
    if not isinstance(assets, dict) or set(assets) != ASSETS:
        raise ValueError('incomplete operational document set')
    for entry in assets.values():
        if not isinstance(entry, dict) or set(entry) != {'sha256', 'bytes'}:
            raise ValueError('unknown operational document fields')
        if not isinstance(entry['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', entry['sha256']):
            raise ValueError('invalid operational digest')
        if type(entry['bytes']) is not int or not 72 <= entry['bytes'] <= LIMIT + 72:
            raise ValueError('invalid operational document size')
    return value


def urls(store, value: dict) -> dict[str, str]:
    return {'manifest': store.url(TAG, 'manifest.json'),
            'index': store.url(TAG, 'dates-index.json'),
            'selected': store.url(f"app-payload-{value['run_date']}-r{value['revision']:06d}", 'manifest.json')}


def _wire(store, url: str) -> bytes:
    from release_transport import transport_header
    raw = store.read_wire_url(url, LIMIT)
    if raw is None:
        raise ValueError('publication document unavailable')
    transport_header(raw, LIMIT)
    return raw


def publish(store, expected_manifest: bytes) -> dict:
    from app_payload_revisions_state import validate_index, validate_manifest
    from app_payload_secure_upload import decode_public_bytes
    manifest = json.loads(expected_manifest)
    validate_manifest(manifest)
    value = {'schema_version': 1, 'run_date': manifest['run_date'],
             'revision': manifest['payload_revision']['revision'], 'assets': {}}
    documents = {name: _wire(store, url) for name, url in urls(store, value).items()}
    decoded = {name: decode_public_bytes(raw, LIMIT, require_encrypted=True)
               for name, raw in documents.items()}
    if decoded['manifest'] != expected_manifest or decoded['selected'] != expected_manifest:
        raise ValueError('publication manifest changed before receipt')
    index = json.loads(decoded['index']);validate_index(index, repo=store.repo)
    head = index['revision_heads'].get(value['run_date'], {})
    if (index['latest_date'] != value['run_date'] or head.get('revision') != value['revision']
            or head.get('manifest_sha256') != hashlib.sha256(expected_manifest).hexdigest()
            or head.get('manifest_url') != urls(store, value)['selected']):
        raise ValueError('publication index and manifest disagree')
    value['assets'] = {name: {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
                       for name, raw in documents.items()}
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode();validate(raw)
    with tempfile.TemporaryDirectory(prefix='ar-publication-status-') as temporary:
        path = Path(temporary) / NAME;path.write_bytes(raw)
        # The ordinary egress guard permits only this exact operational schema.
        store._run(['release', 'upload', TAG, str(path), '--repo', store.repo, '--clobber'])
    if store.read_wire_url(store.url(TAG, NAME), 4096) != raw:
        raise ValueError('operational receipt readback differs')
    verify(store, value)
    return value


def verify(store, value: dict) -> None:
    for name, url in urls(store, value).items():
        raw = _wire(store, url);expected = value['assets'][name]
        if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
            raise ValueError('publication ciphertext changed after receipt')


def check(expected_date: str, repo: str = 'yanniedog/AR-local') -> dict:
    from app_payload_revisions_github import GitHubRevisionStore
    result = {'manifest_run_date': '', 'dates_index_latest_date': '', 'generated_at': '',
              'manifest_error': None, 'dates_index_error': None, 'publication_issues': [],
              'publication_current': False, 'verification_scope': 'public_ciphertext_receipt'}
    try:
        store = GitHubRevisionStore(repo, gh='unused-read-only')
        raw = store.read_wire_url(store.url(TAG, NAME), 4096)
        if raw is None:
            raise ValueError('operational receipt unavailable')
        value = validate(raw);verify(store, value)
        result.update(manifest_run_date=value['run_date'], dates_index_latest_date=value['run_date'])
        if value['run_date'] != expected_date:
            raise ValueError('operational publication date is not current')
        result['publication_current'] = True
    except Exception as error:
        result['manifest_error'] = type(error).__name__
        result['publication_issues'] = ['operational_receipt_unavailable_or_inconsistent']
    return result
