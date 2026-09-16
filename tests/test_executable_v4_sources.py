"""Technical original-byte and independently reviewed source admission controls."""
import copy
import json
import pytest
from cdr_terms.executable_v4_contract import ROOT
from cdr_terms.executable_v4_sources import source_snapshot
from tests.executable_v3_fixture import technical_protocol, reidentify


@pytest.fixture
def activity_protocol(tmp_path):
    subject=json.loads((ROOT/'drafts/positive-technical-example.json').read_bytes())['subject']
    yield from technical_protocol(tmp_path,template=subject)


def test_actual_source_admission_and_changed_material_refusal(activity_protocol):
    store,subject,_=activity_protocol
    assert len(source_snapshot(store,subject))==64
    from cdr_terms.executable_registry import migrate_executable_registry, stage_subject, lookup_subject
    migrate_executable_registry(store,wire_version=3,applied_at='2026-01-12T01:00:00Z')
    migrate_executable_registry(store,wire_version=4,applied_at='2026-01-12T01:00:00Z')
    identity=stage_subject(store,subject,interpreter='activity-technical-writer',staged_at='2026-01-12T01:00:00Z')
    assert lookup_subject(store,identity)==subject
    changed=copy.deepcopy(subject)
    changed['policy']['bonus']['tiers'][0]['annualRate']='0.25'
    reidentify(changed)
    with pytest.raises(ValueError,match='matching reviewed structured material'):
        source_snapshot(store,changed)


def test_source_original_bytes_not_graph_assertion(activity_protocol):
    store,subject,_=activity_protocol
    identity=subject['evidence'][0]['documentSha256']
    path=store.blobs/identity[:2]/identity
    path.write_bytes(b'changed technical fixture source')
    with pytest.raises(ValueError,match='source bytes changed|descriptor|source evidence'):
        source_snapshot(store,subject)
