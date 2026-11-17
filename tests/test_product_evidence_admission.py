"""Native queue boundaries, including conservative time and midnight controls."""
from copy import deepcopy
from datetime import datetime,timedelta
import pytest
from ar_local_ingest_schedule import DAILY_INGEST_TZ
from app_payload_product_evidence_contract import canonical
import pi_product_evidence_admission as admission


def now(value='2026-11-14T23:59:00'):
    return datetime.fromisoformat(value).replace(tzinfo=DAILY_INGEST_TZ)


def state():
    return dict(version=1,next_sequence=1,jobs=[dict(id='daily',project='ar-local',resources=['ar-local'],
        mode='exclusive',cpu_slots=2,max_duration_seconds=21600,state='running',sequence=0,
        queued_monotonic=100,pid=123,start_ticks=88,boot_id='12345678-1234-1234-1234-123456789abc',
        unit='ar-local-daily-watchdog.service',invocation_id='a'*32,
        cgroup='/system.slice/ar-local-daily-watchdog.service',command_started=True)])


class Native:
    def __init__(self,row):
        self.row=row;self.alive=True
        self.native=dict(Id=row['unit'],LoadState='loaded',ActiveState='activating',MainPID='123',
            InvocationID=row['invocation_id'],ControlGroup=row['cgroup'],KillMode='control-group',SendSIGKILL='yes',
            CPUQuotaPerSecUSec='2s',TimeoutStopUSec='15min',Type='oneshot',TimeoutStartUSec='13h')
    def cgroup(self,pid):return self.row['cgroup']
    def wrapper_alive(self,row):return self.alive
    def boot_id(self):return self.row['boot_id']
    def show(self,unit):return self.native


def select(value=None,clock=1000,wall=None):
    value=value or state()
    return admission.select_owner(value,Native(value['jobs'][0]),caller_pid=234,monotonic=clock,now=wall or now())


def test_original_deadline_does_not_renew_across_midnight(tmp_path):
    value=state();native=Native(value['jobs'][0]);queue=tmp_path/'queue.json';queue.write_bytes(canonical(value))
    initial=admission.borrow(now=now(),monotonic=1000,supervisor=native,queue=queue,caller_pid=234)
    assert initial['deadline_monotonic']==2800
    assert admission.recheck(initial,now=now()+timedelta(minutes=2),monotonic=1120,
        supervisor=native,queue=queue,caller_pid=234)==2800
    # Last <300 seconds can be checked without inventing another admission.
    assert admission.recheck(initial,now=now()+timedelta(seconds=1799),monotonic=2799,
        supervisor=native,queue=queue,caller_pid=234)==2800
    with pytest.raises(ValueError):admission.recheck(initial,now=now()+timedelta(seconds=1800),monotonic=2800,
        supervisor=native,queue=queue,caller_pid=234)


@pytest.mark.parametrize('clock',['2026-11-15T00:30:00','2026-11-15T01:00:00','2026-11-15T03:29:59',
                                  '2026-10-04T03:15:00','2026-04-05T02:15:00'])
def test_natural_and_dst_quiet_defer(clock):
    with pytest.raises(ValueError,match='quiet'):select(wall=now(clock))


@pytest.mark.parametrize('clock',['2026-11-14T22:00:00','2026-11-15T00:00:00','2026-11-15T03:30:00',
                                  '2026-10-04T03:30:00','2026-04-05T03:30:00'])
def test_permitted_boundary_and_dst_accept(clock):
    assert select(wall=now(clock))['deadline_monotonic']<=2800


def test_queued_time_is_conservative_and_cleanup_is_reserved():
    value=state();value['jobs'][0]['max_duration_seconds']=1500
    assert select(value)['deadline_monotonic']==1555
    value['jobs'][0]['max_duration_seconds']=1200
    with pytest.raises(ValueError,match='insufficient'):select(value)
    assert select(wall=now('2026-11-15T00:24:15'))['deadline_monotonic']==1300
    with pytest.raises(ValueError,match='insufficient'):select(wall=now('2026-11-15T00:24:16'))


@pytest.mark.parametrize('fault',['host','shared','not_started','waiting','duplicate','conflict','unknown','dead','invocation','mainpid','boot','future'])
def test_invalid_or_replaced_owner_rejected(fault):
    value=state();row=value['jobs'][0];native=Native(row)
    if fault=='host':row['resources'].append('host')
    elif fault=='shared':row['mode']='shared'
    elif fault=='not_started':row['command_started']=False
    elif fault=='waiting':row['state']='waiting'
    elif fault in ('duplicate','conflict','unknown'):
        other=deepcopy(row);other.update(id='other',sequence=1);value['next_sequence']=2
        if fault!='duplicate':other['cgroup']='/system.slice/ar-local-daily.service';other['unit']='ar-local-daily.service'
        if fault=='unknown':other['state']='quarantined'
        value['jobs'].append(other)
    elif fault=='dead':native.alive=False
    elif fault=='invocation':native.native['InvocationID']='b'*32
    elif fault=='mainpid':native.native['MainPID']='999'
    elif fault=='boot':native.boot_id=lambda:'23456789-1234-1234-1234-123456789abc'
    else:row['queued_monotonic']=1001
    with pytest.raises(ValueError):admission.select_owner(value,native,caller_pid=234,monotonic=1000,now=now())


def test_transient_original_notify_deadline_bound():
    value=state();row=value['jobs'][0]
    row['unit']='ar-local-queue-task-'+('c'*32)+'.service';row['cgroup']='/system.slice/'+row['unit']
    native=Native(row);native.native.update(Type='notify',ActiveState='active',TimeoutStopUSec='45s',
        RuntimeMaxUSec='600s',ActiveEnterTimestampMonotonic='900000000')
    result=admission.select_owner(value,native,caller_pid=234,monotonic=1000,now=now())
    assert result['deadline_monotonic']==1455
    native.native['ActiveState']='activating'
    with pytest.raises(ValueError):admission.select_owner(value,native,caller_pid=234,monotonic=1000,now=now())
