"""Retained-parent lock tests; no root, service, process signal or network action."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import os
import pytest
import pi_product_evidence_launch as launch
import pi_product_evidence_lease as lease
from tests.test_product_evidence_launcher import request


@pytest.fixture
def parent(tmp_path,monkeypatch):
    value=request();value['phase']='publish'
    job=value['owner']['job'];boot=tmp_path/'boot';boot.write_text(job['boot_id'])
    monkeypatch.setattr(lease,'Path',lambda p:boot if str(p)=='/proc/sys/kernel/random/boot_id' else Path(p))
    monkeypatch.setattr(lease,'group',lambda pid:job['cgroup'])
    monkeypatch.setattr(lease,'ticks',lambda pid:88)
    monkeypatch.setattr(lease,'os',SimpleNamespace(**{**vars(os),'O_NOFOLLOW':getattr(os,'O_NOFOLLOW',0)}))
    monkeypatch.setattr(lease,'fsync_directory',lambda path:None)
    state=tmp_path/'state';state.mkdir()
    return state,value


@pytest.mark.parametrize('body',[b'pid=1\nrole=ingest\n',b'pid=1\nrecovery=manual\n',b'unknown incumbent'])
def test_existing_stale_manual_or_unknown_lock_is_never_recovered(parent,body):
    state,value=parent;path=state/'daily-ingest.lock';path.write_bytes(body)
    with pytest.raises(FileExistsError):
        with lease.PublicationLease(state,value,value['owner']):pytest.fail('incumbent replaced')
    assert path.read_bytes()==body


def test_unknown_cleanup_and_exceptions_preserve_manual_obligation(parent):
    state,value=parent
    with lease.PublicationLease(state,value,value['owner']) as held:
        original=held.path.read_bytes()
        with pytest.raises(ValueError,match='unknown child cleanup'):held.release(owned_group_empty=False)
        assert b'recovery=manual' in original and held.verify()['fd']==held.fd
    assert (state/'daily-ingest.lock').read_bytes()==original


@pytest.mark.skipif(os.name!='posix',reason='POSIX open-file unlink contract; native acceptance remains required')
def test_exact_owned_lock_released_only_after_terminal_proof(parent):
    state,value=parent
    with lease.PublicationLease(state,value,value['owner']) as held:
        held.release(owned_group_empty=True)
    assert not (state/'daily-ingest.lock').exists()


@pytest.mark.parametrize('fault',['parent_dead','start_reuse','fd_reuse','name_replaced','record_changed','boot_changed','group_changed'])
def test_root_delegation_rejects_parent_descriptor_or_record_drift(tmp_path,monkeypatch,fault):
    value=request();value['phase']='publish';pid=234;fd=9;job=value['owner']['job']
    state=tmp_path/'state';state.mkdir();path=state/'daily-ingest.lock'
    body=launch.publication_record(pid,job['boot_id'],value['attempt_id']);path.write_bytes(body);info=path.stat()
    value['production_lease']=dict(schema='ar-product-evidence-parent-lease-v1',pid=pid,start_ticks=88,fd=fd,
        device=info.st_dev,inode=info.st_ino,boot_id=job['boot_id'],cgroup=job['cgroup'],record_sha256=hashlib.sha256(body).hexdigest())
    status={'fault':None}
    class Proc:
        def __init__(self,text):self.text=text
        def __truediv__(self,other):return Proc(self.text+'/'+str(other))
        def read_text(self):return 'different' if status['fault']=='boot_changed' else job['boot_id']
        def resolve(self):return path
        def stat(self):
            if status['fault']=='parent_dead':raise FileNotFoundError('dead parent')
            if '/fd/' not in self.text:return SimpleNamespace(st_uid=info.st_uid)
            return SimpleNamespace(st_dev=info.st_dev,st_ino=info.st_ino+(status['fault']=='fd_reuse'),
                st_mode=info.st_mode,st_nlink=1,st_uid=info.st_uid)
    monkeypatch.setattr(launch,'Path',lambda p:Proc(str(p)) if str(p).startswith('/proc') else Path(p))
    monkeypatch.setattr(launch,'DATA',tmp_path)
    monkeypatch.setattr(launch,'group',lambda pid:'foreign' if status['fault']=='group_changed' else job['cgroup'])
    monkeypatch.setattr(launch,'ticks',lambda pid:89 if status['fault']=='start_reuse' else 88)
    monkeypatch.setattr(launch,'read',lambda p,maximum,owner:p.read_bytes())
    launch.verify_production_lease(value,info.st_uid)
    status['fault']=fault
    if fault=='record_changed':path.write_bytes(b'foreign')
    if fault=='name_replaced':
        replacement=state/'replacement';replacement.write_bytes(body);replacement.replace(path)
    with pytest.raises((ValueError,FileNotFoundError)):launch.verify_production_lease(value,info.st_uid)


def test_root_timeout_without_terminal_blocks_but_prelaunch_rejection_is_closed(tmp_path,monkeypatch):
    import pi_product_evidence_dispatch as dispatch
    from app_payload_product_evidence_contract import canonical
    work=SimpleNamespace(root=tmp_path/'work');work.root.mkdir();attempt=dict(attempt_id='b'*32)
    monkeypatch.setattr(dispatch.subprocess,'run',lambda *a,**k:pytest.fail('no native query for retained root start'))
    assert dispatch._closed(work,attempt) is True
    (work.root/'launches').mkdir();value=request()
    (work.root/'launches'/('b'*32+'.json')).write_bytes(canonical(value))
    records=tmp_path/'records';records.mkdir();monkeypatch.setattr(dispatch,'RECORDS',records)
    (records/(value['owner']['job']['invocation_id']+'.json')).write_bytes(b'protected root start exists')
    assert dispatch._closed(work,attempt) is False


def test_timeout_without_any_start_record_still_retains_unknown_root_obligation(tmp_path,monkeypatch):
    import subprocess
    import pi_product_evidence_dispatch as dispatch
    work=SimpleNamespace(root=tmp_path/'work',pin=dict(day='2026-11-14',sha256='a'*64))
    work.root.mkdir();attempt=dict(attempt_id='b'*32,phase='snapshot');value=request()
    records=tmp_path/'records';records.mkdir();monkeypatch.setattr(dispatch,'RECORDS',records)
    monkeypatch.setattr(dispatch,'time',SimpleNamespace(monotonic=lambda:1000))
    monkeypatch.setattr(dispatch,'private_directory',lambda path:path.mkdir(exist_ok=True))
    monkeypatch.setattr(dispatch.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired('root-launcher',1800)))
    lifecycle=dict(invoked=False,returned=False)
    with pytest.raises(subprocess.TimeoutExpired):dispatch._launched(work,attempt,value['owner'],lifecycle=lifecycle)
    assert lifecycle==dict(invoked=True,returned=False) and list(records.iterdir())==[]
    # Even an apparently absent systemd unit cannot establish that the timed-out
    # root descendant has exited before its create-only start record.
    assert dispatch._closed(work,attempt) is False
    unit='ar-local-product-evidence-'+attempt['attempt_id']+'.service'
    monkeypatch.setattr(dispatch.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,
        stdout=f'Id={unit}\nLoadState=not-found\nActiveState=inactive\nMainPID=0\nControlGroup=\n'))
    assert dispatch._closed(work,attempt,allow_unstarted=True) is True  # Only conclusively returned rejection.
