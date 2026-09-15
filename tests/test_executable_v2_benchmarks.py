"""Final actual adapter + exact source/asset bytes, engineering acceptance only."""
from cdr_terms.store import EvidenceStore
from cdr_terms.executable_v2_benchmarks import verify_benchmark
from tests.executable_v2_benchmark_fixture import retained_benchmark
import copy
import json
import pytest
from app_payload_build import _gzip_bytes
from app_payload_revisions_state import bundle_sha256
from cdr_terms.executable_v2_benchmarks import _context
from cdr_terms.identity import digest


@pytest.mark.parametrize("revision", ["966be80", "9c6090a"])
def test_actual_committed_adapter_and_independent_expectations(tmp_path, revision):
    with EvidenceStore(tmp_path/'technical') as store:
        identity,subject,_=retained_benchmark(store, revision)
        verify_benchmark(store,identity,subject)


def test_rehashed_extra_shard_member_without_index_association_refused(tmp_path):
    with EvidenceStore(tmp_path/'technical') as store:
        _,subject,bridge=retained_benchmark(store)
        context={k:copy.deepcopy(bridge[k]) for k in ('index','shard','selection')}
        context['manifest']=copy.deepcopy(bridge['context']['manifest'])
        member=copy.deepcopy(context['shard']['products'][subject['scope']['productKey']])
        member.update(productKey='unmapped-technical-product',subjects=[])
        member['identitySha256']=digest({k:v for k,v in member.items() if k!='identitySha256'})
        context['shard']['products'][member['productKey']]=member
        body=_gzip_bytes(context['shard']);sha=store.put_blob(body)
        key=context['index']['products'][subject['scope']['productKey']]
        context['manifest']['executable_v2']['shards'][key]=dict(name=f"{key}-{subject['source']['runDate']}-{sha[:12]}.json.gz",bytes=len(body),sha256=sha)
        identity=bundle_sha256(context['manifest'])
        context['manifest']['payload_revision'].update(bundle_sha256=identity,generation_id='sha256-'+identity)
        context['selection']['edition']=identity
        with pytest.raises(ValueError,match='shard product association'):
            _context(context,subject,None,store,store.read_blob)


def test_reconstructed_shard_without_matching_gzip_refused(tmp_path):
    with EvidenceStore(tmp_path/'technical') as store:
        _,subject,bridge=retained_benchmark(store)
        context={k:copy.deepcopy(bridge[k]) for k in ('index','shard','selection')}
        context['manifest']=bridge['context']['manifest']
        context['shard']['products']={}
        with pytest.raises(ValueError,match='decoded asset differs'):
            _context(context,subject,None,store,store.read_blob)


def test_rehashed_index_product_absent_from_details_refused(tmp_path):
    with EvidenceStore(tmp_path/'technical') as store:
        _,subject,bridge=retained_benchmark(store)
        context={k:copy.deepcopy(bridge[k]) for k in ('index','shard','selection')}
        context['manifest']=copy.deepcopy(bridge['context']['manifest'])
        context['index']['products']['missing-technical-product']=next(iter(context['index']['products'].values()))
        body=_gzip_bytes(context['index']);sha=store.put_blob(body)
        context['manifest']['executable_v2']['index']=dict(name=f"executable_v2_index-{subject['source']['runDate']}-{sha[:12]}.json.gz",bytes=len(body),sha256=sha)
        identity=bundle_sha256(context['manifest'])
        context['manifest']['payload_revision'].update(bundle_sha256=identity,generation_id='sha256-'+identity)
        context['selection']['edition']=identity
        with pytest.raises(ValueError,match='shard inventory differs'):
            _context(context,subject,None,store,store.read_blob)
