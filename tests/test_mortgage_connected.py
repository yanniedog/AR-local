"""No-stub connected technical controller cycle using retained actual app execution."""
import json
import pytest
from tests.executable_v3_fixture import technical_protocol,reidentify
from tests.executable_v3_bridge_fixture import retain_benchmark
from pathlib import Path
from tests.test_mortgage_source_controller import build_mortgage_protocol
ROOT=Path(__file__).parent/'fixtures/mortgage-v3'
from cdr_terms.identity import canonical_json,byte_digest
from cdr_terms.executable_registry import migrate_executable_registry,stage_subject,review_subject
from cdr_terms.executable_v3_sources import source_snapshot
from cdr_terms.executable_v3_reviews import CHECKS,material_projection
from cdr_terms.executable_v3_benchmarks import verify_benchmark
from cdr_terms.executable_v3_publication import publish_asset,build_asset
from app_payload_executable_v3 import load_published_executable_v3,package_executable_v3
from app_payload_build import _gzip_bytes

NOW='2026-09-15T11:00:00Z'


@pytest.mark.parametrize('alternate_gzip_header',[False,True])
def test_actual_same_subject_source_benchmark_review_publication_revocation(tmp_path,monkeypatch,alternate_gzip_header):
    bridge=json.loads((ROOT/'actual-bridge.json').read_bytes())
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
    generator=build_mortgage_protocol(tmp_path,adopted_assets=retained)
    store,subject,observation=next(generator)
    try:
        graph=subject['authorityGraph']
        assert subject==bridge['selection']['subject']  # No rewriting of actual execution identities.
        migrate_executable_registry(store,wire_version=3,applied_at=NOW)
        stage_subject(store,subject,interpreter='technical fixture source author',staged_at=NOW)
        source=source_snapshot(store,subject)
        for path in (ROOT/'blobs').iterdir():assert store.put_blob(path.read_bytes())==path.name
        codes=json.loads((ROOT/'code-identities.json').read_bytes());_,run,put=retain_benchmark(store,bridge,codes)
        benchmark=put(run);verify_benchmark(store,benchmark,subject)
        evidence=dict(schemaVersion=3,subjectId=subject['id'],capability=subject['capability'],adapterVersion=subject['adapterVersion'],evaluatorVersion=subject['evaluatorVersion'],previousReviewId=None,sourceSnapshotSha256=source,authorityGraphSha256=graph['identitySha256'],benchmarkResultSha256=benchmark,materialProjection=material_projection(subject),checks=sorted(CHECKS),passed=True)
        review=review_subject(store,subject['id'],decision='approved',reviewer='independent technical fixture reviewer',reviewer_kind='deterministic',reviewed_at=NOW,evidence_sha256=put(evidence),reason='Engineering mechanics only, not bank approval',expected_previous_review_id=None)
        route=subject['routing'];key=subject['scope']['productKey']
        publication=publish_asset(store,key,routing=route,capability='mortgage_calculation',expected_previous_publication_id=None,expected_observation_id=observation,published_at=NOW)
        args=dict(source_observation=dict(generation_id=route['sourceGenerationId'],contract_digest=route['exportContractSha256']),run_date=route['runDate'],core_asset_sha256=route['coreAssetSha256'],details_asset_sha256=route['detailsAssetSha256'],product_keys=[key])
        snapshot=load_published_executable_v3(store.root,**args);written=[]
        def write(kind,value):
            raw=_gzip_bytes(value);sha=byte_digest(raw);name=kind+'-'+route['runDate']+'-'+sha[:12]+'.json.gz'
            destination=tmp_path/name;destination.write_bytes(raw);written.append(destination)
            assert byte_digest(destination.read_bytes())==sha
            import gzip
            assert json.loads(gzip.decompress(destination.read_bytes()))==value
            return dict(name=name,sha256=sha,bytes=destination.stat().st_size)
        namespace=package_executable_v3(snapshot,core=bridge['context']['core'],details=bridge['context']['details'],core_asset_sha256=route['coreAssetSha256'],details_asset_sha256=route['detailsAssetSha256'],run_date=route['runDate'],write_asset=write)
        assert namespace and len(written)==2
        assert set(namespace['capabilities'])=={'mortgage_calculation'}
        reason='Technical revocation control';proof=put(dict(schemaVersion=3,subjectId=subject['id'],decision='revoked',previousReviewId=review,reason=reason))
        review_subject(store,subject['id'],decision='revoked',reviewer='independent technical fixture reviewer',reviewer_kind='deterministic',reviewed_at=NOW,evidence_sha256=proof,reason=reason,expected_previous_review_id=review)
        assert build_asset(store,key,routing=route,capability='mortgage_calculation') is None
        removed=publish_asset(store,key,routing=route,capability='mortgage_calculation',expected_previous_publication_id=publication,expected_observation_id=observation,published_at=NOW)
        assert tuple(store.db.execute('SELECT state,payload_json FROM executable_publications_v3 WHERE publication_id=?',(removed,)).fetchone())==('removed',None)
        assert load_published_executable_v3(store.root,**args)=={}
    finally:
        generator.close()
