"""Technical regressions for the eight post-merge report findings."""
import json
import os
from pathlib import Path

import pytest

from cdr_product_report import generate
from cdr_report_terms import export_evidence, encoded, sha
from cdr_report_terms_store import Snapshot
from cdr_report_terms_contract import validate_rows, inventory_stages
from tests.test_cdr_report_terms import evidence, bundle, reseal  # noqa: F401


def exported(tmp_path, evidence):
    source = bundle(tmp_path, evidence)
    sealed = tmp_path / 'sealed'
    export_evidence(source, evidence[0].root, sealed)
    value = json.loads((sealed / 'evidence.json').read_bytes())
    return source, sealed, value['products'][evidence[2]]


def test_publications_only_selected_observation(evidence):
    store, observation, key, *_ = evidence
    # Isolate the existing readonly query against the exact publication columns.
    store.db.execute('CREATE TABLE executable_registry_subjects(subject_id,wire_version,capability,scope_id,product_key,observation_id)')
    store.db.execute('CREATE TABLE executable_publications_v3(sequence,publication_id,observation_id,identity_sha256,published_at,capability,state,product_key)')
    for i, observed in enumerate([observation, 'later-observation']):
        store.db.execute('INSERT INTO executable_publications_v3 VALUES(?,?,?,?,?,?,?,?)',
                         (i, str(i), observed, 'a'*64, '2026-09-15T00:00:00Z', 'mortgage_calculation', 'active', key))
    store.db.commit()
    view = Snapshot(store.root)
    try:
        rows = view.executables({'product_key': key, 'observation_id': observation})['publications']
        assert len(rows) == 1 and rows[0]['observation_id'] == observation
    finally:
        view.close()


def test_noncanonical_attachment_cannot_emit_a_mismatched_seal(tmp_path, evidence):
    source, sealed, _ = exported(tmp_path, evidence)
    body = json.dumps(json.loads((sealed / 'evidence.json').read_bytes()), indent=2).encode()
    (sealed / 'evidence.json').write_bytes(body)
    seal = json.loads((sealed / 'seal.json').read_bytes())
    seal.update(bytes=len(body), sha256=sha(body))
    (sealed / 'seal.json').write_bytes(encoded(seal))
    with pytest.raises(ValueError, match='canonical'):
        generate(source, tmp_path / 'report', terms_evidence=sealed)


def test_empty_revocation_delivery_is_not_reported_scopes(tmp_path, evidence):
    source, sealed, _ = exported(tmp_path, evidence)
    def revoke(value):
        row = value['products'][evidence[2]]
        row['delivered'] = [dict(capability='eligibility_only', asset_sha256='a'*64,
            subject_ids=[], status='delivered_as_of_selected_edition', bank_acceptance='unclassified')]
        row['stages'].update(inventory_stages(row))
    reseal(sealed, revoke)
    report = generate(source, tmp_path / 'report', terms_evidence=sealed)
    assert report['products'][0]['executable_terms_coverage'] == 'not_delivered'


def test_equal_latest_timestamps_preserve_current_ambiguity(tmp_path, evidence):
    store, observation, key, _, _, body, record = evidence
    source = bundle(tmp_path, evidence)
    when = store.db.execute('SELECT observed_at FROM observations WHERE observation_id=?', (observation,)).fetchone()[0]
    store.observe(provider=record['brand'], product_key=key, record=json.loads(body), source_bytes=body,
                  observed_at=when, ingest_id='technical-second')
    with store.db:
        store.db.execute('INSERT INTO ingest_captures VALUES(?,?,?,?)', ('technical-second', sha(body), when, 1))
    export_evidence(source, store.root, tmp_path / 'sealed')
    row = json.loads((tmp_path / 'sealed' / 'evidence.json').read_bytes())['products'][key]
    assert row['matches_current_observation'] is None


@pytest.mark.parametrize('kind', ['evidence', 'report'])
def test_late_empty_destination_reservation_is_not_replaced(tmp_path, evidence, monkeypatch, kind):
    source, sealed, _ = exported(tmp_path, evidence)
    output = tmp_path / 'reserved'
    import cdr_report_admission as admission
    real = admission.admit_new_directory
    def competing(stage, destination):
        destination.mkdir()
        with pytest.raises(FileExistsError):
            real(stage, destination)
        assert destination.is_dir() and not list(destination.iterdir())
        raise FileExistsError('Other writer reserved target')
    monkeypatch.setattr(admission, 'admit_new_directory', competing)
    with pytest.raises(FileExistsError):
        if kind == 'evidence':
            export_evidence(source, evidence[0].root, output)
        else:
            generate(source, output, terms_evidence=sealed)


def test_legacy_scope_null_is_valid_only_for_v1(tmp_path, evidence):
    _, _, row = exported(tmp_path, evidence)
    row['executables']['subjects'] = [dict(subject_id='a'*64, wire_version=1, capability='fixed_td_calculation',
        scope_id=None, recorded_review=None, current_approval_revalidated=False)]
    row['stages'].update(inventory_stages(row))
    validate_rows({'p': row})
    row['executables']['subjects'][0]['wire_version'] = 3
    with pytest.raises(ValueError):
        validate_rows({'p': row})


def test_deferred_acquisition_is_reportable(tmp_path, evidence):
    from cdr_terms.observation_checks import bind_manual_check
    store, observation, _, document, *_ = evidence
    check = 'd'*64
    store.record_check(document_id=document, check_id=check, checked_at='2026-09-15T00:00:00Z', status='deferred', error_code='technical_guard')
    bind_manual_check(store, observation, check)
    _, _, row = exported(tmp_path, evidence)
    assert next(d for d in row['documents'] if d['document_id'] == document)['latest_status'] == 'deferred'


def test_nullable_interpretation_and_removed_successor_remain_reportable(tmp_path, evidence):
    _, _, row = exported(tmp_path, evidence)
    row['interpretations'] = [dict(term_revision_id='a'*64, parameter_key='product.name', unit=None,
        rule_set_id=None, applicability_sha256='b'*64, review=None,
        changes=[dict(term_change_id='c'*64, kind='removed', after_revision_id=None)])]
    row['stages'].update(inventory_stages(row))
    validate_rows({'p': row})
