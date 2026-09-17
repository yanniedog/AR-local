"""Readback gate for opt-in migration of unchanged historical domain bundles."""
from pathlib import Path
import re

from app_payload_common import DEFAULT_TAG
from app_payload_optional_assets import iter_payload_assets, executable_asset_url
from app_payload_revisions_state import RevisionError, MAX_DOCUMENT_BYTES, decode_document, bundle_sha256
from release_transport import PlaintextTransportError


def encrypted_selection(store, manifest: dict, root: Path, index_bytes: bytes,
                        controls_root: Path) -> bool:
    """Return False only for legacy plaintext; every other failure stays fatal.

    The coordinator already verified the selected manifest and each domain asset.
    Inspect the complete transport set, including the data-bearing date index,
    before treating an identical bundle as an encrypted idempotent success.
    """
    objects = [(store.url(manifest['tag'], 'manifest.json'), root / 'manifest.json'),
               (store.url(DEFAULT_TAG, 'dates-index.json'), index_bytes)]
    for key, entry in iter_payload_assets(manifest):
        url = (executable_asset_url(manifest, entry, repo=store.repo)
               if key.startswith(('executable_v2_', 'monetary_v3_', 'monetary_v4_')) else entry['url'])
        objects.append((url, root / entry['name']))
    encrypted = True
    for url, source in objects:
        expected = source.read_bytes() if isinstance(source, Path) else source
        try:
            observed = store.read_url(url, max(len(expected), 1), require_encrypted=True)
        except PlaintextTransportError:
            encrypted = False
            continue
        if observed != expected:
            raise RevisionError('encrypted selected revision readback differs or is missing')
    # These archive control documents are not listed in the frozen manifest.
    # Deltas can contain product facts and must not escape transport validation.
    trusted_controls = True
    for name in ('revision-delta.json', 'publication-provenance.json'):
        try:
            observed = store.read_url(store.url(manifest['tag'], name), MAX_DOCUMENT_BYTES,
                                      require_encrypted=True)
        except PlaintextTransportError:
            encrypted = False
            continue
        if observed is None:
            raise RevisionError('encrypted revision control document is missing')
        validate_control(name, decode_document(observed), manifest)
        expected = controls_root / name
        if not expected.is_file():
            trusted_controls = False
        elif observed != expected.read_bytes():
            raise RevisionError('encrypted revision control differs from retained publication evidence')
    if encrypted and not trusted_controls:
        raise RevisionError('retained publication controls required to verify encrypted completion')
    return encrypted


def _strings(value) -> bool:
    return (isinstance(value, list) and all(isinstance(item, str) and item for item in value)
            and value == sorted(set(value)))


def validate_control(name: str, value: dict, manifest: dict) -> None:
    """Validate frozen control contracts before an encrypted no-op is accepted."""
    valid = type(value.get('schema_version')) is int and value['schema_version'] == 1
    if name == 'publication-provenance.json':
        valid = valid and set(value) == {
            'schema_version', 'consumer_commit', 'candidate_manifest_sha256', 'bundle_sha256'}
        valid = (valid and value['bundle_sha256'] == bundle_sha256(manifest)
                 and re.fullmatch('[0-9a-f]{40}', str(value['consumer_commit'])) is not None
                 and re.fullmatch('[0-9a-f]{64}', str(value['candidate_manifest_sha256'])) is not None)
    else:
        valid = valid and set(value) == {
            'schema_version', 'run_date', 'comparison', 'products', 'rate_rows', 'assets_changed'}
        valid = (valid and value['run_date'] == manifest['run_date']
                 and value['comparison'] in ('initial', 'previous_selected_revision')
                 and isinstance(value['products'], dict)
                 and set(value['products']) == {'added', 'removed', 'corrected'}
                 and all(_strings(rows) for rows in value['products'].values())
                 and _strings(value['assets_changed'])
                 and isinstance(value['rate_rows'], dict)
                 and set(value['rate_rows']) == {'added', 'removed'})
        if valid:
            valid = all(isinstance(rows, dict) and all(
                re.fullmatch('[0-9a-f]{64}', key) and type(count) is int and count > 0
                for key, count in rows.items()) for rows in value['rate_rows'].values())
    if not valid:
        raise RevisionError('encrypted revision control document violates its identity or schema')
