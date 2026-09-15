"""Current approved templates only; append-only publication with exact CAS."""
from __future__ import annotations

import json

from .executable_contract import validate_asset, validate_template
from .executable_reviews import current_approval
from .executable_sources import source_checked
from .identity import canonical_json, digest, require_sha, timestamp
from .observation_checks import current_observation


@source_checked
def build_executable_asset(store, product_key, *, core_asset_sha256, run_date):
    require_sha(core_asset_sha256)
    observation = current_observation(store, product_key)
    rows = store.db.execute('SELECT * FROM executable_templates t WHERE product_key=? AND observation_id=? '
                            'AND sequence=(SELECT MAX(sequence) FROM executable_templates '
                            'WHERE product_key=t.product_key AND cohort_key=t.cohort_key AND rate_index=t.rate_index) '
                            'ORDER BY cohort_key,rate_index LIMIT 33', (product_key, observation['observation_id'])).fetchall()
    if len(rows) > 32:
        raise ValueError('Executable product variant bound exceeded')
    items = []
    for row in rows:
        # A new source edition cannot silently inherit a previous template.
        if row['observation_id'] != observation['observation_id']:
            continue
        template = json.loads(row['template_json'])
        validate_template(template)
        approval = current_approval(store, template)
        if approval is not None:
            items.append({'template': template, 'approval': approval})
    value = {'schemaVersion': 1, 'productKey': product_key, 'sourceGenerationId': observation['ingest_id'],
             'runDate': run_date, 'coreAssetSha256': core_asset_sha256, 'approvalPolicy': 'as_of_adopted_edition',
             'templates': items}
    value['identitySha256'] = digest(value)
    validate_asset(value)
    return value


@source_checked
def publish_executable_asset(store, payload, *, expected_previous_identity, expected_observation_id, published_at):
    validate_asset(payload)
    key = payload['productKey']
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        previous = store.db.execute('SELECT * FROM executable_publications WHERE product_key=? '
                                    'ORDER BY sequence DESC LIMIT 1', (key,)).fetchone()
        identity = previous['identity_sha256'] if previous else None
        if identity != expected_previous_identity:
            raise ValueError('Executable publication changed; stale CAS rejected')
        if current_observation(store, key)['observation_id'] != expected_observation_id:
            raise ValueError('Executable source changed before publication')
        if build_executable_asset(store, key, core_asset_sha256=payload['coreAssetSha256'], run_date=payload['runDate']) != payload:
            raise ValueError('Executable source/review changed before publication')
        if identity == payload['identitySha256'] and previous['observation_id'] == expected_observation_id:
            return previous['publication_id']
        fields = (key, expected_observation_id, payload['identitySha256'], expected_previous_identity,
                  timestamp(published_at), canonical_json(payload))
        publication = digest(fields)
        store.db.execute('INSERT INTO executable_publications (publication_id,product_key,observation_id,identity_sha256,previous_identity_sha256,published_at,payload_json) VALUES (?,?,?,?,?,?,?)', (publication, *fields))
    return publication
