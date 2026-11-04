"""Root-owned stdlib resource monitor; producer runs only in a private sandbox."""
from __future__ import annotations
from datetime import datetime
try:
    import fcntl
except ImportError:  # Portable pure-policy tests; actual entry requires Linux.
    fcntl=None
import json
import os
from pathlib import Path,PurePosixPath
import select
import signal
import time

ROOT=PurePosixPath('/usr/local/lib/ar-local-plain-backup')
HANDOFF=PurePosixPath('/var/lib/ar-local-plain-backup-handoff')
WORK=PurePosixPath('/var/lib/ar-local-plain-backup-work')
MIB=1024**2


def sample_host():
    memory=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    vm=dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
    size=os.sysconf('SC_PAGE_SIZE')
    if type(size) is not int or size<1024 or size&(size-1):raise RuntimeError('invalid host page size')
    pressure=Path('/proc/pressure/memory')
    return {'available_bytes':int(memory['MemAvailable'].split()[0])*1024,
        'swap_out_pages':int(vm['pswpout']),'swap_in_pages':int(vm['pswpin']),'page_size_bytes':size,
        'psi_avg10':float(dict(item.split('=') for item in pressure.read_text().splitlines()[0].split()[1:])['avg10']) if pressure.exists() else None}


def host_violation(now,before,previous,*,admission=False):
    if now['page_size_bytes']!=before['page_size_bytes']:return 'page_size_changed'
    if any(now[key]<previous[key] or previous[key]<before[key] for key in ('swap_in_pages','swap_out_pages')):
        return 'host_swap_counter_reset'
    if now['available_bytes']<(3328 if admission else 2560)*MIB:return 'host_reserve_headroom'
    if now['swap_out_pages']!=before['swap_out_pages']:return 'host_swap_out_activity'
    if (now['swap_in_pages']-before['swap_in_pages'])*now['page_size_bytes']>16*MIB:return 'host_cold_swap_in_budget'
    if now['psi_avg10'] is not None and now['psi_avg10']>=10:return 'host_memory_pressure'
    return None


def context(host,packet,owner):
    stamp=host.now();expiry=datetime.fromisoformat(packet['expires_at']);issued=time.monotonic()
    source=Path(packet['data_root']).stat()
    ticks=int(Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19])
    return {'schema':'ar-local-plain-backup-attestation-v1','nonce':packet['nonce'],'unit':packet['unit'],
        'boot_id':host.boot(),'queue':{key:owner[key] for key in ('job_id','owner_pid','owner_ticks','invocation','cgroup','device','inode')},
        'source':{'device':source.st_dev,'inode':source.st_ino},'data_root':packet['data_root'],
        'operation':str(WORK/packet['nonce']/'sandbox'/'archive'),'source_closure_sha256':packet['source_closure_sha256'],
        'remote':packet['remote'],'drive_root_folder_id':packet['drive_root_folder_id'],
        'worker':{'uid':packet['uid'],'gid':packet['gid']},'issued_at':stamp.isoformat(),'expires_at':expiry.isoformat(),
        'issued_monotonic':issued,'deadline_monotonic':issued+min(21600,(expiry-stamp).total_seconds()),
        'monitor':{'pid':os.getpid(),'start_ticks':ticks,
            'user_namespace_inode':Path('/proc/self/ns/user').stat().st_ino,
            'pid_namespace_inode':Path('/proc/self/ns/pid').stat().st_ino,
            'mount_namespace_inode':Path('/proc/self/ns/mnt').stat().st_ino},
        'sandbox':{'private_mount':True,'private_pid':True,'host_uid_mapping':True,
            'readonly_source':True,'no_new_privileges':True,'capabilities_dropped':True}}


def sealed_context(value):
    fd=os.memfd_create('ar-local-plain-backup-context',os.MFD_ALLOW_SEALING|os.MFD_CLOEXEC)
    result=None
    try:
        raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
        if not 0<len(raw)<=16384:raise RuntimeError('bounded root context required')
        if os.write(fd,raw)!=len(raw):raise RuntimeError('short sealed context write')
        os.fchmod(fd,0o400)
        seals=fcntl.F_SEAL_WRITE|fcntl.F_SEAL_GROW|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_SEAL
        fcntl.fcntl(fd,fcntl.F_ADD_SEALS,seals)
        result=os.open(f'/proc/self/fd/{fd}',os.O_RDONLY|os.O_CLOEXEC)
        if fcntl.fcntl(result,fcntl.F_GET_SEALS)!=seals:raise RuntimeError('sealed context differs')
        return result
    except BaseException:
        if result is not None:os.close(result)
        raise
    finally:os.close(fd)


def sandbox_argv(packet):
    nonce=packet['nonce'];sandbox=str(WORK/nonce/'sandbox');operation=sandbox+'/archive';handoff=str(HANDOFF/nonce)
    script='pi_plain_backup_probe.py' if packet['mode']=='PROBE' else 'pi_plain_drive_backup.py'
    worker=['/usr/bin/python3','-B',str(ROOT/'source'/script),'--data-root','/srv/ar-local/data','--operation',operation,
        '--rclone-config',handoff+'/credentials-copy.conf','--remote',packet['remote'],
        '--drive-root-folder-id',packet['drive_root_folder_id'],'--attestation-fd','3','--deadline',packet['expires_at']]
    for path in packet.get('control_files',[]):
        if not str(path).startswith(str(ROOT)+'/') or '..' in PurePosixPath(path).parts:
            raise RuntimeError('explicit nonsecret immutable control path required')
        worker+=['--control-file',str(path)]
    drop=['/usr/bin/setpriv',f"--reuid={packet['uid']}",f"--regid={packet['gid']}",'--clear-groups',
        '--bounding-set=-all','--inh-caps=-all','--ambient-caps=-all','--no-new-privs','--',*worker]
    return ['/usr/bin/bwrap','--unshare-pid','--unshare-ipc','--die-with-parent','--new-session',
        '--ro-bind','/','/','--proc','/proc','--dev','/dev','--tmpfs','/run','--tmpfs','/tmp',
        '--tmpfs','/home','--tmpfs','/root','--tmpfs','/var/lib/ar-local-drive-backup/credentials',
        '--tmpfs','/var/lib/ar-local-plain-backup-control','--bind',sandbox,sandbox,
        '--ro-bind',handoff,handoff,'--chdir',sandbox,'--',*drop]


def bind_parent_lifetime(expected_pid):
    # Fixed Linux prctl closes the fork/exec gap before bwrap's parent-death
    # handling. Root imports only this stdlib libc interface, never producer code.
    import ctypes
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=expected_pid:
        raise RuntimeError('root monitor parent lifetime changed')


def fork_worker(host,packet,ctxfd):
    output=os.open(host.private/'worker.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    argv=sandbox_argv(packet);monitor=os.getpid()
    try:pid=os.fork()
    except BaseException:
        os.close(output)
        raise
    if pid==0:
        try:
            bind_parent_lifetime(monitor)
            os.dup2(ctxfd,3,inheritable=True);os.dup2(output,1);os.dup2(output,2)
            for name in os.listdir('/proc/self/fd'):
                fd=int(name)
                if fd>3:
                    try:os.close(fd)
                    except OSError:pass
            sandbox=str(WORK/packet['nonce']/'sandbox')
            env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','HOME':sandbox,
                'TMPDIR':sandbox,'TEMP':sandbox,'TMP':sandbox,'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1',
                'GOMEMLIMIT':'192MiB','GOGC':'50','GOMAXPROCS':'2'}
            os.execve(argv[0],argv,env)
        except BaseException:os._exit(75)
    os.close(output)
    return pid


def process_memory(pid):
    handle=os.pidfd_open(pid)
    try:
        poll=select.poll();poll.register(handle,select.POLLIN)
        if poll.poll(0):return None
        path=Path('/proc')/str(pid)
        try:
            status=dict(line.split(':',1) for line in (path/'status').read_text().splitlines())
            values=dict(line.split(':',1) for line in (path/'smaps_rollup').read_text().splitlines() if ':' in line)
            if poll.poll(0):return None
            return {'rss':int(values['Rss'].split()[0])*1024,'swap':int(values['Swap'].split()[0])*1024,
                'uid':int(status['Uid'].split()[0]),
                'uids':[int(item) for item in status['Uid'].split()],
                'gids':[int(item) for item in status['Gid'].split()],'nnp':int(status['NoNewPrivs'].strip()),
                'capabilities':sum(int(status[name].strip(),16) for name in ('CapEff','CapPrm','CapInh','CapAmb','CapBnd'))}
        except (FileNotFoundError,ProcessLookupError):
            if poll.poll(250):return None
            raise RuntimeError('live process accounting unavailable')
    finally:os.close(handle)


def snapshot_member(host,pid,group,*,trusted=False):
    """Use an outer pinned handle to distinguish exit races from live errors."""
    try:handle=os.pidfd_open(pid)
    except ProcessLookupError:
        if not trusted and pid not in host._members(group):return None
        raise
    try:
        poll=select.poll();poll.register(handle,select.POLLIN)
        if poll.poll(0):
            if trusted:raise RuntimeError('trusted process exited during accounting')
            return None
        try:
            item=host.process_identity(pid);memory=process_memory(pid)
        except Exception:
            # A live I/O, identity or proof error still fails. Only an exited
            # pinned kernel process can make a routine snapshot disappear.
            if not trusted and poll.poll(0):return None
            raise
        if poll.poll(0):
            if trusted:raise RuntimeError('trusted process exited during accounting')
            return None
        if memory is None:raise RuntimeError('live process memory proof unavailable')
        if item['cgroup']!=group:raise RuntimeError('live accounting process escaped its cgroup')
        return item,memory
    finally:os.close(handle)


def signal_pid(pid,signum,*,group,expected_ticks=None):
    # Pin the kernel object before proving cgroup/ticks; never signal a recycled
    # numeric PID observed in an earlier snapshot.
    handle=os.pidfd_open(pid)
    try:
        poll=select.poll();poll.register(handle,select.POLLIN)
        if poll.poll(0):return
        path=Path('/proc')/str(pid)
        ticks=int((path/'stat').read_text().rsplit(')',1)[1].split()[19])
        if ((path/'cgroup').read_text().strip()!='0::'+group
                or expected_ticks is not None and ticks!=expected_ticks):
            raise RuntimeError('cleanup PID scope/identity changed')
        if not poll.poll(0):signal.pidfd_send_signal(handle,signum)
    finally:os.close(handle)


def cleanup_scope(host,group,excluded,child,child_ticks,status):
    if status is None:
        try:signal_pid(child,signal.SIGKILL,group=group,expected_ticks=child_ticks)
        except ProcessLookupError:pass
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        for pid in set(host._members(group))-set(excluded):
            try:signal_pid(pid,signal.SIGKILL,group=group)
            except ProcessLookupError:pass
        if status is None:
            ended,waitstatus=os.waitpid(child,os.WNOHANG)
            if ended:status=os.waitstatus_to_exitcode(waitstatus)
        if not set(host._members(group))-set(excluded):break
        time.sleep(0.05)
    return not bool(set(host._members(group))-set(excluded))


def supervise(host,packet,owner):
    controller,parents=host._controller(packet)
    excluded={owner['owner_pid']:owner['owner_ticks'],controller['pid']:controller['ticks'],
        os.getpid():context(host,packet,owner)['monitor']['start_ticks']}
    excluded.update({item['pid']:item['ticks'] for item in parents})
    snapshots={pid:host.process_identity(pid) for pid in excluded}
    for pid,ticks in excluded.items():
        if snapshots[pid]['ticks']!=ticks or snapshots[pid]['cgroup']!=owner['cgroup']:
            raise RuntimeError('trusted process identity changed before worker')
    group=owner['cgroup'];before=owner['resource_baseline'];previous=sample_host();started=last=time.monotonic()
    violation=host_violation(previous,before,before,admission=True)
    if violation:raise RuntimeError(violation)
    payload=context(host,packet,owner);fd=sealed_context(payload);child=child_ticks=status=None
    result={'schema':'ar-local-plain-backup-resources-v1','result':'FAIL','mode':'sampled_cgroup_rss',
        'operation_mode':packet['mode'],'baseline':before,'peak_rss_bytes':0,'peak_workload_swap_bytes':0,
        'minimum_available_bytes':before['available_bytes'],'maximum_sample_gap_seconds':0,'samples':0,'group_clean':False}
    try:
        child=fork_worker(host,packet,fd)
        # A direct child cannot recycle its PID before we reap it. If it has
        # already exited, the normal wait-status path below is authoritative.
        try:child_ticks=host.process_identity(child)['ticks']
        except Exception:
            handle=os.pidfd_open(child)
            try:
                poll=select.poll();poll.register(handle,select.POLLIN)
                if not poll.poll(0):raise
            finally:os.close(handle)
        while True:
            host._job(packet)
            native=host._lease({'pid':owner['owner_pid'],'boot_id':owner['boot_id'],'id':owner['job_id']})
            if (native.st_dev,native.st_ino)!=(owner['device'],owner['inode']):raise RuntimeError('native lease inode changed during monitoring')
            now=time.monotonic();rss=swapped=0
            members=host._members(group)
            if not set(excluded)<=set(members):raise RuntimeError('trusted control process left the admitted cgroup')
            for pid in members:
                trusted=pid in excluded
                accounted=snapshot_member(host,pid,group,trusted=trusted)
                if accounted is None:continue
                item,memory=accounted
                if trusted and item!=snapshots[pid]:raise RuntimeError('trusted process identity changed')
                # The existing budget covers EVERY process in the invocation,
                # including wrapper, parent, sudo and the root monitor itself.
                rss+=memory['rss'];swapped+=memory['swap']
                if trusted:continue  # Only producer privilege tests are exempt.
                if memory.get('uids')==[0]*4:
                    if not host.trusted_namespace_process(item,child,packet):raise RuntimeError('unexpected privileged process in backup scope')
                elif (memory.get('uids')!=[packet['uid']]*4 or memory.get('gids')!=[packet['gid']]*4
                        or memory['nnp']!=1 or memory['capabilities']!=0):
                    raise RuntimeError('producer privilege fences differ')
            sample=sample_host();gap=now-last
            result.update(samples=result['samples']+1,peak_rss_bytes=max(result['peak_rss_bytes'],rss),
                peak_workload_swap_bytes=max(result['peak_workload_swap_bytes'],swapped),
                minimum_available_bytes=min(result['minimum_available_bytes'],sample['available_bytes']),
                maximum_sample_gap_seconds=max(result['maximum_sample_gap_seconds'],gap),last_host_sample=sample)
            reason=host_violation(sample,before,previous)
            if rss>=640*MIB:reason='aggregate_rss_early_stop'
            elif swapped:reason='workload_swapped'
            elif gap>2:reason='supervision_sample_gap'
            elif now>=payload['deadline_monotonic']:reason='workload_deadline'
            if reason:raise RuntimeError(reason)
            ended,waitstatus=os.waitpid(child,os.WNOHANG)
            if ended:
                status=os.waitstatus_to_exitcode(waitstatus)
                if status!=0:raise RuntimeError('producer_exit_nonzero')
                if set(host._members(group))-set(excluded):raise RuntimeError('producer_left_descendants')
                result.update(result='PASS',group_clean=True,workload_exit_code=0)
                break
            previous,last=sample,now;time.sleep(0.1)
    except BaseException as error:result['reason']=type(error).__name__+':'+str(error)
    finally:
        os.close(fd)
        if child is not None and result['result']!='PASS':
            result['group_clean']=cleanup_scope(host,group,excluded,child,child_ticks,status)
        result['elapsed_seconds']=time.monotonic()-started
    return result
