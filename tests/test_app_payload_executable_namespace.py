"""Optional namespace transport controls, never a product publication."""
import copy

import pytest

from app_payload_optional_assets import iter_payload_assets, executable_asset_url
from app_payload_revisions_state import bundle_sha256, canonical, digest


def manifest():
    return {'schema_version':1,'run_date':'2026-01-01','files':{
        key:{'name':key+'.json.gz','bytes':1,'sha256':'a'*64,'url':'https://example.invalid/'+key}
        for key in ('core','details')}}


def namespace():
    return {'schema_version':2,'index':{'name':'executable_v2_index-2026-01-01-'+ 'b'*12 +'.json.gz',
        'bytes':1,'sha256':'b'*64},'shards':{}}


def test_absent_namespace_keeps_exact_legacy_bundle_hash():
    value = manifest()
    old = {k:v for k,v in value.items() if k != 'files'}
    old['files'] = {k:{field:item for field,item in v.items() if field != 'url'} for k,v in value['files'].items()}
    assert bundle_sha256(value) == digest(canonical(old))
    assert list(iter_payload_assets(value)) == list(value['files'].items())


def test_misplaced_v2_refused_even_without_namespace():
    value = manifest()
    value['files']['executable_v2_index'] = namespace()['index']
    with pytest.raises(ValueError, match='outside legacy'):
        list(iter_payload_assets(value))


def test_namespace_binds_bundle_and_immutable_url():
    value = manifest()
    original = bundle_sha256(value)
    value['executable_v2'] = namespace()
    identity = bundle_sha256(value)
    assert identity != original
    value.update(tag='app-payload-2026-01-01-r000001',payload_revision={
        'schema_version':1,'revision':1,'generation_id':'sha256-'+identity,'bundle_sha256':identity,'parent_revision':None})
    assert executable_asset_url(value,value['executable_v2']['index'],repo='owner/repo') == 'https://github.com/owner/repo/releases/download/app-payload-2026-01-01-r000001/'+namespace()['index']['name']
    assert bundle_sha256(value) == identity


@pytest.mark.parametrize('field,value',[('name','../escape.json.gz'),('sha256','c'*64),('url','https://example.invalid/')])
def test_namespace_refuses_unsafe_or_unbound_descriptor(field,value):
    current = manifest()
    current['executable_v2'] = namespace()
    current['executable_v2']['index'][field] = value
    with pytest.raises(Exception):
        list(iter_payload_assets(current))
