from pathlib import Path
import pytest

from app_payload_product_evidence_contract import decode
from cdr_product_evidence_delivery_policy import STATUS
import pi_daily_sync as sync
from tests.test_product_evidence_daily_intent import source, session
from tests.product_evidence_daily_fixture import ready_source


def test_ready_input_uses_original_base_and_capability_bytes_then_resumes(source):
    values=ready_source(source);fixture,pointer,_=values
    sync.mark_payload_publication_pending(fixture['state'].parent,'ready_input',pointer)
    worker=session(values);root,manifest=worker.resume()
    assert all(row['state']=='available' for row in manifest[STATUS]['lanes'].values())
    assert len(list(root.glob('*capability*.gz')))==2
    original=(fixture['root']/'manifest.json').read_bytes()
    assert (root.parent/'base/manifest.json').read_bytes()==original
    again,observed=session(values).resume()
    assert root==again and observed==manifest
    worker.check()
    fixture['pointer'].write_bytes(fixture['pointer'].read_bytes()+b' ')
    with pytest.raises(ValueError,match='selection changed'):worker.check()


@pytest.mark.parametrize('fault',['manifest','descriptor','capability'])
def test_ready_missing_or_changed_original_never_becomes_pending(source,fault):
    values=ready_source(source);fixture,pointer,_=values;state=fixture['state']
    sync.mark_payload_publication_pending(state.parent,'ready_input',pointer)
    ready=pointer['optional_product_evidence_intent']['delivery']
    if fault=='manifest':path=fixture['root']/'manifest.json'
    elif fault=='descriptor':path=state/ready['file']
    else:path=next((state.parent/ready['capability_root']).iterdir())
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError):session(values).resume()
