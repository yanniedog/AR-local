"""Bounded URL-free executable assets outside legacy clients' eager file list."""
from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).parent / 'contracts/product_terms/drafts/eligibility-v2/executable-namespace-v2.schema.json'


def iter_payload_assets(manifest):
    """Yield the unchanged legacy descriptors plus validated optional descriptors.

    Callers retain their transport trust checks. This iterator invents no URLs
    and does not modify the manifest or change no-namespace bundle identities.
    """
    files = manifest.get('files')
    if not isinstance(files, dict):
        raise ValueError('Payload files must be an object')
    if any(str(key).startswith(('executable_v2_','monetary_v3_','executable_v3_')) for key in files):
        raise ValueError('Executable v2 descriptors must be outside legacy files')
    if 'executable_v2' not in manifest and 'executable_v3' not in manifest:
        yield from files.items()
        return
    names = set()
    for key, entry in files.items():
        if not isinstance(entry, dict):
            raise ValueError('Payload descriptor must be an object')
        name = entry.get('name')
        if not isinstance(name, str) or name in names:
            raise ValueError('Payload asset names must be unique')
        names.add(name)
        yield key, entry
    entries=[]
    if 'executable_v2' in manifest:
        namespace=manifest['executable_v2']
        if namespace is None:raise ValueError('Executable namespace cannot be null')
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(namespace)
        entries.extend([('executable_v2_index',namespace['index']),*namespace['shards'].items()])
    if 'executable_v3' in manifest:
        namespace=manifest['executable_v3']
        from cdr_terms.executable_v3_contract import schema_validate
        schema_validate(namespace,'namespace',64*1024)
        for capability,route in namespace['capabilities'].items():
            entries.extend([(f'monetary_v3_{capability}_index',route['index']),*route['shards'].items()])
    for key, entry in entries:
        expected = f"{key}-{manifest.get('run_date')}-{entry['sha256'][:12]}.json.gz"
        if entry['name'] != expected or entry['name'] in names:
            raise ValueError('Executable name kind/date/hash or uniqueness differs')
        names.add(entry['name'])
        yield key, entry


def executable_asset_url(manifest, entry, *, repo):
    """Resolve only an already verified immutable edition in the trusted repo."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Executable repository invalid')
    revision = manifest.get('payload_revision')
    tag = manifest.get('tag', '')
    if (not isinstance(revision, dict) or not re.fullmatch(r'app-payload-[0-9]{4}-[0-9]{2}-[0-9]{2}-r[0-9]{6}', tag)
            or type(revision.get('revision')) is not int or not 1 <= revision['revision'] <= 999999
            or tag != f"app-payload-{manifest.get('run_date')}-r{revision['revision']:06d}"):
        raise ValueError('Executable assets require immutable revision')
    from app_payload_revisions_state import bundle_sha256
    identity = bundle_sha256(manifest)
    if (revision.get('schema_version') != 1 or revision.get('bundle_sha256') != identity
            or revision.get('generation_id') != 'sha256-' + identity):
        raise ValueError('Executable immutable bundle identity differs')
    candidates = [value for key, value in iter_payload_assets(manifest) if key.startswith(('executable_v2_','monetary_v3_'))]
    if entry not in candidates:
        raise ValueError('Executable descriptor is outside adopted namespace')
    return f"https://github.com/{repo}/releases/download/{tag}/{entry['name']}"
