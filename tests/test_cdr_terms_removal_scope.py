"""Removal admission controls; mechanical revisions are not bank amendments."""
import json
import sqlite3
from contextlib import closing

import pytest

from cdr_terms.identity import canonical_json, digest
from cdr_terms.observation_checks import bind_manual_check
from cdr_terms.revisions import record_change
from tests.test_cdr_terms_evidence import evidence, _term, LATER


def replacement(evidence):
    store, observation, key, doc, _, body, _ = evidence
    term = _term(evidence)
    # A whitespace-only byte change exercises the protocol, not actual removal.
    version = store.record_check(document_id=doc, check_id='replacement', checked_at=LATER,
                                 status='fetched', body=body + b'\n', media_type='application/json')
    bind_manual_check(store, observation, 'replacement')
    extraction = store.register_extraction(document_version_id=version, extractor_version='technical-completeness',
        text=body.decode(), observed_at=LATER, status='complete', coverage={'technical_control_only': True})
    row = store.db.execute('SELECT * FROM term_revisions WHERE term_revision_id=?', (term,)).fetchone()
    proof = dict(passed=True, kind='removed', before_revision_id=term, after_revision_id=None,
        full_replacement_validated=True, replacement_document_version_id=version,
        replacement_observation_id=observation, replacement_extraction_id=extraction,
        replacement_applicability=json.loads(row['applicability_json']),
        replacement_parameter_keys=[row['parameter_key']])
    return term, proof


def remove(evidence, term, proof):
    store, _, key, *_ = evidence
    blob = store.put_blob(canonical_json(proof).encode())
    return record_change(store, product_key=key, before_revision_id=term, after_revision_id=None,
                         kind='removed', observed_at=LATER, evidence_sha256=blob)


@pytest.mark.parametrize('fault', ['cohort', 'parameter', 'observation', 'extraction', 'missing_scope', 'duplicate_parameter'])
def test_removal_refuses_unbound_replacement_scope(evidence, fault):
    store = evidence[0]
    term, proof = replacement(evidence)
    if fault == 'cohort':
        proof['replacement_applicability']['cohort'] = 'different-cohort'
    elif fault == 'parameter':
        proof['replacement_parameter_keys'] = ['fee.unrelated']
    elif fault == 'observation':
        proof['replacement_observation_id'] = '0' * 64
    elif fault == 'extraction':
        proof['replacement_extraction_id'] = '0' * 64
    elif fault == 'missing_scope':
        proof.pop('replacement_applicability')
    else:
        proof['replacement_parameter_keys'] *= 2
    with pytest.raises(ValueError, match='replacement|Replacement'):
        remove(evidence, term, proof)
    assert store.db.execute('SELECT count(*) FROM term_changes').fetchone()[0] == 0


def test_failed_latest_check_cannot_authorize_removal(evidence):
    store, observation, _, doc, *_ = evidence
    term, proof = replacement(evidence)
    store.record_check(document_id=doc, check_id='later-failure', checked_at=LATER,
                       status='failed', error_code='technical_timeout')
    bind_manual_check(store, observation, 'later-failure')
    with pytest.raises(ValueError, match='replacement|Replacement'):
        remove(evidence, term, proof)
    assert store.db.execute('SELECT count(*) FROM term_changes').fetchone()[0] == 0


def test_explicit_matching_replacement_is_idempotent_and_preserves_original(evidence):
    store = evidence[0]
    term, proof = replacement(evidence)
    old = tuple(store.db.execute('SELECT * FROM term_revisions WHERE term_revision_id=?', (term,)).fetchone())
    first = remove(evidence, term, proof)
    assert remove(evidence, term, proof) == first
    assert tuple(store.db.execute('SELECT * FROM term_revisions WHERE term_revision_id=?', (term,)).fetchone()) == old
    assert store.db.execute('SELECT count(*) FROM term_changes').fetchone()[0] == 1


def test_removal_does_not_commit_or_rollback_callers_transaction(evidence):
    store = evidence[0]
    term, proof = replacement(evidence)
    store.db.execute('BEGIN IMMEDIATE')
    marker = digest(['caller-owned'])
    store.db.execute('INSERT INTO documents VALUES (?,?)', (marker, 'https://example.invalid/caller'))
    with pytest.raises(ValueError, match='own transaction'):
        remove(evidence, term, proof)
    assert store.db.in_transaction
    assert store.db.execute('SELECT 1 FROM documents WHERE document_id=?', (marker,)).fetchone()
    store.db.rollback()
    assert store.db.execute('SELECT 1 FROM documents WHERE document_id=?', (marker,)).fetchone() is None


@pytest.mark.parametrize('fault', ['partial', 'future_extraction', 'superseded', 'future_check', 'new_observation', 'original_blob', 'text_blob'])
def test_replacement_must_remain_complete_current_and_intact(evidence, fault):
    store, observation, _, doc, _, body, _ = evidence
    term, proof = replacement(evidence)
    if fault in ('partial', 'future_extraction'):
        proof['replacement_extraction_id'] = store.register_extraction(
            document_version_id=proof['replacement_document_version_id'], extractor_version='technical-partial',
            text=body.decode(), observed_at=LATER if fault == 'partial' else '2026-09-14T02:00:00Z',
            status='partial' if fault == 'partial' else 'complete', coverage={'technical_control_only': True})
    elif fault in ('superseded', 'future_check'):
        when = LATER if fault == 'superseded' else '2026-09-14T02:00:00Z'
        store.record_check(document_id=doc, check_id='changed-again', checked_at=when,
            status='fetched', body=body + (b'\n\n' if fault == 'superseded' else b'\n'), media_type='application/json')
        bind_manual_check(store, observation, 'changed-again')
    elif fault == 'new_observation':
        source = json.loads(body)
        store.observe(provider=source['data']['brand'], product_key=evidence[2], record=source,
                      source_bytes=body, observed_at='2026-09-14T02:00:00Z', ingest_id='technical-later-observation')
    else:
        sql = ('SELECT content_sha256 FROM document_versions WHERE document_version_id=?' if fault == 'original_blob'
               else 'SELECT text_sha256 FROM extractions WHERE extraction_id=?')
        identity = proof['replacement_document_version_id' if fault == 'original_blob' else 'replacement_extraction_id']
        digest_value = store.db.execute(sql, (identity,)).fetchone()[0]
        (store.blobs / digest_value[:2] / digest_value).write_bytes(b'corrupted control')
    with pytest.raises(ValueError, match='[Rr]eplacement|integrity'):
        remove(evidence, term, proof)
    assert not store.db.in_transaction
    assert store.db.execute('SELECT count(*) FROM term_changes').fetchone()[0] == 0


def test_replacement_validation_and_change_insertion_hold_one_write_lock(evidence, monkeypatch):
    import cdr_terms.removal_admission as admission
    store = evidence[0]
    term, proof = replacement(evidence)
    original = admission.require_replacement
    def concurrent(*args):
        original(*args)
        with closing(sqlite3.connect(store.root / 'evidence.sqlite3', timeout=0.05)) as other:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute('BEGIN IMMEDIATE')
    monkeypatch.setattr(admission, 'require_replacement', concurrent)
    remove(evidence, term, proof)
    assert not store.db.in_transaction
    assert store.db.execute('SELECT count(*) FROM term_changes').fetchone()[0] == 1
