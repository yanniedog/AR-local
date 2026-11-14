"""Fixed ordinary-user child of the installed root-owned evidence launcher.

No queue/lease acquisition. Preparation has no credentials/network. Publication
uses a distinct PID1-loaded environment and the existing transaction exactly once.
"""
from pathlib import Path
import base64
import json
import os
import stat
import sys
import time

# -I excludes the script directory; the launcher has independently verified this
# entire immutable root-owned source inventory before executing this exact file.
if __name__=='__main__':sys.path.insert(0,str(Path(__file__).absolute().parent))

from app_payload_product_evidence_contract import canonical,decode,digest,fields,require
from cdr_atomic import atomic_write_bytes
from pi_product_evidence_dispatch_state import Work
from pi_product_evidence_prepare import run_phase


class DiskGuard:
    """Incremental storage observation with constant-time filesystem floors.

    Existing financial archives are not reclassified as owned scratch. Additional
    filesystem consumption is conservatively charged even if another app caused
    it. Free byte/inode floors apply throughout and retained failed attempts count
    toward this source's private 2 GiB/20k-entry ceiling.
    """
    def __init__(self,root):
        self.root=root;self.initial=None;self.peak=0;self.iterator=None
        self.entries=self.used=0;self.started=0
        self.failure=None

    def floors(self):
        usage=os.statvfs(self.root);free=usage.f_bavail*usage.f_frsize
        require(free>=8*1024**3 and usage.f_favail>=4096,'optional storage reserve exhausted')
        if self.initial is None:self.initial=free
        require(self.initial-free<=2*1024**3,'optional filesystem growth exhausted')

    def _entries(self):
        stack=[self.root];device=self.root.lstat().st_dev
        while stack:
            parent=stack.pop()
            with os.scandir(parent) as values:
                for item in values:
                    try:info=item.stat(follow_symlinks=False)
                    except FileNotFoundError:continue  # Packers atomically retire pending names.
                    self.entries+=1
                    require(self.entries<=20000 and info.st_dev==device and info.st_uid==os.getuid(),
                            'optional storage inventory exceeded or changed owner/device')
                    if stat.S_ISDIR(info.st_mode):stack.append(Path(item.path))
                    else:
                        # Existing durable packers briefly link pending->final.
                        # Their final semantic verification still requires one link.
                        require(stat.S_ISREG(info.st_mode) and info.st_nlink in (1,2),'unsafe optional storage member')
                        self.used+=info.st_size;require(self.used<=2*1024**3,'retained optional stage storage exhausted')
                    yield None
        self.peak=max(self.peak,self.used)

    def _start(self):
        self.entries=self.used=0;self.started=time.monotonic();self.iterator=self._entries()

    def __enter__(self):
        self.floors();self._start()
        for _ in self.iterator:require(time.monotonic()-self.started<15,'initial optional storage scan exceeded')
        self._start();return self

    def __exit__(self,*_):
        if self.iterator is not None:self.iterator.close()

    def check(self):
        if self.failure is not None:return self.failure
        try:
            self.floors();begin=time.monotonic()
            require(begin-self.started<15,'optional storage sweep stale')
            for _ in range(256):
                if time.monotonic()-begin>=.025:break
                try:next(self.iterator)
                except StopIteration:self._start();break
            return None
        except Exception as error:
            self.failure=type(error).__name__+': '+str(error)
            return self.failure

    def finish(self,deadline):
        """A fresh complete terminal inventory is mandatory, never a partial tick."""
        require(self.failure is None,self.failure or 'optional storage already failed')
        if self.iterator is not None:self.iterator.close()
        try:
            self.floors();self._start();end=min(deadline,self.started+15)
            require(time.monotonic()<end,'final optional storage deadline exhausted')
            for _ in self.iterator:
                require(time.monotonic()<end,'final optional storage scan exceeded')
                if self.entries%256==0:self.floors()
            self.floors();require(time.monotonic()<end,'final optional storage deadline exhausted')
        except Exception as error:
            self.failure=type(error).__name__+': '+str(error)
            raise


def validate(value):
    fields(value,('request','source','production','state','root','attempt','source_commit','source_tree',
                  'source_closure_sha256','runtime_sha256','profile_sha256','path_identities'))
    require(Path(value['source'])==Path(__file__).absolute().parent,'worker loaded from another source')
    state=Path(value['state']);request=value['request'];work=Work(state,dict(day=request['day'],sha256=request['request_sha256']))
    require(work.root==Path(value['root']) and Path(value['attempt'])==work.root/'attempts'/request['attempt_id'],
            'worker operation differs')
    from pi_product_evidence_launch import path_identity
    require(value['path_identities']=={str(path):path_identity(path) for path in
            (state,work.root,Path(value['attempt']))},'worker mount identity changed')
    require(work.request['writer_revision']==value['source_commit'] and work.request['writer_tree']==value['source_tree'],
            'worker approved writer differs')
    from pi_deploy_checkout import checkout_binding
    require(checkout_binding(Path(value['production']))==dict(head=value['source_commit'],tree=value['source_tree'],clean=True),
            'production writer differs from immutable worker closure')
    progress=work.progress()
    require(progress.get('status')=='running' and progress.get('attempt_id')==request['attempt_id']
            and progress.get('phase')==request['phase'],'worker phase ownership changed')
    from pi_product_evidence_launch import validate_job,verify_production_lease
    from datetime import datetime,timezone
    validate_job(request,clock=time.monotonic(),now=datetime.now(timezone.utc))
    verify_production_lease(request,os.getuid())
    from pi_shared_queue_store import Supervisor
    supervisor=Supervisor();parent=request['owner']['job'];native=supervisor.show(parent['unit'])
    require(supervisor.wrapper_alive(parent) and supervisor.boot_id()==parent['boot_id']
            and native.get('InvocationID')==parent['invocation_id'] and native.get('MainPID')==str(parent['pid'])
            and native.get('ActiveState') in ('active','activating'),'worker parent changed')
    require(supervisor.cgroup(os.getpid())=='/system.slice/ar-local-product-evidence-'+request['attempt_id']+'.service',
            'worker is outside its exact dedicated cgroup')
    return work


def body(value):
    work=validate(value);request=value['request'];attempt={key:request[key] for key in ('phase','attempt_id')}
    if request['phase']=='publish':
        from pi_product_evidence_retry import publish_optional_retry_delegated
        from app_payload_product_evidence_delivery_check import read_stable
        raw,_=read_stable(work.root/'optional-retry.json',65536);control=decode(raw)
        require(control.get('request_sha256')==work.pin['sha256'] and control.get('delivery_stage')==work.progress()['stages']['delivery'],
                'optional retry differs from committed delivery')
        outcome=publish_optional_retry_delegated(value,control['optional_request_sha256'],
            completion_writer=dict(commit=value['source_commit'],tree=value['source_tree'],
                source_closure_sha256=value['source_closure_sha256'],runtime_sha256=value['runtime_sha256'],
                profile_sha256=value['profile_sha256']))
        require(outcome.get('status')=='published','optional publication did not finish')
        result=dict(schema='ar-product-evidence-stage-v1',result='PASS',phase='publish',attempt_id=request['attempt_id'],
            request_sha256=request['request_sha256'],outputs=outcome,writer_commit=value['source_commit'],writer_tree=value['source_tree'],
            publication_authorized=False,selection_verified=False)
        atomic_write_bytes(Path(value['attempt'])/'result.json',canonical(result),create_once=True)
    else:run_phase(Path(value['production']),work.state,work.pin,attempt)


def supervise(value,encoded):
    work=validate(value);attempt=Path(value['attempt']);(attempt/'tmp').mkdir(mode=0o700)
    from pi_cdr_quality_resources import Limits,supervise as bounded
    runtime=value['request']['owner']['deadline_monotonic']-time.monotonic()-20
    require(0<runtime<=1800,'worker original deadline exhausted')
    with DiskGuard(work.root) as disk:
        def guard():
            if time.monotonic()>=value['request']['owner']['deadline_monotonic']:return 'original optional deadline expired'
            return disk.check()
        receipt=bounded([sys.executable,'-I','-B',str(Path(__file__).absolute()),'--body',encoded],
            attempt/'resources.json',Limits(runtime_seconds=runtime),priority_guard=guard)
        require(receipt.get('result')=='PASS' and receipt.get('group_clean') is True,'optional resource supervision failed')
        disk.finish(value['request']['owner']['deadline_monotonic'])
        terminal=dict(schema='ar-product-evidence-worker-v1',result='PASS',request_sha256=work.pin['sha256'],
            attempt_id=value['request']['attempt_id'],resources_sha256=digest((attempt/'resources.json').read_bytes()),
            source_commit=value['source_commit'],source_tree=value['source_tree'],source_closure_sha256=value['source_closure_sha256'],
            runtime_sha256=value['runtime_sha256'],profile_sha256=value['profile_sha256'],peak_owned_bytes=disk.peak,
            publication_authorized=False,selection_verified=False)
        validate(value)
        atomic_write_bytes(attempt/'worker.json',canonical(terminal),create_once=True)


if __name__=='__main__':
    args=sys.argv[1:];mode='supervise'
    if args and args[0]=='--body':mode='body';args=args[1:]
    require(len(args)==1 and len(args[0])<=32768,'bounded encoded worker input required')
    value=decode(base64.b64decode(args[0],validate=True))
    body(value) if mode=='body' else supervise(value,args[0])
