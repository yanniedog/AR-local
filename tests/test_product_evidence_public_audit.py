"""Offline store transport controls, with retained public rates and CDR bodies."""
from copy import deepcopy
import gzip
import json

import pytest

from app_payload_common import DEFAULT_TAG
from app_payload_publication_assets import complete_assets
from app_payload_revisions_state import RevisionError
from app_payload_product_evidence_contract import canonical
from cdr_quality_accounting import audit_rows
from cdr_quality_public import audit_public
from tests.test_app_payload_complete_publication import payload, Store, publish
from tests.test_cdr_quality_pipeline import source_rows


def current_source(root,manifest):
    core=json.loads(gzip.decompress((root/manifest['files']['core']['name']).read_bytes()))
    current=audit_rows([],source_rows(core))
    current.update(run_date=manifest['run_date'],contract_digest=manifest['source_observation']['contract_digest'])
    return current


def test_public_audit_resolves_all_assets_and_encrypted_selected_roots(payload,tmp_path):
    root,manifest=payload;store=Store();published=publish(root,store,tmp_path/'state')
    current=current_source(root,manifest);expected=dict(complete_assets(manifest,root=root))
    store.reads.clear();result=audit_public(current,store=store)
    assert result['status'] in {'PASS','FAIL'}  # Existing financial findings remain independent.
    assert result['assets_verified']=={key:{k:row[k] for k in ('sha256','bytes')} for key,row in expected.items()}
    value=result['optional_product_evidence']
    assert value['status']=='PASS' and value['scope']=='public_selected'
    assert value['selected_head_verified'] and value['public_transport_verified']
    assert value['namespace_validation_complete'] and not value['population_completeness_verified']
    assert (DEFAULT_TAG,'dates-index.json',True) in store.reads
    assert (published.manifest['tag'],'manifest.json',True) in store.reads
    assert {row['name'] for row in expected.values()} <= {name for tag,name,enc in store.reads if enc}


@pytest.mark.parametrize('fault',['missing','corrupt','index-drift','manifest-drift','head-identity'])
def test_public_optional_audit_never_returns_partial_success(payload,tmp_path,monkeypatch,fault):
    root,manifest=payload;store=Store();published=publish(root,store,tmp_path/'state')
    if fault in {'missing','corrupt'}:
        entry=next(row for key,row in complete_assets(manifest,root=root) if key.endswith('_asset_001'))
        key=(published.manifest['tag'],entry['name'])
        if fault=='missing':del store.objects[key]
        else:store.objects[key]=b'corrupt'
    elif fault=='head-identity':
        index=json.loads(store.objects[(DEFAULT_TAG,'dates-index.json')]);head=index['revision_heads'][manifest['run_date']]
        changed_tag=published.manifest['tag'][:-6]+'000002'
        head['revision']=2;head['manifest_url']=store.url(changed_tag,'manifest.json')
        store.objects[(changed_tag,'manifest.json')]=store.objects[(published.manifest['tag'],'manifest.json')]
        store.objects[(DEFAULT_TAG,'dates-index.json')]=canonical(index)
    else:
        original=store.read
        def changed(tag,name,*args,**kwargs):
            raw=original(tag,name,*args,**kwargs)
            match=name==('dates-index.json' if fault=='index-drift' else 'manifest.json')
            if match and kwargs.get('require_encrypted'):return raw+b' '
            return raw
        monkeypatch.setattr(store,'read',changed)
    with pytest.raises((ValueError,OSError,TypeError,RevisionError)):
        audit_public(current_source(root,manifest),store=store)
