"""Optional immutable executable assets; never interpret, approve or activate."""
from __future__ import annotations

import json

from app_payload_terms import MAX_PRODUCTS, MAX_SHARD_RAW, MAX_SNAPSHOT_RAW, _ReadView, _json
from cdr_terms.executable_contract import validate_asset
from cdr_terms.executable_publication import build_executable_asset
from cdr_terms.executable_sources import validate_row_semantics, source_operation, finalized_capture
from cdr_terms.identity import digest, require_sha
from cdr_terms.observation_checks import current_observation


def load_published_executable(root, *, source_observation, run_date, core_asset_sha256, product_keys):
    require_sha(core_asset_sha256)
    keys = set(product_keys)
    if len(keys) > MAX_PRODUCTS or any(type(key) is not str or not key for key in keys):
        raise ValueError('Bounded executable product keys required')
    if not isinstance(source_observation, dict) or not source_observation.get('generation_id'):
        raise ValueError('Executable source generation required')
    require_sha(source_observation.get('contract_digest'))
    view = _ReadView(root)
    try:
        with source_operation(view):
            receipt = finalized_capture(view, source_observation['generation_id'], run_date)
            if receipt['export_contract_digest'] != source_observation['contract_digest']:
                raise ValueError('Executable finalized capture mismatch')
            result, total = {}, 0
            for key in sorted(keys):
                row = view.db.execute('SELECT * FROM executable_publications WHERE product_key=? ORDER BY sequence DESC LIMIT 1', (key,)).fetchone()
                if row is None:
                    continue
                observation = current_observation(view, key)
                if observation['ingest_id'] != source_observation['generation_id'] or observation['observation_id'] != row['observation_id']:
                    raise ValueError('Executable publication source is stale')
                body = row['payload_json'].encode()
                total += len(body)
                if len(body) > MAX_SHARD_RAW or total > MAX_SNAPSHOT_RAW:
                    raise ValueError('Executable snapshot byte bound exceeded')
                value = json.loads(body)
                validate_asset(value)
                if value['identitySha256'] != row['identity_sha256'] or value != build_executable_asset(view, key, core_asset_sha256=core_asset_sha256, run_date=run_date):
                    raise ValueError('Executable publication source/review changed')
                result[key] = value
            return result
    finally:
        view.db.close()


def package_executable(snapshot, *, core, core_asset_sha256, run_date, write_asset):
    """Manifest-addressed index and shards, bound to the destination's exact core."""
    if not snapshot:
        return {}
    if len(snapshot) > MAX_PRODUCTS:
        raise ValueError('Executable product count bound exceeded')
    files, index, group, total = {}, {}, {}, 0

    def shard(products):
        return {'schema_version': 1, 'run_date': run_date, 'core_asset_sha256': core_asset_sha256, 'products': products}

    def flush():
        if group:
            key = f'executable_shard_{len(files):03d}'
            files[key] = write_asset(key, shard(dict(group)))
            index.update({product: key for product in group})
            group.clear()

    for key, value in sorted(snapshot.items()):
        validate_asset(value)
        if value['productKey'] != key or value['runDate'] != run_date or value['coreAssetSha256'] != core_asset_sha256:
            raise ValueError('Executable destination core/generation mismatch')
        for item in value['templates']:
            template = item['template']
            binding = template['selectedRate']
            rows = core['sections']['TD']['rates']
            if binding['coreRowIndex'] >= len(rows):
                raise ValueError('Executable destination row missing')
            row = rows[binding['coreRowIndex']]
            if digest(row) != binding['rowSha256'] or row.get('product_key') != key or row.get('rate_index') != binding['rateIndex']:
                raise ValueError('Executable destination row mismatch')
            validate_row_semantics(template, row)
        total += len(_json(value))
        if len(_json(shard({key: value}))) > MAX_SHARD_RAW or total > MAX_SNAPSHOT_RAW:
            raise ValueError('Executable shard/snapshot byte bound exceeded')
        if len(_json(shard({**group, key: value}))) > MAX_SHARD_RAW:
            flush()
        group[key] = value
    flush()
    files['executable_index'] = write_asset('executable-index', {
        'schema_version': 1, 'run_date': run_date, 'core_asset_sha256': core_asset_sha256, 'products': index})
    return files
