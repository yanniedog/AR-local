"""Real captured facts/bodies; technical manifest source controls, no publication."""
from copy import deepcopy
import gzip
import pytest

from app_payload_optional_assets import iter_payload_assets
from app_payload_product_evidence_contract import canonical, digest
from app_payload_product_evidence_reference import LANES, SOURCE_FIELDS
from app_payload_product_evidence_publication_inventory import resolve_publication_inventory, verify_local_publication_inventory
from cdr_product_evidence_delivery_policy import STATUS
from tests.test_app_payload_product_evidence_reference import prepared


def ready(manifest):
    value=deepcopy(manifest)
    value[STATUS]=dict(schema='ar-product-evidence-status-v1',
        source={k:value['source_observation'][k] for k in SOURCE_FIELDS},
        lanes={lane:dict(state='available',reason='verified') for lane in LANES})
    return value


def test_complete_resolution_and_local_readback_include_every_transitive_asset(prepared):
    root,manifest,capabilities=prepared;manifest=ready(manifest);raw=canonical(manifest)
    (root/'manifest.json').write_bytes(raw);before={p.name:p.read_bytes() for p in root.iterdir()};reads=[]
    def reader(entry):
        reads.append(entry['name']);return (root/entry['name']).read_bytes()
    frozen=resolve_publication_inventory(raw,digest(raw),reader);value=frozen.document()
    assert len(reads)==2 and all('-capability-' in name for name in reads)
    assert set(before)=={'manifest.json',*(entry['name'] for entry in value['inventory'].values())}
    assert value['asset_bytes_verified'] is False and value['publication_authorized'] is False
    verified=verify_local_publication_inventory(root,expected_manifest_sha256=digest(raw))
    assert verified['asset_bytes_verified'] and verified['inventory'].raw==frozen.raw
    assert verified['selection_verified'] is False
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before
    value['inventory'].clear();assert frozen.document()['inventory']


def test_legacy_inventory_identity_and_callback_nonuse_are_unchanged(prepared):
    _,manifest,_=prepared;base={k:v for k,v in manifest.items() if k not in LANES};base.pop('source_observation')
    raw=canonical(base)
    result=resolve_publication_inventory(raw,digest(raw),lambda *a:pytest.fail('legacy fetched capability')).document()
    assert result['inventory']==dict(iter_payload_assets(base))
    assert canonical(base)==raw
    from app_payload_revisions_state import bundle_sha256
    assert result['bundle_sha256']==bundle_sha256(base)


def test_full_bundle_keeps_exact_original_identity_with_explicit_structural_admission(prepared):
    from app_payload_revisions_state import bundle_sha256
    from app_payload_product_evidence_reference import bound_bundle_sha256
    _,manifest,_=prepared;value=ready(manifest)
    value.update(generated_at='irrelevant',tag='irrelevant',payload_revision={'revision':1})
    value['files']['core']['url']='https://example.invalid/alias'
    expected={k:v for k,v in value.items() if k not in {'generated_at','tag','payload_revision','files'}}
    expected['files']={k:{name:field for name,field in entry.items() if name!='url'} for k,entry in value['files'].items()}
    assert bound_bundle_sha256(value)==digest(canonical(expected))
    assert bound_bundle_sha256(value)!=bound_bundle_sha256({k:v for k,v in value.items() if k not in (*LANES,STATUS)})
    assert bundle_sha256(value)==bound_bundle_sha256(value)


@pytest.mark.parametrize('ready_lane',[None,'product_evidence_v1'])
def test_pending_lanes_never_acquire_or_advertise_newly_present_packages(prepared,ready_lane):
    root,manifest,_=prepared;value=ready(manifest);reads=[]
    for lane in LANES:
        if lane != ready_lane:
            value.pop(lane);value[STATUS]['lanes'][lane]=dict(state='pending',reason='not_prepared')
    raw=canonical(value)
    def reader(entry):
        reads.append(entry['name']);return (root/entry['name']).read_bytes()
    result=resolve_publication_inventory(raw,digest(raw),reader).document()
    assert len(reads)==(1 if ready_lane else 0)
    assert not any(key.startswith('product_response_evidence_') for key in result['inventory'])
    if ready_lane is None:assert set(result['inventory'])==set(value['files'])
    assert result['asset_bytes_verified'] is False and result['publication_authorized'] is False


@pytest.mark.parametrize('fault',['missing-status','contradiction','future','source','pin','deep','oversize'])
def test_manifest_ready_contract_rejects_before_capability_io(prepared,fault):
    _,manifest,_=prepared;value=ready(manifest)
    if fault=='missing-status':value.pop(STATUS)
    elif fault=='contradiction':value[STATUS]['lanes']['product_evidence_v1']=dict(state='pending',reason='not_prepared')
    elif fault=='future':value['product_evidence_v2']=value.pop('product_evidence_v1')
    elif fault=='source':value[STATUS]['source']['contract_digest']='0'*64
    raw=canonical(value)
    if fault=='deep':raw=b'['*2000+b'0'+b']'*2000
    elif fault=='oversize':raw=b' '*65537
    with pytest.raises(ValueError):
        resolve_publication_inventory(raw,'0'*64 if fault=='pin' else digest(raw),lambda *a:pytest.fail('bad manifest reached IO'))


@pytest.mark.parametrize('fault',['missing-capability','corrupt-capability','missing-index','missing-shard','changed-shard','extra'])
def test_complete_readback_cannot_silently_omit_transitive_failures(prepared,fault):
    root,manifest,caps=prepared;value=ready(manifest);raw=canonical(value);(root/'manifest.json').write_bytes(raw)
    cap=value['product_evidence_v1']['capability'];fact=caps['product_evidence_v1']
    if fault=='extra':(root/'unbound.json').write_bytes(b'{}')
    else:
        name=cap['name'] if 'capability' in fault else fact['index']['name'] if 'index' in fault else fact['shards'][0]['name']
        path=root/name
        if fault.startswith('missing'):path.unlink()
        else:path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises((ValueError,FileNotFoundError)):
        verify_local_publication_inventory(root,expected_manifest_sha256=digest(raw))


def test_capability_uses_original_gzip_encoding_and_callback_gets_copy(prepared):
    root,manifest,_=prepared;value=ready(manifest);lane='product_evidence_v1'
    descriptor=value[lane]['capability'];original=(root/descriptor['name']).read_bytes()
    alternative=gzip.compress(gzip.decompress(original),mtime=123)
    assert alternative!=original
    checksum=digest(alternative)
    value[lane]['capability']={**descriptor,'sha256':checksum,'name':f'product-evidence-capability-{checksum}.json.gz','bytes':len(alternative)}
    raw=canonical(value)
    def reader(entry):
        data=alternative if entry['sha256']==checksum else (root/entry['name']).read_bytes()
        entry['sha256']='0'*64  # Mutable reader arguments cannot rewrite frozen intent.
        return data
    result=resolve_publication_inventory(raw,digest(raw),reader).document()
    assert result['inventory'][lane+'_capability']['sha256']==checksum


@pytest.mark.parametrize('kind',['ready','pending','future'])
def test_unadapted_iterators_fail_before_yielding_partial_inventory(prepared,kind):
    _,manifest,_=prepared;value=ready(manifest)
    if kind=='pending':
        for lane in LANES:
            value.pop(lane);value[STATUS]['lanes'][lane]=dict(state='pending',reason='not_prepared')
    elif kind=='future':value['product_evidence_v2']=value.pop('product_evidence_v1')
    iterator=iter_payload_assets(value)
    with pytest.raises(ValueError,match='complete publication inventory'):next(iterator)
