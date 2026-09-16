"""Monetary storage adapter behind the shared executable controller."""
from .identity import canonical_json,timestamp
from .observation_checks import current_observation
from .executable_v4_contract import validate_subject
from .executable_v4_sources import source_snapshot
from .executable_v3_evidence import evidence_checked


def _links(store,subject):
    identity=subject['id']
    for term in subject['termRevisionIds']:store.db.execute('INSERT INTO executable_subject_terms_v4 VALUES(?,?)',(identity,term))
    for document in subject['documentVersionIds']:store.db.execute('INSERT INTO executable_subject_documents_v4 VALUES(?,?)',(identity,document))
    observations=set()
    for authority in subject['authorityGraph']['authorities']:
        body=canonical_json(authority)
        old=store.db.execute('SELECT authority_json FROM executable_authorities_v4 WHERE authority_id=?',(authority['id'],)).fetchone()
        if old is not None and old[0]!=body:raise ValueError('Monetary authority collision')
        store.db.execute('INSERT OR IGNORE INTO executable_authorities_v4 VALUES(?,?,?)',(authority['id'],authority['kind'],body))
        store.db.execute('INSERT INTO executable_subject_authorities_v4 VALUES(?,?)',(identity,authority['id']))
        observations.update(x['observationId'] for x in authority.get('observations',[]))
    for observation in sorted(observations):store.db.execute('INSERT INTO executable_subject_observations_v4 VALUES(?,?)',(identity,observation))
    for member in subject['authorityGraph']['members']:
        store.db.execute('INSERT INTO executable_subject_members_v4 VALUES(?,?,?,?,?,?)',
            (identity,member['sha256'],member['kind'],member['encoding'],member['bytes'],member['decodedBytes']))


@evidence_checked
def stage_subject(store,subject,*,interpreter,staged_at,expected_previous_subject_id=None):
    validate_subject(subject)
    if not isinstance(interpreter,str) or not interpreter.strip() or len(interpreter)>256:raise ValueError('Monetary interpreter required')
    staged=timestamp(staged_at)
    if staged<timestamp(subject['authorityGraph']['completedPeriod']['asOf']):raise ValueError('Monetary staging predates completeness authority')
    if store.db.in_transaction:raise ValueError('Monetary staging requires own transaction')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        source_snapshot(store,subject)
        old=store.db.execute('SELECT subject_json FROM executable_subjects_v4 WHERE subject_id=?',(subject['id'],)).fetchone()
        if old is not None:
            if old[0]!=canonical_json(subject):raise ValueError('Monetary subject identity collision')
            return subject['id']
        previous=store.db.execute('SELECT subject_id FROM executable_subjects_v4 WHERE scope_id=? ORDER BY sequence DESC LIMIT 1',(subject['scopeId'],)).fetchone()
        if (previous[0] if previous else None)!=expected_previous_subject_id:raise ValueError('Monetary stage CAS changed')
        body=canonical_json(subject['scope'])
        old_scope=store.db.execute('SELECT scope_json FROM executable_scopes_v4 WHERE scope_id=?',(subject['scopeId'],)).fetchone()
        if old_scope is not None and old_scope[0]!=body:raise ValueError('Monetary scope identity collision')
        store.db.execute('INSERT OR IGNORE INTO executable_scopes_v4 VALUES(?,?,?,?)',(subject['scopeId'],subject['capability'],subject['scope']['productKey'],body))
        observation=current_observation(store,subject['scope']['productKey'])
        fields=(subject['id'],4,subject['capability'],subject['kind'],subject['adapterVersion'],subject['evaluatorVersion'],subject['scopeId'],
            observation['observation_id'],expected_previous_subject_id,interpreter,staged,subject['authorityGraph']['identitySha256'],canonical_json(subject))
        store.db.execute('INSERT INTO executable_subjects_v4(subject_id,wire_version,capability,kind,adapter_version,evaluator_version,scope_id,observation_id,previous_subject_id,interpreter,staged_at,authority_graph_sha256,subject_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',fields)
        _links(store,subject)
    return subject['id']
