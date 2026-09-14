"""Exact May22 archive authority. Embedded exports never become HTTP captures."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from cdr_historical_fee_archive import MIB, inspect_archive, read_verified, safe_path
from cdr_historical_fee_exact import decode, encode, sha

DATE = '2026-05-22'
POLICY = 'may22-observation-archive-fees-v1'
DESIGN_SHA = '2e217e2bb55bcbc176217a59765513cf75d1829245d0509b8bf21e83c722cb0f'
PINS = {
    'source-manifest.json': {'bytes': 3649, 'sha256': '0c3e301fb93fcffd4f26b1b77b5a61b13f27f7f51571dd3ba5c20ec0f05de756'},
    'receipt.json': {'bytes': 3059, 'sha256': '9ce8c894ad33cc4d0addaca2a910362e3292e396dfbde59110d6042cb6148f3c'},
    'observation.tar.zst': {'bytes': 13585116, 'sha256': '4b8149f6a59330f49ec3474d388807322189e0ebe53a87a15f466dda06ab08c1'},
}
ANCHOR = {
    'manifest': {'bytes': 1112, 'sha256': 'f2d6fc0d53f814c55189f1dffe4277d77172e1035845a86a8b12d39c8580f506'},
    'core': {'bytes': 222545, 'sha256': '65a64471794d8f22659e8db47aa45f9439d9bd6c8e55bdc3636f2f5124f5cbd1'},
    'details': {'bytes': 415422, 'sha256': '9c7890d5e13a8cbb3dfe6ce7918ea96bd48dbcc3b512b8ac007f8dfbff00b7fd'},
}
SOURCE = {'path': 'data/runs/2026-05-22/_exports/banks-2026-05-22.json', 'bytes': 80749954,
          'sha256': '3ecc57557254d1f9c7584b275e218794a4fc6553880c16f34a518cdbec8a92ec'}


def _profile(profile):
    if profile is None:
        return DATE, PINS, SOURCE, ANCHOR
    # This optional seam accepts only the reviewed fixed registry, never a
    # runtime dictionary supplying arbitrary dates/source hashes/parents.
    from cdr_historical_fee_plan import archive_profile
    return archive_profile(profile)


def source_generation(source, *, date=DATE):
    if not isinstance(source, dict) or source.get('sector') != 'banks':
        raise ValueError('WITHHELD_GENERATION_BINDING:source_shape_invalid')
    value = source.get('generated_at')
    if source.get('run_date') != date or not isinstance(value, str):
        raise ValueError('WITHHELD_GENERATION_BINDING:source_date_or_time_missing')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('WITHHELD_GENERATION_BINDING:source_time_invalid') from exc
    if parsed.tzinfo is None or parsed.astimezone(ZoneInfo('Australia/Hobart')).date().isoformat() != date:
        raise ValueError('WITHHELD_GENERATION_BINDING:source_observation_day_unproved')
    return value


def metadata(manifest, receipt, *, profile=None):
    """Metadata admission is separate from physical member and fee admission."""
    date, pins, source, anchor = _profile(profile)
    if (manifest.get('observation_date') != date or receipt.get('observation_date') != date
            or manifest.get('kind') != 'observation' or receipt.get('kind') != 'observation'
            or receipt.get('result') != 'PASS'
            or receipt.get('source_manifest_sha256') != pins['source-manifest.json']['sha256']
            or receipt.get('archive_sha256') != pins['observation.tar.zst']['sha256']
            or receipt.get('archive_bytes') != pins['observation.tar.zst']['bytes']):
        raise ValueError('archive_receipt_identity_mismatch')
    files = manifest.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('archive_manifest_files_required')
    if (manifest.get('file_count') != len(files) or manifest.get('total_bytes') != sum(row['size'] for row in files)
            or receipt.get('source_bytes') != manifest['total_bytes']
            or receipt.get('checks', {}).get('files_verified') != len(files)):
        raise ValueError('archive_manifest_count_mismatch')
    chosen = {'source': source['path']}
    matches = [row for row in files if row['path'] == source['path']]
    if len(matches) != 1 or matches[0]['sha256'] != source['sha256'] or matches[0]['size'] != source['bytes']:
        raise ValueError('source_member_identity_mismatch')
    for role, identity in anchor.items():
        matches = [row for row in files if row['sha256'] == identity['sha256'] and row['size'] == identity['bytes']]
        if len(matches) != 1:
            raise ValueError('WITHHELD_GENERATION_BINDING:public_asset_member_missing_or_ambiguous')
        chosen[role] = matches[0]['path']
    for index, name in enumerate((f'data/state/{date}.done.json', f'data/state/{date}.integrity.json')):
        matches = [row for row in files if row['path'] == name]
        if len(matches) != 1 or matches[0]['size'] > MIB:
            raise ValueError('named_generation_control_missing_or_ambiguous')
        chosen['control' + str(index)] = name
    if profile is not None:
        from cdr_historical_fee_plan_candidate import validate_selected_members
        validate_selected_members(files, chosen)
    return files, chosen


def load(archive_dir, anchor_dir, cache, budget, *, profile=None):
    date, pins, source_pin, anchor = _profile(profile)
    archive_dir, anchor_dir = safe_path(archive_dir, directory=True), safe_path(anchor_dir, directory=True)
    inputs = {}
    small = {}
    for name in ('source-manifest.json', 'receipt.json'):
        identity = pins[name]
        small[name] = decode(read_verified(archive_dir / name, identity, budget, limit=MIB))
        inputs[name] = {'path': str(archive_dir / name), **identity}
    files, selected = metadata(small['source-manifest.json'], small['receipt.json'], profile=profile)
    anchored, anchor_bodies = {}, {}
    for role, identity in anchor.items():
        filename = 'manifest.json' if role == 'manifest' else role + '.json.gz'
        body = read_verified(anchor_dir / filename, identity, budget, limit=96 * MIB)
        anchor_bodies[role] = body
        anchored[role] = decode(body, compressed=role != 'manifest')
        if anchored[role].get('run_date') != date or type(anchored[role].get('schema_version')) is not int or anchored[role]['schema_version'] != 1:
            raise ValueError('anchor_date_or_schema_mismatch')
        inputs['anchor_' + role] = {'path': str(anchor_dir / filename), **identity}
    for role in ('core', 'details'):
        descriptor = anchored['manifest']['files'][role]
        if descriptor['sha256'] != anchor[role]['sha256'] or descriptor['bytes'] != anchor[role]['bytes']:
            raise ValueError('anchor_manifest_asset_binding_mismatch')
    if profile is None:
        record = inspect_archive(archive_dir / 'observation.tar.zst', pins['observation.tar.zst'], files, selected, cache, budget)
    else:
        record = inspect_archive(archive_dir / 'observation.tar.zst', pins['observation.tar.zst'], files, selected,
                                 cache, budget, allow_resume=False)
    inputs['archive_container'] = {'path': str(archive_dir / 'observation.tar.zst'), **pins['observation.tar.zst']}
    inputs['source_cache'] = {'path': str(Path(cache).absolute() / 'source.bin'), 'bytes': source_pin['bytes'], 'sha256': source_pin['sha256']}
    budget.check()
    source = decode(read_verified(Path(cache) / 'source.bin', record['selected']['source'], budget, limit=256 * MIB), limit=256 * MIB)
    generation = source_generation(source, date=date)
    budget.check()
    controls = {}
    for role in ('control0', 'control1'):
        obj = decode(read_verified(Path(cache) / (role + '.bin'), record['selected'][role], budget, limit=MIB))
        if not isinstance(obj, dict) or ('run_date' in obj and obj['run_date'] != date):
            raise ValueError('WITHHELD_GENERATION_BINDING:control_calendar_conflict')
        controls[role] = {'member': record['selected'][role], 'value': obj,
                          'interpretation': 'RETAINED_CONTROL_ONLY_NOT_COMPLETION_AUTHORITY'}
    for role in anchor:
        if record['selected'][role]['sha256'] != sha(anchor_bodies[role]):
            raise ValueError('archive_public_anchor_identity_mismatch')
    return {'source': source, 'manifest': anchored['manifest'], 'core': anchored['core'],
            'details': anchored['details'], 'core_bytes': anchor_bodies['core'], 'inputs': inputs,
            'container': {'evidence_kind': 'verified_observation_archive_member',
                          'archive': {'path': str(archive_dir / 'observation.tar.zst'), **pins['observation.tar.zst']},
                          'source_manifest': inputs['source-manifest.json'], 'backup_receipt': inputs['receipt.json'],
                          'source_member': record['selected']['source'], 'generation_controls': controls,
                          'archive_membership_sha256': sha(encode(record)), 'source_file_references': 'UNVERIFIED_NOT_DEREFERENCED'},
            'generation': {'observation_date': date, 'source_generation_time': generation,
                           'public_generation_time': anchored['manifest'].get('generated_at'),
                           'backup_completed_at': small['receipt.json'].get('completed_at'),
                           'legal_effective_from': None, 'legal_effective_to': None}}


def recheck_inputs(loaded, budget):
    for key, record in loaded['inputs'].items():
        read_verified(Path(record['path']), record, budget, limit=256 * MIB, capture=False,
                      budget_kind='compressed' if key == 'archive_container' else 'verified_read')
