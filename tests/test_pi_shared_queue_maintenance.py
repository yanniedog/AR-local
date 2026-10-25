"""Authority, native-service and terminal safety tests for maintenance retention."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import pytest
import pi_shared_queue_post_hooks as hooks
import pi_shared_queue_store as store
import pi_shared_queue_native as native
import pi_plain_backup_reconcile as reclaim
from tests.shared_pi_queue_fixtures import record,FakeSupervisor,MemoryStore

NONCE='a'*32
PLAN='b'*64
IMAGE_UNIT='ar-local-plain-backup-'+NONCE+'.service'
CI_UNIT='ar-local-ci-activate-'+PLAN+'.service'
NOW=datetime(2030,1,1,tzinfo=timezone.utc)
sha=lambda body:hashlib.sha256(body).hexdigest()
canonical=lambda value:json.dumps(value,separators=(',',':')).encode()


def job(unit=CI_UNIT,**changes):
    return record(unit=unit,cgroup='/system.slice/'+unit,resources=['ar-local','host'],
                  cpu_slots=2,max_duration_seconds=1800,**changes)


def ci_fixture(monkeypatch):
    body=b'root-qualified source'
    modules={name:sha(body) for name in ('pi_ci_release.py','pi_ci_resources.py','pi_ci_activate.py','pi_ci_snapshot.py','pi_ci_worker.py')}
    queue={name:sha(body) for name in ('pi_shared_queue.py','pi_shared_queue_policy.py','pi_shared_queue_store.py',
        'pi_shared_queue_native.py','pi_shared_queue_post_hooks.py','pi_shared_queue_stop_hook.py')}
    profile={'schema':'ar-local-ci-runtime-v1','queue_contract':'ci-retained-v1','modules':modules,'queue_files':queue}
    rows={hooks.CI_RUNTIME:canonical(profile),hooks.CI_CONTROL:body}
    rows.update({hooks.CI_ROOT/name:body for name in modules})
    rows.update({hooks.QUEUE_ROOT/name:body for name in queue})
    authority={'schema':'ar-local-ci-authority-v1','plan':PLAN,'unit':CI_UNIT,'scope':'activate-immutable-d027',
        'expires_at':'2099-01-01T00:00:00+00:00','target_commit':'c'*40,'control_sha256':sha(body),
        'adapter_sha256':sha(body),'runtime_profile_sha256':sha(rows[hooks.CI_RUNTIME]),
        'queue_argv_sha256':sha(canonical(hooks.ci_start(PLAN)))}
    rows[hooks.CI_STATE/'authority'/(PLAN+'.json')]=canonical(authority)
    monkeypatch.setattr(hooks,'root_bytes',lambda path,maximum=1048576:rows[Path(path)])
    return authority,rows


def image_fixture(monkeypatch):
    rows={hooks.IMAGE_ROOT/name:b'fixed image root source' for name in ('parent.py','broker.py','pi_system_guard_resources.py')}
    authority={'schema':'ar-local-system-recovery-authority-v1','nonce':NONCE,'unit':IMAGE_UNIT,
        'manual_system_recovery':True,'mode':'RUN_ARCHIVE','phase':'archive','expires_at':'2099-01-01T00:00:00+00:00',
        'source_closure_sha256':'d'*64,'parent_sha256':sha(rows[hooks.IMAGE_ROOT/'parent.py']),
        'resources_sha256':sha(rows[hooks.IMAGE_ROOT/'pi_system_guard_resources.py']),
        'broker_sha256':sha(rows[hooks.IMAGE_ROOT/'broker.py']),'queue_argv_sha256':'e'*64}
    rows[hooks.IMAGE_HANDOFF/NONCE/'approval.json']=canonical(authority)
    monkeypatch.setattr(hooks,'_present',lambda path:Path(path) in rows)
    monkeypatch.setattr(hooks,'root_bytes',lambda path,maximum=1048576:rows[Path(path)])
    return authority,rows


def publish_authority(authority,rows):
    path=hooks.CI_STATE/'authority'/(PLAN+'.json') if authority['schema']=='ar-local-ci-authority-v1' else hooks.IMAGE_HANDOFF/NONCE/'approval.json'
    rows[path]=canonical(authority)


def native_row(argv,flags=None):
    return [argv[0],argv,flags or [],0,0,0,0,0,0,0]


def commands(start,stop):
    return {'ExecStartEx':[native_row(start)],'ExecStopPostEx':[native_row(stop,['privileged'])],
        'ExecConditionEx':[],'ExecStartPreEx':[],'ExecStartPostEx':[],'ExecStopEx':[]}


def service_fixture():
    values={name:('s',value) for name,value in {'User':'pi','Group':'pi','Type':'notify','NotifyAccess':'main',
        'KillMode':'control-group','ProtectSystem':'strict','ProtectHome':'yes','WorkingDirectory':'/'}.items()}
    values.update({name:('b',value) for name,value in {'NoNewPrivileges':False,'SendSIGKILL':True,
        'PrivateTmp':True,'ProtectControlGroups':True}.items()})
    values.update({name:('t',value) for name,value in {'RuntimeMaxUSec':1800000000,'TimeoutStartUSec':960000000,
        'TimeoutStopUSec':900000000,'CPUQuotaPerSecUSec':2000000,'LimitAS':2147483648,
        'MemoryHigh':805306368,'MemoryMax':1073741824,'MemorySwapMax':0}.items()})
    values['ReadWritePaths']=('as',['/srv/ar-local','/var/lib/ar-local-ci','/var/lib/shared-pi-queue'])
    values['Environment']=('as',['HOME=/nonexistent','PATH=/usr/sbin:/usr/bin:/sbin:/bin'])
    values['EnvironmentFiles']=('a(sb)',[])
    return values


def native_run(command_rows,properties=None):
    def run(argv,**kwargs):
        name=argv[-1]
        if name in command_rows:kind,data='a(sasasttttuii)',command_rows[name]
        else:kind,data=properties[name]
        return SimpleNamespace(stdout=json.dumps({'type':kind,'data':data}),returncode=0)
    return run


def test_names_alone_never_admit_ci_or_image(monkeypatch):
    assert hooks.retained_stop(CI_UNIT) and hooks.retained_stop(IMAGE_UNIT)
    assert CI_UNIT not in store.FIXED_AR_UNITS and IMAGE_UNIT not in store.FIXED_AR_UNITS
    assert not hooks.retained_stop('ar-local-ci-activate-'+NONCE+'.service')
    monkeypatch.setattr(hooks,'root_bytes',lambda *args:(_ for _ in ()).throw(FileNotFoundError()))
    for unit in (CI_UNIT,IMAGE_UNIT):
        with pytest.raises((ValueError,OSError)):hooks.approval(unit,current=True)


def test_ci_approval_binds_all_installed_root_modules_and_queue_closure(monkeypatch):
    authority,rows=ci_fixture(monkeypatch)
    assert hooks.approval(CI_UNIT,current=True,now=NOW)==authority
    rows[hooks.CI_ROOT/'pi_ci_resources.py']=b'changed root helper'
    with pytest.raises(ValueError):hooks.approval(CI_UNIT)


@pytest.mark.parametrize('key,value',[('scope','other'),('plan','c'*64),('unit',IMAGE_UNIT),
    ('target_commit','x'*40),('expires_at','2030-01-01T01:00:00+01:00'),('queue_argv_sha256','0'*64)])
def test_ci_approval_rejects_wrong_scope_identity_expiry_and_command(monkeypatch,key,value):
    authority,rows=ci_fixture(monkeypatch);authority[key]=value;publish_authority(authority,rows)
    with pytest.raises(ValueError):hooks.approval(CI_UNIT,current=True,now=NOW)


def test_ci_expiry_blocks_new_admission_but_not_bound_terminal_cleanup(monkeypatch):
    authority,rows=ci_fixture(monkeypatch);authority['expires_at']='2029-01-01T00:00:00+00:00';publish_authority(authority,rows)
    with pytest.raises(ValueError):hooks.approval(CI_UNIT,current=True,now=NOW)
    assert hooks.approval(CI_UNIT)==authority


def test_ci_native_fixed_execution_hooks_and_loaded_profile_are_qualified(monkeypatch):
    ci_fixture(monkeypatch)
    rows=commands(hooks.ci_start(PLAN),['/usr/bin/python3','-I',str(hooks.CI_CONTROL),'--finalize',PLAN])
    assert hooks.verify_plain_service(CI_UNIT,native_run(rows,service_fixture()))['plan']==PLAN
    rows['ExecStartPreEx']=[native_row(['/bin/true'])]
    with pytest.raises(ValueError):hooks.verify_plain_service(CI_UNIT,native_run(rows,service_fixture()))


@pytest.mark.parametrize('key,value',[('NoNewPrivileges',('b',True)),('User',('s','root')),
    ('RuntimeMaxUSec',('t',2700000000)),('TimeoutStopUSec',('t',901000000)),
    ('MemorySwapMax',('t',1)),('PrivateTmp',('s','yes')),
    ('EnvironmentFiles',('a(sb)',[['/tmp/foreign',False]])),
    ('ReadWritePaths',('as',['/srv/ar-local','/var/lib/ar-local-ci','/var/lib/shared-pi-queue','/etc']))])
def test_ci_native_profile_mutation_cannot_get_privileged_retention(monkeypatch,key,value):
    ci_fixture(monkeypatch);properties=service_fixture();properties[key]=value
    rows=commands(hooks.ci_start(PLAN),['/usr/bin/python3','-I',str(hooks.CI_CONTROL),'--finalize',PLAN])
    with pytest.raises(ValueError):hooks.verify_plain_service(CI_UNIT,native_run(rows,properties))


def test_ci_fixed_command_cannot_be_replaced_even_with_corresponding_root_hash(monkeypatch):
    authority,rows=ci_fixture(monkeypatch)
    authority['queue_argv_sha256']=sha(canonical(['/bin/sh']));publish_authority(authority,rows)
    with pytest.raises(ValueError):hooks.approval(CI_UNIT)


def test_image_and_plain_authority_cannot_ambiguously_share_nonce(monkeypatch):
    authority,rows=image_fixture(monkeypatch)
    assert hooks.approval(IMAGE_UNIT)==authority
    rows[hooks.HANDOFF/NONCE/'approval.json']=b'other root authority'
    with pytest.raises(ValueError):hooks.approval(IMAGE_UNIT)


@pytest.mark.parametrize('changes',[{'manual_system_recovery':False},{'phase':'unknown'},
    {'phase':'PROBE','mode':'RUN_ARCHIVE'},{'phase':'archive','mode':'PROBE'},
    {'phase':'upload','manual_image_drive_write':False},{'source_closure_sha256':'x'}])
def test_image_authority_has_distinct_scope_phase_and_upload_permission(monkeypatch,changes):
    authority,rows=image_fixture(monkeypatch);authority.update(changes);publish_authority(authority,rows)
    with pytest.raises(ValueError):hooks.approval(IMAGE_UNIT)


def test_image_cold_fetch_requires_explicit_read_and_quarantined_credential(monkeypatch):
    authority,rows=image_fixture(monkeypatch)
    authority.update(phase='fetch',manual_image_drive_read=True)
    publish_authority(authority,rows)
    assert hooks.approval(IMAGE_UNIT)==authority
    j=job(IMAGE_UNIT);terminal=image_terminal(j,authority)
    rows[hooks.IMAGE_HANDOFF/NONCE/'completion.json']=canonical(terminal)
    assert not hooks.completion_proved(j)
    terminal['credential_custody']='QUARANTINED'
    rows[hooks.IMAGE_HANDOFF/NONCE/'completion.json']=canonical(terminal)
    assert hooks.completion_proved(j)
    authority['manual_image_drive_write']=True;publish_authority(authority,rows)
    with pytest.raises(ValueError):hooks.approval(IMAGE_UNIT)
    authority.pop('manual_image_drive_write');authority['manual_image_drive_read']=False
    publish_authority(authority,rows)
    with pytest.raises(ValueError):hooks.approval(IMAGE_UNIT)


def test_image_stop_hook_uses_distinct_fixed_no_site_root_broker(monkeypatch):
    authority,rows=image_fixture(monkeypatch);start=['/usr/bin/python3','queue','image'];authority['queue_argv_sha256']=sha(canonical(start));publish_authority(authority,rows)
    stop=['/usr/bin/python3','-I','-S','-B',str(hooks.IMAGE_ROOT/'broker.py'),'recover',NONCE]
    props=commands(start,stop)
    assert hooks.verify_plain_service(IMAGE_UNIT,native_run(props))['phase']=='archive'
    stop.remove('-S');props=commands(start,stop)
    with pytest.raises(ValueError):hooks.verify_plain_service(IMAGE_UNIT,native_run(props))


def ci_terminal(job):
    return {'schema':'ar-local-ci-terminal-v1','plan':PLAN,'result':'PASS','accepted_release_sha256':'f'*64,
        'binding':{'job_id':job['id'],'unit':job['unit'],'invocation':job['invocation_id'],'cgroup':job['cgroup'],
            'native_device':1,'native_inode':2,'owner_pid':job['pid'],'owner_ticks':job['start_ticks'],'boot_id':job['boot_id']},
        'restored_timers':True,'previous_checkout':'RETAINED_COMPLETE','untrusted_processes_gone':True,'code_restore_proved':True}


def test_ci_root_terminal_requires_exact_job_and_successor_native_inode(monkeypatch):
    authority,rows=ci_fixture(monkeypatch);j=job();terminal=ci_terminal(j)
    rows[hooks.CI_STATE/'completed'/(PLAN+'.json')]=canonical(terminal)
    assert hooks.completion_proved(j) and hooks.native_completion_proved(j,(1,2))
    assert not hooks.native_completion_proved(j,(1,3))
    terminal['binding']['owner_ticks']+=1;rows[hooks.CI_STATE/'completed'/(PLAN+'.json')]=canonical(terminal)
    assert not hooks.completion_proved(j)


@pytest.mark.parametrize('key,value',[('restored_timers',False),('previous_checkout','MISSING'),
    ('untrusted_processes_gone',False),('code_restore_proved',False),('accepted_release_sha256',''),
    ('result','AMBIGUOUS')])
def test_ci_missing_terminal_safety_proof_retains_claim(monkeypatch,key,value):
    _,rows=ci_fixture(monkeypatch);j=job();terminal=ci_terminal(j);terminal[key]=value
    rows[hooks.CI_STATE/'completed'/(PLAN+'.json')]=canonical(terminal)
    assert not hooks.completion_proved(j)


@pytest.mark.parametrize('result',['ROLLED_BACK','FAILED_BEFORE_SWITCH','ABORTED_RESTORED'])
def test_ci_restored_terminal_releases_coordination_without_claiming_acceptance(monkeypatch,result):
    _,rows=ci_fixture(monkeypatch);j=job();terminal=ci_terminal(j);terminal['result']=result;terminal.pop('accepted_release_sha256')
    rows[hooks.CI_STATE/'completed'/(PLAN+'.json')]=canonical(terminal)
    assert hooks.completion_proved(j)


def image_terminal(j,authority):
    return {'schema':'ar-local-system-recovery-root-completion-v1','nonce':NONCE,'unit':j['unit'],'job_id':j['id'],
        'invocation':j['invocation_id'],'boot_id':j['boot_id'],'owner_pid':j['pid'],'owner_ticks':j['start_ticks'],
        'phase':authority['phase'],'source_closure_sha256':authority['source_closure_sha256'],
        'result':'RESTORED','readback':60,'untrusted_processes_gone':True,'credential_custody':'NOT_EXPOSED',
        'stop_post_verified':True,'owned_loop_terminal':True,'writers_restored':True}


@pytest.mark.parametrize('field',['owned_loop_terminal','writers_restored','untrusted_processes_gone'])
def test_image_terminal_requires_own_loop_terminal_and_writer_restoration(monkeypatch,field):
    authority,rows=image_fixture(monkeypatch);j=job(IMAGE_UNIT);terminal=image_terminal(j,authority)
    rows[hooks.IMAGE_HANDOFF/NONCE/'completion.json']=canonical(terminal)
    assert hooks.completion_proved(j)
    terminal[field]=False;rows[hooks.IMAGE_HANDOFF/NONCE/'completion.json']=canonical(terminal)
    assert not hooks.completion_proved(j)


def test_plain_schema_cannot_release_image_authority(monkeypatch):
    authority,rows=image_fixture(monkeypatch);j=job(IMAGE_UNIT);terminal=image_terminal(j,authority)
    terminal.update(schema='ar-local-plain-backup-root-completion-v1',credential_quarantined=True)
    rows[hooks.IMAGE_HANDOFF/NONCE/'completion.json']=canonical(terminal)
    assert not hooks.completion_proved(j)


def test_ci_stop_grace_is_qualified_without_changing_ingest_fixed_units(monkeypatch):
    called=[];monkeypatch.setattr(hooks,'verify_plain_service',lambda unit:called.append(unit))
    assert hooks.stop_grace(CI_UNIT,45)==900 and called==[CI_UNIT]
    assert hooks.stop_grace(IMAGE_UNIT,45)==45
    assert hooks.stop_grace('ar-local-queue-task-foreign.service',45)==45
    monkeypatch.setattr(hooks,'verify_plain_service',lambda unit:(_ for _ in ()).throw(ValueError('unapproved')))
    with pytest.raises(ValueError):hooks.stop_grace(CI_UNIT,45)


def test_ci_supervisor_accepts_only_qualified_separate_start_execution_stop_budgets(monkeypatch):
    s=FakeSupervisor();s.cgroup=lambda pid:'/system.slice/'+CI_UNIT
    s.details.update(ControlGroup='/system.slice/'+CI_UNIT,Type='notify',NotifyAccess='main',RuntimeMaxUSec='1800s',
        TimeoutStartUSec='960s',TimeoutStopUSec='900s',CPUQuotaPerSecUSec='2s')
    monkeypatch.setattr(store,'verify_plain_service',lambda unit:None)
    monkeypatch.setattr(store,'stop_grace',lambda unit,default:900 if unit==CI_UNIT else default)
    assert s.current(2,2760,execution_runtime=1800,wait_seconds=900)['unit']==CI_UNIT
    s.details['RuntimeMaxUSec']='2700s'
    with pytest.raises(ValueError):s.current(2,2760,execution_runtime=1800,wait_seconds=900)


def test_ci_root_completion_cannot_release_before_empty_cgroup_or_with_missing_proof(monkeypatch):
    j=job(state='running');s=MemoryStore([j]);calls=[]
    monkeypatch.setattr(store,'completion_proved',lambda job:False)
    monkeypatch.setattr(native,'clear_native_manual',lambda job:calls.append(job['id']) or True)
    s.supervisor.ownership=lambda job:'gone'
    assert not s.reconcile(s.state) and not calls and len(s.state['jobs'])==1
    monkeypatch.setattr(store,'completion_proved',lambda job:True);s.supervisor.ownership=lambda job:'present'
    s.reconcile(s.state);assert not calls and len(s.state['jobs'])==1
    s.supervisor.ownership=lambda job:'gone';assert s.reconcile(s.state) and calls==[j['id']]


def test_image_recovery_callback_is_independent_even_if_existing_pass_raises(monkeypatch):
    calls=[]
    monkeypatch.setattr(reclaim,'reconcile_owned',lambda *a:(_ for _ in ()).throw(RuntimeError('damaged journal')))
    monkeypatch.setattr(reclaim,'reconcile_image',lambda *a:calls.append('image') or 0)
    assert reclaim.reconcile()==2 and calls==['image']


def test_absent_image_registry_preserves_existing_callback_behavior(monkeypatch):
    monkeypatch.setattr(reclaim,'IMAGE_REGISTRY',Path('/nonexistent-root-image-registry'))
    assert reclaim.reconcile_image()==0


def registry_fixture(monkeypatch):
    source=b'root image callback';wrapper=b'root loaded wrapper'
    registry={'schema':'ar-local-system-recovery-reconcile-v1','callback':str(reclaim.IMAGE/'reconcile.py'),
        'callback_sha256':sha(source),'source_closure_sha256':'f'*64,'wrapper_sha256':sha(wrapper)}
    monkeypatch.setattr(Path,'lstat',lambda path:SimpleNamespace())
    monkeypatch.setattr(hooks,'root_json',lambda path:registry)
    monkeypatch.setattr(reclaim,'protected',lambda path:source if path==reclaim.IMAGE/'reconcile.py' else wrapper)
    return registry


def test_image_registry_selects_only_fixed_hash_bound_callback_with_five_second_bound(monkeypatch):
    registry=registry_fixture(monkeypatch);calls=[]
    def run(argv,**kwargs):
        calls.append(argv);assert kwargs['timeout']==5;return SimpleNamespace(returncode=0)
    assert reclaim.reconcile_image(run)==0
    assert calls==[['/usr/bin/python3','-I','-S','-B',str(reclaim.IMAGE/'reconcile.py')]]
    registry['callback']='/bin/sh'
    with pytest.raises(RuntimeError):reclaim.reconcile_image(run)


@pytest.mark.parametrize('field',['callback_sha256','wrapper_sha256'])
def test_image_registry_rejects_changed_root_callback_or_loaded_wrapper(monkeypatch,field):
    registry=registry_fixture(monkeypatch);registry[field]='0'*64
    with pytest.raises(RuntimeError):reclaim.reconcile_image(lambda *a,**kw:pytest.fail('unqualified callback executed'))


@pytest.mark.skipif(os.name!='posix',reason='real native lease inode and nofollow semantics')
def test_ci_successor_inode_is_bound_before_spawn_and_cleared_only_by_matching_root_terminal(tmp_path,monkeypatch):
    from tests.shared_pi_queue_fixtures import _recovery_lock_factory
    _,rows=ci_fixture(monkeypatch);j=job(pid=os.getpid());path=tmp_path/'native.lock'
    body=(f"pid={j['pid']}\nboot_id={j['boot_id']}\nrole=shared-pi-host-task:{j['id']}\nrecovery=manual\n").encode()
    path.write_bytes(body);original=path.stat().st_ino
    assert native.retain_native_for_stop_hook(j,path,_recovery_lock_factory)
    current=path.stat();assert current.st_ino!=original and path.read_bytes()==body
    terminal=ci_terminal(j);terminal['binding'].update(native_device=current.st_dev,native_inode=original)
    rows[hooks.CI_STATE/'completed'/(PLAN+'.json')]=canonical(terminal)
    assert not native.clear_native_manual(j,path,_recovery_lock_factory)
    assert path.read_bytes()==body
    terminal['binding']['native_inode']=current.st_ino
    rows[hooks.CI_STATE/'completed'/(PLAN+'.json')]=canonical(terminal)
    assert native.clear_native_manual(j,path,_recovery_lock_factory) and not path.exists()


@pytest.mark.parametrize('change',['missing_privileged','extra_flag','different_executable'])
def test_ci_native_stop_privilege_and_executable_identity_are_not_inferred_from_argv(monkeypatch,change):
    ci_fixture(monkeypatch)
    rows=commands(hooks.ci_start(PLAN),['/usr/bin/python3','-I',str(hooks.CI_CONTROL),'--finalize',PLAN])
    if change=='missing_privileged':rows['ExecStopPostEx'][0][2]=[]
    elif change=='extra_flag':rows['ExecStopPostEx'][0][2]=['privileged','ignore-failure']
    else:rows['ExecStartEx'][0][0]='/bin/false'
    with pytest.raises(ValueError):hooks.verify_plain_service(CI_UNIT,native_run(rows,service_fixture()))
