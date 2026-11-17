"""Real captured packages through LOCAL full-backup freeze/readback; no Drive."""
from copy import deepcopy
from pathlib import Path
import shutil

import pytest

import pi_product_evidence_intent as intent
from app_payload_product_evidence_contract import decode, digest
from app_payload_product_evidence_delivery_check import verify_prepared as verify_facts
from app_payload_product_response_transport import verify_prepared as verify_responses
from cdr_product_evidence_preparation import prepare_source_snapshot
from pi_drive_backup_manifest import close_manifest
from pi_drive_backup_source import freeze, restore_relative, verify_restore
from pi_product_evidence_locations import supported_location
from tests.product_evidence_daily_fixture import ready_source
from tests.product_evidence_finalized_fixture import finalized, open_source, WRITER
from tests.test_product_evidence_daily_intent import source


def test_ready_captured_packages_and_external_pins_survive_supported_full_backup(source,tmp_path):
    fixture,pointer,_=ready_source(source);state=fixture['state'];data=state.parent
    original={p.relative_to(state).as_posix():p.read_bytes() for p in state.rglob('*') if p.is_file() and not p.name.endswith('.lock')}
    staged=tmp_path/'backup-stage';restored=tmp_path/'restore';restored.mkdir()
    frozen=freeze(data,staged,controls=[],guard=lambda:None,max_freeze_seconds=60)
    try:
        rows=list(frozen['files']);state_rows=[r for r in rows if r['logical_path'].startswith('data/state/')]
        expected={f'data/state/{name}' for name in original}
        assert expected <= {r['logical_path'] for r in state_rows}
        for row in rows:
            target=restored/restore_relative(row['backup_path']);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(row['backup_path'],target)
        result=verify_restore(restored,rows)
        assert result['result']=='PASS' and result['files_verified']==len(rows)
        # State is copied, so the existing Restic absolute-path mapping is exact.
        restored_state=restored/restore_relative(str(staged/'data/state'))
        assert all((restored_state/name).read_bytes()==raw for name,raw in original.items())
        raw,base,evidence=intent.read_delivery(restored_state,pointer)
        assert digest(raw)==pointer[intent.KEY]['delivery']['sha256']
        document=decode(raw)
        for lane,verify in [('product_evidence_v1',verify_facts),('product_response_evidence_v1',verify_responses)]:
            package=evidence/document['packages'][lane]['root']
            marker=decode((package/'prepared.json').read_bytes())
            assert digest((package/'prepared.json').read_bytes())==document['packages'][lane]['sha256']
            verified=verify(package,expected_binding=marker['capability']['binding'])
            assert verified
        shard=next(evidence.rglob('*-shard-*.json.gz'));shard.write_bytes(b'corrupt')
        with pytest.raises(ValueError,match='restored bytes differ'):verify_restore(restored,rows)
    finally:close_manifest(frozen)


@pytest.mark.parametrize('part',['base','evidence','capability'])
def test_resumed_ready_locator_outside_backed_up_state_is_rejected(source,tmp_path,part):
    fixture,pointer,_=ready_source(source);pointer=deepcopy(pointer);ready=pointer[intent.KEY]['delivery']
    outside=fixture['state'].parent/'unclassified-prepared';outside.mkdir()
    if part=='base':ready['base']['directory']='unclassified-prepared'
    else:ready[part+'_root']='unclassified-prepared'
    with pytest.raises(ValueError,match='claimed-ready'):intent.read_delivery(fixture['state'],pointer)


def test_preparation_still_rejects_output_under_original_contract_directory(tmp_path):
    fixture=finalized(tmp_path,dated_contract=True)
    with pytest.raises(ValueError,match='overlapping snapshot'):
        prepare_source_snapshot(open_source(fixture),fixture['contract'].parent/'new-snapshot',writer_revision=WRITER)


def test_supported_placement_requires_existing_canonical_descendant(tmp_path):
    state=tmp_path/'state';state.mkdir();good=state/'product-evidence-prepared-v1';good.mkdir()
    assert supported_location(state,good)==good
    for invalid in (state,state/'absent',tmp_path):
        with pytest.raises(ValueError):supported_location(state,invalid)


@pytest.mark.parametrize('name',['.git','credentials','oauth-material','.env-private'])
def test_scope_placement_cannot_hide_packages_in_an_excluded_directory(tmp_path,name):
    state=tmp_path/'state';state.mkdir();excluded=state/name;excluded.mkdir()
    with pytest.raises(ValueError,match='excluded from full backup'):supported_location(state,excluded)
