import copy,json
import pytest
from pathlib import Path
from app_payload_optional_assets import iter_payload_assets
from app_payload_revisions_state import bundle_sha256
from cdr_terms.executable_v3_migration import ROOT
from tests.executable_v3_bridge_fixture import actual_savings_bridge


def manifest():
    namespace=json.loads((ROOT/'controls/positive-technical-example.json').read_bytes())['namespace']
    return {'schema_version':1,'run_date':'2026-01-12','files':{'core':{'name':'core-original.json.gz','sha256':'b'*64,'bytes':1},'details':{'name':'details-original.json.gz','sha256':'c'*64,'bytes':1}},'executable_v3':namespace}


def test_reserved_routes_accounted_without_fetch():
    value=manifest();entries=dict(iter_payload_assets(value))
    assert len(entries)==4
    assert all('url' not in x for k,x in entries.items() if k not in {'core','details'})
    assert 'executable_v3' not in value['files']
    changed=copy.deepcopy(value);changed['executable_v3']['capabilities']['savings_calculation']['index']['bytes']=2
    assert bundle_sha256(value)!=bundle_sha256(changed)


def test_v3_in_legacy_files_refuses_even_without_namespace():
    value=manifest();value.pop('executable_v3');value['files']['monetary_v3_savings_calculation_index']=value['files']['core']
    with pytest.raises(ValueError,match='outside legacy'):list(iter_payload_assets(value))


def test_actual_asset_packaging_counts_core_details_and_namespace(actual_savings_bridge,monkeypatch):
    import app_payload_executable_v3 as package
    from app_payload_build import _gzip_bytes
    from cdr_terms.identity import byte_digest
    _,subject,_,_,bridge=actual_savings_bridge;source=subject['routing'];written=[]
    snapshot={'savings_calculation':bridge['shard']['products']}
    def write(kind,payload):
        raw=_gzip_bytes(payload);sha=byte_digest(raw);written.append(kind)
        return dict(name=kind+'-'+source['runDate']+'-'+sha[:12]+'.json.gz',sha256=sha,bytes=len(raw))
    args=dict(core=bridge['context']['core'],details=bridge['context']['details'],core_asset_sha256=source['coreAssetSha256'],details_asset_sha256=source['detailsAssetSha256'],run_date=source['runDate'],write_asset=write)
    namespace=package.package_executable_v3(snapshot,**args)
    assert set(namespace['capabilities'])=={'savings_calculation'} and len(written)==2
    base=len(package._json(args['core']))+len(package._json(args['details']))
    asset_bytes=sum(len(package._json(asset)) for asset in snapshot['savings_calculation'].values())
    monkeypatch.setattr(package,'MAX_SNAPSHOT_RAW',base+asset_bytes-1)
    written.clear()
    with pytest.raises(ValueError,match='public snapshot'):package.package_executable_v3(snapshot,**args)
    assert written==[]


def test_public_build_default_off_and_encrypted_refusal(actual_savings_bridge,tmp_path,monkeypatch):
    import app_payload_build as builder
    _,subject,_,_,bridge=actual_savings_bridge
    data=dict(core=bridge['context']['core'],details=bridge['context']['details'],run_date=subject['routing']['runDate'],counts={},search_index=None,history_banks=None,bank_history=None)
    monkeypatch.setattr(builder,'_compute_payload',lambda *a,**k:copy.deepcopy(data))
    monkeypatch.setattr(builder.payload_crypto,'resolve_key_from_env',lambda:None)
    assert 'executable_v3' not in builder.build_payload(tmp_path,tmp_path/'default')
    monkeypatch.setattr(builder.payload_crypto,'resolve_key_from_env',lambda:b'x'*32)
    with pytest.raises(ValueError,match='unencrypted'):builder.build_payload(tmp_path,tmp_path/'encrypted',executable_v3_root=tmp_path/'never-opened')
