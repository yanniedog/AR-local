"""Current scoped eligibility publications; append-only CAS, no delivery activation."""
import json

from .executable_sources import source_checked
from .executable_v2_contract import validate_asset
from .executable_v2_reviews import current_approval
from .identity import canonical_json, digest, require_sha, timestamp
from .observation_checks import current_observation


@source_checked
def build_asset(store, product_key, *, core_asset_sha256, details_asset_sha256, run_date):
    require_sha(core_asset_sha256); require_sha(details_asset_sha256)
    observation = current_observation(store,product_key)
    rows = store.db.execute('SELECT s.* FROM executable_subjects_v2 s JOIN executable_scopes_v2 k USING(scope_id) '
        'WHERE k.product_key=? AND s.observation_id=? AND s.sequence=(SELECT MAX(x.sequence) FROM executable_subjects_v2 x WHERE x.scope_id=s.scope_id) '
        'ORDER BY s.scope_id LIMIT 33',(product_key,observation['observation_id'])).fetchall()
    if len(rows)>32:
        raise ValueError('Eligibility current product scope bound exceeded')
    items=[]
    for row in rows:
        subject=json.loads(row['subject_json'])
        approval=current_approval(store,subject)
        if approval is not None:
            items.append({'subject':subject,'approval':approval})
    value=dict(schemaVersion=2,productKey=product_key,sourceObservationId=observation['observation_id'],
        sourceGenerationId=observation['ingest_id'],runDate=run_date,coreAssetSha256=core_asset_sha256,
        detailsAssetSha256=details_asset_sha256,approvalPolicy='as_of_adopted_edition',subjects=items)
    value['identitySha256']=digest(value)
    validate_asset(value)
    return value


@source_checked
def publish_asset(store,payload,*,expected_previous_publication_id,expected_observation_id,published_at):
    validate_asset(payload)
    key=payload['productKey']
    if store.db.in_transaction:
        raise ValueError('Eligibility publication needs its own transaction')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        previous=store.db.execute('SELECT * FROM executable_publications_v2 WHERE product_key=? ORDER BY sequence DESC LIMIT 1',(key,)).fetchone()
        if (previous['publication_id'] if previous else None) != expected_previous_publication_id:
            raise ValueError('Eligibility publication CAS changed')
        observation=current_observation(store,key)
        if observation['observation_id'] != expected_observation_id or payload['sourceObservationId'] != expected_observation_id:
            raise ValueError('Eligibility publication source changed')
        current=build_asset(store,key,core_asset_sha256=payload['coreAssetSha256'],details_asset_sha256=payload['detailsAssetSha256'],run_date=payload['runDate'])
        if current != payload:
            raise ValueError('Eligibility publication source/review changed')
        if previous and previous['identity_sha256']==payload['identitySha256']:
            return previous['publication_id']
        fields=(key,expected_observation_id,payload['identitySha256'],expected_previous_publication_id,timestamp(published_at),canonical_json(payload))
        identity=digest(fields)
        store.db.execute('INSERT INTO executable_publications_v2(publication_id,product_key,observation_id,identity_sha256,previous_publication_id,published_at,payload_json) VALUES(?,?,?,?,?,?,?)',(identity,*fields))
    return identity
