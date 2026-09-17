"""Readback gate for opt-in migration of unchanged historical domain bundles."""
from pathlib import Path

from app_payload_common import DEFAULT_TAG
from app_payload_optional_assets import iter_payload_assets, executable_asset_url
from app_payload_revisions_state import RevisionError, MAX_DOCUMENT_BYTES, decode_document
from release_transport import PlaintextTransportError


def encrypted_selection(store, manifest: dict, root: Path, index_bytes: bytes) -> bool:
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
    for name in ('revision-delta.json', 'publication-provenance.json'):
        try:
            observed = store.read_url(store.url(manifest['tag'], name), MAX_DOCUMENT_BYTES,
                                      require_encrypted=True)
        except PlaintextTransportError:
            encrypted = False
            continue
        if observed is None:
            raise RevisionError('encrypted revision control document is missing')
        decode_document(observed)
    return encrypted
