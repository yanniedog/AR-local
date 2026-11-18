"""Exact local-only transaction controls accompanying a complete payload.

These files are never implicitly uploaded. Every file must match an owning
protocol's fixed path and schema; pins are rechecked by the inventory verifier.
"""
from pathlib import Path
import re

from app_payload_product_evidence_contract import canonical, decode, digest, require
from app_payload_product_evidence_delivery_check import read_stable

MAX_CONTROL_FILES = 4096
# Includes the existing v2 product_history allowance (32 MiB), its original
# core/details, and bounded revision receipts. Does not alter any asset budget.
MAX_CONTROL_BYTES = 128 * 1024 * 1024


def _walk(root):
    pending = [root]; count = 0
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            count += 1
            require(count <= 4*MAX_CONTROL_FILES+1024 and not path.is_symlink(), 'unsafe or excessive publication controls')
            if path.is_dir(): pending.append(path)
            else:
                require(path.is_file(), 'nonregular publication control')
                yield path


def _validate(name, value, raw, manifest):
    from app_payload_revisions_state import bundle_sha256, validate_index, validate_manifest
    from app_payload_revision_transport import validate_control
    identity = manifest.get('payload_revision', {})
    if name in ('revision-delta.json', 'publication-provenance.json'):
        validate_control(name, value, manifest)
    elif name == 'reservation.json':
        require(set(value) == {'schema_version', 'revision', 'generation_id', 'bundle_sha256',
                             'parent_revision', 'run_date'} and value['run_date'] == manifest['run_date']
                and all(value[key] == identity.get(key) for key in value if key != 'run_date'),
                'reservation control differs from revision')
    elif re.fullmatch(r'verified-[0-9a-f]{64}\.json', name):
        require(set(value) == {'schema_version', 'head', 'index_sha256'} and value['schema_version'] == 1
                and name == f"verified-{value['index_sha256']}.json"
                and value['head'].get('bundle_sha256') == bundle_sha256(manifest), 'invalid verified control')
    elif name in ('.prev-manifest/manifest.json', 'source-manifest.json'):
        validate_manifest(value)  # Exact displaced alias retained by its owning publisher.
    elif name == 'preservation.json':
        require(set(value) == {'schema_version','source_manifest_sha256','source_tag','source_manifest_file'}
                and value['schema_version'] == 1 and value['source_manifest_file'] == 'source-manifest.json'
                and re.fullmatch('[0-9a-f]{64}', str(value['source_manifest_sha256']))
                and re.fullmatch(r'app-payload-(?:latest|[0-9]{4}-[0-9]{2}-[0-9]{2})', str(value['source_tag'])),
                'invalid preservation control')
    elif name.startswith('promotions/'):
        parts = name.split('/')
        require(len(parts) in (3, 4) and re.fullmatch('[0-9a-f]{64}', parts[1]), 'invalid promotion control path')
        suffix = '/'.join(parts[2:])
        if suffix in ('dates-index.json', 'predecessor/dates-index.json'):
            validate_index(value, repo=manifest['repo'])
            if suffix == 'dates-index.json': require(digest(raw) == parts[1], 'promotion index pin differs')
        elif suffix in ('promotion-intent.json', 'promotion-receipt.json'):
            expected = {'schema_version', 'index_sha256', 'predecessor_index_sha256'}
            if suffix == 'promotion-receipt.json': expected.add('head')
            require(set(value) == expected and value['schema_version'] == 1 and value['index_sha256'] == parts[1]
                    and (value['predecessor_index_sha256'] is None or re.fullmatch(
                        '[0-9a-f]{64}', str(value['predecessor_index_sha256']))), 'invalid promotion receipt')
            if 'head' in value:
                require(value['head'].get('bundle_sha256') == bundle_sha256(manifest), 'promotion head differs')
        else: raise ValueError('unknown promotion control')
    else:
        raise ValueError('unknown publication control: ' + name)


def publication_controls(root, manifest):
    """Pin only recognized controls; extra or malformed state fails closed.

    The v2 subtree is expanded from its exact preservation receipts, including
    selector/base/source hashes. No subtree wildcard exempts unbound files.
    """
    from app_payload_publication_assets import complete_assets
    root = Path(root).absolute()
    require(not any(p.is_symlink() for p in (root, *root.parents)), 'unsafe publication root')
    assets = {'manifest.json', *(entry['name'] for _, entry in complete_assets(manifest, root=root))}
    from app_payload_publication_v2_controls import v2_control_inventory
    v2 = v2_control_inventory(root, repo=manifest.get('repo'))
    result = {}; total = 0
    for path in _walk(root):
        name = path.relative_to(root).as_posix()
        if name in assets: continue
        raw, _ = read_stable(path, v2[name]['bytes'] if name in v2 else 8 * 1024 * 1024); total += len(raw)
        require(total <= MAX_CONTROL_BYTES, 'publication control bytes exceed budget')
        if name in v2:
            require(v2[name] == dict(bytes=len(raw), sha256=digest(raw)), 'v2 preserved control changed')
        else:
            value = decode(raw); require(type(value) is dict, 'publication control must be an object')
            _validate(name, value, raw, manifest)
        result[name] = dict(bytes=len(raw), sha256=digest(raw))
    require(set(v2) <= set(result), 'v2 preserved inventory is incomplete')
    if 'preservation.json' in result:
        receipt = decode(read_stable(root/'preservation.json', 8*1024*1024)[0])
        require(result.get('source-manifest.json', {}).get('sha256') == receipt['source_manifest_sha256'],
                'preserved source manifest digest differs')
    return result
