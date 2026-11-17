"""Captured product bodies/facts; offline audit metadata is a technical control."""
import json

import pytest

from app_payload_product_evidence_contract import canonical, digest
from app_payload_product_evidence_reference import LANES
from cdr_product_evidence_acceptance import receipt, verified_inventory, validate_private_app_receipt
from cdr_product_evidence_delivery_policy import STATUS
from pi_cdr_quality_activate_checks import app_checks
from tests.test_app_payload_product_evidence_reference import prepared
from tests.test_app_payload_product_evidence_publication_inventory import ready
from tests.test_cdr_quality_activate import app_proof, save


def audit_candidate(prepared, tmp_path):
    root, manifest, _ = prepared; manifest = ready(manifest)
    raw = canonical(manifest); (root/'manifest.json').write_bytes(raw)
    assets, proof = verified_inventory(root,manifest,digest(raw))
    operation = tmp_path/'audit'; operation.mkdir()
    candidate = save(root/'manifest.json',manifest)
    # save uses a different JSON encoding; bind the exact resulting bytes.
    checksum = candidate['sha256']
    app_proof(operation,manifest,candidate)
    app = json.loads((operation/'app.json').read_bytes())
    audit = json.loads((operation/'headless_audit.json').read_bytes())
    audit['assets'] = {key:dict(status='PASS',sha256=row['sha256'],bytes=row['bytes']) for key,row in assets.items()}
    audit['optional_product_evidence'] = receipt(manifest,checksum,assets,scope='private_candidate')
    app['headless_audit'] = dict(result='PASS',**save(operation/'headless_audit.json',audit))
    return app, dict(candidate_manifest=candidate,run_date=manifest['run_date']), audit, assets, proof


def test_actual_complete_private_candidate_cross_checks_app_receipt(prepared,tmp_path):
    app,canary,audit,assets,proof = audit_candidate(prepared,tmp_path)
    assert len(assets) > 6 and proof['namespaces']
    app_checks(app,canary)
    assert all(row['verified_asset_count'] > 2 for row in audit['optional_product_evidence']['lanes'].values())
    assert audit['optional_product_evidence']['original_wire_bytes_verified'] is False


@pytest.mark.parametrize('fault',['missing-receipt','unsupported','count','authority','manifest','missing-asset','asset-hash','extra'])
def test_private_audit_cannot_claim_financial_only_or_other_optional_authority(prepared,tmp_path,fault):
    app,canary,audit,assets,_ = audit_candidate(prepared,tmp_path)
    value = audit['optional_product_evidence']
    if fault=='missing-receipt': audit.pop('optional_product_evidence')
    elif fault=='unsupported': value['status']='UNSUPPORTED'
    elif fault=='count': value['lanes'][next(iter(LANES))]['verified_asset_count']-=1
    elif fault=='authority': value['selected_head_verified']=True
    elif fault=='manifest': value['manifest_sha256']='0'*64
    elif fault=='missing-asset': audit['assets'].pop(next(k for k in assets if k.endswith('_asset_001')))
    elif fault=='asset-hash': audit['assets'][next(k for k in assets if k.endswith('_asset_001'))]['sha256']='0'*64
    else: value['complete_population']=True
    path=tmp_path/'audit/headless_audit.json'
    app['headless_audit']=dict(result='PASS',**save(path,audit))
    with pytest.raises(ValueError): app_checks(app,canary)


@pytest.mark.parametrize('part',['capability','index','shard'])
@pytest.mark.parametrize('fault',['missing','corrupt'])
def test_even_app_pass_cannot_hide_missing_or_changed_local_transitive_bytes(prepared,tmp_path,part,fault):
    app,canary,*_=audit_candidate(prepared,tmp_path)
    root,manifest,caps=prepared; lane=next(iter(LANES))
    entry=manifest[lane]['capability'] if part=='capability' else caps[lane]['index'] if part=='index' else caps[lane]['shards'][0]
    path=root/entry['name']
    if fault=='missing':path.unlink()
    else:path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises((ValueError,OSError)):app_checks(app,canary)


def test_known_pending_status_is_complete_metadata_without_lazy_assets(prepared):
    root,manifest,_=prepared;manifest=ready(manifest)
    keep={row['name'] for row in manifest['files'].values()}|{'manifest.json'}
    for path in root.iterdir():
        if path.name not in keep:path.unlink()
    for lane in LANES:
        manifest.pop(lane);manifest[STATUS]['lanes'][lane]=dict(state='pending',reason='not_prepared')
    raw=canonical(manifest);(root/'manifest.json').write_bytes(raw)
    assets,proof=verified_inventory(root,manifest,digest(raw))
    value=receipt(manifest,digest(raw),assets,scope='private_candidate')
    validate_private_app_receipt(value,manifest,digest(raw),assets)
    assert proof and set(assets)==set(manifest['files'])
    assert all(row==dict(state='pending',reason='not_prepared',verified_asset_count=0) for row in value['lanes'].values())


@pytest.mark.parametrize('module',['cdr_product_report','cdr_report_parts_io'])
def test_legacy_report_refuses_to_call_optional_financial_subset_complete(prepared,module):
    import importlib
    root,manifest,_=prepared;manifest=ready(manifest);(root/'manifest.json').write_bytes(canonical(manifest))
    with pytest.raises(ValueError,match='optional_product_evidence_unsupported_by_legacy_report'):
        importlib.import_module(module).read_bundle(root)


def test_financial_only_app_proof_keeps_existing_contract(prepared,tmp_path):
    root,manifest,_=prepared
    for lane in LANES:manifest.pop(lane)
    operation=tmp_path/'legacy-audit';operation.mkdir()
    candidate=save(root/'manifest.json',manifest)
    app_proof(operation,manifest,candidate)
    app_checks(json.loads((operation/'app.json').read_bytes()),
               dict(candidate_manifest=candidate,run_date=manifest['run_date']))


def test_unadapted_public_binders_keep_failure_even_when_financial_rows_are_returned(prepared):
    import pi_canary_gate_bind_ops  # Initialize the existing public binder through its owning entry point.
    from pi_canary_gate_bind_checks import validate_v1_payload_root
    from pi_canary_gate_bind_public import _public_asset_entries
    root,manifest,_=prepared;manifest=ready(manifest)
    assert validate_v1_payload_root(manifest,{p.name:p.read_bytes() for p in root.iterdir()})
    entries,findings=_public_asset_entries(manifest)
    assert findings and set(dict(entries))==set(manifest['files'])
