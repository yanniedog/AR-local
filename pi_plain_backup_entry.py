"""Installed as broker.py; fixed root verbs only, never producer imports."""
from __future__ import annotations

from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import types

ROOT=Path("/usr/local/lib/ar-local-plain-backup")
STATE=Path("/var/lib/ar-local-plain-backup-control")


def control_bytes(path):
    info=path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022
            or info.st_nlink!=1 or info.st_size>65536):
        raise RuntimeError('bounded protected root control required')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        stable=lambda item:(item.st_dev,item.st_ino,item.st_uid,item.st_mode,item.st_nlink,
                            item.st_size,item.st_mtime_ns,item.st_ctime_ns)
        if stable(before)!=stable(info):raise RuntimeError('root control changed before read')
        raw=os.read(fd,65537);after=os.fstat(fd)
        if len(raw)!=before.st_size or stable(before)!=stable(after) or stable(after)!=stable(path.lstat()):
            raise RuntimeError('root control changed during read')
        return raw
    finally:os.close(fd)


def bootstrap():
    if sys.platform!="linux" or os.geteuid()!=0 or Path(__file__).resolve()!=ROOT/"broker.py":
        raise RuntimeError("fixed installed Linux root broker required")
    for path in (ROOT,*ROOT.parents,STATE,*STATE.parents):
        info=path.lstat()
        if info.st_uid!=0 or stat.S_ISLNK(info.st_mode) or info.st_mode&0o022:
            raise RuntimeError("root control path is not protected")
    value=json.loads(control_bytes(ROOT/"root-control-manifest.json"))
    names={"broker.py","pi_plain_backup_core.py","pi_plain_backup_linux.py","pi_shared_queue_post_hooks.py",
           "pi_plain_drive_resources.py","parent.py","reconcile.py"}
    if set(value)!=names: raise RuntimeError("root import closure differs")
    bodies={}
    for name,expected in value.items():
        raw=control_bytes(ROOT/name)
        if hashlib.sha256(raw).hexdigest()!=expected:
            raise RuntimeError("root import closure hash differs")
        bodies[name]=raw
    load_controls(bodies)


def load_controls(bodies):
    """Execute only captured, already verified source; never path/pyc loaders."""
    names=('pi_plain_backup_core','pi_shared_queue_post_hooks','pi_plain_drive_resources','pi_plain_backup_linux')
    if any(name in sys.modules for name in names):
        raise RuntimeError('unqualified root control module cache exists')
    for name in names:
        path=str(ROOT/(name+'.py'));module=types.ModuleType(name)
        module.__file__=path;module.__package__='';sys.modules[name]=module
        try:exec(compile(bodies[name+'.py'],path,'exec'),module.__dict__)
        except BaseException:
            sys.modules.pop(name,None)
            raise


def failure_record(action,nonce,stage,error):
    """Best-effort root-private metadata only; never exception text or argv."""
    if action not in ("acquire","finish","recover") or not re.fullmatch("[0-9a-f]{32}",nonce):return
    private=STATE/nonce
    for path in (private,*private.parents):
        info=path.lstat()
        if info.st_uid!=0 or not stat.S_ISDIR(info.st_mode) or info.st_mode&0o022:
            raise RuntimeError("failure receipt custody differs")
    if private.stat().st_mode&0o077:raise RuntimeError("private failure receipt required")
    if not re.fullmatch('[a-z_]{1,48}',stage):stage='unknown'
    value={'schema':'ar-local-plain-backup-root-failure-v1','nonce':nonce,'action':action,
        'stage':stage,'error_type':type(error).__name__,'recorded_at':datetime.now(timezone.utc).isoformat()}
    raw=(json.dumps(value,sort_keys=True)+'\n').encode()
    directory=os.open(private,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fd=os.open('failure-'+action+'.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
        try:
            if os.write(fd,raw)!=len(raw):raise RuntimeError('short failure receipt')
            os.fchmod(fd,0o600);os.fsync(fd)
        finally:os.close(fd)
        os.fsync(directory)
    finally:os.close(directory)


def main(action,nonce):
    if action not in ("acquire","finish","recover") or not re.fullmatch("[0-9a-f]{32}",nonce):
        raise RuntimeError("fixed verb and nonce required")
    stage='entry_bootstrap';host=None;qualified=False;fd=None
    try:
        bootstrap();qualified=True
        import fcntl
        import pi_plain_backup_core as broker_core
        from pi_plain_backup_linux import Host
        private=STATE/nonce;stage='entry_lock'
        info=private.lstat()
        if info.st_uid!=0 or not stat.S_ISDIR(info.st_mode) or info.st_mode&0o077:
            raise RuntimeError("protected nonce state required")
        fd=os.open(private/"lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        host=Host(nonce);host.stage='acquire_policy' if action=='acquire' else 'finish_policy'
        if action=="acquire":
            result=broker_core.acquire(host,nonce)
            host.stage='worker'
            host.run_worker(host.packet(nonce),host.intent(nonce)["identity"])
            result["worker_result"]="PASS"
        else:
            result=broker_core.finish(host,nonce,recovery=action=="recover")
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception as error:
        stage=getattr(host,'stage',stage)
        try:error.diagnostic_stage=stage
        except Exception:pass
        if qualified:
            try:failure_record(action,nonce,stage,error)
            except Exception:pass  # Preserve the primary failure and first record.
        raise
    finally:
        if fd is not None:os.close(fd)


if __name__=="__main__":
    try:
        if len(sys.argv)!=3: raise RuntimeError("fixed verb/nonce required")
        raise SystemExit(main(*sys.argv[1:]))
    except Exception as error:
        # Never include secret config, environment, argv or provider bodies.
        print(json.dumps({"result":"BLOCKED","error":type(error).__name__,"stage":getattr(error,"diagnostic_stage","entry_arguments")}))
        raise SystemExit(2)
