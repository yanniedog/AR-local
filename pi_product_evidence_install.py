"""Held root-stage-only installation/rollback of three fixed launch definitions.

No service start, timer, source checkout, package installation or credential
changes. No repository imports. All approval/old-preimage hashes are external
operator pins; this helper does not manufacture CI or runtime qualification.
"""
from datetime import datetime,timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import time

STAGES=Path('/var/lib/ar-local-product-evidence-stage')
ROOT=Path('/usr/local/lib/ar-local-product-evidence')
PROFILE=Path('/etc/ar-local/product-evidence-launch.json')
SUDO=Path('/etc/sudoers.d/ar-local-product-evidence')
RECORDS=Path('/var/lib/ar-local-product-evidence-launch')
TARGETS={'helper':ROOT/'launch.py','profile':PROFILE,'sudoers':SUDO}
MODES={'helper':0o644,'profile':0o644,'sudoers':0o440}


def require(value,message):
    if not value:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def protected(path,maximum=8*1024**2):
    path=Path(path)
    require(path.is_absolute() and path.resolve()==path,'noncanonical protected install path')
    for ancestor in path.parents:
        info=ancestor.lstat();require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'writable install ancestor')
    info=path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1
            and not info.st_mode&0o022 and info.st_size<=maximum,'unsafe protected installation input')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        opened=os.fstat(fd);chunks=[];count=0
        while count<=maximum:
            block=os.read(fd,min(65536,maximum+1-count))
            if not block:break
            chunks.append(block);count+=len(block)
        raw=b''.join(chunks);after=os.fstat(fd);named=path.lstat()
        ident=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_uid,s.st_gid,s.st_mode,s.st_mtime_ns,s.st_ctime_ns)
        require(ident(info)==ident(opened)==ident(after)==ident(named) and count==info.st_size,'protected install input changed')
        return raw
    finally:os.close(fd)


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def create(path,raw,mode=0o400):
    if path.exists():require(protected(path)==raw,'retained install evidence differs');return
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fchmod(stream.fileno(),mode);os.fsync(stream.fileno())
    sync(path.parent)


def replace(path,raw,mode):
    fd,name=tempfile.mkstemp(prefix='.evidence-',dir=path.parent)
    temporary=Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fchmod(stream.fileno(),mode);os.fsync(stream.fileno())
        os.replace(temporary,path);sync(path.parent)
    finally:
        if temporary.exists():temporary.unlink()  # Protected root-owned parent only.


def host_owner(helper,uid):
    """Reuse only pure protected-stage stdlib readers; never imports queue code."""
    group=helper['group'](os.getpid())
    require(re.fullmatch(r'/system.slice/ar-local-queue-task-[0-9a-f]{32}\.service',group),'explicit host queue unit required')
    state=helper['decode'](helper['read'](Path('/var/lib/shared-pi-queue/state.json'),1024*1024,owner=uid))
    require(type(state) is dict and state.get('version')==1 and type(state.get('jobs')) is list and len(state['jobs'])<=1024,'complete queue state required')
    matches=[row for row in state['jobs'] if type(row) is dict and row.get('cgroup')==group]
    require(len(matches)==1,'unique host owner required');job=matches[0]
    require(all(row is job or type(row) is dict and row.get('state')=='waiting' for row in state['jobs']), 'another queue owner exists')
    require(set(job)==helper['FIELDS'] and job['project']=='ar-local' and job['state']=='running'
            and job['command_started'] is True and job['mode']=='exclusive' and set(job['resources'])=={'ar-local','host'},
            'AR+host executing claim required')
    require(type(job['pid']) is int and 0<job['pid']<2**31 and type(job['start_ticks']) is int and job['start_ticks']>0
            and type(job['max_duration_seconds']) is int and 0<job['max_duration_seconds']<=21600
            and type(job['queued_monotonic']) in (int,float) and 0<=job['queued_monotonic']<=time.monotonic(),
            'invalid bounded host owner')
    native=helper['show'](job['unit'])
    require(native['Id']==job['unit']==group.rsplit('/',1)[-1] and native['ControlGroup']==group
            and native['InvocationID']==job['invocation_id'] and native['MainPID']==str(job['pid'])
            and native['ActiveState']=='active' and helper['ticks'](job['pid'])==job['start_ticks']
            and helper['group'](job['pid'])==group and (Path('/proc')/str(job['pid'])).stat().st_uid==uid,'host invocation changed')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    lease=helper['read'](Path('/srv/ar-local/data/state/daily-ingest.lock'),65536,owner=uid).decode().splitlines()
    require(len(lease)==4 and dict(line.split('=',1) for line in lease)==dict(pid=str(job['pid']),boot_id=boot,
        role='shared-pi-host-task:'+job['id'],recovery='manual') and job['boot_id']==boot,'native host lease differs')
    remaining=job['queued_monotonic']+job['max_duration_seconds']-time.monotonic()
    quiet=(helper['cutoff'](datetime.now(timezone.utc))-datetime.now(timezone.utc)).total_seconds()
    require(remaining>=180 and quiet>=180,'installation/rollback reserve unavailable')
    output=helper['command']('list-units','--all','--type=service','--plain','--no-legend','--no-pager')
    for line in output.splitlines():
        unit=line.split()[0]
        if re.fullmatch(r'ar-local-product-evidence-[0-9a-f]{32}\.service',unit):helper['terminal_empty'](unit)
    return dict(id=job['id'],invocation_id=job['invocation_id'],boot_id=boot)


def validate_plan(value):
    require(type(value) is dict and set(value)=={'schema','uid','source_commit','source_tree','helper_sha256','profile_sha256',
            'ci_receipt_sha256','qualification_receipt_sha256','expires_utc','preimages'},'invalid explicit installation plan')
    require(value['schema']=='ar-product-evidence-install-v1' and type(value['uid']) is int and value['uid']>0,'invalid install identity')
    for key in ('helper_sha256','profile_sha256','ci_receipt_sha256','qualification_receipt_sha256'):
        require(type(value[key]) is str and re.fullmatch('[0-9a-f]{64}',value[key]),'external qualification/hash pin missing')
    for key in ('source_commit','source_tree'):require(re.fullmatch('[0-9a-f]{40}',value[key]),'exact source pin required')
    expires=datetime.fromisoformat(value['expires_utc']);require(expires.tzinfo is not None,'approval requires timezone')
    require(type(value['preimages']) is dict and set(value['preimages'])==set(TARGETS),'only three fixed installation targets permitted')
    for key,pin in value['preimages'].items():
        require(pin is None or type(pin) is dict and set(pin)=={'sha256','mode'}
                and re.fullmatch('[0-9a-f]{64}',pin['sha256']) and type(pin['mode']) is int and 0<=pin['mode']<=0o777,
                'invalid root preimage')
    return expires


def installed_proof(bodies,preimages,action):
    proof={name:None if not path.exists() else dict(sha256=sha(protected(path)),mode=stat.S_IMODE(path.stat().st_mode))
           for name,path in TARGETS.items()}
    expected={name:dict(sha256=sha(bodies[name]),mode=MODES[name]) for name in TARGETS} if action=='apply' else preimages
    require(proof==expected,'final installed definitions differ from exact requested postimages')
    return proof


def source_pair(profile,helper,installer):
    files=profile.get('source_files') if type(profile) is dict else None
    require(type(files) is dict,'profile source inventory missing')
    for name,raw in (('pi_product_evidence_launch.py',helper),('pi_product_evidence_install.py',installer)):
        require(files.get(name)==dict(bytes=len(raw),sha256=sha(raw)),'staged root helper differs from exact approved source inventory')


def _execute(stage,expected_plan,expected_self,action):
    require(os.geteuid()==0,'root protected-stage installation only')
    require(action in ('check','apply','rollback'),'unknown installation action')
    stage=Path(stage)
    require(stage.parent==STAGES and re.fullmatch('[0-9a-f]{32}',stage.name),'fixed new installation stage required')
    installer_raw=protected(stage/'install.py')
    require(Path(__file__).absolute()==stage/'install.py' and sha(installer_raw)==expected_self,'installer bytes differ')
    raw=protected(stage/'plan.json');require(sha(raw)==expected_plan,'installation plan differs from external pin')
    plan=json.loads(raw);expires=validate_plan(plan)
    for name in ('ci','qualification'):
        receipt=protected(stage/(name+'-receipt.json'),4*1024**2)
        require(sha(receipt)==plan[name+'_receipt_sha256'],'externally reviewed qualification receipt differs')
    helper_raw=protected(stage/'launch.py',256*1024);profile_raw=protected(stage/'profile.json')
    require(sha(helper_raw)==plan['helper_sha256'] and sha(profile_raw)==plan['profile_sha256'],'approved staged source differs')
    profile=json.loads(profile_raw);source_pair(profile,helper_raw,installer_raw)
    helper={'__name__':'reviewed_root_launcher','__file__':str(stage/'launch.py')}
    exec(compile(helper_raw,str(stage/'launch.py'),'exec'),helper)  # Root-owned, external-hash-pinned reviewed stdlib only.
    owner=host_owner(helper,plan['uid'])
    require(profile['uid']==plan['uid'] and profile['source_commit']==plan['source_commit'] and profile['source_tree']==plan['source_tree'],
            'profile and qualification target differ')
    if action!='rollback':
        require(datetime.now(timezone.utc)<expires,'installation approval expired')
        helper['profile_value'](profile_raw,time.monotonic()+120)
    sudo=(f"{profile['user']} ALL=(root) NOPASSWD: /usr/bin/python3 -I -B {ROOT}/launch.py *\n").encode()
    bodies=dict(helper=helper_raw,profile=profile_raw,sudoers=sudo)
    create(stage/'sudoers-check',sudo,0o440)
    subprocess.run(['/usr/sbin/visudo','-cf',str(stage/'sudoers-check')],check=True,capture_output=True,timeout=10,
                   env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
    for name,path in TARGETS.items():
        current=protected(path) if path.exists() else None;old=plan['preimages'][name]
        require(current is None and old is None or current is not None and (current==bodies[name]
                or old is not None and sha(current)==old['sha256'] and stat.S_IMODE(path.stat().st_mode)==old['mode']),
                'installed object is neither approved preimage nor owned postimage')
        backup=stage/(name+'.original')
        if old is not None:
            if backup.exists():require(sha(protected(backup))==old['sha256'],'retained rollback preimage changed')
            else:
                require(current is not None and sha(current)==old['sha256'],'rollback preimage unavailable')
                create(backup,current)
    if action=='check':return {'result':'PASS','mode':'definition_check','installation_performed':False}
    # A later separately admitted rollback must reuse the exact immutable plan,
    # without pretending its new queue invocation is the original apply owner.
    create(stage/'prepared.json',canonical(dict(plan_sha256=expected_plan)))
    for directory in (ROOT,RECORDS):
        if not directory.exists():directory.mkdir(mode=0o755);sync(directory.parent)
        helper['trusted'](directory,directory=True)
    try:
        for name,path in (list(TARGETS.items()) if action=='apply' else reversed(list(TARGETS.items()))):
            require(host_owner(helper,plan['uid'])==owner,'host owner changed during installation')
            current=protected(path) if path.exists() else None;old=plan['preimages'][name]
            if action=='apply':
                require(datetime.now(timezone.utc)<expires,'installation approval expired')
                require(current==bodies[name] or current is None and old is None or old is not None and current is not None and sha(current)==old['sha256'],
                        'installation preimage changed')
                replace(path,bodies[name],MODES[name])
            elif current==bodies[name]:
                if old is None:path.unlink();sync(path.parent)  # Only exact owned postimage, root-owned ancestry.
                else:replace(path,protected(stage/(name+'.original')),old['mode'])
            else:require(current is None and old is None or old is not None and current is not None and sha(current)==old['sha256'],
                         'rollback refuses foreign postimage')
        require(host_owner(helper,plan['uid'])==owner,'host owner changed before final readback')
        proof=installed_proof(bodies,plan['preimages'],action)
        create(stage/(action+'-complete.json'),canonical(dict(result='PASS',plan_sha256=expected_plan,installed=proof)))
        return dict(result='PASS',mode=action,installed=proof,service_or_timer_actions=False)
    except Exception:
        create(stage/(action+'-incomplete.json'),canonical(dict(result='INCOMPLETE',plan_sha256=expected_plan,rollback_required=True)))
        raise


def execute(stage,expected_plan,expected_self,action):
    """Fixed whole-process bound inside the independently admitted 300s queue."""
    def expired(_signal,_frame):raise TimeoutError('installation lifetime exceeded 240 seconds')
    previous=signal.signal(signal.SIGALRM,expired);signal.alarm(240)
    try:return _execute(stage,expected_plan,expected_self,action)
    finally:signal.alarm(0);signal.signal(signal.SIGALRM,previous)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('stage','expected-plan-sha256','expected-self-sha256'):parser.add_argument('--'+name,required=True)
    parser.add_argument('action',choices=('check','apply','rollback'));args=parser.parse_args()
    print(json.dumps(execute(args.stage,args.expected_plan_sha256,args.expected_self_sha256,args.action),sort_keys=True))
