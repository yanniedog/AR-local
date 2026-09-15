"""Reachable late-review regressions using isolated technical protocol evidence."""
import json

import pytest

from cdr_terms.executable_reviews import review_template, source_snapshot
from cdr_terms.executable_sources import finalized_capture, source_operation, validate_row_semantics
from cdr_terms.identity import canonical_json
from tests.executable_protocol_fixture import NOW, protocol, stage_and_proof  # noqa: F401
from tests.test_cdr_executable_templates import approve, build


def test_repeated_negative_disposition_has_new_transition_identity(protocol):
    store, template, *_ = protocol
    proof = stage_and_proof(store, template)
    first = approve(store, template, proof=proof)
    negative = store.put_blob(canonical_json({'templateId': template['id'], 'decision': 'revoked'}).encode())
    def revoke(previous):
        return review_template(store, template['id'], decision='revoked', reviewer='revoker', reviewer_kind='human',
            reviewed_at=NOW, evidence_sha256=negative, reason='Same negative evidence', expected_previous_review_id=previous)
    old_negative = revoke(first)
    second = approve(store, template, proof={**proof, 'previousReviewId': old_negative})
    new_negative = revoke(second)
    assert new_negative != old_negative
    assert build(store, template)['templates'] == []


def test_added_product_evidence_invalidates_existing_snapshot(protocol):
    store, template, *_ = protocol
    before = source_snapshot(store, template)
    # A newly discovered incorporated document changes the complete evidence inventory.
    document = store.register_document('https://example.invalid/new-fee-schedule')
    with store.db:
        store.db.execute('INSERT INTO applicability VALUES (?,?,?,?,?,?)',
            ('new-fee-document', template['sourceObservationId'], document, '/fees', 'incorporated', '{}'))
    assert source_snapshot(store, template) != before


def test_finalized_capture_is_read_once_per_operation(protocol, monkeypatch):
    store, template, *_ = protocol
    reads = []
    original = store.read_blob
    monkeypatch.setattr(store, 'read_blob', lambda identity: (reads.append(identity), original(identity))[1])
    with source_operation(store):
        for _ in range(25):
            finalized_capture(store, template['sourceGenerationId'], template['runDate'])
    assert len(reads) == 2
    finalized_capture(store, template['sourceGenerationId'], template['runDate'])
    assert len(reads) == 4


@pytest.mark.parametrize('bound', ['MAX_CAPTURES', 'MAX_CAPTURE_BYTES'])
def test_finalized_capture_operation_bounds(protocol, monkeypatch, bound):
    store, template, *_ = protocol
    import cdr_terms.executable_sources as sources
    monkeypatch.setattr(sources, bound, 0)
    with source_operation(store), pytest.raises(ValueError, match='capture operation bound'):
        finalized_capture(store, template['sourceGenerationId'], template['runDate'])


@pytest.mark.parametrize('field', ['contract_digest', 'source_generation_digest'])
def test_unrecomputed_contract_digest_is_refused(protocol, monkeypatch, field):
    store, template, *_ = protocol
    capture = store.db.execute('SELECT * FROM ingest_captures').fetchone()
    receipt = json.loads(store.read_blob(capture['receipt_sha256']))
    contract_sha = receipt['source_provenance']['contract_sha256']
    contract = json.loads(store.read_blob(contract_sha))
    if field == 'source_generation_digest':
        contract['artifacts'][0]['sha256'] = 'f' * 64
    else:
        contract['observed_at'] = '2026-01-01T02:00:00Z'
    original = store.read_blob
    monkeypatch.setattr(store, 'read_blob', lambda identity: canonical_json(contract).encode() if identity == contract_sha else original(identity))
    with pytest.raises(ValueError, match='digest mismatch'):
        finalized_capture(store, template['sourceGenerationId'], template['runDate'])


@pytest.mark.parametrize('cadence', ['monthly', 'quarterly', 'annually'])
def test_conflicting_published_interest_cadence_is_refused(protocol, cadence):
    _, template, core, _ = protocol
    row = {**core['sections']['TD']['rates'][0], 'interest_payment': cadence}
    with pytest.raises(ValueError, match='pay at maturity'):
        validate_row_semantics(template, row)
