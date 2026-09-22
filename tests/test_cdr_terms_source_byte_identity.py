"""Source-URL changes must not masquerade as publisher term amendments."""
import json

import pytest

from cdr_terms.identity import canonical_json
from cdr_terms.observation_checks import bind_manual_check
from cdr_terms.revisions import record_change
from tests.test_cdr_terms_evidence import evidence, _term, NOW, LATER


def alias_evidence(evidence):
    store, _, key, _, _, body, record = evidence
    before = _term(evidence)
    source = json.loads(body)
    source['links']['self'] = 'https://example.com/retained-source-alias'
    new_body = canonical_json(source).encode()
    observation = store.observe(provider=record['brand'], product_key=key, record=source,
        source_bytes=new_body, observed_at='2026-09-14T00:30:00Z', ingest_id='source-url-protocol')
    doc = store.db.execute('SELECT document_id FROM documents WHERE source_url=?',
                          (source['links']['self'],)).fetchone()[0]
    version = store.record_check(document_id=doc, check_id='same-bytes-new-url', checked_at=NOW,
        status='fetched', body=body, media_type='application/json')
    bind_manual_check(store, observation, 'same-bytes-new-url')
    after_evidence = (store, observation, key, doc, version, new_body, record)
    return before, after_evidence, body


@pytest.mark.parametrize('kind', ['removed', 'changed'])
def test_same_original_bytes_at_another_url_are_not_a_bank_amendment(evidence, kind):
    before, alias, body = alias_evidence(evidence)
    store, observation, key, _, version, *_ = alias
    after = _term(alias) if kind == 'changed' else None
    proof = dict(passed=True, kind=kind, before_revision_id=before, after_revision_id=after)
    if kind == 'removed':
        extraction = store.register_extraction(document_version_id=version,
            extractor_version='technical-completeness', text=body.decode(), observed_at=NOW,
            status='complete', coverage={'technical_control_only': True})
        term = store.db.execute('SELECT * FROM term_revisions WHERE term_revision_id=?', (before,)).fetchone()
        proof.update(full_replacement_validated=True, replacement_document_version_id=version,
            replacement_observation_id=observation, replacement_extraction_id=extraction,
            replacement_applicability=json.loads(term['applicability_json']),
            replacement_parameter_keys=[term['parameter_key']])
    blob = store.put_blob(canonical_json(proof).encode())
    with pytest.raises(ValueError, match='Unchanged source bytes'):
        record_change(store, product_key=key, before_revision_id=before, after_revision_id=after,
                      kind=kind, observed_at=LATER, evidence_sha256=blob)
    assert store.db.execute('SELECT count(*) FROM term_changes').fetchone()[0] == 0


def test_same_bytes_alias_still_allows_reviewed_extraction_correction(evidence):
    before, alias, _ = alias_evidence(evidence)
    store, _, key, *_ = alias
    after = _term(alias)
    proof = dict(passed=True, kind='extraction_corrected',
                 before_revision_id=before, after_revision_id=after)
    blob = store.put_blob(canonical_json(proof).encode())
    identity = record_change(store, product_key=key, before_revision_id=before,
        after_revision_id=after, kind='extraction_corrected', observed_at=LATER,
        evidence_sha256=blob)
    assert store.db.execute('SELECT kind FROM term_changes WHERE term_change_id=?',
                            (identity,)).fetchone()[0] == 'extraction_corrected'
