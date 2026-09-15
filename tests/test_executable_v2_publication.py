"""Controller composition controls; actual engine benchmark is separately retained."""
import copy

import pytest

from cdr_terms.executable_registry import stage_subject, review_subject
from cdr_terms.executable_v2_contract import CHECKS
from cdr_terms.executable_v2_migration import migrate_registry
from cdr_terms.executable_v2_sources import source_snapshot
from cdr_terms.executable_v2_publication import build_asset, publish_asset
from cdr_terms.identity import canonical_json
from tests.executable_protocol_fixture import protocol, NOW
from tests.test_executable_v2_sources import v2_protocol


def approve_controller_control(store,subject,monkeypatch,previous=None):
    # Isolate controller composition from the independently executed committed
    # app benchmark test. This callback grants no production approval capability.
    import cdr_terms.executable_v2_reviews as reviews
    benchmark=store.put_blob(b'{"purpose":"controller call-binding control only"}')
    def verified(current,identity,value):
        assert identity==benchmark and value==subject
    monkeypatch.setattr(reviews,'verify_benchmark',verified)
    proof=dict(schemaVersion=2,subjectId=subject['id'],capability=subject['capability'],adapterVersion=subject['adapterVersion'],
        evaluatorVersion=subject['evaluatorVersion'],sourceSnapshotSha256=source_snapshot(store,subject),benchmarkResultSha256=benchmark,
        previousReviewId=previous,checks={key:True for key in CHECKS},passed=True)
    return review_subject(store,subject['id'],decision='approved',reviewer='independent',reviewer_kind='human',reviewed_at=NOW,
        evidence_sha256=store.put_blob(canonical_json(proof).encode()),reason='Controller protocol only',expected_previous_review_id=previous)


def test_approval_publication_revocation_and_cas(v2_protocol,monkeypatch):
    store,subject,_,_=v2_protocol
    migrate_registry(store,applied_at=NOW)
    stage_subject(store,subject,interpreter='author',staged_at=NOW)
    args=dict(core_asset_sha256=subject['source']['coreAssetSha256'],details_asset_sha256=subject['source']['detailsAssetSha256'],run_date=subject['source']['runDate'])
    with pytest.raises(ValueError,match='no independent disposition'):
        build_asset(store,subject['scope']['productKey'],**args)
    review=approve_controller_control(store,subject,monkeypatch)
    asset=build_asset(store,subject['scope']['productKey'],**args)
    assert asset['subjects'][0]['approval']['reviewId']==review
    publication=publish_asset(store,asset,expected_previous_publication_id=None,expected_observation_id=subject['source']['observationId'],published_at=NOW)
    proof=dict(schemaVersion=2,subjectId=subject['id'],decision='revoked',previousReviewId=review,reason='Technical removal')
    review_subject(store,subject['id'],decision='revoked',reviewer='independent',reviewer_kind='human',reviewed_at=NOW,
        evidence_sha256=store.put_blob(canonical_json(proof).encode()),reason=proof['reason'],expected_previous_review_id=review)
    with pytest.raises(ValueError,match='source/review changed'):
        publish_asset(store,asset,expected_previous_publication_id=publication,expected_observation_id=subject['source']['observationId'],published_at=NOW)
    removed=build_asset(store,subject['scope']['productKey'],**args)
    assert removed['subjects']==[] and removed['identitySha256']!=asset['identitySha256']
    publish_asset(store,removed,expected_previous_publication_id=publication,expected_observation_id=subject['source']['observationId'],published_at=NOW)
    assert store.db.execute('SELECT COUNT(*) FROM executable_publications_v2').fetchone()[0]==2
