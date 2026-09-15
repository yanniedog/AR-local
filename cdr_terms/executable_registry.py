"""One executable identity/controller entry point with immutable version dispatch."""
import json

from .executable_contract import validate_template
from .executable_reviews import stage_template
from .executable_sources import source_checked
from .executable_v2_contract import validate_subject
from .executable_v2_sources import source_snapshot
from .identity import canonical_json, timestamp


def lookup_subject(store, identity):
    migrated = store.db.execute("SELECT 1 FROM sqlite_master WHERE name='executable_registry_subjects' AND type='view'").fetchone()
    if migrated:
        row = store.db.execute('SELECT * FROM executable_registry_subjects WHERE subject_id=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('Executable subject not found')
        value = json.loads(row['subject_json'])
        version = row['wire_version']
        capability = {1: 'fixed_td_calculation', 2: 'eligibility_only'}.get(version)
        if capability is None or value.get('schemaVersion') != version or row['capability'] != capability:
            raise ValueError('Executable registry wire/capability mismatch')
    else:
        row = store.db.execute('SELECT template_json FROM executable_templates WHERE template_id=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('Executable subject not found')
        value = json.loads(row[0])
        version = 1
    (validate_subject if version == 2 else validate_template)(value)
    if value['id'] != identity:
        raise ValueError('Executable registry identity mismatch')
    return value


@source_checked
def stage_subject(store, subject, *, interpreter, staged_at, expected_previous_subject_id=None):
    if subject.get('schemaVersion') == 1:
        if expected_previous_subject_id is not None:
            raise ValueError('Legacy staging does not reinterpret v2 scope predecessors')
        return stage_template(store, subject, interpreter=interpreter, staged_at=staged_at)
    validate_subject(subject)
    if not isinstance(interpreter, str) or not interpreter.strip() or len(interpreter) > 256:
        raise ValueError('Executable interpreter identity required')
    staged = timestamp(staged_at)
    if store.db.in_transaction:
        raise ValueError('Eligibility staging needs its own transaction')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        source_snapshot(store, subject)
        existing = store.db.execute('SELECT * FROM executable_subjects_v2 WHERE subject_id=?', (subject['id'],)).fetchone()
        if existing:
            if existing['subject_json'] != canonical_json(subject):
                raise ValueError('Executable subject identity collision')
            return subject['id']
        previous = store.db.execute('SELECT subject_id FROM executable_subjects_v2 WHERE scope_id=? ORDER BY sequence DESC LIMIT 1',
                                    (subject['scopeId'],)).fetchone()
        if (previous[0] if previous else None) != expected_previous_subject_id:
            raise ValueError('Executable subject CAS changed')
        _insert_scope(store, subject)
        store.db.execute('INSERT INTO executable_subjects_v2(subject_id,scope_id,observation_id,previous_subject_id,interpreter,staged_at,subject_json) VALUES(?,?,?,?,?,?,?)',
            (subject['id'],subject['scopeId'],subject['source']['observationId'],expected_previous_subject_id,interpreter,staged,canonical_json(subject)))
        for identity in subject['source']['termRevisionIds']:
            store.db.execute('INSERT INTO executable_subject_terms_v2 VALUES(?,?)',(subject['id'],identity))
        for identity in subject['source']['documentVersionIds']:
            store.db.execute('INSERT INTO executable_subject_documents_v2 VALUES(?,?)',(subject['id'],identity))
    return subject['id']


def _insert_scope(store, subject):
    scope = subject['scope']
    body = canonical_json(scope)
    existing = store.db.execute('SELECT scope_json FROM executable_scopes_v2 WHERE scope_id=?', (subject['scopeId'],)).fetchone()
    if existing:
        if existing[0] != body:
            raise ValueError('Executable scope identity collision')
        return
    store.db.execute('INSERT INTO executable_scopes_v2 VALUES(?,?,?,?,?,?,?,?,?,?,?)',
        (subject['scopeId'],subject['capability'],scope['family'],scope['productKey'],scope['cohortKey'],scope['tierKey'],
         scope['packageKey'],scope['effectiveFrom'],scope['effectiveToExclusive'],scope['coverage'],body))


def review_subject(store, identity, **decision):
    subject = lookup_subject(store,identity)
    if subject['schemaVersion'] == 1:
        from .executable_reviews import review_template
        return review_template(store,identity,**decision)
    from .executable_v2_reviews import review_subject as review_v2
    return review_v2(store,identity,**decision)
