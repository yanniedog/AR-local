"""Full historical I/O proof and nonbusiness metadata boundary controls."""
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from app_payload_historical_source import historical_contract
from cdr_atomic import canonical_json_bytes
from cdr_export_contract import read_json
from cdr_finalization import finalize_observation
from cdr_population_baseline import _verified_baseline
from cdr_population_history import _bounded_metadata, historical_pointer
from tests.test_cdr_product_facts import captured


DAY = '2026-05-19'  # Capture date of the existing authentic product-detail fixture.


def finalized_capture(tmp_path):
    """Normal exporter/finalizer; no fabricated products, rates or register claims."""
    from cdr_outputs import build_outputs
    run = tmp_path/'runs'/DAY
    product = captured()[0]
    source = run/'banks'/product['dataset']/product['provider']/'captured/product-detail.json'
    source.parent.mkdir(parents=True)
    source.write_bytes(canonical_json_bytes({'data':product['record']}))
    result = build_outputs(run)
    exports = run/'_exports'
    # Explicitly incomplete audit metadata grants no invented register/HTTP proof.
    (exports/'ingest-status.json').write_bytes(canonical_json_bytes({
        'incomplete':True,'failure_provenance_complete':False,'provider_states':[]}))
    state = tmp_path/'state'
    marker = finalize_observation(exports,state,state/f'{DAY}.done.json',
                                  observation_date=DAY,result=result)
    return state,exports,marker


def test_real_historical_pointer_and_verified_baseline_bind_export_ledger_database(tmp_path):
    state,exports,marker = finalized_capture(tmp_path)
    before = {str(path):hashlib.sha256(path.read_bytes()).hexdigest()
              for path in tmp_path.rglob('*') if path.is_file()}
    pointer = historical_pointer(state,DAY,lambda **kw:None)
    observation,baseline,counts = _verified_baseline(state,pointer,lambda **kw:None)
    assert pointer['generation_id'] == marker['generation_id'] == baseline['generation_id']
    assert observation['export_root'] == exports.resolve()
    assert baseline['contract_digest'] == observation['contract']['contract_digest']
    assert baseline['ledger_event_digest'] == marker['ledger_event_digest']
    assert baseline['database_sha256'] == hashlib.sha256((exports/'local-cdr.sqlite').read_bytes()).hexdigest()
    assert counts[0] == {'Up':1}  # Generated from the retained authentic product.
    assert counts[1]['Up'] > 0
    assert before == {str(path):hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in tmp_path.rglob('*') if path.is_file()}


@pytest.mark.parametrize('fault',['database','contract','ledger','marker'])
def test_real_historical_pipeline_rejects_corrupted_bound_artifacts(tmp_path,fault):
    state,exports,marker = finalized_capture(tmp_path)
    if fault == 'database':
        path = exports/'local-cdr.sqlite'
        path.write_bytes(path.read_bytes()+b'integrity-control')
    elif fault == 'contract':
        path = state/marker['export_contract_path']
        value=json.loads(path.read_bytes());value['source_path']='runs/missing/_exports'
        path.write_bytes(canonical_json_bytes(value))
    elif fault == 'ledger':
        path = state/f"ledger-v2/events/{DAY}/{marker['generation_id']}.json"
        value=json.loads(path.read_bytes());value['event_digest']='0'*64
        path.write_bytes(canonical_json_bytes(value))
    else:
        (state/f'{DAY}.done.json').write_bytes(b'{}')
    with pytest.raises((ValueError,KeyError,OSError)):
        pointer = historical_pointer(state,DAY,lambda **kw:None)
        _verified_baseline(state,pointer,lambda **kw:None)


@pytest.mark.parametrize('snapshot',[False,True])
@pytest.mark.parametrize('selected',[False,True])
def test_lone_contract_with_missing_referenced_generation_never_falls_back(tmp_path,snapshot,selected):
    state,_,marker = finalized_capture(tmp_path)
    # Pure selection-protocol control: a receipt references a missing predecessor.
    receipt = {'schema_version':1,'observation_date':DAY,
        'candidate_generation_id':marker['generation_id'],
        'previous_generation_id':f'obs-{DAY}-missing-control',
        'candidate_event_digest':marker['ledger_event_digest'],
        'previous_event_digest':'0'*64,'selected':selected}
    raw = canonical_json_bytes(receipt)
    decision = state/f'observation-selections-v1/{DAY}/{hashlib.sha256(raw).hexdigest()}.json'
    decision.parent.mkdir(parents=True)
    decision.write_bytes(raw)
    kwargs = {'paths':[state/marker['export_contract_path']],
              'decision_paths':[decision],'budget':lambda **kw:None} if snapshot else {}
    with pytest.raises(ValueError,match='Historical selection binding differs'):
        historical_contract(state,DAY,**kwargs)
    with pytest.raises(ValueError,match='Historical selection binding differs'):
        historical_pointer(state,DAY,lambda **kw:None)


def test_metadata_inventory_rejects_directory_named_json(tmp_path):
    (tmp_path/'control.json').mkdir()
    with pytest.raises(ValueError,match='metadata budget'):
        _bounded_metadata(tmp_path,8,65536,lambda **kw:None)


def test_budgeted_reader_checks_open_descriptor_and_closes_nonregular_control(tmp_path,monkeypatch):
    path=tmp_path/'control.json';path.write_bytes(b'{}')
    real_open,real_fstat = os.open,os.fstat
    descriptors=[]
    def opened(*args,**kw):
        descriptor=real_open(*args,**kw);descriptors.append(descriptor);return descriptor
    def metadata(descriptor):
        value=list(real_fstat(descriptor));value[0]=stat.S_IFIFO|0o600
        return os.stat_result(value)
    monkeypatch.setattr(os,'open',opened)
    monkeypatch.setattr(os,'fstat',metadata)
    with pytest.raises(ValueError,match='regular file'):
        read_json(path,budget=lambda **kw:None)
    assert len(descriptors)==1
    with pytest.raises(OSError):real_fstat(descriptors[0])
    assert path.read_bytes()==b'{}'


@pytest.mark.parametrize('cap',[65536,512*1024,4*1024*1024,16*1024*1024])
def test_exact_metadata_cap_is_checked_on_open_descriptor(tmp_path,monkeypatch,cap):
    path=tmp_path/'control.json';path.write_bytes(b'{}')
    original=os.fstat
    def replaced(descriptor):
        value=list(original(descriptor));value[6]=cap+1
        return os.stat_result(value)
    monkeypatch.setattr(os,'fstat',replaced)
    with pytest.raises(ValueError,match='bounded read limit'):
        read_json(path,budget=lambda **kw:None,max_bytes=cap)
    assert path.read_bytes()==b'{}'


def test_real_fifo_metadata_is_rejected_without_opening_a_writer(tmp_path):
    if not hasattr(os,'mkfifo'):
        pytest.skip('FIFO creation is unavailable on Windows')
    path=tmp_path/'control.json';os.mkfifo(path)
    with pytest.raises(ValueError,match='regular file'):
        read_json(path,budget=lambda **kw:None)
    with pytest.raises(ValueError,match='metadata budget'):
        _bounded_metadata(tmp_path,8,65536,lambda **kw:None)
