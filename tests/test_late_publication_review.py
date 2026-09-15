"""Concrete late-review controls; synthetic metadata only, no source replay."""
import json
from pathlib import Path
import pytest
from cdr_terms.executable_registry import stage_subject,review_subject
from cdr_terms.executable_v2_migration import migrate_registry
from cdr_terms.executable_v2_publication import build_asset
from tests.executable_protocol_fixture import protocol,NOW
from tests.test_executable_v2_sources import v2_protocol

@pytest.mark.parametrize('author,reviewer',[('alice','alice '),(' alice ','alice')])
def test_v1_whitespace_does_not_create_independence(protocol,author,reviewer):
    store,template,_,_=protocol
    stage_subject(store,template,interpreter=author,staged_at=NOW)
    with pytest.raises(ValueError,match='separate reviewer'):
        review_subject(store,template['id'],decision='approved',reviewer=reviewer,reviewer_kind='human',reviewed_at=NOW,
            evidence_sha256='0'*64,reason='Technical control',expected_previous_review_id=None)
    assert store.db.execute('SELECT COUNT(*) FROM executable_reviews').fetchone()[0]==0

@pytest.mark.parametrize('actor',[None,' ',42])
def test_v1_blank_or_nonstrings_refuse(protocol,actor):
    store,template,_,_=protocol
    with pytest.raises(ValueError,match='identity required'):
        stage_subject(store,template,interpreter=actor,staged_at=NOW)
    stage_subject(store,template,interpreter='author',staged_at=NOW)
    with pytest.raises(ValueError,match='disposition required'):
        review_subject(store,template['id'],decision='approved',reviewer=actor,reviewer_kind='human',reviewed_at=NOW,
            evidence_sha256='0'*64,reason='Technical control',expected_previous_review_id=None)

@pytest.mark.parametrize('field',['core_asset_sha256','details_asset_sha256','run_date'])
def test_empty_subject_publication_rejects_unbound_assets(v2_protocol,field):
    store,subject,_,_=v2_protocol
    migrate_registry(store,applied_at=NOW)
    stage_subject(store,subject,interpreter='alice',staged_at=NOW)
    args=dict(core_asset_sha256=subject['source']['coreAssetSha256'],details_asset_sha256=subject['source']['detailsAssetSha256'],run_date=subject['source']['runDate'])
    args[field]='2020-01-01' if field=='run_date' else '0'*64
    with pytest.raises(ValueError,match='adopted source'):
        build_asset(store,subject['scope']['productKey'],**args)

@pytest.mark.parametrize('author,reviewer',[('alice','alice '),(' alice ','alice')])
def test_reviewer_whitespace_is_not_independent(v2_protocol,author,reviewer):
    store,subject,_,_=v2_protocol
    migrate_registry(store,applied_at=NOW)
    stage_subject(store,subject,interpreter=author,staged_at=NOW)
    with pytest.raises(ValueError,match='separate reviewer'):
        review_subject(store,subject['id'],decision='approved',reviewer=reviewer,reviewer_kind='human',reviewed_at=NOW,evidence_sha256='0'*64,reason='Technical control',expected_previous_review_id=None)

@pytest.mark.parametrize('namespace',['executable_v2','executable_v3'])
@pytest.mark.parametrize('where',['manifest','core'])
def test_optional_namespace_refuses_encryption_before_yield(namespace,where):
    from app_payload_optional_assets import iter_payload_assets
    manifest={'files':{'core':{'name':'core'}},namespace:{}}
    (manifest if where=='manifest' else manifest['files']['core'])['enc']={'algorithm':'test'}
    with pytest.raises(ValueError,match='unencrypted'):
        next(iter_payload_assets(manifest))

def test_archive_admission_records_observed_projection_without_archive(monkeypatch):
    import cdr_historical_fee_archive_candidate as module
    observed={'app_payload_details.py':'a'*64,'app_payload_common.py':'b'*64}
    monkeypatch.setattr(module,'validate_admission',lambda value:None)
    loaded={'container':{},'inputs':{},'generation':{},'manifest':{'files':{}},'source':{'fees':[]}}
    result=module._admission(loaded,{'fees':[],'products':[],'rates':[]},{},observed)
    assert result['projection_source_sha256_lf']==observed
    assert result['projection_source_sha256_lf']!=module.PROJECTION_SOURCES


@pytest.mark.parametrize('old_observation',[False,True])
def test_removal_without_current_subject_binding_refuses(v2_protocol,old_observation):
    store,subject,_,_=v2_protocol
    migrate_registry(store,applied_at=NOW)
    if old_observation:
        stage_subject(store,subject,interpreter='author',staged_at=NOW)
        from cdr_terms.identity import canonical_json
        record={'data':{'name':'New engineering observation','brand':'Protocol only','productId':'protocol'}}
        raw=canonical_json(record).encode()
        store.observe(provider='Protocol only',product_key=subject['scope']['productKey'],record=record,source_bytes=raw,
            observed_at='2026-09-16T00:00:00Z',ingest_id='technical-later-observation')
    with pytest.raises(ValueError,match='retained current source binding'):
        build_asset(store,subject['scope']['productKey'],core_asset_sha256=subject['source']['coreAssetSha256'],
            details_asset_sha256=subject['source']['detailsAssetSha256'],run_date=subject['source']['runDate'])
