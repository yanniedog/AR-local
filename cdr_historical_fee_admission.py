"""May13-only retained embedded-export admission; no archive or database reader."""
from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

from cdr_historical_fee_exact import (canonical_sha, decode, exact, pointer_get,
                                      read_bound, sha)

DATE = '2026-05-13'
SOURCE_SHA = '5da7f5ebc1ee11591a062b086757a737d4da92c9fbc95e44e0214e38823b73d6'
SOURCE_BYTES = 80616373
ANCHOR = {
    'manifest.json': 'c6807bfaa3559479036e4d7c69048267a1fc145747c2275e064d02a0129c56a8',
    'core.json.gz': '3f291b09725d3b3ca8235e2aeb8641d78ed9e058d95f63572b778058b5e1b390',
    'details.json.gz': 'e77a7394a8221daa6f8ebd479fc3ff06dfb718f00d53d8a2569af205f8ca837a',
}
PARENT_MANIFEST_SHA = 'ec632441ad4b1df1c6996228ef57d9a18793c5d19edbc9bc3c5bdfd674b501dd'
PARENT_CORE_SHA = 'b03ae14b4e56759cc18339371304237615cbfa9e32e5fedf6cc29ec76b8d8b39'
RECOVERY = {
    'may13-image-capture-receipt.json': '832addc0446fbdd1e51f795bace69d581a6aff53edcb4e46c3225579bf35fbc9',
    'image-post-capture-preservation.json': 'bc5d973d1cf5b54089923f236db813b7e49e2ef75f8ccfdc663080b0515f1686',
    'selected-control-json/99d4a0092b98724dc3996b165527540aba284143a49924dea75245075cfdd81b.json':
        '99d4a0092b98724dc3996b165527540aba284143a49924dea75245075cfdd81b',
}


class Inputs:
    def __init__(self):
        self.records = {}

    def read(self, label, path, expected, *, limit=16 * 1024**2, size=None):
        body, before = read_bound(path, expected, limit=limit, expected_bytes=size)
        self.records[label] = {'path': str(path.resolve()), 'sha256': expected,
                               'bytes': len(body), 'fingerprint': before, 'limit': limit}
        return body

    def recheck(self):
        for record in self.records.values():
            _, fingerprint = read_bound(Path(record['path']), record['sha256'],
                                         limit=record['limit'], expected_bytes=record['bytes'])
            if fingerprint != record['fingerprint']:
                raise ValueError('input_fingerprint_changed_during_preparation')


def verify_parent(anchor, parent, dispositions, source):
    """Verify full parent lineage without running a classifier or redoing rates."""
    stripped = copy.deepcopy(parent)
    rows = {}
    if set(anchor.get('sections', {})) != {'Mortgage', 'Savings', 'TD'}:
        raise ValueError('anchor_sections_invalid')
    if set(parent.get('sections', {})) != set(anchor['sections']):
        raise ValueError('parent_section_membership_changed')
    for section, content in anchor['sections'].items():
        before = content['rates']
        after = stripped['sections'][section]['rates']
        if len(before) != len(after):
            raise ValueError('parent_rate_count_changed')
        for index, (old, new) in enumerate(zip(before, after)):
            pointer = f'/sections/{section}/rates/{index}'
            if 'taxonomy_path' not in old and 'taxonomy_path' in new:
                value = new.pop('taxonomy_path')
                if not isinstance(value, str) or not value:
                    raise ValueError('parent_taxonomy_value_invalid')
                rows[pointer] = value
    if not exact(stripped, anchor):
        raise ValueError('parent_changed_existing_value_or_non_taxonomy_field')
    covered, added, source_proofs = set(), set(), 0
    for entry in dispositions:
        pointer = entry['public_row_pointer']
        if pointer in covered:
            raise ValueError('parent_disposition_duplicate')
        covered.add(pointer)
        old = pointer_get(anchor, pointer)
        if old['product_key'] != entry['product_key']:
            raise ValueError('parent_disposition_product_mismatch')
        product = pointer_get(source, entry['source_product_pointer'])
        retained = pointer_get(source, entry['source_rate_pointer'])
        if product['product_key'] != old['product_key'] or retained['product_key'] != old['product_key']:
            raise ValueError('parent_source_product_mismatch')
        encoded = pointer_get(source, entry['embedded_string_pointer'])
        if not isinstance(encoded, str) or sha(encoded.encode('utf-8')) != entry['embedded_string_utf8_sha256']:
            raise ValueError('parent_embedded_string_hash_mismatch')
        raw = decode(encoded.encode('utf-8'))
        if not exact(old.get('rate'), entry['published_rate_preserved']):
            raise ValueError('parent_retained_rate_changed')
        if entry['status'] == 'ADDED':
            if pointer not in rows or not exact(rows[pointer], entry['after']):
                raise ValueError('parent_addition_receipt_mismatch')
            added.add(pointer)
            for dimension in entry['dimensions']:
                for proof in dimension['evidence']:
                    if not exact(pointer_get(raw, proof['pointer']), proof['value']):
                        raise ValueError('parent_taxonomy_source_pointer_mismatch')
                    source_proofs += 1
    expected = {f'/sections/{section}/rates/{index}' for section, content in anchor['sections'].items()
                for index in range(len(content['rates']))}
    if covered != expected or added != rows.keys():
        raise ValueError('parent_disposition_coverage_incomplete')
    return {'rows': len(covered), 'taxonomy_additions_preserved': len(rows),
            'taxonomy_source_proofs_rechecked': source_proofs,
            'all_existing_rate_values_order_and_multiplicity_preserved': True}


def _recovery_binding(inputs, recovery, source_body, anchor_bodies):
    values = {name: decode(inputs.read('recovery/' + name, recovery / name, expected))
              for name, expected in RECOVERY.items()}
    capture = values['may13-image-capture-receipt.json']
    preserved = values['image-post-capture-preservation.json']
    control = values[next(name for name in RECOVERY if name.startswith('selected-control-json/'))]
    if (capture['source_sha256'] != sha(source_body) or capture['source_bytes'] != len(source_body)
            or capture['independent_control_integrity_export_sha256'] != sha(source_body)
            or capture['image_sha256'] != preserved['post_capture_image_sha256']
            or preserved['matches_pre_capture_and_retained_image_sha256'] is not True
            or capture['matches_independent_control_integrity'] is not True or control['date'] != DATE):
        raise ValueError('recovered_export_receipt_chain_mismatch')
    for name, body in [('banks-' + DATE + '.json', source_body),
                       ('app-payload/core-' + DATE + '-3f291b09725d.json.gz', anchor_bodies['core.json.gz']),
                       ('app-payload/details-' + DATE + '-e77a7394a822.json.gz', anchor_bodies['details.json.gz'])]:
        matches = [item for item in control['files'] if item['path'] == name]
        if len(matches) != 1 or matches[0]['sha256'] != sha(body) or matches[0]['size'] != len(body):
            raise ValueError('independent_control_source_public_binding_mismatch')
    return {'kind': 'sealed_recovered_export', 'source_member_path': capture['source_member_path'],
            'image_sha256_from_prior_receipts': capture['image_sha256'], 'image_read_this_run': False,
            'prior_filesystem_recovery_required': capture['image_filesystem_metadata']['journal_recovery_required_bit'],
            'original_http_capture_supplied': False, 'original_http_availability': 'unverified',
            'source_and_core_details_byte_agreement': True,
            'control_manifest_differs_from_original_public_anchor': True}


def load_inputs(source_path: Path, recovery: Path, anchor: Path, parent: Path, parent_review: Path):
    """Only explicit recovered JSON and receipt files; never dereference source_file."""
    inputs = Inputs()
    source_body = inputs.read('source_export', source_path, SOURCE_SHA,
                              limit=96 * 1024**2, size=SOURCE_BYTES)
    source = decode(source_body)
    if not isinstance(source, dict) or source.get('run_date') != DATE or source.get('sector') != 'banks':
        raise ValueError('source_observation_date_or_shape_invalid')
    instant = datetime.fromisoformat(source['generated_at'].replace('Z', '+00:00'))
    if instant.tzinfo is None:
        raise ValueError('source_generation_clock_requires_timezone')
    anchor_bodies = {name: inputs.read('anchor/' + name, anchor / name, expected) for name, expected in ANCHOR.items()}
    manifest = decode(anchor_bodies['manifest.json'])
    for kind in ('core', 'details'):
        body = anchor_bodies[kind + '.json.gz']
        if manifest['files'][kind]['sha256'] != sha(body) or manifest['files'][kind]['bytes'] != len(body):
            raise ValueError('anchor_manifest_asset_mismatch')
    core = decode(anchor_bodies['core.json.gz'], compressed=True)
    details = decode(anchor_bodies['details.json.gz'], compressed=True)
    if any(value.get('run_date') != DATE or type(value.get('schema_version')) is not int or value['schema_version'] != 1
           for value in (manifest, core, details)):
        raise ValueError('anchor_date_or_schema_mismatch')
    recovered = _recovery_binding(inputs, recovery, source_body, anchor_bodies)
    parent_manifest = decode(inputs.read('parent/artifact-manifest.json', parent / 'artifact-manifest.json', PARENT_MANIFEST_SHA))
    expected_files = {'core-candidate.json.gz', 'details.json.gz', 'receipt.json', 'row-dispositions.jsonl'}
    if set(parent_manifest) != expected_files:
        raise ValueError('parent_artifact_inventory_changed')
    parent_bodies = {name: inputs.read('parent/' + name, parent / name, entry['sha256'],
                                     limit=32 * 1024**2, size=entry['bytes']) for name, entry in parent_manifest.items()}
    if sha(parent_bodies['core-candidate.json.gz']) != PARENT_CORE_SHA or parent_bodies['details.json.gz'] != anchor_bodies['details.json.gz']:
        raise ValueError('unreviewed_immediate_candidate_parent')
    parent_core = decode(parent_bodies['core-candidate.json.gz'], compressed=True)
    receipt = decode(parent_bodies['receipt.json'])
    review = decode(inputs.read('parent/independent-review.json', parent_review,
                                 'ad4d99b09e5546e88938f4c4adcb569eb3dd6cd3a1535e5dbb4fa40c3088c283'))
    if (receipt['source_export_sha256'] != SOURCE_SHA or receipt['candidate_core_sha256'] != PARENT_CORE_SHA
            or receipt['source_asset_sha256'] != ANCHOR or receipt['publication'] != 'NOT_ATTEMPTED'
            or review['result'] != 'PARENT_ALL_ADDITIONS_POINTERS_AND_INVARIANTS_PASS'):
        raise ValueError('parent_review_or_lineage_mismatch')
    dispositions = [decode(line, limit=256 * 1024) for line in parent_bodies['row-dispositions.jsonl'].splitlines()]
    lineage = verify_parent(core, parent_core, dispositions, source)
    if lineage['taxonomy_additions_preserved'] != receipt['rows_added']:
        raise ValueError('parent_addition_count_disagrees_with_receipt')
    return {'inputs': inputs, 'source': source, 'anchor_core': core, 'details': details,
            'core_bytes': parent_bodies['core-candidate.json.gz'], 'anchor_manifest': manifest,
            'container': recovered, 'parent_lineage': lineage,
            'source_generation_time': source['generated_at']}
