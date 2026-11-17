"""Standalone installed root launcher. Stdlib only; NEVER imports repository code.

Requires independently reviewed root-owned profile, source and runtime. The
caller supplies opaque work IDs and a borrowed owner, never argv/env/mounts.
Missing commissioning is a defer at the ordinary caller, not a fallback path.
"""
from datetime import date,datetime,time as wall_time,timedelta,timezone
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from zoneinfo import ZoneInfo

ROOT=Path('/usr/local/lib/ar-local-product-evidence')
PROFILE=Path('/etc/ar-local/product-evidence-launch.json')
RECORDS=Path('/var/lib/ar-local-product-evidence-launch')
QUEUE=Path('/var/lib/shared-pi-queue/state.json')
DATA=Path('/srv/ar-local/data')
PRODUCTION=Path('/srv/ar-local/AR-local')
FIELDS={'id','project','resources','mode','cpu_slots','max_duration_seconds','state','sequence',
        'queued_monotonic','pid','start_ticks','boot_id','unit','invocation_id','cgroup','command_started'}
FIXED={'ar-local-daily.service','ar-local-daily-watchdog.service','ar-local-ingest-now.service'}
PARENT=re.compile(r'(?:ar-local-queue-task|shared-pi-task)-[0-9a-f]{32}\.service')
SHA=re.compile('[0-9a-f]{64}')
PHASES={'snapshot','facts','responses','delivery','publish'}
TZ=ZoneInfo('Australia/Hobart')


def require(condition,message):
    if not condition:raise ValueError(message)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def decode(raw):
    def pairs(values):
        result={}
        for key,value in values:
            require(key not in result,'duplicate launch field');result[key]=value
        return result
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,
                      parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite launch field')))


def trusted(path,*,directory=False,owner=0):
    path=Path(path)
    require(path.is_absolute() and path.resolve()==path,'noncanonical trusted path')
    for parent in path.parents:
        info=parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'writable trusted ancestor')
    info=path.lstat()
    require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid==owner and not info.st_mode&0o022
            and (directory or info.st_nlink==1),'unsafe protected launch object')
    return info


def read(path,limit,*,owner=None):
    path=Path(path);before=path.lstat()
    require(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_nlink==1
            and before.st_size<=limit and (owner is None or before.st_uid==owner),'unsafe launch input')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        opened=os.fstat(fd);chunks=[];size=0
        while size<=limit:
            block=os.read(fd,min(65536,limit+1-size))
            if not block:break
            chunks.append(block);size+=len(block)
        raw=b''.join(chunks);after=os.fstat(fd);named=path.lstat()
        identity=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        require(identity(before)==identity(opened)==identity(after)==identity(named) and len(raw)==before.st_size,
                'launch input changed')
        return raw
    finally:os.close(fd)


def command(*args,timeout=5):
    value=subprocess.run(['/usr/bin/systemctl',*args],check=True,capture_output=True,
        timeout=timeout,env={'PATH':'/usr/bin:/bin','LC_ALL':'C'},text=True)
    require(len(value.stdout)<=65536,'oversized native launch evidence')
    return value.stdout


def show(unit):
    names=('Id','LoadState','ActiveState','MainPID','InvocationID','ControlGroup','User','KillMode','SendSIGKILL')
    lines=command('show',unit,'--property='+','.join(names)).splitlines()
    values=dict(line.split('=',1) for line in lines)
    require(len(lines)==len(names) and set(values)==set(names),'incomplete parent native evidence')
    return values


def group(pid):
    with (Path('/proc')/str(pid)/'cgroup').open() as stream:raw=stream.read(4097)
    require(len(raw)<=4096 and raw.startswith('0::/') and raw.count('\n')==1,'unified native cgroup required')
    value=raw[3:].strip();require('..' not in Path(value).parts,'unsafe native group')
    return value


def ticks(pid):
    with (Path('/proc')/str(pid)/'stat').open() as stream:raw=stream.read(4097)
    require(len(raw)<=4096,'oversized native PID evidence')
    return int(raw.rsplit(')',1)[1].split()[19])


def cutoff(now):
    local=now.astimezone(TZ)
    require(not wall_time(0,30)<=local.time()<wall_time(3,30),'natural quiet window')
    end=local.replace(hour=0,minute=30,second=0,microsecond=0)
    if local>=end:end+=timedelta(days=1)
    return end.astimezone(timezone.utc)


def validate_job(value,*,clock,now):
    require(type(value) is dict and set(value)=={'day','request_sha256','attempt_id','phase','owner','production_lease'},'invalid launch request')
    require(type(value['day']) is str and date.fromisoformat(value['day']).isoformat()==value['day']
            and type(value['request_sha256']) is str and SHA.fullmatch(value['request_sha256'])
            and type(value['attempt_id']) is str and re.fullmatch('[0-9a-f]{32}',value['attempt_id'])
            and value['phase'] in PHASES,'invalid opaque work identifiers')
    require(type(value['production_lease']) is dict if value['phase']=='publish' else value['production_lease'] is None,
            'publication delegation required only for publication')
    proof=value['owner']
    require(type(proof) is dict and set(proof)=={'schema','job','admitted_monotonic','deadline_monotonic','cleanup_seconds','quiet_utc'}
            and proof['schema']=='ar-product-evidence-borrowed-owner-v1' and proof['cleanup_seconds']==45,'unsupported borrowed owner')
    job=proof['job'];require(type(job) is dict and set(job)==FIELDS,'invalid queue owner shape')
    require(job['project']=='ar-local' and job['resources']==['ar-local'] and job['mode']=='exclusive'
            and job['state']=='running' and job['command_started'] is True,'AR-only executing owner required')
    require(type(job['unit']) is str and (job['unit'] in FIXED or PARENT.fullmatch(job['unit']))
            and job['cgroup']=='/system.slice/'+job['unit']
            and type(job['invocation_id']) is str and re.fullmatch('[0-9a-f]{32}',job['invocation_id']), 'unsupported parent namespace')
    for key,low,high in (('cpu_slots',1,3),('max_duration_seconds',1,21600),('pid',1,2**31-1),('start_ticks',1,2**63-1)):
        require(type(job[key]) is int and low<=job[key]<=high,'invalid queue owner integer')
    for number in (clock,proof['admitted_monotonic'],proof['deadline_monotonic'],job['queued_monotonic']):
        require(type(number) in (int,float) and math.isfinite(number) and number>=0,'invalid owner clock')
    require(job['queued_monotonic']<=proof['admitted_monotonic']<=clock,'owner clock origin differs')
    deadline=proof['deadline_monotonic'];end=cutoff(now)
    require(end.isoformat()==proof['quiet_utc'] and clock<deadline
            and deadline<=proof['admitted_monotonic']+1800
            and deadline+45<=job['queued_monotonic']+job['max_duration_seconds']
            and deadline-clock+45<=(end-now.astimezone(timezone.utc)).total_seconds(),'expired or extended owner deadline')
    return job,deadline


def owner_live(value,profile):
    job,end=validate_job(value,clock=time.monotonic(),now=datetime.now(timezone.utc))
    state=decode(read(QUEUE,1024*1024,owner=profile['uid']))
    require(type(state) is dict and set(state)=={'version','next_sequence','jobs'} and state['version']==1
            and type(state['jobs']) is list and len(state['jobs'])<=1024,'unsupported queue state')
    matches=[row for row in state['jobs'] if row.get('id')==job['id']]
    require(matches==[job],'borrowed queue claim changed')
    for row in state['jobs']:
        require(type(row) is dict and type(row.get('resources')) is list,'ambiguous queue owner')
        if row.get('id')==job['id'] or row.get('state')=='waiting':continue
        require(row.get('state')=='running' and not {'host','ar-local'}.intersection(row['resources']),'conflicting queue claim')
    require(group(os.getpid())==job['cgroup'] and group(job['pid'])==job['cgroup']
            and ticks(job['pid'])==job['start_ticks']
            and (Path('/proc/sys/kernel/random/boot_id').read_text().strip()==job['boot_id']), 'parent process identity changed')
    require((Path('/proc')/str(job['pid'])).stat().st_uid==profile['uid'],'parent process owner differs')
    native=show(job['unit'])
    require(native['Id']==job['unit'] and native['LoadState']=='loaded' and native['ActiveState'] in ('active','activating')
            and native['MainPID']==str(job['pid']) and native['InvocationID']==job['invocation_id']
            and native['ControlGroup']==job['cgroup'] and native['User'] in (str(profile['uid']),profile['user'])
            and native['KillMode']=='control-group' and native['SendSIGKILL']=='yes','parent service identity changed')
    verify_production_lease(value,profile['uid'])
    return end


def publication_record(pid,boot,attempt):
    return f'pid={pid}\nrole=product-evidence-publication:{attempt}\nboot_id={boot}\nrecovery=manual\n'.encode('ascii')


def verify_production_lease(value,uid):
    """Verify the retained ordinary parent descriptor; never creates a lock."""
    proof=value['production_lease']
    if value['phase']!='publish':
        require(proof is None,'unexpected preparation lease');return
    require(type(proof) is dict and set(proof)=={'schema','pid','start_ticks','fd','device','inode','boot_id','cgroup','record_sha256'}
            and proof['schema']=='ar-product-evidence-parent-lease-v1','invalid parent publication lease')
    for key,low in (('pid',1),('start_ticks',1),('fd',0),('device',0),('inode',1)):
        require(type(proof[key]) is int and low<=proof[key]<2**63,'invalid parent lease integer')
    require(proof['fd']<1048576 and proof['pid']<2**31,'unbounded parent descriptor identity')
    job=value['owner']['job'];path=DATA/'state/daily-ingest.lock'
    proc=Path('/proc')/str(proof['pid']);descriptor=proc/'fd'/str(proof['fd'])
    require(proof['boot_id']==job['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            and proof['cgroup']==job['cgroup']==group(proof['pid']) and ticks(proof['pid'])==proof['start_ticks']
            and proc.stat().st_uid==uid,'publication parent died or changed')
    expected=publication_record(proof['pid'],proof['boot_id'],value['attempt_id'])
    require(read(path,16384,owner=uid)==expected and hashlib.sha256(expected).hexdigest()==proof['record_sha256'],
            'publication lease record changed')
    held=descriptor.stat();named=path.lstat()
    require(descriptor.resolve()==path and (held.st_dev,held.st_ino)==(named.st_dev,named.st_ino)==(proof['device'],proof['inode'])
            and stat.S_ISREG(held.st_mode) and held.st_nlink==named.st_nlink==1 and held.st_uid==uid,
            'publication parent descriptor or name changed')


def _tree(root,inventory,deadline):
    """Complete root-owned source/runtime inventory, not a caller-supplied closure."""
    trusted(root,directory=True);seen={};count=total=0
    for directory,dirs,files in os.walk(root,followlinks=False,onerror=lambda e:(_ for _ in ()).throw(e)):
        for name in dirs:trusted(Path(directory)/name,directory=True)
        for name in files:
            require(time.monotonic()<deadline,'approved code verification deadline exceeded')
            path=Path(directory)/name;info=trusted(path);count+=1;total+=info.st_size
            require(count<=50000 and total<=1024**3,'approved source/runtime exceeds bound')
            h=hashlib.sha256();fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            try:
                before=os.fstat(fd)
                require((before.st_dev,before.st_ino)==(info.st_dev,info.st_ino),'approved code replaced')
                while block:=os.read(fd,1024*1024):
                    require(time.monotonic()<deadline,'approved code verification deadline exceeded');h.update(block)
                after=os.fstat(fd);named=path.lstat()
                require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                        (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)==
                        (named.st_dev,named.st_ino,named.st_size,named.st_mtime_ns,named.st_ctime_ns),'approved code changed')
            finally:os.close(fd)
            seen[path.relative_to(root).as_posix()]=dict(bytes=info.st_size,sha256=h.hexdigest())
    require(seen==inventory,'approved import closure differs')


def profile(deadline):
    trusted(PROFILE);raw=read(PROFILE,8*1024**2,owner=0)
    return profile_value(raw,deadline)


def profile_value(raw,deadline):
    value=decode(raw)
    require(type(value) is dict and set(value)=={'schema','uid','gid','user','source_commit','source_tree','source_files','runtime_files',
            'runtime_sha256','python_sha256','credential_sha256'},'invalid installed launch profile')
    require(value['schema']=='ar-product-evidence-launch-profile-v1' and type(value['uid']) is int and 0<value['uid']<2**31
            and type(value['gid']) is int and 0<value['gid']<2**31 and re.fullmatch('[a-z_][a-z0-9_-]{0,31}',value['user'])
            and re.fullmatch('[0-9a-f]{40}',value['source_commit']) and re.fullmatch('[0-9a-f]{40}',value['source_tree'])
            and SHA.fullmatch(value['runtime_sha256']), 'invalid approved source/runtime identity')
    import pwd
    account=pwd.getpwnam(value['user'])
    require((account.pw_uid,account.pw_gid)==(value['uid'],value['gid']),'approved account changed')
    source=ROOT/'source'/value['source_commit'];runtime=ROOT/'runtime'/value['runtime_sha256']
    require(type(value['source_files']) is dict and type(value['runtime_files']) is dict,'invalid approved file inventory')
    _tree(source,value['source_files'],deadline);_tree(runtime,value['runtime_files'],deadline)
    # Runtime is a deliberately materialized root-owned venv: no mutable symlink
    # chain or include-system-site-packages escape. Commissioning creates it;
    # this launcher never installs packages or rewrites a venv.
    python=runtime/'bin/python3';trusted(python)
    require(value['runtime_files'].get('bin/python3',{}).get('sha256')==value['python_sha256'], 'interpreter pin differs')
    cfg=read(runtime/'pyvenv.cfg',65536,owner=0).decode('utf-8')
    require(re.search(r'(?im)^include-system-site-packages\s*=\s*false\s*$',cfg) is not None,'system site packages forbidden')
    require('pi_product_evidence_worker.py' in value['source_files'],'approved worker missing')
    require(canonical(value['runtime_files']) and hashlib.sha256(canonical(value['runtime_files'])).hexdigest()==value['runtime_sha256'],
            'runtime inventory identity differs')
    value['_source']=str(source);value['_runtime']=str(runtime);value['_python']=str(python)
    value['_profile_sha256']=hashlib.sha256(raw).hexdigest()
    return value


def work_path(value,uid):
    root=DATA/'state/product-evidence-dispatch-v1'/value['day']/value['request_sha256']
    attempt=root/'attempts'/value['attempt_id']
    for path in (DATA,DATA/'state',*reversed(attempt.parents[:len(attempt.parts)-len(DATA.parts)-1]),attempt):
        info=path.lstat()
        require(path.resolve()==path and stat.S_ISDIR(info.st_mode) and info.st_uid==uid and not info.st_mode&0o022,
                'unsafe ordinary-owned dispatch path')
    require(not any(attempt.iterdir()),'launch attempt is not fresh')
    request=decode(read(root/'request.json',98304,owner=uid))
    require(hashlib.sha256(canonical(request)).hexdigest()==value['request_sha256'],'request identity differs')
    progress=decode(read(root/'progress.json',65536,owner=uid))
    require(progress.get('status')=='running' and progress.get('request_sha256')==value['request_sha256']
            and progress.get('attempt_id')==value['attempt_id'] and progress.get('phase')==value['phase'],'phase reservation differs')
    return root,attempt,request


def path_identity(path):
    info=path.lstat()
    require(path.resolve()==path and stat.S_ISDIR(info.st_mode),'unsafe worker mount identity')
    return dict(device=info.st_dev,inode=info.st_ino,uid=info.st_uid,mode=stat.S_IMODE(info.st_mode))


def properties(value,approved,attempt,seconds):
    parent=value['owner']['job']['unit'];slots=min(2,value['owner']['job']['cpu_slots'])
    result=['Type=exec','User='+approved['user'],'Group='+str(approved['gid']),
        'BindsTo='+parent,'After='+parent,'KillMode=control-group','SendSIGKILL=yes','TimeoutStopSec=35s',
        'RuntimeMaxSec='+str(seconds-15)+'s','CPUQuota='+str(slots*100)+'%','MemoryHigh=2560M','MemoryMax=3G',
        'MemorySwapMax=0','TasksMax=64','IOWeight=10','Nice=10','NoNewPrivileges=yes','PrivateTmp=yes','ProtectSystem=strict',
        'ProtectHome=yes','ReadOnlyPaths=/tmp /var/tmp','UMask=0077','WorkingDirectory='+approved['_source'],
        'ReadOnlyPaths='+str(DATA),'ReadWritePaths='+str(attempt),
        'Environment=PATH=/usr/bin:/bin HOME=/nonexistent PYTHONNOUSERSITE=1 OPENBLAS_NUM_THREADS=1',
        'Environment=AR_LOCAL_DATA_ROOT='+str(DATA)+' PORTABLE_ROOT=/srv/ar-local TMPDIR='+str(attempt/'tmp')]
    if value['phase']=='publish':
        result+=['EnvironmentFile=/etc/ar-local/app-payload.env','InaccessiblePaths=/root /home',
            'ReadWritePaths='+str(DATA/'state/app-payload')+' '+str(DATA/'state/product-evidence-financial-v1')
                +' '+str(DATA/'state/product-evidence-retries-v1')]
    else:result+=['PrivateNetwork=yes','RestrictAddressFamilies=AF_UNIX','InaccessiblePaths=/etc/ar-local /root /home']
    return result


def record(path,value):
    trusted(path.parent,directory=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
    try:
        with os.fdopen(fd,'wb',closefd=False) as stream:stream.write(canonical(value));stream.flush();os.fsync(fd)
    finally:os.close(fd)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def terminal_empty(unit):
    body=command('show',unit,'--property=Id,ActiveState,MainPID,ControlGroup,ExecMainStatus,Result')
    rows=dict(line.split('=',1) for line in body.splitlines())
    require(rows.get('Id')==unit and rows.get('ActiveState') in ('inactive','failed') and rows.get('MainPID')=='0',
            'worker is not terminal')
    root=Path('/sys/fs/cgroup/system.slice')/unit
    if root.exists():
        count=0
        for directory,dirs,_ in os.walk(root,followlinks=False):
            count+=1;require(count<=64 and not any((Path(directory)/name).is_symlink() for name in dirs),'ambiguous child cgroup')
            require(not (Path(directory)/'cgroup.procs').read_text().strip(),'worker descendants remain')
    return rows


def launch(value):
    require(os.geteuid()==0 and str(os.environ.get('SUDO_UID','')).isdigit(),'ordinary sudo caller required')
    job,deadline=validate_job(value,clock=time.monotonic(),now=datetime.now(timezone.utc))
    approved=profile(min(deadline,time.monotonic()+120))
    require(int(os.environ['SUDO_UID'])==approved['uid'],'caller is not approved owner')
    owner_live(value,approved);root,attempt,request=work_path(value,approved['uid'])
    require(request.get('writer_revision')==approved['source_commit'] and request.get('writer_tree')==approved['source_tree'],
            'request writer is not commissioned')
    if value['phase']=='publish':
        secret=Path('/etc/ar-local/app-payload.env');trusted(secret)
        require(hashlib.sha256(read(secret,65536,owner=0)).hexdigest()==approved['credential_sha256'],'publication credential profile changed')
    seconds=math.floor(owner_live(value,approved)-time.monotonic())
    require(seconds>=300,'verification consumed useful phase allowance')
    trusted(RECORDS,directory=True)
    unit='ar-local-product-evidence-'+value['attempt_id']+'.service'
    initial=dict(schema='ar-product-evidence-launch-v1',request=value,profile_sha256=approved['_profile_sha256'],unit=unit)
    record(RECORDS/(job['invocation_id']+'.json'),initial)  # One phase per parent invocation, including failure.
    envelope=dict(request=value,source=approved['_source'],production=str(PRODUCTION),state=str(DATA/'state'),
                  root=str(root),attempt=str(attempt),source_commit=approved['source_commit'],source_tree=approved['source_tree'],
                  source_closure_sha256=hashlib.sha256(canonical(approved['source_files'])).hexdigest(),
                  runtime_sha256=approved['runtime_sha256'],profile_sha256=approved['_profile_sha256'],
                  path_identities={str(path):path_identity(path) for path in (DATA/'state',root,attempt)})
    encoded=base64.b64encode(canonical(envelope)).decode('ascii')
    argv=['/usr/bin/systemd-run','--quiet','--unit='+unit]
    for item in properties(value,approved,attempt,seconds):argv+=['--property='+item]
    argv += ['--',approved['_python'],'-I','-B',str(Path(approved['_source'])/'pi_product_evidence_worker.py'),encoded]
    outcome=dict(initial,result='FAIL',owned_group_empty=False)
    try:
        subprocess.run(argv,check=True,timeout=min(15,seconds),capture_output=True,
                       env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
        while True:
            owner_live(value,approved)
            native=show(unit)
            if native['ActiveState'] in ('inactive','failed'):break
            time.sleep(min(1,max(0,deadline-time.monotonic())))
        final=terminal_empty(unit);outcome['owned_group_empty']=True;outcome['native']=final
        require(final.get('Result')=='success' and final.get('ExecMainStatus')=='0','bounded worker failed')
        outcome['artifacts']={}
        for name,maximum in (('worker.json',65536),('result.json',98304),('resources.json',8*1024**2)):
            raw=read(attempt/name,maximum,owner=approved['uid'])
            require(decode(raw).get('result')=='PASS','worker did not produce a passing terminal artifact')
            outcome['artifacts'][name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        require(hashlib.sha256(read(PROFILE,8*1024**2,owner=0)).hexdigest()==approved['_profile_sha256'],
                'launch profile changed before completion')
        outcome['result']='PASS'
    except Exception as error:
        outcome['error']=type(error).__name__
        try:
            command('stop',unit,timeout=40);terminal_empty(unit);outcome['owned_group_empty']=True
        except Exception:outcome['cleanup_failed']=True
        raise
    finally:
        record(RECORDS/(job['invocation_id']+'-terminal.json'),outcome)
    return outcome


if __name__=='__main__':
    import sys
    require(Path(__file__).absolute()==ROOT/'launch.py','only the installed fixed helper may launch')
    trusted(ROOT/'launch.py')
    require(len(sys.argv)==2 and len(sys.argv[1])<=32768,'one bounded encoded request required')
    value=decode(base64.b64decode(sys.argv[1],validate=True))
    print(canonical(launch(value)).decode('utf-8'))
