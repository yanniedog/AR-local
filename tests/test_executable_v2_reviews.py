"""Independent disposition and stale-source revocation protocol controls."""
import pytest

from cdr_terms.executable_registry import stage_subject, review_subject
from cdr_terms.executable_v2_migration import migrate_registry
from cdr_terms.executable_v2_reviews import current_approval
from cdr_terms.identity import canonical_json
from tests.executable_protocol_fixture import protocol, NOW
from tests.test_executable_v2_sources import v2_protocol


def staged(v2_protocol):
    store, subject, _, _ = v2_protocol
    migrate_registry(store,applied_at=NOW)
    stage_subject(store,subject,interpreter='author',staged_at=NOW)
    return store,subject


def negative(store,subject,previous=None):
    return store.put_blob(canonical_json(dict(schemaVersion=2,subjectId=subject['id'],decision='revoked',previousReviewId=previous,reason='Technical revocation')).encode())


def test_negative_review_remains_available_after_source_changes(v2_protocol):
    store,subject = staged(v2_protocol)
    raw=canonical_json({'data':{'name':'New technical observation'}}).encode()
    store.observe(provider='Protocol only',product_key=subject['scope']['productKey'],record={'data':{'name':'New technical observation'}},
        source_bytes=raw,observed_at='2026-01-02T01:00:00Z',ingest_id='new-technical-generation')
    proof=negative(store,subject)
    review_subject(store,subject['id'],decision='revoked',reviewer='independent',reviewer_kind='human',reviewed_at='2026-01-02T02:00:00Z',
        evidence_sha256=proof,reason='Technical revocation',expected_previous_review_id=None)
    assert current_approval(store,subject) is None


@pytest.mark.parametrize('reviewer,kind',[('author','human'),('independent','model')])
def test_self_or_model_review_refused(v2_protocol,reviewer,kind):
    store,subject=staged(v2_protocol)
    with pytest.raises(ValueError):
        review_subject(store,subject['id'],decision='revoked',reviewer=reviewer,reviewer_kind=kind,reviewed_at=NOW,
            evidence_sha256=negative(store,subject),reason='Technical revocation',expected_previous_review_id=None)


def test_review_predecessor_blocks_late_disposition(v2_protocol):
    store,subject=staged(v2_protocol)
    args=dict(decision='revoked',reviewer='independent',reviewer_kind='human',reviewed_at=NOW,
        evidence_sha256=negative(store,subject),reason='Technical revocation',expected_previous_review_id=None)
    review_subject(store,subject['id'],**args)
    args['reviewer']='late-independent'
    with pytest.raises(ValueError,match='CAS changed'):
        review_subject(store,subject['id'],**args)
