"""Packet-clipped native runtime and recovery policy; no Pi/process effects."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import stat
from zoneinfo import ZoneInfo

import pytest

import pi_plain_backup_core as core
import pi_plain_backup_linux as linux
import pi_plain_backup_packet as builder
import pi_plain_backup_plan as plan
import pi_plain_drive_resources as resources
from pi_shared_queue_policy import admission, STOP_GRACE_SECONDS
from tests.shared_pi_queue_fixtures import record
from tests.test_pi_plain_backup_host_control import NONCE, packet, host_sample


def timed_packet(start, mode='RUN_ARCHIVE'):
    value=packet()
    end=builder.expiry_for(mode,start)
    value.update(mode=mode,created_at=start.isoformat(),expires_at=end.isoformat(),
        runtime_seconds=int((end-start).total_seconds()))
    return value


def test_actual_queue_admits_1845_clipped_packet_and_rejects_six_hour_reservation():
    start=datetime(2026,10,24,18,45,tzinfo=ZoneInfo('Australia/Hobart')).astimezone(timezone.utc)
    value=timed_packet(start)
    result=plan.service_plan(NONCE,packet=value)
    runtime=core.packet_runtime_seconds(value)
    assert runtime==20399
    assert result['argv'][result['argv'].index('--max-runtime')+1]==str(runtime)
    assert result['properties']['RuntimeMaxSec']==str(runtime)
    assert result['argv'][result['argv'].index('--wait-timeout')+1]=='0'
    assert result['properties']['TimeoutStartSec']=='60'
    job=record(unit=value['unit'],resources=['ar-local','host'],max_duration_seconds=runtime,
        ready_since=start.isoformat())
    assert admission(job,[job],start)==(True,'admitted')
    old=dict(job,max_duration_seconds=21600)
    assert admission(old,[old],start)==(False,'would-cross-ingest-start')
    quiet=datetime(2026,10,25,0,30,tzinfo=ZoneInfo('Australia/Hobart')).astimezone(timezone.utc)
    assert start+timedelta(seconds=runtime+STOP_GRACE_SECONDS)<quiet
    # A delayed dispatch never gains a window by shortening or bypassing admission.
    assert admission(job,[job],start+timedelta(minutes=5))==(False,'would-cross-ingest-start')
    assert plan.service_plan(NONCE,packet=result['runtime_inputs'])==result


@pytest.mark.parametrize('date',[(2026,7,1),(2026,10,3),(2026,10,4),(2027,4,3),(2027,4,4)])
def test_packet_window_is_derived_in_utc_across_hobart_dates_and_dst(date):
    start=datetime(*date,23,10,0,123456,tzinfo=ZoneInfo('Australia/Hobart')).astimezone(timezone.utc)
    value=timed_packet(start)
    runtime=core.packet_runtime_seconds(value)
    end=datetime.fromisoformat(value['expires_at'])
    local_end=end.astimezone(ZoneInfo('Australia/Hobart'))
    assert local_end.date()==(start.astimezone(local_end.tzinfo)+timedelta(days=1)).date()
    assert (local_end.hour,local_end.minute,local_end.second)==(0,24,59)
    assert 15<=runtime<=21600 and runtime<=(end-start).total_seconds()<runtime+1
    core.validate_packet(value,NONCE,start)


@pytest.mark.parametrize('seconds',[120,30,15])
def test_probe_runtime_is_unchanged_or_exactly_clipped(seconds):
    start=datetime(2026,10,24,7,tzinfo=timezone.utc)
    value=timed_packet(start,'PROBE')
    value.update(expires_at=(start+timedelta(seconds=seconds)).isoformat(),runtime_seconds=seconds)
    core.validate_packet(value,NONCE,start)
    result=plan.service_plan(NONCE,packet=value,mode='PROBE')
    assert result['properties']['RuntimeMaxSec']==str(seconds)
    assert result['argv'][result['argv'].index('--wait-timeout')+1]=='0'


@pytest.mark.parametrize('runtime',[True,False,1,14,7199,7201,21601,7200.0,'7200',None])
def test_new_runtime_cannot_be_an_arbitrary_short_override_or_invalid_type(runtime):
    value=packet();value['runtime_seconds']=runtime
    with pytest.raises(core.Blocked):core.packet_runtime_seconds(value)
    with pytest.raises(core.Blocked):core.packet_runtime_seconds(value,allow_legacy=True)


def test_missing_runtime_is_terminal_legacy_recovery_only_and_expiry_never_extends():
    value=packet();del value['runtime_seconds']
    with pytest.raises(core.Blocked,match='explicit packet runtime'):
        core.validate_packet(value,NONCE,datetime.fromisoformat(value['created_at']))
    assert core.packet_runtime_seconds(value,allow_legacy=True)==21600
    value.update(mode='PROBE',expires_at=(datetime.fromisoformat(value['created_at'])+timedelta(seconds=120)).isoformat())
    assert core.packet_runtime_seconds(value,allow_legacy=True)==120
    value=packet();expiry=datetime.fromisoformat(value['expires_at'])
    with pytest.raises(core.Blocked,match='expired'):
        core.validate_packet(value,NONCE,expiry)
    with pytest.raises(core.Blocked,match='insufficient remaining'):
        core.validate_packet(value,NONCE,expiry-timedelta(seconds=14))


@pytest.mark.parametrize('value,seconds',[('2h',7200),('120min',7200),('7200s',7200),
    ('5h 39min 59s',20399),('5h39min59s',20399),('2min',120),('15s',15),('6h 0min 0s',21600)])
def test_native_systemd_runtime_format_is_compared_as_exact_microseconds(value,seconds):
    assert core.parse_runtime_microseconds(value)==seconds*1000000


@pytest.mark.parametrize('value',['infinity','',None,True,'6h 1s','0s','1h1h','1s 2min',
    '2min\n1s','1.5h','1000000us','1d','1s garbage','1h '*50])
def test_native_runtime_unknown_duplicate_fractional_and_oversized_evidence_is_denied(value):
    with pytest.raises(core.Blocked):core.parse_runtime_microseconds(value)


def job_fixture(monkeypatch,value,runtime):
    job=record(unit=value['unit'],cgroup='/system.slice/'+value['unit'],resources=['ar-local','host'],
        state='running',max_duration_seconds=runtime)
    raw=json.dumps({'jobs':[job]}).encode()
    monkeypatch.setattr(linux.os,'O_NOFOLLOW',0,raising=False)
    monkeypatch.setattr(linux.os,'open',lambda *a,**k:12345)
    monkeypatch.setattr(linux.os,'fstat',lambda fd:SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=1000,st_nlink=1,st_size=len(raw)))
    monkeypatch.setattr(linux.os,'read',lambda fd,size:raw)
    monkeypatch.setattr(linux.os,'close',lambda fd:None)
    host=linux.Host(NONCE)
    service={'InvocationID':job['invocation_id'],'LoadState':'loaded','MainPID':str(job['pid']),
        'ControlPID':'0','ActiveState':'active'}
    monkeypatch.setattr(host,'_show',lambda unit:service)
    return host,job


def test_root_job_requires_the_same_canonical_runtime_and_only_recovers_legacy(monkeypatch):
    value=packet()
    with monkeypatch.context() as scoped:
        host,job=job_fixture(scoped,value,7200)
        assert host._job(value)[0]==job
    with monkeypatch.context() as scoped:
        host,_job=job_fixture(scoped,value,7199)
        with pytest.raises(core.Blocked,match='invocation differs'):host._job(value)
    del value['runtime_seconds']
    with monkeypatch.context() as scoped:
        host,job=job_fixture(scoped,value,21600)
        assert host._job(value,allow_terminal=True)[0]==job
        with pytest.raises(core.Blocked,match='explicit packet runtime'):host._job(value)


@pytest.mark.parametrize('native,accepted',[('2h',True),('120min',True),('7200s',True),('6h',False),('2h1h',False)])
def test_root_actual_unit_admission_compares_native_runtime_to_chosen_packet(monkeypatch,native,accepted):
    value=packet();host=linux.Host(NONCE)
    group='/system.slice/'+value['unit']
    job=record(unit=value['unit'],cgroup=group,resources=['ar-local','host'],state='running',max_duration_seconds=7200)
    service={'User':'pi','NoNewPrivileges':'no','Type':'notify','KillMode':'control-group',
        'RuntimeMaxUSec':native,'CPUQuotaPerSecUSec':'1s','TasksMax':'64','IOWeight':'10'}
    parent={'pid':20,'ppid':job['pid'],'ticks':30,'cgroup':group}
    owner={'pid':job['pid'],'ticks':job['start_ticks'],'uids':[1000]*4,'gids':[1000]*4,'cgroup':group}
    monkeypatch.setattr(host,'_controls',lambda p:None)
    monkeypatch.setattr(host,'_job',lambda p:(job,service))
    monkeypatch.setattr(host,'_controller',lambda p:(parent,[]))
    monkeypatch.setattr(host,'boot',lambda:job['boot_id'])
    monkeypatch.setattr(host,'_lease',lambda j:SimpleNamespace(st_dev=1,st_ino=2))
    monkeypatch.setattr(linux,'identity',lambda pid:owner)
    original_stat=linux.os.stat
    monkeypatch.setattr(linux.os,'stat',lambda path,*a,**k:SimpleNamespace(st_dev=1,st_ino=2)
        if str(path)=='/proc/20/fd/3' else original_stat(path,*a,**k))
    monkeypatch.setattr(resources,'sample_host',lambda:host_sample())
    if accepted:
        assert host.admission(value)['job_id']==job['id']
    else:
        with pytest.raises(core.Blocked):host.admission(value)


@pytest.mark.parametrize('changed',['runtime_seconds','root_control_manifest_sha256','source_closure_sha256','nonce'])
def test_old_or_different_commissioning_packet_never_qualifies_new_controls(changed):
    current=packet();probe=dict(current,mode='PROBE',runtime_seconds=120,
        expires_at=(datetime.fromisoformat(current['created_at'])+timedelta(seconds=120)).isoformat())
    core.validate_commissioning_packet(probe,NONCE,current)
    if changed=='runtime_seconds':del probe[changed]
    elif changed=='nonce':probe[changed]='f'*32
    else:probe[changed]='c'*64
    with pytest.raises(core.Blocked):core.validate_commissioning_packet(probe,NONCE,current)


def test_new_acquisition_binds_the_actual_root_manifest_before_other_controls(monkeypatch):
    host=linux.Host(NONCE)
    monkeypatch.setattr(linux,'digest',lambda path:'c'*64)
    monkeypatch.setattr(linux,'approval',lambda *a,**k:pytest.fail('must reject manifest first'))
    with pytest.raises(core.Blocked,match='installed root control manifest'):
        host._controls(packet())


@pytest.mark.parametrize('legacy',[True,False])
def test_terminal_probe_recovery_preserves_legacy_proof_and_new_proof_binds_manifest(tmp_path,monkeypatch,legacy):
    value=packet();value.update(mode='PROBE',runtime_seconds=120,
        expires_at=(datetime.fromisoformat(value['created_at'])+timedelta(seconds=120)).isoformat())
    if legacy:
        del value['runtime_seconds'];del value['root_control_manifest_sha256']
    host=linux.Host(NONCE);host.private=tmp_path/'private';host.public=tmp_path/'public'
    host.private.mkdir();host.public.mkdir();host.stop_post_verified=True
    monkeypatch.setattr(host,'value',lambda:60)
    now=datetime.fromisoformat(value['created_at'])
    monkeypatch.setattr(host,'now',lambda:now)
    monkeypatch.setattr(host,'boot',lambda:'same-boot')
    expected={'owner_pid':123,'owner_ticks':456,'boot_id':'same-boot','job_id':'job',
        'unit':value['unit'],'invocation':'a'*32}
    completion=dict(expected,schema='ar-local-plain-backup-root-completion-v1',nonce=NONCE,
        result='RESTORED',readback=60,untrusted_processes_gone=True,credential_quarantined=True,
        stop_post_verified=True,operation_mode='PROBE',resource_acceptance='PASS',
        recorded_at=now.isoformat(),recorded_boot_id='same-boot')
    (host.public/'completion.json').write_text(json.dumps(completion),encoding='utf-8')
    (host.private/'resources.json').write_text(json.dumps({'result':'PASS','group_clean':True}),encoding='utf-8')
    (host.private/'terminal-resources.json').write_text(json.dumps({'observations':[
        {'stage':'before_restore','violation':None,'readback':0},
        {'stage':'after_restore','violation':None,'readback':60}]}),encoding='utf-8')
    proof=host.public/'coupled-probe.json'
    original=b'legacy proof retained byte for byte\n'
    if legacy:proof.write_bytes(original)
    monkeypatch.setattr(linux,'root_json',lambda path:json.loads(path.read_bytes()))
    writes=[]
    monkeypatch.setattr(linux,'atomic',lambda path,data,**kwargs:writes.append((path,data)))
    monkeypatch.setattr(linux.os,'chown',lambda *a:None,raising=False)
    host.complete(value,expected,result='RESTORED',readback=60)
    if legacy:
        assert proof.read_bytes()==original and writes==[]
    else:
        assert len(writes)==1 and writes[0][0]==proof
        assert writes[0][1]['root_control_manifest_sha256']==value['root_control_manifest_sha256']
