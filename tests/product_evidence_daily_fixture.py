"""Captured fact/raw bytes, explicit local financial and selection controls."""
import shutil

from app_payload_product_evidence_contract import decode, digest
from app_payload_product_evidence_reference import encode_reference
from app_payload_product_evidence_transport import pack_snapshot
from app_payload_product_response_sources import ResponseSources
from app_payload_product_response_transport import pack_responses
from cdr_product_evidence_preparation import prepare_source_snapshot, _checked_snapshot
from cdr_product_evidence_runtime import freeze_delivery
from tests.product_evidence_finalized_fixture import open_source, WRITER, FACTS, RESPONSES, ENABLED
import pi_product_evidence_intent as intent


def ready_source(source):
    fixture,_,contract=source;state=fixture['state']
    base=state/'original-base';shutil.copytree(fixture['root'],base);fixture['root']=base
    current=open_source(fixture);evidence=state.parent/'prepared';evidence.mkdir()
    snapshot=prepare_source_snapshot(current,evidence/'snapshot',writer_revision=WRITER)
    binding=_checked_snapshot(current,snapshot,WRITER)
    facts=pack_snapshot(snapshot.root,evidence/'facts',expected_source=binding['source'],
        core_sha256=binding['core_sha256'],details_sha256=binding['details_sha256'])
    responses=pack_responses(ResponseSources(snapshot.root,current.exports,current.contract_path,expected_binding=binding),evidence/'responses')
    packages={lane:dict(root=root,sha256=digest((root/'prepared.json').read_bytes()))
        for lane,root in ((FACTS,evidence/'facts'),(RESPONSES,evidence/'responses'))}
    frozen=freeze_delivery(current,snapshot,ENABLED,packages,evidence_root=evidence,
        writer_revision=WRITER,expected_preparation_sha256=snapshot.sha256)
    caps=state/'capabilities';caps.mkdir()
    for lane,pack in ((FACTS,facts),(RESPONSES,responses)):
        ref,blob=encode_reference(lane,pack['capability'],current.base)
        (caps/ref['capability']['name']).write_bytes(blob)
    descriptor=intent.persist_delivery(state,frozen,frozen.sha256,base_root=base,
        expected_manifest_sha256=digest((base/'manifest.json').read_bytes()),evidence_root=evidence,capability_root=caps)
    pointer=intent.enrich_pointer(state.parent,decode(fixture['pointer'].read_bytes()),enabled=ENABLED,
        revision=WRITER,delivery=descriptor)
    return fixture,pointer,contract
