import copy,json,gzip
import pytest
from tests.executable_v3_fixture import monetary_protocol,reidentify
from cdr_terms.executable_registry import migrate_executable_registry,stage_subject,review_subject,lookup_subject
from cdr_terms.executable_v3_reviews import current_approval,validate_completion_proof
from cdr_terms.identity import canonical_json
from cdr_terms.executable_v3_evidence import EvidenceOperation
from cdr_terms.executable_v3_sources import _json
NOW='2026-01-12T02:00:00Z'


def setup(store,subject):
    migrate_executable_registry(store,wire_version=3,applied_at=NOW)
    stage_subject(store,subject,interpreter='technical-author',staged_at=NOW)


def test_shared_dispatch_and_same_scope_predecessor(monetary_protocol):
    store,subject,_=monetary_protocol;setup(store,subject)
    assert lookup_subject(store,subject['id'])==subject
    changed=copy.deepcopy(subject);changed['policy']['inputDefinitions'][0]['label']='Changed technical prompt';reidentify(changed)
    with pytest.raises(ValueError,match='CAS'):stage_subject(store,changed,interpreter='author',staged_at=NOW)
    stage_subject(store,changed,interpreter='author',staged_at=NOW,expected_previous_subject_id=subject['id'])


def test_negative_review_preserves_stale_source_and_cas(monetary_protocol):
    store,subject,_=monetary_protocol;setup(store,subject)
    proof=store.put_blob(canonical_json(dict(schemaVersion=3,subjectId=subject['id'],decision='revoked',previousReviewId=None,reason='Technical revocation')).encode())
    args=dict(decision='revoked',reviewer='independent',reviewer_kind='human',reviewed_at=NOW,evidence_sha256=proof,reason='Technical revocation',expected_previous_review_id=None)
    review_subject(store,subject['id'],**args)
    assert current_approval(store,subject) is None
    with pytest.raises(ValueError,match='CAS'):review_subject(store,subject['id'],**args)


def test_arbitrary_original_blob_is_not_completion_authority(monetary_protocol):
    store,subject,_=monetary_protocol
    with pytest.raises(ValueError,match='completed-period proof'):validate_completion_proof(store,subject)


def test_member_decode_is_reused_at_operation_boundary(monetary_protocol):
    store,_,_=monetary_protocol;operation=EvidenceOperation(store)
    body=json.dumps({'technical':'x'*1000}).encode();raw=gzip.compress(body,mtime=0);sha=store.put_blob(raw)
    descriptor=dict(sha256=sha,bytes=len(raw),decodedBytes=len(body),encoding='gzip',kind='core')
    operation.decoded_bytes=24*1024*1024-len(body)
    operation.member(descriptor)
    assert _json(operation,sha,True)==json.loads(body)
    assert operation.decoded_bytes==24*1024*1024
    with pytest.raises(ValueError,match='encoding differs'):_json(operation,sha,False)


def test_adopted_assets_have_separate_aggregate_budget(monetary_protocol):
    store,_,_=monetary_protocol;operation=EvidenceOperation(store)
    body=json.dumps({'technical':'x'*(2*1024*1024)}).encode()
    sha=store.put_blob(gzip.compress(body,mtime=0))
    operation.decoded_bytes=24*1024*1024
    assert operation.adopted_json(sha)['technical'].startswith('x')
    assert operation.decoded_bytes==24*1024*1024
    assert operation.adopted_decoded_bytes==len(body)
    assert operation.adopted_json(sha)['technical'].startswith('x')
    assert operation.adopted_decoded_bytes==len(body)
    other=store.put_blob(gzip.compress(b'{"other":true}',mtime=0))
    operation.adopted_decoded_bytes=24*1024*1024-1
    with pytest.raises(ValueError,match='expanded snapshot'):operation.adopted_json(other)
    assert other not in operation.adopted
