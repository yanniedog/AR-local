"""One bounded, offline preparation phase; caller owns admission/resources.

Only the fresh attempt is writable in the installed worker sandbox. Completed
phase descriptors are committed by the supervising parent after terminal proof.
No provider fetch, financial recomputation, publication or latest-package search.
"""
from pathlib import Path

from app_payload_optional_assets import iter_payload_assets
from app_payload_product_evidence_contract import canonical, decode, digest, fields, require
from app_payload_product_evidence_delivery_check import read_stable
from app_payload_product_evidence_reference import encode_reference
from cdr_atomic import atomic_write_bytes
from cdr_product_evidence_preparation import (PreparedSourceSnapshot, _checked_snapshot,
                                             prepare_source_snapshot)
from cdr_product_evidence_runtime import freeze_delivery
from cdr_product_evidence_source import FinalizedSource, safe_path
from pi_product_evidence_dispatch_state import Work, current_pointer, financial_manifest
from pi_deploy_checkout import checkout_binding

LANES={'facts':'product_evidence_v1','responses':'product_response_evidence_v1'}


def _descriptor(work,path,maximum):
    raw,_=read_stable(path,maximum)
    return dict(file=path.relative_to(work.root).as_posix(),sha256=digest(raw),bytes=len(raw))


def _read(work,descriptor,maximum):
    fields(descriptor,('file','sha256','bytes'))
    require(type(descriptor['bytes']) is int and 0<descriptor['bytes']<=maximum,'invalid phase byte bound')
    path=safe_path(work.root,descriptor['file']);raw,_=read_stable(path,maximum)
    require(len(raw)==descriptor['bytes'] and digest(raw)==descriptor['sha256'],'committed phase bytes changed')
    return path,raw


def _check_request(work,repo_root):
    binding=checkout_binding(repo_root)
    require(binding==dict(head=work.request['writer_revision'],tree=work.request['writer_tree'],clean=True),'preparation writer changed')
    pointer,checksum=current_pointer(work.state)
    require(checksum==work.request['pointer_sha256'] and canonical(pointer)==canonical(work.request['pointer']),
            'preparation source superseded')
    root=safe_path(work.state,work.request['published_directory'])
    raw,_=read_stable(root/'manifest.json',65536)
    require(digest(raw)==work.request['published_manifest_sha256'],'published preparation base changed')
    return root,decode(raw)


def _copy_base(work,attempt_root):
    original=safe_path(work.state,work.request['published_directory'])
    raw,_=read_stable(original/'manifest.json',65536)
    require(digest(raw)==work.request['published_manifest_sha256'],'published base changed')
    base=financial_manifest(decode(raw));base_raw=canonical(base)
    require(digest(base_raw)==work.request['financial_manifest_sha256'],'financial projection changed')
    output=attempt_root/'base';output.mkdir(mode=0o700)
    total=0
    for _,entry in iter_payload_assets(base):
        total+=entry['bytes'];require(total<=16*1024**2,'financial copy exceeds existing network budget')
        body,_=read_stable(original/entry['name'],entry['bytes'])
        require(len(body)==entry['bytes'] and digest(body)==entry['sha256'],'published financial asset changed')
        atomic_write_bytes(output/entry['name'],body,create_once=True)
    atomic_write_bytes(output/'manifest.json',base_raw,create_once=True)
    return output


def _source(work,base):
    return FinalizedSource(work.state,base,expected_pointer_sha256=work.request['pointer_sha256'],
                           expected_manifest_sha256=work.request['financial_manifest_sha256'])


def _snapshot(work):
    row=work.stage('snapshot');fields(row['outputs'],('base','preparation'))
    manifest,_=_read(work,row['outputs']['base'],65536)
    receipt,raw=_read(work,row['outputs']['preparation'],65536)
    return manifest.parent,PreparedSourceSnapshot(receipt.parent/'snapshot',raw)


def snapshot(work,attempt_root):
    base=_copy_base(work,attempt_root);source=_source(work,base)
    prepared=prepare_source_snapshot(source,attempt_root/'snapshot',writer_revision=work.request['writer_revision'])
    atomic_write_bytes(attempt_root/'preparation.json',prepared.receipt,create_once=True)
    return dict(base=_descriptor(work,base/'manifest.json',65536),
                preparation=_descriptor(work,attempt_root/'preparation.json',65536))


def package(work,attempt_root,phase):
    base,prepared=_snapshot(work);source=_source(work,base)
    source.recheck();binding=_checked_snapshot(source,prepared,work.request['writer_revision'])
    output=attempt_root/'package'
    if phase=='facts':
        from app_payload_product_evidence_transport import pack_snapshot
        pack_snapshot(prepared.root,output,expected_source=binding['source'],
                      core_sha256=binding['core_sha256'],details_sha256=binding['details_sha256'])
    else:
        from app_payload_product_response_sources import ResponseSources
        from app_payload_product_response_transport import pack_responses
        original=ResponseSources(prepared.root,source.exports,source.contract_path,expected_binding=binding)
        pack_responses(original,output);original.recheck()
    source.recheck()
    return dict(prepared=_descriptor(work,output/'prepared.json',66560))


def delivery(work,attempt_root):
    base,prepared=_snapshot(work);source=_source(work,base);packages={}
    for phase,lane in LANES.items():
        if lane not in work.request['enabled']:continue
        row=work.stage(phase);fields(row['outputs'],('prepared',))
        path,raw=_read(work,row['outputs']['prepared'],66560)
        packages[lane]=dict(root=path.parent,sha256=digest(raw))
    frozen=freeze_delivery(source,prepared,work.request['enabled'],packages,evidence_root=work.root,
        writer_revision=work.request['writer_revision'],expected_preparation_sha256=prepared.sha256)
    caps=attempt_root/'capabilities';caps.mkdir(mode=0o700)
    import base64
    candidate=decode(base64.b64decode(frozen.document()['candidate']['base64'],validate=True))
    for lane,supplied in packages.items():
        raw,_=read_stable(supplied['root']/'prepared.json',66560)
        require(digest(raw)==supplied['sha256'],'prepared package changed after adoption')
        reference,blob=encode_reference(lane,decode(raw)['capability'],source.base)
        require(reference==candidate['lanes'][lane]['reference'],'detached capability changed after adoption')
        atomic_write_bytes(caps/reference['capability']['name'],blob,create_once=True)
    atomic_write_bytes(attempt_root/'delivery.json',frozen.raw,create_once=True)
    return dict(delivery=_descriptor(work,attempt_root/'delivery.json',256*1024),
                capability_root=caps.relative_to(work.root).as_posix())


def run_phase(repo_root,state,pin,attempt):
    """Pure phase body, invoked only inside the externally bounded worker."""
    work=Work(state,pin);row=work.progress()
    require(row.get('status')=='running' and all(row.get(key)==attempt.get(key) for key in ('phase','attempt_id')),
            'preparation attempt lost ownership')
    phase=attempt['phase'];require(phase in ('snapshot','facts','responses','delivery'),'offline phase required')
    require(work.next_phase()==phase,'preparation stages cannot be skipped')
    if phase in LANES:require(LANES[phase] in work.request['enabled'],'disabled package phase')
    root=safe_path(work.root,f"attempts/{attempt['attempt_id']}")
    require(root.is_dir() and all(path.name=='tmp' and path.is_dir() and not path.is_symlink()
                                and not any(path.iterdir()) for path in root.iterdir()),'fresh empty attempt required')
    _check_request(work,repo_root)
    outputs=(snapshot(work,root) if phase=='snapshot' else delivery(work,root) if phase=='delivery'
             else package(work,root,phase))
    _check_request(work,repo_root)
    require(work.progress()==row,'preparation ownership changed during phase')
    result=dict(schema='ar-product-evidence-stage-v1',result='PASS',phase=phase,
        request_sha256=pin['sha256'],attempt_id=attempt['attempt_id'],outputs=outputs,
        writer_commit=work.request['writer_revision'],writer_tree=work.request['writer_tree'],
        publication_authorized=False,selection_verified=False)
    atomic_write_bytes(root/'result.json',canonical(result),create_once=True)
    return result


def ready_retry(repo_root,work):
    """Parent commits small intent only from the pinned, completed delivery phase."""
    from cdr_product_evidence_runtime import FrozenDelivery
    from pi_product_evidence_intent import persist_delivery,enrich_pointer
    from pi_product_evidence_retry import register_optional_retry
    _check_request(work,repo_root)
    row=work.stage('delivery');fields(row['outputs'],('delivery','capability_root'))
    path,raw=_read(work,row['outputs']['delivery'],256*1024)
    base,_=_snapshot(work)
    ready=persist_delivery(work.state,FrozenDelivery(raw),digest(raw),base_root=base,
        expected_manifest_sha256=work.request['financial_manifest_sha256'],evidence_root=work.root,
        capability_root=safe_path(work.root,row['outputs']['capability_root']))
    pointer=enrich_pointer(repo_root,work.request['pointer'],enabled=work.request['enabled'],
        revision=work.request['writer_revision'],delivery=ready)
    index,_=read_stable(work.root/'published-index.json',8*1024**2)
    request=register_optional_retry(work.state,pointer,
        published_root=safe_path(work.state,work.request['published_directory']),index_raw=index,
        expected_index_sha256=work.request['predecessor_index_sha256'])
    value=dict(schema='ar-product-evidence-dispatch-retry-v1',request_sha256=work.pin['sha256'],
        delivery_stage=work.progress()['stages']['delivery'],optional_request_sha256=request)
    atomic_write_bytes(work.root/'optional-retry.json',canonical(value),create_once=True)
    return request
