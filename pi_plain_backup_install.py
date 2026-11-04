"""Reviewable fixed plaintext-control installer; never launches a unit or backup.

Run only from the protected install-tools path, inside an admitted host queue
invocation. All payload bytes and expected incumbent hashes are root-bound by a
reviewed bundle SHA. Partial installation is preserved for operator review.
"""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
try:
    import pwd
except ImportError:
    pwd=None
import re
import stat
import subprocess
import sys
import threading
import tarfile
import time

TOOLS=Path('/var/lib/ar-local-plain-backup-install-tools')
STAGE=Path('/var/lib/ar-local-plain-backup-stage')
HISTORY=Path('/var/lib/ar-local-plain-backup-install')
ROOT=Path('/usr/local/lib/ar-local-plain-backup')
QUEUE=Path('/usr/local/lib/shared-pi-queue')
RECLAIM=Path('/usr/local/lib/ar-local-drive-reclaim/pi_drive_reclaim.py')
STATE=Path('/var/lib/ar-local-plain-backup-control')
CONTROL={'broker.py','parent.py','reconcile.py','pi_plain_backup_core.py','pi_plain_backup_linux.py',
    'pi_plain_drive_resources.py','pi_shared_queue_post_hooks.py'}
QUEUE_NAMES={'pi_shared_queue.py','pi_shared_queue_store.py','pi_shared_queue_policy.py',
    'pi_shared_queue_native.py','pi_shared_queue_post_hooks.py'}
GUARD=None
RESOURCE_TARGET=None
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','HOME':'/root'}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def protected(path,maximum=64*1024**2):
    if path!=path.resolve(strict=True):raise RuntimeError('noncanonical protected path')
    for node in (path,*path.parents):
        info=node.lstat()
        if info.st_uid!=0 or stat.S_ISLNK(info.st_mode) or info.st_mode&0o022:
            raise RuntimeError('unprotected root installation input')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>maximum:
            raise RuntimeError('invalid bounded installation input')
        data=os.read(fd,maximum+1)
        if len(data)!=info.st_size:raise RuntimeError('installation input changed')
        return data
    finally:os.close(fd)


def validate_directory_stat(info,mode=None,gid=None):
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022
            or mode is not None and stat.S_IMODE(info.st_mode)!=mode
            or gid is not None and info.st_gid!=gid):
        raise RuntimeError('unprotected fixed installation directory')


def directory(path,mode=None,gid=None):
    created=False
    if not path.exists():
        directory(path.parent)
        path.mkdir(mode=0o755 if mode is None else mode);created=True
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        if created:
            # Explicit permissions survive serviceUMask0077, on this new inode
            # only. Existing private parents remain private and are not changed.
            os.fchown(fd,0,0 if gid is None else gid)
            os.fchmod(fd,0o755 if mode is None else mode);os.fsync(fd)
        info=os.fstat(fd);validate_directory_stat(info,mode,gid)
        current=path.lstat()
        if path.resolve()!=path or (info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino):
            raise RuntimeError('installation directory changed')
    finally:os.close(fd)


def publish(path,data,mode=0o644,*,exclusive=False):
    directory(path.parent)
    temporary=path.with_name('.'+path.name+'.install-pending')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        view=memoryview(data)
        while view:
            count=os.write(fd,view)
            if count<=0:raise RuntimeError('short installation write')
            view=view[count:]
        os.fchmod(fd,mode);os.fsync(fd)
    finally:os.close(fd)
    if exclusive:os.link(temporary,path);temporary.unlink()
    else:os.replace(temporary,path)
    fd=os.open(path.parent,os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    if GUARD is not None:GUARD.check()


def validate_plan(plan):
    if plan.get('schema')!='ar-local-plain-backup-install-v1' or plan.get('manual_plaintext_backup_scope') is not True:
        raise RuntimeError('specific backup-control installation authority absent')
    if set(plan.get('control',{}))!=CONTROL|{'build-packet.py','plan.py'} or set(plan.get('queue',{}))!=QUEUE_NAMES:
        raise RuntimeError('fixed installation file mapping differs')
    if set(plan.get('expected_existing_queue',{}))!=QUEUE_NAMES:
        raise RuntimeError('reviewed incumbent queue inventory incomplete')
    producer=plan.get('producer',{})
    if not 1<=len(producer)<=128 or 'pi_plain_backup_probe.py' not in producer:
        raise RuntimeError('bounded probe/producer closure required')
    for relative in producer:
        p=PurePosixPath(relative)
        if p.is_absolute() or '..' in p.parts or '\\' in relative or str(p)!=relative:
            raise RuntimeError('unsafe producer closure member')
    hashes=[*plan['control'].values(),*plan['queue'].values(),*producer.values(),
        plan.get('wrapper_sha256'),plan.get('expected_reclaim_sha256'),plan.get('global_hold_sha256'),
        plan.get('bwrap_sha256'),plan.get('setpriv_sha256'),plan.get('installer_sha256')]
    hashes += [v for v in plan['expected_existing_queue'].values() if v is not None]
    if any(not re.fullmatch('[a-f0-9]{64}',str(value)) for value in hashes):
        raise RuntimeError('reviewed source/incumbent hash missing')
    if (not re.fullmatch('[A-Za-z][A-Za-z0-9_-]*:plaintext-recovery',plan.get('remote',''))
            or not re.fullmatch('[A-Za-z0-9_-]{10,128}',plan.get('drive_root_folder_id',''))):
        raise RuntimeError('approved Drive destination pin missing')


def bounded_runtime(value):
    parts=re.findall(r'([0-9.]+)(us|ms|s|min|h|d)',value)
    if ''.join(n+unit for n,unit in parts)!=value.replace(' ',''):
        raise RuntimeError('finite installation runtime required')
    total=sum(float(n)*{'us':1e-6,'ms':0.001,'s':1,'min':60,'h':3600,'d':86400}[unit] for n,unit in parts)
    if not 0<total<=600:raise RuntimeError('installation runtime exceeds ten minutes')
    return total


def admitted_owner():
    group=Path('/proc/self/cgroup').read_text().strip()
    prefix='0::/system.slice/'
    if not group.startswith(prefix):raise RuntimeError('admitted installation service required')
    unit=group[len(prefix):]
    if not re.fullmatch('ar-local-queue-task-[a-f0-9]{32}\\.service',unit):
        raise RuntimeError('fixed manual installation queue prefix required')
    fd=os.open('/var/lib/shared-pi-queue/state.json',os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd);raw=os.read(fd,1048577)
        if not stat.S_ISREG(info.st_mode) or len(raw)!=info.st_size or len(raw)>1048576:
            raise RuntimeError('bounded actual queue state unavailable')
        jobs=json.loads(raw).get('jobs',[])
    finally:os.close(fd)
    rows=[job for job in jobs if job.get('unit')==unit]
    if len(rows)!=1:raise RuntimeError('unique installation claim absent')
    job=rows[0]
    if any(other.get('id')!=job['id'] and other.get('state')!='waiting' for other in jobs):
        raise RuntimeError('another occupied or ambiguous queue claim exists')
    if (job.get('project')!='ar-local' or job.get('state')!='running' or job.get('mode')!='exclusive'
            or set(job.get('resources',[]))!={'ar-local','host'} or job.get('cgroup')!=group[3:]):
        raise RuntimeError('exclusive host/ar-local installation claim absent')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    ticks=int(Path(f"/proc/{job['pid']}/stat").read_text().rsplit(')',1)[1].split()[19])
    current=os.getppid()
    for _ in range(4):
        if current==job['pid']:break
        proc=Path('/proc')/str(current)
        if str((proc/'exe').resolve())!=str(Path('/usr/bin/sudo').resolve()):
            raise RuntimeError('unexpected root installation ancestry')
        current=int((proc/'stat').read_text().rsplit(')',1)[1].split()[1])
    else:raise RuntimeError('installation is not a direct queued sudo command')
    native=Path('/srv/ar-local/data/state/daily-ingest.lock')
    fd=os.open(native,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd);body=os.read(fd,4097)
        values=dict(line.split('=',1) for line in body.decode('ascii').splitlines())
    finally:os.close(fd)
    expected={'pid':str(job['pid']),'boot_id':boot,'role':'shared-pi-host-task:'+job['id'],'recovery':'manual'}
    if (boot!=job.get('boot_id') or ticks!=job.get('start_ticks') or values!=expected
            or info.st_uid!=pwd.getpwnam('pi').pw_uid or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1):
        raise RuntimeError('exact installation native lease differs')
    result=subprocess.run(['/usr/bin/systemctl','show',unit,'--property=MainPID,InvocationID,ControlGroup,CPUQuotaPerSecUSec,IOWeight,TasksMax,KillMode,User,RuntimeMaxUSec','--no-pager'],
        capture_output=True,text=True,timeout=10,check=True,env=ENV)
    actual=dict(line.split('=',1) for line in result.stdout.splitlines())
    bounded_runtime(actual.pop('RuntimeMaxUSec',''))
    if actual!={'MainPID':str(job['pid']),'InvocationID':job['invocation_id'],'ControlGroup':job['cgroup'],
        'CPUQuotaPerSecUSec':'1s','IOWeight':'10','TasksMax':'64','KillMode':'control-group','User':'pi'}:
        raise RuntimeError('actual installation unit differs')
    return {key:job[key] for key in ('id','pid','start_ticks','boot_id','unit','invocation_id','cgroup')}


def preflight(plan):
    owner=admitted_owner()
    if Path('/proc/sys/vm/swappiness').read_text().strip()!='60' or Path('/var/lib/ar-local-drive-reclaim/current.json').exists():
        raise RuntimeError('unowned reclaim policy or active legacy journal')
    if sha(protected(Path('/etc/ar-local/drive-write-hold.json')))!=plan['global_hold_sha256']:
        raise RuntimeError('global legacy Drive hold changed')
    if STATE.exists() and any((entry/'intent.json').exists() for entry in STATE.iterdir()):
        raise RuntimeError('prior plaintext operation state needs independent review')
    for name,expected in plan['expected_existing_queue'].items():
        path=QUEUE/name
        if expected is None:
            if path.exists():raise RuntimeError('unexpected incumbent queue file')
        elif sha(protected(path))!=expected:raise RuntimeError('incumbent queue source changed')
    result=subprocess.run(['/usr/bin/systemctl','show','ar-local-drive-backup.service','ar-local-drive-reclaim.service',
        '--property=Id,ActiveState,MainPID,ControlPID','--no-pager'],capture_output=True,text=True,timeout=10,check=True,env=ENV)
    blocks=[dict(line.split('=',1) for line in block.splitlines()) for block in result.stdout.strip().split('\n\n')]
    if (len(blocks)!=2 or {row.get('Id') for row in blocks}!={'ar-local-drive-backup.service','ar-local-drive-reclaim.service'}
            or any(row.get('ActiveState') not in ('inactive','failed') or row.get('MainPID')!='0' or row.get('ControlPID')!='0' for row in blocks)):
        raise RuntimeError('legacy backup/reclaim is not quiescent')
    if sha(protected(RECLAIM))!=plan['expected_reclaim_sha256']:
        raise RuntimeError('incumbent reclaim entry changed')
    for path,key in ((Path('/usr/bin/bwrap').resolve(),'bwrap_sha256'),(Path('/usr/bin/setpriv').resolve(),'setpriv_sha256')):
        if sha(protected(path))!=plan[key]:raise RuntimeError('qualified sandbox runtime changed')
    return owner


def initial_host_sample():
    """Capture before reading the bounded bundle; same units as root policy."""
    memory=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    vm=dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
    page=os.sysconf('SC_PAGE_SIZE')
    if type(page) is not int or page<1024 or page&(page-1):raise RuntimeError('invalid actual page size')
    pressure=Path('/proc/pressure/memory')
    return {'available_bytes':int(memory['MemAvailable'].split()[0])*1024,'swap_out_pages':int(vm['pswpout']),
        'swap_in_pages':int(vm['pswpin']),'page_size_bytes':page,
        'psi_avg10':float(dict(item.split('=') for item in pressure.read_text().splitlines()[0].split()[1:])['avg10']) if pressure.exists() else None}


def prepare(bundle_id,archive_sha):
    """Unpack only expected regular members from an already protected archive."""
    if (sys.platform!='linux' or os.geteuid()!=0 or Path(__file__).resolve()!=TOOLS/'install.py'
            or not all(re.fullmatch('[a-f0-9]{64}',value) for value in (bundle_id,archive_sha))):
        raise RuntimeError('fixed root staging arguments required')
    owner=admitted_owner();before=initial_host_sample()
    raw=protected(TOOLS/'bundle.tar',maximum=64*1024**2)
    if sha(raw)!=archive_sha:raise RuntimeError('reviewed complete bundle archive SHA differs')
    import io
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        members=archive.getmembers()
        if len(members)>256 or any(not member.isfile() or member.size>64*1024**2 for member in members):
            raise RuntimeError('regular bounded staging members only')
        names=[member.name for member in members]
        if len(set(names))!=len(names) or 'manifest.json' not in names:raise RuntimeError('duplicate/missing staging manifest')
        manifest=archive.extractfile('manifest.json').read(65537)
        if len(manifest)>65536 or sha(manifest)!=bundle_id:raise RuntimeError('reviewed bundle manifest differs')
        plan=json.loads(manifest);validate_plan(plan)
        if sha(protected(TOOLS/'install.py'))!=plan['installer_sha256']:raise RuntimeError('installer source differs')
        expected={'manifest.json':bundle_id,'wrapper.py':plan['wrapper_sha256']}
        for family in ('control','queue','producer'):
            expected.update({family+'/'+name:value for name,value in plan[family].items()})
        if set(names)!=set(expected):raise RuntimeError('archive contains an unapproved destination')
        resource_source=archive.extractfile('control/pi_plain_drive_resources.py').read(1048577)
        if sha(resource_source)!=plan['control']['pi_plain_drive_resources.py']:
            raise RuntimeError('reviewed resource staging policy differs')
        global GUARD,RESOURCE_TARGET
        GUARD=InstallResources(owner,resource_source,baseline=before);GUARD.sample();GUARD.thread.start()
        target=STAGE/bundle_id
        if target.exists():raise RuntimeError('existing stage must be reviewed, never overwritten')
        directory(target,0o700)
        RESOURCE_TARGET=target/'preparation-resources.json'
        for member in members:
            content=archive.extractfile(member).read(member.size+1)
            if len(content)!=member.size or sha(content)!=expected[member.name]:raise RuntimeError('staged member hash differs')
            publish(target/member.name,content,0o444,exclusive=True)
        observations=GUARD.finish();GUARD=None
        publish(RESOURCE_TARGET,canonical(observations),0o400,exclusive=True)
    return {'result':'STAGED_NOT_INSTALLED','bundle':bundle_id}


class InstallResources:
    """Whole invocation sampled budget; existing swappiness60 is never changed."""
    def __init__(self,owner,reviewed_resource_source,baseline=None):
        self.owner=owner;self.stop=threading.Event();self.error=None;self.last=time.monotonic()
        namespace={"__name__":"_qualified_install_resource_policy"}
        # These exact protected bytes were hash-validated as root CONTROL code,
        # contain only stdlib monitoring definitions, and import no producer.
        exec(compile(reviewed_resource_source,"<reviewed-root-install-resource-policy>","exec"),namespace)
        self.policy=namespace;self.baseline=baseline if baseline is not None else namespace["sample_host"]()
        reason=namespace["host_violation"](self.baseline,self.baseline,self.baseline,admission=True)
        if reason:raise RuntimeError(reason)
        self.receipt={"schema":"ar-local-plain-backup-install-resources-v1","result":"RUNNING",
            "baseline":self.baseline,"samples":0,"peak_rss_bytes":0,"peak_workload_swap_bytes":0,
            "minimum_available_bytes":self.baseline["available_bytes"],"maximum_sample_gap_seconds":0}
        self.thread=threading.Thread(target=self.run,daemon=True)
    def members(self):
        root=Path('/sys/fs/cgroup')/self.owner['cgroup'].lstrip('/')
        files=list(root.glob('**/cgroup.procs'))
        if not 1<=len(files)<=8:raise RuntimeError('bounded installation cgroup required')
        pids={int(pid) for file in files for pid in file.read_text().split()}
        if len(pids)>64:raise RuntimeError('installation task bound exceeded')
        return pids
    def sample(self):
        rss=swapped=0
        for pid in self.members():
            try:memory=self.policy['process_memory'](pid)
            except ProcessLookupError:
                if pid not in self.members():continue
                raise
            if memory is None:continue
            rss+=memory['rss'];swapped+=memory['swap']
        current=self.policy['sample_host']();now=time.monotonic();gap=now-self.last
        self.receipt.update(samples=self.receipt['samples']+1,peak_rss_bytes=max(self.receipt['peak_rss_bytes'],rss),
            peak_workload_swap_bytes=max(self.receipt['peak_workload_swap_bytes'],swapped),
            minimum_available_bytes=min(self.receipt['minimum_available_bytes'],current['available_bytes']),
            maximum_sample_gap_seconds=max(self.receipt['maximum_sample_gap_seconds'],gap),last_host_sample=current)
        reason=self.policy['host_violation'](current,self.baseline,self.baseline)
        if rss>=640*1024**2:reason='aggregate_rss_early_stop'
        elif swapped:reason='workload_swapped'
        elif gap>2:reason='supervision_sample_gap'
        elif Path('/proc/sys/vm/swappiness').read_text().strip()!='60':reason='unowned_parameter_changed'
        self.last=now
        if reason:raise RuntimeError(reason)
    def run(self):
        while not self.stop.wait(0.1):
            try:self.sample()
            except Exception as error:
                self.error=error;return
    def check(self):
        if self.error is not None:raise RuntimeError('installation resource guard: '+type(self.error).__name__)
    def finish(self):
        self.stop.set();self.thread.join(timeout=2)
        if self.thread.is_alive():raise RuntimeError('installation resource supervisor did not terminate')
        self.check();self.sample();self.receipt['result']='PASS'
        return self.receipt


def apply(bundle_id):
    if not re.fullmatch('[a-f0-9]{64}',bundle_id):raise RuntimeError('exact reviewed bundle SHA required')
    if sys.platform!='linux' or os.geteuid()!=0 or Path(__file__).resolve()!=TOOLS/'install.py':
        raise RuntimeError('fixed protected Linux root installer required')
    bundle=STAGE/bundle_id;raw=protected(bundle/'manifest.json',maximum=65536)
    if sha(raw)!=bundle_id:raise RuntimeError('reviewed installation plan SHA differs')
    plan=json.loads(raw);validate_plan(plan)
    if sha(protected(TOOLS/'install.py'))!=plan['installer_sha256']:raise RuntimeError('installer reviewed bytes differ')
    owner=preflight(plan)
    history=HISTORY/bundle_id
    if history.exists():raise RuntimeError('existing installation journal must be reviewed, never overwritten')
    directory(history,0o700)
    publish(history/'prepared.json',canonical({'schema':1,'bundle':bundle_id,'owner':owner,
        'recorded_at':datetime.now(timezone.utc).isoformat()}),0o600,exclusive=True)
    global RESOURCE_TARGET
    RESOURCE_TARGET=history/'resources.json'
    resource_source=protected(bundle/'control/pi_plain_drive_resources.py')
    if sha(resource_source)!=plan['control']['pi_plain_drive_resources.py']:
        raise RuntimeError('installation resource policy differs')
    global GUARD
    GUARD=InstallResources(owner,resource_source);GUARD.sample();GUARD.thread.start()
    payload={}
    for family in ('control','queue','producer'):
        for name,expected in plan[family].items():
            data=protected(bundle/family/name)
            if sha(data)!=expected:raise RuntimeError('qualified staged source differs')
            payload[(family,name)]=data
            GUARD.check()
    wrapper=protected(bundle/'wrapper.py')
    if sha(wrapper)!=plan['wrapper_sha256']:raise RuntimeError('reviewed wrapper differs')
    if preflight(plan)!=owner:raise RuntimeError("installation admission changed during qualification")
    for name,expected in plan['expected_existing_queue'].items():
        if expected is not None:publish(history/'original-queue'/name,protected(QUEUE/name),0o600,exclusive=True)
    original=protected(RECLAIM)
    publish(history/'original-reclaim.py',original,0o600,exclusive=True)
    preserved=RECLAIM.with_name('pi_drive_reclaim.original.py')
    if preserved.exists():
        if sha(protected(preserved))!=plan['expected_reclaim_sha256']:raise RuntimeError('preserved original differs')
    else:publish(preserved,original,exclusive=True)
    # Publish the new optional dependency before queue modules start importing it.
    for name in sorted(plan['queue'],key=lambda name:name!='pi_shared_queue_post_hooks.py'):
        publish(QUEUE/name,payload[('queue',name)])
    for name in plan['control']:publish(ROOT/name,payload[('control',name)])
    for name in plan['producer']:publish(ROOT/'source'/name,payload[('producer',name)])
    controls={name:plan['control'][name] for name in CONTROL}
    publish(ROOT/'root-control-manifest.json',canonical(controls))
    bindings={'original_sha256':plan['expected_reclaim_sha256'],'wrapper_sha256':plan['wrapper_sha256'],
        'callback_sha256':plan['control']['reconcile.py'],'root_control_manifest_sha256':sha(canonical(controls))}
    publish(ROOT/'reconcile-wrapper-manifest.json',canonical(bindings))
    directory(STATE,0o700)
    receipt={'schema':'ar-local-plain-backup-installation-v1','bundle':bundle_id,'plan':plan,'owner':owner,
        'root_control_manifest_sha256':sha(canonical(controls)),'installed_at':datetime.now(timezone.utc).isoformat()}
    publish(STATE/'installation.json',canonical(receipt),0o600,exclusive=True)
    # The existing active timer keeps its SAME loaded entry path. The wrapper is
    # last, so it cannot see a half-published control/source closure.
    if admitted_owner()!=owner or Path('/var/lib/ar-local-drive-reclaim/current.json').exists():
        raise RuntimeError('installation ownership/legacy journal changed before dispatcher publication')
    result=subprocess.run(['/usr/bin/systemctl','show','ar-local-drive-backup.service','ar-local-drive-reclaim.service',
        '--property=Id,ActiveState,MainPID,ControlPID','--no-pager'],capture_output=True,text=True,timeout=10,check=True,env=ENV)
    blocks=[dict(line.split('=',1) for line in block.splitlines()) for block in result.stdout.strip().split('\n\n')]
    if (len(blocks)!=2 or {row.get('Id') for row in blocks}!={'ar-local-drive-backup.service','ar-local-drive-reclaim.service'}
            or any(row.get('ActiveState') not in ('inactive','failed') or row.get('MainPID')!='0' or row.get('ControlPID')!='0' for row in blocks)):
        raise RuntimeError('legacy backup/reclaim is not quiescent')
    if sha(protected(RECLAIM))!=plan['expected_reclaim_sha256']:raise RuntimeError('dispatcher changed during staging')
    publish(RECLAIM,wrapper)
    resource_receipt=GUARD.finish();GUARD=None
    publish(history/'resources.json',canonical(resource_receipt),0o600,exclusive=True)
    publish(history/'installed.json',canonical({'result':'INSTALLED_NOT_COMMISSIONED','bundle':bundle_id,
        'root_dispatcher_sha256':sha(protected(RECLAIM))}),0o600,exclusive=True)
    return {'result':'INSTALLED_NOT_COMMISSIONED','bundle':bundle_id,'preserved_originals':str(history)}


if __name__=='__main__':
    try:
        if len(sys.argv)==4 and sys.argv[1]=='prepare':
            result=prepare(sys.argv[2],sys.argv[3])
        elif len(sys.argv)==3 and sys.argv[1]=='apply':
            result=apply(sys.argv[2])
        else:raise RuntimeError('fixed prepare bundle archiveSHA or apply bundle required')
        print(json.dumps(result,sort_keys=True))
    except Exception as error:
        if GUARD is not None:
            GUARD.stop.set();GUARD.thread.join(timeout=2)
            receipt={**GUARD.receipt,'result':'FAIL','error_type':type(error).__name__}
            GUARD=None
            try:
                if RESOURCE_TARGET is not None and not RESOURCE_TARGET.exists():
                    publish(RESOURCE_TARGET,canonical(receipt),0o600,exclusive=True)
            except Exception:pass  # Preserve the original error and prepared journal.
        print(json.dumps({'result':'BLOCKED','error_type':type(error).__name__}))
        raise SystemExit(2)
