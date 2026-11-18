"""Read-only borrowing of an existing AR queue owner and its original deadline.

No queue admission, reconciliation, lease, lock, notification or timer mutation.
The installed launcher independently checks the same native ownership boundary.
"""
from datetime import datetime,timezone
import math
import os
from pathlib import Path
import re
import time

from app_payload_product_evidence_contract import decode,require
from app_payload_product_evidence_delivery_check import read_stable
from ar_local_ingest_schedule import maintenance_closes_at,maintenance_window_open
from pi_shared_queue_store import Store,Supervisor,FIXED_AR_UNITS,duration

QUEUE=Path('/var/lib/shared-pi-queue/state.json')
TRANSIENT=re.compile(r'(?:ar-local-queue-task|shared-pi-task)-[0-9a-f]{32}\.service')
MAX_SECONDS=1800
CLEANUP_SECONDS=45
MIN_SECONDS=300


def select_owner(state,supervisor,*,caller_pid,monotonic,now,minimum=MIN_SECONDS):
    """Injected clocks/supervisor make replacement and clock boundaries testable."""
    Store.validate(state)
    require(now.tzinfo is not None and math.isfinite(monotonic) and monotonic>=0,'invalid dispatch clock')
    require(maintenance_window_open(now),'optional preparation deferred during natural quiet window')
    group=supervisor.cgroup(caller_pid)
    matches=[row for row in state['jobs'] if row['cgroup']==group and row['state']=='running']
    require(len(matches)==1,'no unique existing queue claim')
    job=matches[0]
    require(job['project']=='ar-local' and job['resources']==['ar-local'] and job['mode']=='exclusive'
            and job.get('command_started') is True,'optional work requires an executing AR-only exclusive claim')
    require(job['unit'] in FIXED_AR_UNITS or TRANSIENT.fullmatch(job['unit']),'unsupported optional parent unit')
    for row in state['jobs']:
        if row['id']==job['id'] or row['state']=='waiting':continue
        require(row['state']=='running' and 'host' not in row['resources'] and 'ar-local' not in row['resources'],
                'conflicting or ambiguous queue owner')
    require(supervisor.boot_id()==job['boot_id'] and supervisor.wrapper_alive(job),'parent wrapper replaced')
    native=supervisor.show(job['unit'])
    require(native.get('Id')==job['unit'] and native.get('LoadState')=='loaded'
            and native.get('ActiveState') in ('active','activating')
            and native.get('MainPID')==str(job['pid']) and native.get('InvocationID')==job['invocation_id']
            and native.get('ControlGroup')==group and native.get('KillMode')=='control-group'
            and native.get('SendSIGKILL')=='yes','native parent ownership differs')
    require(duration(native.get('CPUQuotaPerSecUSec',''))<=job['cpu_slots'],'parent exceeds declared CPU slots')
    stop=duration(native.get('TimeoutStopUSec',''))
    require(stop<=(900 if job['unit'] in FIXED_AR_UNITS else 60),'unbounded parent cleanup')
    queued=float(job['queued_monotonic'])
    require(math.isfinite(queued) and 0<=queued<=monotonic,'queue clock changed')
    # Earlier than actual execution expiry when admission waited. Never extend it.
    parent_end=queued+job['max_duration_seconds']
    if native.get('Type')=='notify':
        require(native['ActiveState']=='active','notify parent not admitted')
        started=int(native.get('ActiveEnterTimestampMonotonic','0'))/1_000_000
        require(0<started<=monotonic,'native execution origin unavailable')
        parent_end=min(parent_end,started+duration(native.get('RuntimeMaxUSec','')))
    else:
        require(job['unit'] in FIXED_AR_UNITS and native.get('Type')=='oneshot','unsupported parent runtime')
        require(duration(native.get('TimeoutStartUSec',''))<=46800,'unbounded fixed parent lifetime')
    quiet_seconds=(maintenance_closes_at(now).astimezone(timezone.utc)-now.astimezone(timezone.utc)).total_seconds()
    end=min(monotonic+MAX_SECONDS,parent_end-CLEANUP_SECONDS,monotonic+quiet_seconds-CLEANUP_SECONDS)
    require(end-monotonic>=minimum,'insufficient original parent/quiet allowance')
    return dict(schema='ar-product-evidence-borrowed-owner-v1',job=dict(job),
        admitted_monotonic=monotonic,deadline_monotonic=end,cleanup_seconds=CLEANUP_SECONDS,
        quiet_utc=maintenance_closes_at(now).astimezone(timezone.utc).isoformat())


def borrow(*,now=None,monotonic=None,supervisor=None,queue=QUEUE,caller_pid=None,minimum=MIN_SECONDS):
    raw,_=read_stable(queue,1024*1024)
    return select_owner(decode(raw),supervisor or Supervisor(),caller_pid=os.getpid() if caller_pid is None else caller_pid,
        monotonic=time.monotonic() if monotonic is None else monotonic,now=now or datetime.now(timezone.utc),minimum=minimum)


def recheck(proof,*,now=None,monotonic=None,supervisor=None,queue=QUEUE,caller_pid=None):
    """Fresh ownership may shorten a deadline; it may never renew the first one."""
    current=borrow(now=now,monotonic=monotonic,supervisor=supervisor,queue=queue,caller_pid=caller_pid,minimum=0)
    require(current['job']==proof['job'],'borrowed queue owner changed')
    clock=time.monotonic() if monotonic is None else monotonic
    require(clock<proof['deadline_monotonic'] and current['quiet_utc']==proof['quiet_utc'],
            'original optional deadline expired or quiet boundary changed')
    return min(proof['deadline_monotonic'],current['deadline_monotonic'])
