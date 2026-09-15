"""Append-only monetary publication; removals never become empty public assets."""
import json
from .identity import canonical_json,digest,timestamp
from .observation_checks import current_observation
from .executable_v3_contract import validate_asset,CAPABILITY
from .executable_v3_reviews import current_approval
from .executable_v3_evidence import evidence_checked


@evidence_checked
def build_asset(store,product_key,*,routing,capability=CAPABILITY):
    if capability!=CAPABILITY or routing['productKey']!=product_key:raise ValueError('Unsupported monetary publication capability/product')
    observation=current_observation(store,product_key)
    if observation['ingest_id']!=routing['sourceGenerationId']:raise ValueError('Monetary publication routing stale')
    rows=store.db.execute('SELECT s.* FROM executable_subjects_v3 s JOIN executable_scopes_v3 k USING(scope_id) '
        'WHERE k.product_key=? AND s.capability=? AND s.observation_id=? AND s.sequence=(SELECT MAX(x.sequence) FROM executable_subjects_v3 x WHERE x.scope_id=s.scope_id) '
        'ORDER BY s.scope_id LIMIT 33',(product_key,capability,observation['observation_id'])).fetchall()
    if len(rows)>32:raise ValueError('Monetary current subjects exceed bound')
    subjects=[]
    for row in rows:
        subject=json.loads(row['subject_json'])
        approval=current_approval(store,subject)
        if approval is not None:
            if subject['routing']!=routing:raise ValueError('Monetary approved destination routing differs')
            subjects.append({'subject':subject,'approval':approval})
    if not subjects:return None
    value=dict(schemaVersion=3,capability=capability,productKey=product_key,routing=routing,approvalPolicy='as_of_adopted_edition',subjects=subjects)
    value['identitySha256']=digest(value);validate_asset(value,product_key)
    return value


@evidence_checked
def publish_asset(store,product_key,*,routing,expected_previous_publication_id,expected_observation_id,published_at,capability=CAPABILITY):
    if store.db.in_transaction:raise ValueError('Monetary publication requires own transaction')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        observation=current_observation(store,product_key)
        if observation['observation_id']!=expected_observation_id:raise ValueError('Monetary publication observation CAS changed')
        previous=store.db.execute('SELECT publication_id FROM executable_publications_v3 WHERE product_key=? AND capability=? ORDER BY sequence DESC LIMIT 1',(product_key,capability)).fetchone()
        if (previous[0] if previous else None)!=expected_previous_publication_id:raise ValueError('Monetary publication predecessor CAS changed')
        asset=build_asset(store,product_key,routing=routing,capability=capability)
        state='active' if asset is not None else 'removed'
        identity=asset['identitySha256'] if asset else digest(dict(schemaVersion=3,capability=capability,productKey=product_key,observationId=expected_observation_id,state='removed'))
        fields=(product_key,capability,expected_observation_id,expected_previous_publication_id,state,identity,timestamp(published_at),canonical_json(asset) if asset else None)
        publication_id=digest(fields)
        store.db.execute('INSERT INTO executable_publications_v3(publication_id,product_key,capability,observation_id,previous_publication_id,state,identity_sha256,published_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?)',(publication_id,*fields))
    return publication_id
