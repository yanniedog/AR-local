import json
import pytest
from tests.executable_v3_fixture import monetary_protocol
from tests.test_executable_v3_registry import setup,NOW
from cdr_terms.executable_registry import review_subject
from cdr_terms.executable_v3_publication import publish_asset,build_asset
from cdr_terms.identity import canonical_json
from app_payload_executable_v3 import load_published_executable_v3,package_executable_v3


def test_controller_positive_review_publication_and_revocation_boundary(monetary_protocol,monkeypatch):
    """Controller-only integration. Actual benchmark is tested separately; no bank approval."""
    from tests.executable_v3_fixture import reidentify
    from cdr_terms.executable_v3_reviews import material_projection,CHECKS
    from cdr_terms.executable_v3_sources import source_snapshot
    from cdr_terms.identity import digest
    store,subject,observation=monetary_protocol;graph=subject['authorityGraph'];completion=graph['completedPeriod']
    proof=canonical_json(dict(schemaVersion=1,kind='monetary_completed_period_v1',productKey=subject['scope']['productKey'],asOf=completion['asOf'],timezone=completion['timezone'],completedThroughExclusive=completion['completedThroughExclusive'],authorityIds=sorted(a['id'] for a in graph['authorities']),evidenceIds=sorted(completion['evidenceIds']))).encode()
    completion['sourceSnapshotSha256']=store.put_blob(proof)
    graph['members'].append(dict(sha256=completion['sourceSnapshotSha256'],bytes=len(proof),decodedBytes=len(proof),encoding='identity',kind='coverage_proof'))
    reidentify(subject);setup(store,subject)
    calls=[]
    def benchmark_boundary(s,identity,actual):
        calls.append((identity,actual['id']))
        assert identity=='a'*64 and actual==subject
    monkeypatch.setattr('cdr_terms.executable_v3_benchmarks.verify_benchmark',benchmark_boundary)
    evidence=dict(schemaVersion=3,subjectId=subject['id'],capability=subject['capability'],adapterVersion=subject['adapterVersion'],evaluatorVersion=subject['evaluatorVersion'],previousReviewId=None,sourceSnapshotSha256=source_snapshot(store,subject),authorityGraphSha256=graph['identitySha256'],benchmarkResultSha256='a'*64,materialProjection=material_projection(subject),checks=sorted(CHECKS),passed=True)
    sha=store.put_blob(canonical_json(evidence).encode())
    review=review_subject(store,subject['id'],decision='approved',reviewer='independent',reviewer_kind='human',reviewed_at=NOW,evidence_sha256=sha,reason='Technical controller boundary only',expected_previous_review_id=None)
    asset=build_asset(store,subject['scope']['productKey'],routing=subject['routing'])
    assert calls and asset['subjects'][0]['approval']['reviewId']==review
    publication=publish_asset(store,subject['scope']['productKey'],routing=subject['routing'],expected_previous_publication_id=None,expected_observation_id=observation,published_at=NOW)
    assert store.db.execute('SELECT state FROM executable_publications_v3 WHERE publication_id=?',(publication,)).fetchone()[0]=='active'
    negative=store.put_blob(canonical_json(dict(schemaVersion=3,subjectId=subject['id'],decision='revoked',previousReviewId=review,reason='Technical revocation')).encode())
    review_subject(store,subject['id'],decision='revoked',reviewer='independent',reviewer_kind='human',reviewed_at=NOW,evidence_sha256=negative,reason='Technical revocation',expected_previous_review_id=review)
    assert build_asset(store,subject['scope']['productKey'],routing=subject['routing']) is None


def test_unreviewed_candidate_cannot_be_removed(monetary_protocol):
    store,subject,observation=monetary_protocol;setup(store,subject)
    with pytest.raises(ValueError,match='no independent disposition'):
        publish_asset(store,subject['scope']['productKey'],routing=subject['routing'],expected_previous_publication_id=None,expected_observation_id=observation,published_at=NOW)


def test_negative_becomes_internal_null_tombstone_not_public_asset(monetary_protocol):
    store,subject,observation=monetary_protocol;setup(store,subject)
    proof=store.put_blob(canonical_json(dict(schemaVersion=3,subjectId=subject['id'],decision='revoked',previousReviewId=None,reason='Technical revocation')).encode())
    review_subject(store,subject['id'],decision='revoked',reviewer='independent',reviewer_kind='human',reviewed_at=NOW,evidence_sha256=proof,reason='Technical revocation',expected_previous_review_id=None)
    route=subject['routing'];key=subject['scope']['productKey']
    identity=publish_asset(store,key,routing=route,expected_previous_publication_id=None,expected_observation_id=observation,published_at=NOW)
    row=store.db.execute('SELECT * FROM executable_publications_v3 WHERE publication_id=?',(identity,)).fetchone()
    assert row['state']=='removed' and row['payload_json'] is None
    with pytest.raises(ValueError,match='predecessor CAS'):
        publish_asset(store,key,routing=route,expected_previous_publication_id=None,expected_observation_id=observation,published_at=NOW)
    snapshot=load_published_executable_v3(store.root,source_observation={'generation_id':route['sourceGenerationId'],'contract_digest':route['exportContractSha256']},run_date=route['runDate'],core_asset_sha256=route['coreAssetSha256'],details_asset_sha256=route['detailsAssetSha256'],product_keys=[key])
    assert snapshot=={}
    assert package_executable_v3(snapshot,core={},details={},core_asset_sha256=route['coreAssetSha256'],details_asset_sha256=route['detailsAssetSha256'],run_date=route['runDate'],write_asset=lambda *args:pytest.fail('empty route wrote artifact')) is None
