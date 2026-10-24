"""Fixed root-owned packet builder. It never starts a unit or writes to Drive."""
from datetime import datetime,timezone,timedelta,time
import hashlib
import json
import os
from pathlib import Path
try:
    import pwd
except ImportError:
    pwd=None
import re
import stat
import sys
from zoneinfo import ZoneInfo

ROOT=Path('/usr/local/lib/ar-local-plain-backup')
STATE=Path('/var/lib/ar-local-plain-backup-control')
HANDOFF=Path('/var/lib/ar-local-plain-backup-handoff')
WORK=Path('/var/lib/ar-local-plain-backup-work')
CONFIG=Path('/var/lib/ar-local-drive-backup/credentials/dedicated-20260913-ready3/rclone-verified-ready3.conf')


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def digest(raw):return hashlib.sha256(raw).hexdigest()


def protected(path,maximum=64*1024**2):
    if path.resolve(strict=True)!=path:raise RuntimeError('canonical protected source required')
    for node in (path,*path.parents):
        info=node.lstat()
        if info.st_uid!=0 or stat.S_ISLNK(info.st_mode) or info.st_mode&0o022:
            raise RuntimeError('root packet source not protected')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>maximum:
            raise RuntimeError('invalid bounded packet source')
        raw=os.read(fd,maximum+1)
        if len(raw)!=info.st_size:raise RuntimeError('packet source changed')
        return raw
    finally:os.close(fd)


def directory(path,mode,gid=0):
    if not path.exists():path.mkdir(mode=mode);os.chown(path,0,gid)
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or path.resolve()!=path:
        raise RuntimeError('root packet directory differs')


def publish(path,raw,mode=0o600,gid=0):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        view=memoryview(raw)
        while view:
            count=os.write(fd,view)
            if count<=0:raise RuntimeError('short packet write')
            view=view[count:]
        os.fchmod(fd,mode);os.fchown(fd,0,gid);os.fsync(fd)
    finally:os.close(fd)
    fd=os.open(path.parent,os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def validate_credential_stat(info,uid,gid):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=uid or info.st_gid!=gid
            or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600 or not 0<info.st_size<=65536):
        raise RuntimeError('canonical original credential leaf differs')


def credential_original(uid,gid):
    # The existing canonical leaf is Pi-owned0600 below root-owned0700 custody.
    # Only the operation COPY is root-owned0440; never chmod/chown the original.
    if CONFIG.resolve(strict=True)!=CONFIG:raise RuntimeError('credential source is not canonical')
    for parent in CONFIG.parents:
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
            raise RuntimeError('credential parent custody differs')
    if stat.S_IMODE(CONFIG.parent.lstat().st_mode)!=0o700:
        raise RuntimeError("canonical credential custody parent must stay root0700")
    fd=os.open(CONFIG,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd);validate_credential_stat(before,uid,gid)
        raw=os.read(fd,65537);after=os.fstat(fd);leaf=CONFIG.lstat()
        stable=lambda item:(item.st_dev,item.st_ino,item.st_size,item.st_mtime_ns,item.st_ctime_ns)
        if len(raw)!=before.st_size or stable(before)!=stable(after) or stable(after)!=stable(leaf):
            raise RuntimeError('credential source changed during private read')
        validate_credential_stat(after,uid,gid)
        return raw
    finally:os.close(fd)


def normalized_kernel(evidence,boot,bwrap,setpriv):
    o=evidence.get('observed',{});host=evidence.get('host_namespaces',{});names=o.get('namespaces',{})
    if (evidence.get('boot_id')!=boot or evidence.get('exit')!=0
            or evidence.get('scope')!='kernel-confinement-probe-only-no-backup-acceptance'
            or evidence.get('runtime_sha256')!={'/usr/bin/bwrap':bwrap,'/usr/bin/setpriv':setpriv}
            or o.get('result')!='PASS_KERNEL_CONFINEMENT_ONLY' or o.get('groups')!=[] or o.get('NNP')!='1'
            or o.get('source_ro') is not True or o.get('pid1_root')!='ACCESS_DENIED'
            or o.get('fd_root_owned') is not True or o.get('fd_readonly') is not True or o.get('fd_seals')!=15
            or set(o.get('caps',{}))!={'CapInh','CapPrm','CapEff','CapBnd','CapAmb'}
            or any(value!='0000000000000000' for value in o['caps'].values())
            or not all(type(host.get(name)) is int and host[name]>0 for name in ('user','pid','mnt'))
            or not all(type(names.get(name)) is int and names[name]>0 for name in ('user','pid','mnt'))
            or names.get('user')!=host['user'] or names.get('pid')==host['pid'] or names.get('mnt')==host['mnt']):
        raise RuntimeError('actual qualified kernel confinement evidence differs')
    return {'schema':'ar-local-plain-backup-sandbox-probe-v1','result':'PASS','boot_id':boot,
        'bwrap_sha256':bwrap,'setpriv_sha256':setpriv,'private_pid_mount':True,'host_uid_mapping':True,
        'source_readonly':True,'no_host_proc_alias':True,'nnp_all_caps_dropped':True,'sealed_context_verified':True,
        'scope':'KERNEL_ONLY_NOT_COUPLED_OR_BACKUP','evidence_sha256':digest(canonical(evidence))}


def expiry_for(mode,now):
    local=now.astimezone(ZoneInfo('Australia/Hobart'))
    if time(0,25)<=local.time().replace(tzinfo=None)<time(3,30):
        raise RuntimeError('natural-ingest quiet window')
    limit=now+timedelta(seconds=120 if mode=='PROBE' else 21600)
    midnight=local.replace(hour=0,minute=25,second=0,microsecond=0)
    if midnight<=local:midnight+=timedelta(days=1)
    # Leave one second before00:25 to satisfy the producer cleanup boundary.
    limit=min(limit,midnight.astimezone(timezone.utc)-timedelta(seconds=1))
    if (limit-now).total_seconds()<15:raise RuntimeError('insufficient bounded operation window')
    return limit


def bootstrap():
    if sys.platform!='linux' or os.geteuid()!=0 or Path(__file__).resolve()!=ROOT/'build-packet.py':
        raise RuntimeError('fixed protected Linux root packet builder required')
    receipt=json.loads(protected(STATE/'installation.json',65536));plan=receipt['plan']
    if receipt.get('schema')!='ar-local-plain-backup-installation-v1':raise RuntimeError('installation receipt missing')
    for name,expected in plan['control'].items():
        if digest(protected(ROOT/name))!=expected:raise RuntimeError('installed root control changed')
    if digest(protected(ROOT/'root-control-manifest.json'))!=receipt['root_control_manifest_sha256']:
        raise RuntimeError('installed root import manifest changed')
    for name,expected in plan['queue'].items():
        if digest(protected(Path('/usr/local/lib/shared-pi-queue')/name))!=expected:
            raise RuntimeError('installed queue closure changed')
    return receipt


def build(mode,nonce,coupled_nonce=None):
    if mode not in ('PROBE','RUN_ARCHIVE') or not re.fullmatch('[a-f0-9]{32}',nonce):
        raise RuntimeError('fixed mode and fresh nonce required')
    receipt=bootstrap();plan=receipt['plan'];pi=pwd.getpwnam('pi')
    if pi.pw_uid==0:raise RuntimeError('non-root Pi account required')
    if Path('/proc/sys/vm/swappiness').read_text().strip()!='60':raise RuntimeError('unowned parameter must already be60')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    for row in Path('/proc/self/mountinfo').read_text().splitlines():
        left,right=row.split(' - ',1)
        if right.split()[0]=='proc' and left.split()[4]!='/proc':raise RuntimeError('host proc alias present')
    probe=normalized_kernel(plan['kernel_probe'],boot,plan['bwrap_sha256'],plan['setpriv_sha256'])
    if (plan['kernel_probe']['observed']['uid'],plan['kernel_probe']['observed']['gid'])!=(pi.pw_uid,pi.pw_gid):
        raise RuntimeError('qualified worker identity changed')
    closure={'source/'+name:value for name,value in plan['producer'].items()}
    for name,expected in closure.items():
        if digest(protected(ROOT/name))!=expected:raise RuntimeError('installed producer dependency changed')
    now=datetime.now(timezone.utc);expires=expiry_for(mode,now)
    packet={'schema':'ar-local-plain-backup-packet-v1','mode':mode,'nonce':nonce,
        'unit':'ar-local-plain-backup-'+nonce+'.service','manual_plaintext_drive_write':True,
        'created_at':now.isoformat(),'expires_at':expires.isoformat(),'uid':pi.pw_uid,'gid':pi.pw_gid,
        'data_root':'/srv/ar-local/data','credential_source':str(CONFIG),'remote':plan['remote'],
        'drive_root_folder_id':plan['drive_root_folder_id'],'closure':closure,
        'source_closure_sha256':digest(canonical(closure)),'queue_closure':plan['queue'],
        'queue_closure_sha256':digest(canonical(plan['queue'])),'global_hold_sha256':plan['global_hold_sha256'],
        'parent_sha256':plan['control']['parent.py'],'resources_sha256':plan['control']['pi_plain_drive_resources.py'],
        'broker_sha256':plan['control']['broker.py'],'bwrap_sha256':plan['bwrap_sha256'],
        'setpriv_sha256':plan['setpriv_sha256'],'reconcile_wrapper_sha256':plan['wrapper_sha256'],
        'reconcile_original_sha256':plan['expected_reclaim_sha256'],'reconcile_callback_sha256':plan['control']['reconcile.py']}
    if mode=='RUN_ARCHIVE':
        if not coupled_nonce or not re.fullmatch('[a-f0-9]{32}',coupled_nonce) or coupled_nonce==nonce:
            raise RuntimeError('distinct actual commissioning nonce required')
        packet['coupled_probe_nonce']=coupled_nonce
        complete=json.loads(protected(HANDOFF/coupled_nonce/'completion.json',65536))
        coupled=json.loads(protected(HANDOFF/coupled_nonce/'coupled-probe.json',65536))
        if (complete.get('operation_mode')!='PROBE' or complete.get('stop_post_verified') is not True
                or complete.get('resource_acceptance')!='PASS' or complete.get('readback')!=60
                or coupled.get('boot_id')!=boot or coupled.get('result')!='PROBE_PASS'
                or any(coupled.get(key)!=packet[key] for key in ('source_closure_sha256','queue_closure_sha256',
                    'bwrap_sha256','setpriv_sha256','parent_sha256','resources_sha256','broker_sha256'))):
            raise RuntimeError('actual same-closure coupled commissioning proof required')
    config=credential_original(pi.pw_uid,pi.pw_gid);packet['credential_sha256']=digest(config)
    # Both imported modules are already hash-verified installed root controls.
    sys.path.insert(0,str(ROOT))
    from pi_plain_backup_core import validate_packet
    from plan import service_plan
    validate_packet(packet,nonce,now);service=service_plan(nonce,mode=mode)
    private=STATE/nonce;public=HANDOFF/nonce;work=WORK/nonce
    if any(path.exists() for path in (private,public,work)):raise RuntimeError('fresh unused nonce required')
    directory(HANDOFF,0o750,pi.pw_gid);directory(WORK,0o755)
    directory(private,0o700);directory(public,0o750,pi.pw_gid);directory(work,0o750,pi.pw_gid)
    (work/'sandbox').mkdir(mode=0o700);os.chown(work/'sandbox',pi.pw_uid,pi.pw_gid)
    publish(private/'packet.json',canonical(packet))
    publish(private/'sandbox-probe.json',canonical(probe))
    publish(private/'service-plan.json',canonical(service))
    authority={key:packet[key] for key in ('nonce','unit','manual_plaintext_drive_write','data_root',
        'expires_at','source_closure_sha256','parent_sha256','resources_sha256','broker_sha256')}
    authority.update(schema='ar-local-plain-backup-authority-v1',queue_argv_sha256=service['queue_argv_sha256'])
    publish(public/'credentials-copy.conf',config,0o440,pi.pw_gid)
    publish(public/'worker.json',canonical({'schema':'ar-local-plain-backup-worker-v1','nonce':nonce}),0o640,pi.pw_gid)
    # Authority is published last; no recognizable unit can register before the
    # complete packet/config/private sandbox exists. This does not launch it.
    publish(public/'approval.json',canonical(authority),0o640,pi.pw_gid)
    return {'result':'PACKET_PREPARED_NOT_STARTED','mode':mode,'nonce':nonce,'expires_at':expires.isoformat(),
        'service_plan':str(private/'service-plan.json'),'source_closure_sha256':packet['source_closure_sha256']}


if __name__=='__main__':
    try:
        if len(sys.argv) not in (3,4):raise RuntimeError('fixed mode nonce and optional probe nonce required')
        print(json.dumps(build(*sys.argv[1:]),sort_keys=True))
    except Exception as error:
        print(json.dumps({'result':'BLOCKED','error_type':type(error).__name__}))
        raise SystemExit(2)
