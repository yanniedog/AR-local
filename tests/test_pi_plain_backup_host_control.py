"""Failure-path policy tests; no root/Pi/systemd effects."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import json
import os
import stat

import pytest
import pi_plain_backup_core as core
import pi_plain_backup_plan as plan
import pi_plain_drive_resources as resources
import pi_shared_queue as queue
import pi_shared_queue_native as native
import pi_shared_queue_post_hooks as hooks
import pi_shared_queue_store as store_module
from tests.shared_pi_queue_fixtures import MemoryStore,record,_recovery_lock_factory

NONCE='a'*32
NOW=datetime(2026,10,24,7,tzinfo=timezone.utc)


def packet():
    result={'schema':'ar-local-plain-backup-packet-v1','nonce':NONCE,
        'unit':'ar-local-plain-backup-'+NONCE+'.service','manual_plaintext_drive_write':True,
        'data_root':'/srv/ar-local/data',
        'credential_source':'/var/lib/ar-local-drive-backup/credentials/dedicated-20260913-ready3/rclone-verified-ready3.conf',
        'created_at':NOW.isoformat(),'expires_at':(NOW+timedelta(hours=2)).isoformat(),
        'mode':'RUN_ARCHIVE','uid':1000,'gid':1000,'remote':'approved:plaintext-recovery','drive_root_folder_id':'approved-folder-012345'}
    for key in ('queue_closure_sha256','source_closure_sha256','parent_sha256','resources_sha256','bwrap_sha256',
        'credential_sha256','global_hold_sha256','broker_sha256','setpriv_sha256','reconcile_wrapper_sha256','reconcile_original_sha256','reconcile_callback_sha256'):
        result[key]='b'*64
    return result


class Host:
    def __init__(self):
        self.p=packet();self.record=None;self.vm=60;self.events=[];self.live=False;self.boot_id='same'
    def now(self):return NOW
    def packet(self,nonce):assert nonce==NONCE;return self.p
    def boot(self):return self.boot_id
    def intent(self,nonce):return deepcopy(self.record)
    def value(self):return self.vm
    def set_value(self,value):self.events.append(('write',value));self.vm=value
    def admission(self,p):self.events.append('admission');return {'owner':'exact'}
    def recheck(self,p,identity):self.events.append('recheck')
    def save_intent(self,nonce,value,create=False):
        if create:assert self.record is None
        self.events.append(('journal',value['phase']));self.record=deepcopy(value)
    def write_handoff(self,p,identity):self.events.append('handoff')
    def prove_terminal(self,p,identity,recovery):
        self.events.append('terminal')
        if self.live:raise core.Blocked('live worker')
    def observe_terminal(self,p,identity,stage):pass
    def quarantine_credential(self,p):self.events.append('quarantine')
    def complete(self,p,identity,result,readback):self.events.append(('completion',result,readback))
    def no_acquire_identity(self,p):return {'known':'failed-invocation'}


def test_durable_intent_precedes_zero_terminal_precedes_restore_and_quarantine():
    h=Host();core.acquire(h,NONCE)
    assert h.events.index(('journal','PREPARED'))<h.events.index(('write',0))
    assert h.vm==0
    core.finish(h,NONCE)
    assert h.events.index('terminal')<h.events.index('quarantine')<h.events.index(('write',60))
    assert h.events.index(('journal','RESTORING'))<h.events.index(('write',60))
    assert h.events[-1]==('completion','RESTORED',60)


@pytest.mark.parametrize('value',[0,1,59,61,100])
def test_acquire_never_overwrites_unowned_parameter(value):
    h=Host();h.vm=value
    with pytest.raises(core.Blocked):core.acquire(h,NONCE)
    assert not h.events


def test_repeat_nonce_does_not_reacquire():
    h=Host();core.acquire(h,NONCE)
    with pytest.raises(core.Blocked):core.acquire(h,NONCE)
    assert h.events.count(('write',0))==1


def test_live_worker_prevents_restore_and_credential_quarantine():
    h=Host();core.acquire(h,NONCE);h.live=True
    with pytest.raises(core.Blocked):core.finish(h,NONCE,recovery=True)
    assert h.vm==0 and 'quarantine' not in h.events


@pytest.mark.parametrize('value',[1,59,61,100])
def test_unknown_parameter_after_acquire_preserved(value):
    h=Host();core.acquire(h,NONCE);h.vm=value
    with pytest.raises(core.Blocked):core.finish(h,NONCE,recovery=True)
    assert h.vm==value and 'quarantine' not in h.events


def test_unexpected_active60_not_claimed_as_our_restoration():
    h=Host();core.acquire(h,NONCE);h.vm=60
    with pytest.raises(core.Blocked):core.finish(h,NONCE,recovery=True)
    assert 'quarantine' not in h.events


@pytest.mark.parametrize('crash_phase,value',[('PREPARED',60),('PREPARED',0),('RESTORING',0),('RESTORING',60)])
def test_crash_recovery_handles_journal_before_or_after_kernel_write(crash_phase,value):
    h=Host();core.acquire(h,NONCE);h.record['phase']=crash_phase;h.vm=value
    core.finish(h,NONCE,recovery=True)
    assert h.vm==60 and h.record['phase']=='RESTORED'


def test_completed_old_intent_cannot_authorize_new_zero():
    h=Host();core.acquire(h,NONCE);core.finish(h,NONCE);h.vm=0
    with pytest.raises(core.Blocked):core.finish(h,NONCE,recovery=True)
    assert h.vm==0


def test_new_boot_closes_only_kernel_already_reset60():
    h=Host();core.acquire(h,NONCE);h.boot_id='new'
    with pytest.raises(core.Blocked):core.finish(h,NONCE,recovery=True)
    h.vm=60;core.finish(h,NONCE,recovery=True)
    assert ('write',60) not in h.events


def test_preacquire_failure_can_close_known_terminal_without_new_backup_requirement():
    h=Host();core.finish(h,NONCE,recovery=True)
    assert h.events==['terminal','quarantine',('completion','NOT_ACQUIRED',60)]
    assert not any('backup' in key for key in h.p if key!='manual_plaintext_drive_write')


def test_no_intent_never_restores_another_zero():
    h=Host();h.vm=0
    with pytest.raises(core.Blocked):core.finish(h,NONCE,recovery=True)
    assert not h.events


@pytest.mark.parametrize('key,value',[('manual_plaintext_drive_write',False),('uid',0),('setpriv_sha256',''),
    ('remote','other:anywhere'),('drive_root_folder_id',''),('data_root','/'),('nonce','b'*32)])
def test_packet_specific_scope_is_required(key,value):
    p=packet();p[key]=value
    with pytest.raises(core.Blocked):core.validate_packet(p,NONCE,NOW)


def test_six_hour_and_natural_ingest_boundaries():
    p=packet();p['expires_at']=(NOW+timedelta(hours=7)).isoformat()
    with pytest.raises(core.Blocked):core.validate_packet(p,NONCE,NOW)
    start=datetime(2026,10,24,13,10,tzinfo=timezone.utc) # 00:10 Hobart
    p=packet();p.update(created_at=start.isoformat(),expires_at=(start+timedelta(minutes=30)).isoformat())
    with pytest.raises(core.Blocked):core.validate_packet(p,NONCE,start)


def host_sample(**changes):
    value={'available_bytes':8*1024**3,'swap_out_pages':5,'swap_in_pages':10,
        'page_size_bytes':16384,'psi_avg10':0.0};value.update(changes);return value


@pytest.mark.parametrize('changes,reason',[
    ({'swap_out_pages':6},'host_swap_out_activity'),({'swap_out_pages':4},'host_swap_counter_reset'),
    ({'swap_in_pages':1035},'host_cold_swap_in_budget'),({'page_size_bytes':4096},'page_size_changed'),
    ({'available_bytes':2500*1024**2},'host_reserve_headroom'),({'psi_avg10':10},'host_memory_pressure')])
def test_unchanged_host_resource_guards(changes,reason):
    assert resources.host_violation(host_sample(**changes),host_sample(),host_sample())==reason


def test_service_and_sandbox_commands_have_fixed_privilege_boundary_and_new_operation():
    p=packet();argv=resources.sandbox_argv(p)
    assert '--unshare-pid' in argv and '--unshare-ipc' in argv and '--unshare-user' not in argv
    assert argv[argv.index('--ro-bind')+1:argv.index('--ro-bind')+3]==['/','/']
    assert '--no-new-privs' in argv and '--clear-groups' in argv
    assert argv[argv.index('--bind')+1].endswith('/sandbox')
    assert argv[argv.index('--operation')+1].endswith('/sandbox/archive')
    assert argv[argv.index('--attestation-fd')+1]=='3'
    profile=plan.service_plan(NONCE)
    assert profile['properties']['ExecStopPost'].endswith('recover '+NONCE)
    assert profile['properties']['ExecStopPost'].startswith('+/usr/bin/python3 -I -B ')
    assert profile['properties']['NoNewPrivileges']=='no'
    assert profile['argv'][-1]==NONCE and '--resource' in profile['argv']
    assert not any(x in json.dumps(profile) for x in ('enable','restart','mkfs','dd '))


def backup_job(**changes):
    return record(unit='ar-local-plain-backup-'+NONCE+'.service',
        cgroup='/system.slice/ar-local-plain-backup-'+NONCE+'.service',resources=['ar-local','host'],**changes)


def test_retained_plain_service_never_uses_ingest_hook_contract_or_live_release():
    job=backup_job(state='running');assert job['unit'] not in store_module.FIXED_AR_UNITS
    assert not queue.release(MemoryStore([job]),job)
    assert not hooks.retained_stop('ar-local-plain-backup-123.service')


@pytest.mark.parametrize('proved',[False,True])
def test_reconcile_requires_root_completion_before_native_release(monkeypatch,proved):
    job=backup_job(state='running');s=MemoryStore([job]);s.supervisor.ownership=lambda job:'gone'
    calls=[];monkeypatch.setattr(store_module,'completion_proved',lambda job:proved)
    monkeypatch.setattr(native,'clear_native_manual',lambda job:calls.append(job['id']) or True)
    assert s.reconcile(s.state) is proved
    assert calls==([job['id']] if proved else [])
    assert len(s.state['jobs'])==(0 if proved else 1)


@pytest.mark.skipif(os.name!='posix',reason='Linux nofollow/inode/native-fsync semantics')
def test_native_handoff_preserves_same_manual_bytes_but_changes_inode(tmp_path,monkeypatch):
    job=backup_job(pid=os.getpid());path=tmp_path/'native.lock'
    body=f"pid={job['pid']}\nboot_id={job['boot_id']}\nrole=shared-pi-host-task:{job['id']}\nrecovery=manual\n".encode()
    path.write_bytes(body);old=path.stat().st_ino
    monkeypatch.setattr(native,'approval',lambda *a,**kw:{})
    assert native.retain_native_for_stop_hook(job,path,_recovery_lock_factory)
    assert path.read_bytes()==body and path.stat().st_ino!=old and stat.S_IMODE(path.stat().st_mode)==0o600


@pytest.mark.skipif(os.name!='posix',reason='Linux nofollow/inode/native-fsync semantics')
def test_native_handoff_does_not_remove_foreign_preexisting_scratch(tmp_path,monkeypatch):
    job=backup_job(pid=os.getpid());path=tmp_path/'native.lock'
    body=f"pid={job['pid']}\nboot_id={job['boot_id']}\nrole=shared-pi-host-task:{job['id']}\nrecovery=manual\n".encode()
    path.write_bytes(body);scratch=path.with_name('.native.lock.plain-handoff-'+job['id']);scratch.write_bytes(b'preserve')
    monkeypatch.setattr(native,'approval',lambda *a,**kw:{})
    with pytest.raises(FileExistsError):native.retain_native_for_stop_hook(job,path,_recovery_lock_factory)
    assert scratch.read_bytes()==b'preserve' and path.read_bytes()==body

def test_busy_native_admission_does_not_leave_persistent_stop_hook_lease(monkeypatch):
    from contextlib import contextmanager
    job=backup_job(state='running');s=MemoryStore([job]);events=[]
    @contextmanager
    def lease(*args):
        events.append('lock')
        try:yield
        finally:events.append('unlock')
    monkeypatch.setattr(native,'retain_native_for_stop_hook',lambda job:events.append('retain'))
    with pytest.raises(native.NativeHostBusy):
        with native.NativeHostGuard(s,lock_factory=lambda:lease,ready=lambda units:False,marker=lambda job:None).hold(job):
            pytest.fail('busy child launched')
    assert events==['lock','unlock']


def test_preacquire_terminal_proof_does_not_require_a_never_acquired_native_file(monkeypatch):
    import pi_plain_backup_linux as linux
    h=linux.Host(NONCE);root=os.getpid();p=packet()
    h._show=lambda unit:{'LoadState':'loaded','InvocationID':'old','ControlPID':str(root),'MainPID':'0'}
    h._members=lambda group:[root]
    h.boot=lambda:'same'
    h._job=lambda *a,**kw:pytest.fail('no native/queue reacquisition permitted in stop hook')
    h.prove_terminal(p,{'invocation':'old','cgroup':'known','boot_id':'same'},recovery=True)
