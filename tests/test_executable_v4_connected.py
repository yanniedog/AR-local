"""Private integration mechanics using retained execution; public packaging stays blocked."""
import json
import gzip
import pytest
from tests.executable_v3_fixture import technical_protocol,reidentify
from tests.executable_v4_bridge_fixture import ROOT,retain_benchmark
from cdr_terms.identity import canonical_json,byte_digest
from cdr_terms.executable_registry import migrate_executable_registry,stage_subject,review_subject
from cdr_terms.executable_v4_sources import source_snapshot
from cdr_terms.executable_v4_reviews import CHECKS,material_projection
from cdr_terms.executable_v4_benchmarks import verify_benchmark
from cdr_terms.executable_v4_publication import publish_asset,build_asset
from app_payload_executable_v4 import load_published_executable_v4,package_executable_v4
from app_payload_build import _gzip_bytes

NOW='2026-09-15T07:50:00Z'


@pytest.mark.parametrize('alternate_gzip_header',[False,True])
def test_actual_same_subject_source_benchmark_review_publication_revocation(tmp_path,monkeypatch,alternate_gzip_header):
    bridge=json.loads(gzip.decompress((ROOT/'actual-bridge.json.gz').read_bytes()))
    if alternate_gzip_header:
        import tests.executable_v3_fixture as fixture
        def alternate(value):
            raw=bytearray(_gzip_bytes(value));raw[9]=254  # Different from both Linux and retained Windows.
            return bytes(raw)
        assert byte_digest(alternate(bridge['context']['core']))!=bridge['selection']['subject']['routing']['coreAssetSha256']
        monkeypatch.setattr(fixture,'_gzip_bytes',alternate)
    routing=bridge['selection']['subject']['routing']
    retained={kind:((ROOT/'blobs'/routing[field]).read_bytes(),routing[field]) for kind,field in
        (('core','coreAssetSha256'),('details','detailsAssetSha256'))}
    from cdr_terms.executable_v4_contract import ROOT as CONTRACT_ROOT
    template=json.loads((CONTRACT_ROOT/'drafts/positive-technical-example.json').read_bytes())['subject']
    generator=technical_protocol(tmp_path,template=template,adopted_assets=retained)
    store,subject,observation=next(generator)
    try:
        graph=subject['authorityGraph'];bound=graph['completedPeriod']
        proof=canonical_json(dict(schemaVersion=1,kind='monetary_completed_period_v1',productKey=subject['scope']['productKey'],asOf=bound['asOf'],timezone=bound['timezone'],completedThroughExclusive=bound['completedThroughExclusive'],authorityIds=sorted(a['id'] for a in graph['authorities']),evidenceIds=sorted(bound['evidenceIds']))).encode()
        bound['sourceSnapshotSha256']=store.put_blob(proof)
        graph['members'].append(dict(sha256=bound['sourceSnapshotSha256'],bytes=len(proof),decodedBytes=len(proof),encoding='identity',kind='coverage_proof'))
        reidentify(subject)
        assert subject==bridge['selection']['subject']  # No rewriting of actual execution identities.
        migrate_executable_registry(store,wire_version=3,applied_at=NOW)
        migrate_executable_registry(store,wire_version=4,applied_at=NOW)
        stage_subject(store,subject,interpreter='technical fixture source author',staged_at=NOW)
        source=source_snapshot(store,subject)
        for path in (ROOT/'blobs').iterdir():assert store.put_blob(path.read_bytes())==path.name
        codes=json.loads((ROOT/'code-identities.json').read_bytes());_,run,put=retain_benchmark(store,bridge,codes)
        benchmark=put(run);verify_benchmark(store,benchmark,subject)
        evidence=dict(schemaVersion=4,subjectId=subject['id'],capability=subject['capability'],adapterVersion=subject['adapterVersion'],evaluatorVersion=subject['evaluatorVersion'],previousReviewId=None,sourceSnapshotSha256=source,authorityGraphSha256=graph['identitySha256'],benchmarkResultSha256=benchmark,materialProjection=material_projection(subject),checks=sorted(CHECKS),passed=True)
        review=review_subject(store,subject['id'],decision='approved',reviewer='independent technical fixture reviewer',reviewer_kind='deterministic',reviewed_at=NOW,evidence_sha256=put(evidence),reason='Engineering mechanics only, not bank approval',expected_previous_review_id=None)
        route=subject['routing'];key=subject['scope']['productKey']
        publication=publish_asset(store,key,routing=route,expected_previous_publication_id=None,expected_observation_id=observation,published_at=NOW)
        args=dict(source_observation=dict(generation_id=route['sourceGenerationId'],contract_digest=route['exportContractSha256']),run_date=route['runDate'],core_asset_sha256=route['coreAssetSha256'],details_asset_sha256=route['detailsAssetSha256'],product_keys=[key])
        with pytest.raises(ValueError, match='approved publication freeze'):
            load_published_executable_v4(store.root,**args)
        snapshot={subject['capability']:{key:build_asset(store,key,routing=route)}}
        with pytest.raises(ValueError, match='approved publication freeze'):
            package_executable_v4(snapshot,core=bridge['context']['core'],details=bridge['context']['details'],core_asset_sha256=route['coreAssetSha256'],details_asset_sha256=route['detailsAssetSha256'],run_date=route['runDate'],write_asset=lambda *args:pytest.fail('public asset written'))
        reason='Technical revocation control';proof=put(dict(schemaVersion=4,subjectId=subject['id'],decision='revoked',previousReviewId=review,reason=reason))
        review_subject(store,subject['id'],decision='revoked',reviewer='independent technical fixture reviewer',reviewer_kind='deterministic',reviewed_at=NOW,evidence_sha256=proof,reason=reason,expected_previous_review_id=review)
        assert build_asset(store,key,routing=route) is None
        removed=publish_asset(store,key,routing=route,expected_previous_publication_id=publication,expected_observation_id=observation,published_at=NOW)
        assert tuple(store.db.execute('SELECT state,payload_json FROM executable_publications_v4 WHERE publication_id=?',(removed,)).fetchone())==('removed',None)
        with pytest.raises(ValueError, match='approved publication freeze'):
            load_published_executable_v4(store.root,**args)
    finally:
        generator.close()
