"""Optional eligibility-only shards; no staging, approval or activation here."""
from app_payload_terms import MAX_PRODUCTS, MAX_SHARD_RAW, MAX_SNAPSHOT_RAW, _json
from cdr_terms.executable_v2_contract import validate_asset
from cdr_terms.executable_v2_sources import validate_destination


def load_published_executable_v2(root, *, source_observation, run_date, core_asset_sha256, details_asset_sha256, product_keys):
    import json
    from app_payload_terms import _ReadView
    from cdr_terms.executable_sources import source_operation, finalized_capture
    from cdr_terms.executable_v2_publication import build_asset
    from cdr_terms.observation_checks import current_observation
    keys=set(product_keys)
    if len(keys)>MAX_PRODUCTS or any(not isinstance(key,str) or not key for key in keys):
        raise ValueError('Eligibility product inventory exceeds bound')
    view=_ReadView(root)
    try:
        with source_operation(view):
            receipt=finalized_capture(view,source_observation['generation_id'],run_date)
            if receipt['export_contract_digest']!=source_observation['contract_digest']:
                raise ValueError('Eligibility capture contract differs')
            result,total={},0
            for key in sorted(keys):
                row=view.db.execute('SELECT * FROM executable_publications_v2 WHERE product_key=? ORDER BY sequence DESC LIMIT 1',(key,)).fetchone()
                if row is None:
                    continue
                observation=current_observation(view,key)
                if observation['ingest_id']!=source_observation['generation_id'] or observation['observation_id']!=row['observation_id']:
                    raise ValueError('Eligibility publication source is stale')
                body=row['payload_json'].encode('utf8')
                total+=len(body)
                if len(body)>MAX_SHARD_RAW or total>MAX_SNAPSHOT_RAW:
                    raise ValueError('Eligibility publication snapshot exceeds bound')
                value=json.loads(body)
                validate_asset(value,product_key=key)
                if value['identitySha256']!=row['identity_sha256'] or value!=build_asset(view,key,core_asset_sha256=core_asset_sha256,details_asset_sha256=details_asset_sha256,run_date=run_date):
                    raise ValueError('Eligibility published review/source changed')
                result[key]=value
            return result
    finally:
        view.db.close()


def package_executable_v2(snapshot, *, core, details, core_asset_sha256, details_asset_sha256, run_date, write_asset):
    if len(snapshot) > MAX_PRODUCTS:
        raise ValueError('Executable v2 product count bound exceeded')
    shards, index, group, total = {}, {}, {}, 0

    def document(products):
        return dict(schema_version=2, run_date=run_date, core_asset_sha256=core_asset_sha256,
                    details_asset_sha256=details_asset_sha256, products=products)

    def write(kind, payload):
        descriptor = write_asset(kind, payload)
        if descriptor['bytes'] > 512 * 1024:
            raise ValueError('Executable v2 compressed asset exceeds bound')
        return {key: descriptor[key] for key in ('name', 'bytes', 'sha256')}

    def flush():
        if group:
            if len(shards) >= 999:
                raise ValueError('Executable v2 shard count exceeds bound')
            key = f'executable_v2_shard_{len(shards):03d}'
            shards[key] = write(key, document(dict(group)))
            index.update({product: key for product in group})
            group.clear()

    for key, value in sorted(snapshot.items()):
        validate_asset(value, product_key=key)
        if (value['runDate'] != run_date or value['coreAssetSha256'] != core_asset_sha256
                or value['detailsAssetSha256'] != details_asset_sha256):
            raise ValueError('Executable v2 destination assets differ')
        for item in value['subjects']:
            validate_destination(item['subject'], core, details, core_sha=core_asset_sha256, details_sha=details_asset_sha256)
        total += len(_json(value))
        if len(_json(document({key: value}))) > MAX_SHARD_RAW or total > MAX_SNAPSHOT_RAW:
            raise ValueError('Executable v2 shard/snapshot exceeds byte bound')
        if len(_json(document({**group, key: value}))) > MAX_SHARD_RAW:
            flush()
        group[key] = value
    flush()
    payload = document(index)
    if len(_json(payload)) > MAX_SHARD_RAW:
        raise ValueError('Executable v2 index exceeds byte bound')
    return {'schema_version': 2, 'index': write('executable_v2_index', payload), 'shards': shards}
