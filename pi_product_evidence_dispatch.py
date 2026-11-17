"""Financial-first optional work, using only the existing watchdog opportunity.

Default flags perform no optional I/O. No timer, queue admission, host lease,
source mutation, financial pending clear or replacement of a frozen candidate.
Publication retains one parent-owned production descriptor until child cleanup.
"""
from datetime import datetime,timezone
from pathlib import Path
import base64
import subprocess
import time

from app_payload_common import DEFAULT_REPO,DEFAULT_TAG
from app_payload_product_evidence_contract import canonical,decode,digest,require
from app_payload_product_evidence_delivery_check import read_stable
from app_payload_revisions_state import validate_index,revision_tag
from cdr_atomic import atomic_write_bytes
from cdr_product_evidence_delivery_policy import delivery_flags
from cdr_product_evidence_source import safe_path
from pi_product_evidence_admission import borrow,recheck
from pi_product_evidence_dispatch_state import DIRECTORY,Work,register,current_pointer,private_directory
from pi_deploy_checkout import checkout_binding

PROFILE=Path('/etc/ar-local/product-evidence-launch.json')
LAUNCH=Path('/usr/local/lib/ar-local-product-evidence/launch.py')
RECORDS=Path('/var/lib/ar-local-product-evidence-launch')


def _reference(state,pointer):
    return state/DIRECTORY/'sources'/(digest(canonical(pointer))+'.json')


def existing(state,pointer):
    path=_reference(state,pointer)
    if not path.exists():return None
    raw,_=read_stable(path,65536);value=decode(raw)
    require(set(value)=={'schema','source_pointer_sha256','work'}
            and value['schema']=='ar-product-evidence-dispatch-source-v1'
            and value['source_pointer_sha256']==digest(canonical(pointer)),'dispatch source reference changed')
    work=Work(state,value['work'])
    require(canonical(work.request['pointer'])==canonical(pointer),'dispatch source request differs')
    return work


def _local_publication(state,manifest):
    identity=manifest.get('payload_revision',{});revision=identity.get('revision');day=manifest['run_date']
    tag=revision_tag(day,revision)
    root=state/'app-payload/v1/revision-history/revisions'/day/f'r{revision:06d}'
    raw,_=read_stable(root/'manifest.json',65536);local=decode(raw)
    require(local.get('payload_revision')==identity and local.get('source_observation')==manifest.get('source_observation'),
            'local publication differs from completed financial edition')
    require(local.get('tag')==tag and local.get('repo')==DEFAULT_REPO,'local immutable route differs')
    found=[];promotions=root/'promotions'
    for number,directory in enumerate(promotions.iterdir(),1):
        require(number<=16 and directory.is_dir() and not directory.is_symlink(),'bounded promotion inventory required')
        receipt_path=directory/'promotion-receipt.json'
        if not receipt_path.exists():continue  # Uncommitted intent is never accepted.
        receipt=decode(read_stable(receipt_path,65536)[0]);index_raw,_=read_stable(directory/'dates-index.json',8*1024**2)
        index=decode(index_raw);validate_index(index,repo=DEFAULT_REPO);head=index.get('revision_heads',{}).get(day)
        if head and receipt.get('head')==head and head['manifest_sha256']==digest(raw):
            require(receipt.get('schema_version')==1 and receipt.get('index_sha256')==digest(index_raw)
                    and directory.name==digest(index_raw),'committed promotion pin differs')
            found.append(index_raw)
    require(len(found)==1,'unique committed financial promotion required')
    return root,found[0]


def enqueue_published(repo_root,manifest,*,enabled=None):
    """Nonfatal caller hook after verified financial success, with no remote I/O."""
    enabled=delivery_flags() if enabled is None else enabled
    if not enabled:return {'status':'disabled'}
    from ar_local_pi_runtime import data_state_root
    state=data_state_root(repo_root).absolute();pointer,_=current_pointer(state)
    prior=existing(state,pointer)
    if prior:return {'status':'queued','work':prior.pin,'existing':True}
    source=manifest.get('source_observation',{})
    require(all(source.get(key)==pointer.get(key) for key in ('generation_id','observation_date','observation_state')),
            'completed financial source is no longer current')
    root,index=_local_publication(state,manifest);writer=checkout_binding(repo_root)
    pin=register(state,pointer,published_root=root,index_raw=index,expected_index_sha256=digest(index),
                 enabled=enabled,writer_revision=writer['head'],writer_tree=writer['tree'])
    private_directory(state/DIRECTORY/'sources')
    raw=canonical(dict(schema='ar-product-evidence-dispatch-source-v1',source_pointer_sha256=digest(canonical(pointer)),work=pin))
    atomic_write_bytes(_reference(state,pointer),raw,create_once=True)
    return {'status':'queued','work':pin,'existing':False}


def enqueue_after_financial(repo_root,manifest):
    """A committed financial success cannot be reversed by optional setup errors."""
    try:return enqueue_published(repo_root,manifest)
    except Exception as error:return {'status':'failed','reason':type(error).__name__}


def _remote_head(store,day):
    raw=store.read(DEFAULT_TAG,'dates-index.json',8*1024**2,require_encrypted=True)
    require(type(raw) is bytes,'selected public index unavailable')
    index=decode(raw);validate_index(index,repo=DEFAULT_REPO)
    head=index.get('revision_heads',{}).get(day);require(type(head) is dict,'source date has no selected immutable head')
    return head,raw


def _head_matches(store,work):
    head,_=_remote_head(store,work.pin['day'])
    require(head==work.request['predecessor'],'optional preparation predecessor superseded')
    raw=store.read_url(head['manifest_url'],65536,require_encrypted=True)
    require(type(raw) is bytes and digest(raw)==head['manifest_sha256']==work.request['published_manifest_sha256'],
            'selected financial manifest differs')


def _resume_or_enqueue(repo_root,state,pointer,store):
    work=existing(state,pointer)
    if work:return work
    head,_=_remote_head(store,pointer['observation_date'])
    raw=store.read_url(head['manifest_url'],65536,require_encrypted=True)
    require(type(raw) is bytes and digest(raw)==head['manifest_sha256'],'selected published bytes unavailable')
    # Recovery after financial-success/enqueue crash still needs the exact local
    # committed promotion; never downloads/rebuilds a replacement financial base.
    enqueue_published(repo_root,decode(raw));return existing(state,pointer)


def _launched(work,attempt,proof,production_lease=None,*,lifecycle):
    request=dict(day=work.pin['day'],request_sha256=work.pin['sha256'],phase=attempt['phase'],
                 attempt_id=attempt['attempt_id'],owner=proof,production_lease=production_lease)
    encoded=base64.b64encode(canonical(request)).decode('ascii')
    private_directory(work.root/'launches')
    atomic_write_bytes(work.root/'launches'/(attempt['attempt_id']+'.json'),canonical(request),create_once=True)
    remaining=proof['deadline_monotonic']-time.monotonic()
    require(remaining>=300,'original dispatch allowance consumed')
    lifecycle['invoked']=True
    result=subprocess.run(['sudo','-n','/usr/bin/python3','-I','-B',str(LAUNCH),encoded],
        capture_output=True,timeout=remaining+45,check=False)
    lifecycle['returned']=True
    require(result.returncode==0,'restricted optional worker failed')
    path=RECORDS/(proof['job']['invocation_id']+'-terminal.json')
    raw,_=read_stable(path,98304);terminal=decode(raw)
    info=path.lstat()
    require(info.st_uid==0 and not info.st_mode&0o022 and terminal.get('request')==request
            and terminal.get('result')=='PASS' and terminal.get('owned_group_empty') is True,
            'root worker terminal ownership proof missing')
    root=work.root/'attempts'/attempt['attempt_id'];raws={}
    for name,maximum in (('worker.json',65536),('result.json',98304),('resources.json',8*1024**2)):
        body,_=read_stable(root/name,maximum);raws[name]=body
        require(terminal.get('artifacts',{}).get(name)==dict(bytes=len(body),sha256=digest(body)),
                'terminal artifact differs from protected root receipt')
    worker=decode(raws['worker.json']);resources=raws['resources.json'];resource=decode(resources)
    require(worker.get('result')=='PASS' and worker.get('attempt_id')==attempt['attempt_id']
            and worker.get('request_sha256')==work.pin['sha256'] and worker.get('profile_sha256')==terminal['profile_sha256']
            and worker.get('source_commit')==work.request['writer_revision'] and worker.get('source_tree')==work.request['writer_tree']
            and worker.get('resources_sha256')==digest(resources) and resource.get('result')=='PASS'
            and resource.get('group_clean') is True and resource.get('workload_started') is True,
            'bounded worker/resource receipt differs')
    return terminal,worker


def _closed(work,attempt,*,allow_unstarted=False):
    """Unknown root/native cleanup quarantines this work; never auto-reuses it."""
    path=work.root/'launches'/(attempt['attempt_id']+'.json')
    if not path.exists():return True  # No launcher was invoked by this attempt.
    request=decode(read_stable(path,32768)[0]);invocation=request['owner']['job']['invocation_id']
    terminal=RECORDS/(invocation+'-terminal.json')
    if terminal.exists():
        value=decode(read_stable(terminal,98304)[0]);info=terminal.lstat()
        return (info.st_uid==0 and not info.st_mode&0o022 and value.get('request')==request
                and value.get('owned_group_empty') is True)
    if (RECORDS/(invocation+'.json')).exists():return False
    if not allow_unstarted:return False  # Timeout/unknown root lifetime cannot prove rejection.
    # Root writes its protected start record BEFORE asking PID1 to start a unit.
    # Failure before that point is safe only with an independently absent unit.
    unit='ar-local-product-evidence-'+attempt['attempt_id']+'.service'
    result=subprocess.run(['/usr/bin/systemctl','show',unit,'--property=Id,LoadState,ActiveState,MainPID,ControlGroup'],
        capture_output=True,text=True,timeout=5,check=False)
    rows=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    return (result.returncode in (0,1) and rows==dict(Id=unit,LoadState='not-found',ActiveState='inactive',MainPID='0',ControlGroup='')
            and not (Path('/sys/fs/cgroup/system.slice')/unit).exists())


def dispatch(repo_root,*,store=None):
    enabled=delivery_flags()
    if not enabled:return {'status':'disabled'}
    if not PROFILE.is_file() or not LAUNCH.is_file():return {'status':'deferred','reason':'optional_launcher_uncommissioned'}
    from pi_daily_sync import payload_publication_pending
    from ar_local_pi_runtime import data_state_root
    if payload_publication_pending(repo_root):return {'status':'deferred','reason':'financial_publication_pending'}
    proof=borrow();state=data_state_root(repo_root).absolute();pointer,_=current_pointer(state)
    if store is None:
        from app_payload_revisions_github import GitHubRevisionStore
        store=GitHubRevisionStore(DEFAULT_REPO)
    work=_resume_or_enqueue(repo_root,state,pointer,store)
    require(work is not None,'optional source was not enqueued')
    if tuple(work.request['enabled'])!=tuple(enabled):return {'status':'deferred','reason':'frozen_lane_configuration_changed'}
    require(checkout_binding(repo_root)==dict(head=work.request['writer_revision'],tree=work.request['writer_tree'],clean=True),
            'frozen preparation writer changed')
    phase=work.next_phase()
    if phase is None:return {'status':'complete','work':work.pin}
    prior=work.progress()
    if prior.get('status')=='blocked':return {'status':'blocked','reason':'prior_worker_cleanup_requires_review','work':work.pin}
    if prior.get('status')=='running' and not _closed(work,dict(phase=prior['phase'],attempt_id=prior['attempt_id'])):
        return {'status':'blocked','reason':'prior_worker_cleanup_unverified','work':work.pin}
    # Publish retries must reach the existing promotion-lineage recovery, even
    # after their own child was selected before an alias/receipt interruption.
    if phase!='publish':_head_matches(store,work)
    recheck(proof)
    if payload_publication_pending(repo_root):return {'status':'deferred','reason':'financial_publication_pending'}
    if phase=='publish':
        from pi_product_evidence_prepare import ready_retry
        ready_retry(repo_root,work)
    attempt=work.begin(datetime.now(timezone.utc))
    if attempt is None:return {'status':'deferred','reason':'optional_cooldown_complete_or_exhausted','work':work.pin}
    lifecycle=dict(invoked=False,returned=False)
    try:
        if phase=='publish':
            from pi_product_evidence_lease import PublicationLease
            with PublicationLease(state,attempt,proof) as lease:
                try:_launched(work,attempt,proof,lease.verify(),lifecycle=lifecycle)
                finally:
                    if _closed(work,attempt,allow_unstarted=not lifecycle['invoked'] or lifecycle['returned']):
                        lease.release(owned_group_empty=True)
        else:_launched(work,attempt,proof,lifecycle=lifecycle)
        if phase!='publish':_head_matches(store,work)
        recheck(proof)
        require(work.finish(attempt,now=datetime.now(timezone.utc),status='complete'),'phase lost completion CAS')
        return {'status':'phase_complete','phase':phase,'work':work.pin}
    except Exception as error:
        try:closed=_closed(work,attempt,allow_unstarted=not lifecycle['invoked'] or lifecycle['returned'])
        except Exception:closed=False
        work.finish(attempt,now=datetime.now(timezone.utc),status='failed' if closed else 'blocked',reason=type(error).__name__)
        raise
