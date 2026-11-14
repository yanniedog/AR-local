"""Held complete local inventory adapter; no uploads, writes or selection changes.

Accepts a clean isolated payload staging directory, or an exact externally
validated inventory of its local transaction control documents.
"""
from pathlib import Path
import re
import time

from app_payload_network_budget import validate_payload_network_budget, MANIFEST_MAX_BYTES
from app_payload_optional_assets import iter_payload_assets
from app_payload_product_evidence_contract import canonical, decode, digest, require
from app_payload_product_evidence_delivery_check import read_stable, signature, verify_assets as verify_facts
from app_payload_product_response_transport import verify_assets as verify_responses
from app_payload_product_evidence_reference import LANES, decode_capability, reference_namespaces, bound_bundle_sha256
from app_payload_revisions_state import validate_manifest

MAX_FILES = 1024
MAX_SECONDS = 600


def _members(root, controls=None):
    require(root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)), 'unsafe inventory root')
    members = {}
    controls = controls or {}
    pending = [root]; directories = set()
    for name in controls:
        require(type(name) is str and len(name) <= 512
                and re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name)
                and not Path(name).is_absolute() and '\\' not in name
                and all(part not in ('.', '..', '') for part in name.split('/')), 'unsafe control path')
        parts = Path(name).parts
        directories.update('/'.join(parts[:index]) for index in range(1, len(parts)))
    while pending:
        for path in pending.pop().iterdir():
            name = path.relative_to(root).as_posix()
            require(not path.is_symlink(), 'unsafe inventory link')
            if path.is_dir():
                require(name in directories, 'unbound inventory directory'); pending.append(path)
            else:
                require(len(members) < MAX_FILES + len(controls) and path.is_file(), 'unsafe or oversized inventory')
                members[name] = signature(path.lstat())
    return members


def _check(deadline):
    require(time.monotonic() < deadline, 'evidence inventory deadline exceeded')


def _read(root, descriptor, identities, deadline):
    _check(deadline)
    raw, before = read_stable(root / descriptor['name'], descriptor['bytes'])
    require(len(raw) == descriptor['bytes'] and digest(raw) == descriptor['sha256'], 'inventory asset digest or size differs')
    identities[descriptor['name']] = before
    return raw


def _add(inventory, key, descriptor):
    require(key not in inventory and descriptor['name'] not in {v['name'] for v in inventory.values()},
            'duplicate inventory key or filename')
    inventory[key] = descriptor


def _direct(manifest):
    entries = dict(iter_payload_assets(manifest))
    for key, entry in entries.items():
        require(not key.startswith(('product_evidence_', 'product_response_evidence_')) and
                not entry['name'].startswith(('product-evidence-', 'product-response-')),
                'lazy evidence cannot enter eager or unrelated namespace inventory')
    return entries


def verify_local_inventory(root, *, controls=None):
    """Verify every local byte and transitive route; return diagnostic-only evidence.

    Root manifest remains <=64 KiB; existing current assets keep the unchanged
    16 MiB budget. Each evidence lane independently retains its reviewed limits.
    The source fields are publisher attestations, not current-selection proof.
    """
    deadline = time.monotonic() + MAX_SECONDS
    controls = controls or {}
    require(type(controls) is dict and len(controls) <= 4096, 'invalid control inventory')
    root = Path(root).absolute(); initial = _members(root, controls)
    raw, before = read_stable(root / 'manifest.json', MANIFEST_MAX_BYTES)
    manifest = decode(raw); namespaces = reference_namespaces(manifest)
    require(len(raw) <= MANIFEST_MAX_BYTES, 'root manifest exceeds 64 KiB')
    # This complete verifier owns the detached namespaces; legacy iterators now
    # reject them rather than silently enumerate only the financial assets.
    base = {k: v for k, v in manifest.items() if k not in (*LANES, 'optional_product_evidence_status')}
    validate_manifest(base)
    base_report = validate_payload_network_budget(base, manifest_bytes=len(raw), asset_root=root)
    inventory = {}; identities = {'manifest.json': before}
    for key, descriptor in _direct(base).items():
        _add(inventory, key, descriptor); _read(root, descriptor, identities, deadline)
    bindings = {}; totals = {}
    for namespace in namespaces:
        reference = manifest[namespace]; descriptor = reference['capability']
        _add(inventory, namespace + '_capability', descriptor)
        blob = _read(root, descriptor, identities, deadline)
        capability = decode_capability(namespace, reference, blob, manifest)
        bindings[namespace] = (capability['binding'] if namespace == 'product_evidence_v1'
                               else capability['binding']['facts'])
        if len(bindings) == 2:
            require(canonical(bindings['product_evidence_v1']) == canonical(bindings['product_response_evidence_v1']),
                    'normalized and original-response source bindings differ')
        assets = [capability['index'], *capability['shards']]
        for number, item in enumerate(assets):
            _add(inventory, f'{namespace}_asset_{number:03d}', item)
            # Record every identity before the full semantic verifier reads it.
            identities[item['name']] = signature((root / item['name']).lstat())
        if namespace == 'product_evidence_v1':
            result = verify_facts(root, capability, deadline=deadline)
        else:
            result = verify_responses(root, capability, check=lambda: _check(deadline))
        totals[namespace] = {**result, 'compressed_bytes': sum(a['bytes'] for a in assets),
                             'decoded_bytes': sum(a['decoded_bytes'] for a in assets),
                             'capability_compressed_bytes': descriptor['bytes']}
    expected = {'manifest.json', *(item['name'] for item in inventory.values())}
    require(not expected.intersection(controls), 'control shadows payload asset')
    control_bytes = 0
    for name, entry in controls.items():
        require(type(entry) is dict and set(entry) == {'bytes', 'sha256'} and type(entry['bytes']) is int
                and 0 <= entry['bytes'] <= 64 * 1024 * 1024, 'invalid control descriptor')
        control_bytes += entry['bytes']; require(control_bytes <= 128 * 1024 * 1024, 'control byte budget exceeded')
        _read(root, dict(name=name, **entry), identities, deadline)
    expected.update(controls)
    require(set(initial) == expected and _members(root, controls) == initial, 'incomplete or changed payload inventory')
    require(all(initial[name] == value for name, value in identities.items()), 'payload changed during inventory verification')
    _check(deadline)
    return dict(selection_verified=False, publication_authorized=False, manifest_sha256=digest(raw),
                bundle_sha256=bound_bundle_sha256(manifest), inventory=inventory, namespaces=totals,
                base_network_budget=base_report, total_compressed_bytes=sum(x['bytes'] for x in inventory.values()))
