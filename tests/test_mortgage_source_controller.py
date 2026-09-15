"""Actual isolated evidence store mechanics using declared engineering policy."""
import copy,json
from pathlib import Path
import pytest
from cdr_terms.identity import canonical_json
from cdr_terms.executable_registry import migrate_executable_registry,stage_subject,lookup_subject,review_subject
from cdr_terms.executable_v3_sources import source_snapshot
from cdr_terms.executable_v3_publication import publish_asset,build_asset
from tests.executable_v3_fixture import technical_protocol,reidentify

NOW='2026-09-15T10:00:00Z'


@pytest.fixture
def mortgage_protocol(tmp_path):
    yield from build_mortgage_protocol(tmp_path)


def build_mortgage_protocol(tmp_path,adopted_assets=None):
    subject=json.loads((Path(__file__).parent/'fixtures/mortgage-v3/subject.json').read_bytes())
    from cdr_terms.mortgage_material_fields import GROUPS,project_field
    declaration='ENGINEERING TEST SPECIFICATION ONLY. '+canonical_json({field:project_field(subject,field) for field in GROUPS}).replace('"',"'")
    generator=technical_protocol(tmp_path,template=subject,source_description=declaration,adopted_assets=adopted_assets)
    store,value,observation=next(generator)
    try:
        graph=value['authorityGraph'];bound=graph['completedPeriod']
        proof=canonical_json(dict(schemaVersion=1,kind='monetary_completed_period_v1',productKey=value['scope']['productKey'],asOf=bound['asOf'],timezone=bound['timezone'],completedThroughExclusive=bound['completedThroughExclusive'],authorityIds=sorted(a['id'] for a in graph['authorities']),evidenceIds=sorted(bound['evidenceIds']))).encode()
        bound['sourceSnapshotSha256']=store.put_blob(proof)
        graph['members'].append(dict(sha256=bound['sourceSnapshotSha256'],bytes=len(proof),decodedBytes=len(proof),encoding='identity',kind='coverage_proof'))
        yield store,reidentify(value),observation
    finally:generator.close()


def test_actual_mortgage_store_stage_and_negative_removal(mortgage_protocol):
    store,subject,observation=mortgage_protocol
    source_snapshot(store,subject)
    migrate_executable_registry(store,wire_version=3,applied_at=NOW)
    stage_subject(store,subject,interpreter='engineering author',staged_at=NOW)
    assert lookup_subject(store,subject['id'])==subject
    reason='Technical independent rejection, no bank approval'
    proof=store.put_blob(canonical_json(dict(schemaVersion=3,subjectId=subject['id'],decision='rejected',previousReviewId=None,reason=reason)).encode())
    review_subject(store,subject['id'],decision='rejected',reviewer='engineering reviewer',reviewer_kind='human',reviewed_at=NOW,evidence_sha256=proof,reason=reason,expected_previous_review_id=None)
    key=subject['scope']['productKey'];capability='mortgage_calculation'
    assert build_asset(store,key,routing=subject['routing'],capability=capability) is None
    publication=publish_asset(store,key,routing=subject['routing'],capability=capability,expected_previous_publication_id=None,expected_observation_id=observation,published_at=NOW)
    row=store.db.execute('SELECT capability,state,payload_json FROM executable_publications_v3 WHERE publication_id=?',(publication,)).fetchone()
    assert tuple(row)==(capability,'removed',None)


@pytest.mark.parametrize('field',['annualRate','paymentRounding','openingState','eligibility'])
def test_mortgage_material_tampering_refuses(mortgage_protocol,field):
    store,subject,_=mortgage_protocol;changed=copy.deepcopy(subject)
    if field=='annualRate':changed['policy'][field]='0.04'
    elif field=='paymentRounding':changed['policy'][field]='half_even'
    elif field=='openingState':changed['policy']['inputDefinitions'][0]['label']='Changed reviewed prompt'
    else:changed['policy']['eligibility']['expected']['value']=False
    reidentify(changed)
    with pytest.raises(ValueError,match='structured material'):source_snapshot(store,changed)
