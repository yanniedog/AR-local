"""Complete, bounded publication inventory for explicitly supplied evidence lanes.

No feature discovery or enablement. Financial-only callers keep their original
iterator. A reference requires its original capability bytes, never a guessed
list of filenames; remote evidence is always read through ARE2.
"""
from pathlib import Path

from app_payload_optional_assets import iter_payload_assets, executable_asset_url
from app_payload_product_evidence_contract import canonical, digest, require
from app_payload_product_evidence_delivery_check import read_stable
from app_payload_product_evidence_reference import LANES, reference_namespaces, bound_bundle_sha256

STATUS = 'optional_product_evidence_status'


def has_evidence(manifest):
    return any(key == STATUS or key.startswith(('product_evidence_', 'product_response_evidence_'))
               for key in manifest)


def validate_root(manifest):
    """Structural admission only. Does not claim complete asset verification."""
    from app_payload_product_evidence_publication_inventory import _status
    namespaces = reference_namespaces(manifest)
    _status(manifest, namespaces)
    require(len(canonical(manifest)) <= 65536, 'root manifest exceeds 64 KiB')
    return {key: value for key, value in manifest.items() if key not in (*LANES, STATUS)}


def _evidence_tag(manifest, *, retained=False):
    from app_payload_common import DEFAULT_REPO
    from app_payload_revisions_state import revision_tag
    require(manifest.get('repo') == DEFAULT_REPO, 'evidence repository differs')
    tag = manifest.get('tag'); bundle = bound_bundle_sha256(manifest)
    revision = manifest.get('payload_revision', {})
    if retained and tag == f"app-payload-archive-{manifest['run_date']}-{bundle}":
        value = manifest.get('retention', {})
        require(value.get('mode') == 'archive_only' and value.get('selected_for_app') is False,
                'retention is not a consumer selection')
        return tag
    require(type(revision) is dict and type(revision.get('schema_version')) is int
            and revision['schema_version'] == 1
            and tag == revision_tag(manifest['run_date'], revision.get('revision'))
            and revision.get('bundle_sha256') == bundle
            and revision.get('generation_id') == 'sha256-' + bundle,
            'evidence requires a bound immutable revision')
    return tag


def _read_capability(manifest, entry, *, root, store):
    if root is not None:
        return read_stable(Path(root) / entry['name'], entry['bytes'])[0]
    require(store is not None, 'complete inventory requires local or immutable remote capability bytes')
    tag = _evidence_tag(manifest, retained=True)
    require(store.repo == manifest['repo'], 'evidence store repository differs')
    return store.read_url(store.url(tag, entry['name']), entry['bytes'], require_encrypted=True)


def complete_assets(manifest, *, root=None, store=None):
    """Materialize the entire finite inventory before returning any descriptor."""
    if not has_evidence(manifest):
        return tuple(iter_payload_assets(manifest))
    from app_payload_product_evidence_publication_inventory import resolve_publication_inventory
    raw = canonical(manifest)
    result = resolve_publication_inventory(raw, digest(raw), lambda entry:
        _read_capability(manifest, entry, root=root, store=store))
    return tuple(result.document()['inventory'].items())


def checked_asset_bytes(root, entry):
    raw, _ = read_stable(Path(root) / entry['name'], entry['bytes'])
    require(len(raw) == entry['bytes'] and digest(raw) == entry['sha256'], 'publication asset changed before copy')
    return raw


def asset_url(manifest, key, entry, *, repo, inventory):
    """Only entries in a complete resolved inventory may get a transport URL."""
    require(any(key == known and canonical(entry) == canonical(value)
                for known, value in inventory), 'asset is outside complete inventory')
    if key.startswith(tuple(lane + '_' for lane in LANES)):
        tag = _evidence_tag(manifest, retained=True)
        require(repo == manifest['repo'], 'evidence repository differs')
        return f"https://github.com/{repo}/releases/download/{tag}/{entry['name']}"
    if key.startswith(('executable_v2_', 'monetary_v3_', 'monetary_v4_')):
        return executable_asset_url(manifest, entry, repo=repo)
    return entry['url']


def verify_stage(root, *, expected_manifest_sha256, controls=None):
    """Full byte/route verification, exact inventory, no publication authority.

    controls is an explicit relative-path -> {bytes, sha256} map supplied by the
    owning transaction. Unknown files/directories and stale pins are rejected.
    """
    from app_payload_product_evidence_publication_inventory import verify_local_publication_inventory
    return verify_local_publication_inventory(root, expected_manifest_sha256=expected_manifest_sha256,
                                              controls=controls)


def verify_publication_root(root, manifest):
    if not has_evidence(manifest):
        return
    from app_payload_publication_controls import publication_controls
    raw, _ = read_stable(Path(root) / 'manifest.json', 65536)
    from app_payload_product_evidence_contract import decode
    require(canonical(decode(raw)) == canonical(manifest), 'manifest differs from staged bytes')
    return verify_stage(root, expected_manifest_sha256=digest(raw),
                        controls=publication_controls(root, manifest))


def verify_selected_remote(store, manifest, root, inventory):
    """Aliases cannot advertise an uncommitted or incomplete evidence revision."""
    from app_payload_common import DEFAULT_TAG
    from app_payload_revisions_state import decode_document, validate_index
    tag = _evidence_tag(manifest)
    index_raw = store.read(DEFAULT_TAG, 'dates-index.json', require_encrypted=True)
    require(index_raw is not None, 'selected evidence index is missing')
    index = decode_document(index_raw); validate_index(index, repo=store.repo)
    raw, _ = read_stable(Path(root)/'manifest.json', 65536)
    identity = manifest['payload_revision']; head = index.get('revision_heads', {}).get(manifest['run_date'], {})
    require(all(head.get(key) == identity[key] for key in ('revision','generation_id','bundle_sha256'))
            and head.get('manifest_sha256') == digest(raw)
            and head.get('manifest_url') == store.url(tag,'manifest.json'), 'evidence revision is not selected')
    require(store.read(tag,'manifest.json',len(raw),require_encrypted=True) == raw,
            'immutable evidence manifest readback differs')
    for key, entry in inventory:
        observed = store.read_url(asset_url(manifest,key,entry,repo=store.repo,inventory=inventory),
                                  entry['bytes'],require_encrypted=True)
        require(observed == checked_asset_bytes(root,entry), 'immutable evidence asset readback differs')
