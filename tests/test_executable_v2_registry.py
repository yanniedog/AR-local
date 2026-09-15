"""Single registry dispatch and scope predecessor controls."""
import copy

import pytest

from cdr_terms.executable_registry import lookup_subject, stage_subject
from cdr_terms.executable_v2_migration import migrate_registry
from tests.executable_protocol_fixture import protocol, NOW
from tests.executable_v2_fixture import reidentify
from tests.test_executable_v2_sources import v2_protocol


def test_old_and_new_subjects_share_lookup_without_rewriting(protocol, v2_protocol):
    store, template, _, _ = protocol
    stage_subject(store, template, interpreter='technical', staged_at=NOW)
    assert lookup_subject(store, template['id']) == template
    migrate_registry(store, applied_at=NOW)
    subject = v2_protocol[1]
    stage_subject(store, subject, interpreter='technical', staged_at=NOW)
    assert lookup_subject(store, subject['id']) == subject
    assert lookup_subject(store, template['id']) == template
    assert store.db.execute('SELECT COUNT(*) FROM executable_registry_subjects').fetchone()[0] == 2


def test_same_scope_successor_requires_exact_predecessor(v2_protocol):
    store, original, _, _ = v2_protocol
    migrate_registry(store, applied_at=NOW)
    stage_subject(store, original, interpreter='technical', staged_at=NOW)
    updated = copy.deepcopy(original)
    updated['inputDefinitions'][0]['label'] = 'Updated technical prompt'
    reidentify(updated)
    with pytest.raises(ValueError, match='CAS changed'):
        stage_subject(store, updated, interpreter='technical', staged_at=NOW)
    stage_subject(store, updated, interpreter='technical', staged_at=NOW, expected_previous_subject_id=original['id'])
    assert store.db.execute('SELECT previous_subject_id FROM executable_subjects_v2 WHERE subject_id=?',(updated['id'],)).fetchone()[0] == original['id']


def test_v2_body_cannot_be_admitted_as_legacy_registry_record(v2_protocol):
    from cdr_terms.identity import canonical_json
    store, subject, _, _ = v2_protocol
    with store.db:
        store.db.execute('INSERT INTO executable_templates(template_id,observation_id,product_key,cohort_key,rate_index,interpreter,staged_at,template_json) VALUES(?,?,?,?,?,?,?,?)',
            (subject['id'],subject['source']['observationId'],subject['scope']['productKey'],'technical',1,'technical',NOW,canonical_json(subject)))
    migrate_registry(store, applied_at=NOW)
    with pytest.raises(ValueError, match='wire/capability'):
        lookup_subject(store, subject['id'])
