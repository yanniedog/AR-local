"""Held complete publication inventory; no upload, remote fetch or selection.

Resolution reads at most two bounded capability blobs through a supplied reader.
It enumerates every declared index/shard without claiming their bytes verified.
The separate local verifier then checks all actual bytes and semantic routes.
"""
from dataclasses import dataclass
from pathlib import Path
import time

from app_payload_network_budget import validate_payload_network_budget
from app_payload_product_evidence_contract import canonical, decode, digest, fields, require, SHA
from app_payload_product_evidence_delivery_check import read_stable
from app_payload_product_evidence_inventory import _direct, verify_local_inventory
from app_payload_product_evidence_reference import LANES, decode_capability, reference_namespaces, bound_bundle_sha256
from app_payload_revisions_state import validate_manifest
from cdr_product_evidence_delivery_policy import STATUS, REASONS, source_reference

MAX_FILES = 1024
MAX_RECEIPT = 512 * 1024
SECONDS = 600


@dataclass(frozen=True)
class PublicationInventory:
    raw: bytes

    @property
    def sha256(self): return digest(self.raw)

    def document(self): return decode(self.raw)


def _status(manifest, namespaces):
    if STATUS not in manifest:
        require(not namespaces, 'evidence references need explicit delivery status')
        return
    value = manifest[STATUS]
    fields(value, ('schema', 'source', 'lanes'))
    require(value['schema'] == 'ar-product-evidence-status-v1' and value['source'] == source_reference(manifest),
            'unsupported or detached optional status')
    fields(value['lanes'], LANES)
    for lane, state in value['lanes'].items():
        fields(state, ('state', 'reason'))
        require(type(state['state']) is str and state['state'] in REASONS and type(state['reason']) is str
                and state['reason'] in REASONS[state['state']], 'invalid optional status/reason')
        require((state['state'] == 'available') == (lane in namespaces), 'ready optional status/reference contradicts')


def resolve_publication_inventory(manifest_raw, expected_manifest_sha256, read_capability):
    """Return immutable complete descriptors, never a readback/selection receipt.

    read_capability accepts a copied validated descriptor and must itself enforce
    its I/O timeout/byte ceiling. This resolver checks actual returned byte count,
    compressed SHA, inflation bounds, schema and independent manifest bindings.
    """
    deadline = time.monotonic() + SECONDS
    require(type(manifest_raw) is bytes and len(manifest_raw) <= 65536
            and type(expected_manifest_sha256) is str and SHA.fullmatch(expected_manifest_sha256)
            and digest(manifest_raw) == expected_manifest_sha256, 'root manifest differs from fixed pin or exceeds 64 KiB')
    try: manifest = decode(manifest_raw)
    except RecursionError: raise ValueError('root manifest nesting exceeds parser budget') from None
    namespaces = reference_namespaces(manifest); _status(manifest, namespaces)
    base = {key: value for key, value in manifest.items() if key not in (*LANES, STATUS)}
    validate_manifest(base)
    budget = validate_payload_network_budget(base, manifest_bytes=len(manifest_raw))
    entries = {}; names = set(); bindings = {}
    def add(key, entry):
        require(len(entries) < MAX_FILES and key not in entries and entry['name'] not in names,
                'duplicate or oversized complete inventory')
        entries[key] = decode(canonical(entry)); names.add(entry['name'])
    for key, entry in _direct(base).items(): add(key, entry)
    for lane in namespaces:
        require(time.monotonic() < deadline, 'publication inventory deadline exceeded')
        reference = manifest[lane]; entry = reference['capability']; add(lane + '_capability', entry)
        blob = read_capability(decode(canonical(entry)))
        require(time.monotonic() < deadline, 'publication inventory deadline exceeded')
        capability = decode_capability(lane, reference, blob, manifest)
        bindings[lane] = capability['binding'] if lane == 'product_evidence_v1' else capability['binding']['facts']
        for number, asset in enumerate([capability['index'], *capability['shards']]):
            add(f'{lane}_asset_{number:03d}', asset)
    if len(bindings) == 2:
        require(canonical(bindings['product_evidence_v1']) == canonical(bindings['product_response_evidence_v1']),
                'normalized and original source provenance differs')
    value = dict(schema='ar-product-evidence-publication-inventory-v1', manifest_sha256=digest(manifest_raw),
        bundle_sha256=bound_bundle_sha256(manifest), inventory=entries, base_network_budget=budget,
        publication_authorized=False, selection_verified=False, asset_bytes_verified=False)
    raw = canonical(value); require(len(raw) <= MAX_RECEIPT, 'complete inventory receipt exceeds 512 KiB')
    return PublicationInventory(raw)


def verify_local_publication_inventory(root, *, expected_manifest_sha256, controls=None):
    """All transitive bytes/routes plus root and explicit control pins rechecked.

    Clean staging is the default. Owning transactions may supply an exact,
    bounded map of independently validated reservation/control descriptors.
    """
    deadline = time.monotonic() + SECONDS
    root = Path(root).absolute()
    raw, identity = read_stable(root / 'manifest.json', 65536)
    resolved = resolve_publication_inventory(raw, expected_manifest_sha256,
        lambda entry: read_stable(root / entry['name'], entry['bytes'])[0])
    proof = verify_local_inventory(root, controls=controls)
    require(proof['manifest_sha256'] == expected_manifest_sha256
            and canonical(proof['inventory']) == canonical(resolved.document()['inventory']),
            'full local readback differs from frozen inventory')
    require(read_stable(root / 'manifest.json', 65536) == (raw, identity)
            and time.monotonic() < deadline, 'root changed or local inventory deadline exceeded')
    return dict(inventory=resolved, proof=proof, asset_bytes_verified=True,
                publication_authorized=False, selection_verified=False)
