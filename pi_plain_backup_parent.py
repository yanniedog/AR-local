"""Root-owned but unprivileged trusted parent; no producer imports before NNP."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import stat
import types

ROOT=Path("/usr/local/lib/ar-local-plain-backup")
HANDOFF=Path("/var/lib/ar-local-plain-backup-handoff")
WORK=Path("/var/lib/ar-local-plain-backup-work")


class HelperFailure(RuntimeError):
    def __init__(self,action,stage='unknown',error_type='UNKNOWN'):
        super().__init__('fixed helper failed')
        self.action=action;self.stage=stage;self.error_type=error_type;self.cleanup_error=None


def helper(action,nonce):
    if action not in ("acquire","finish"): raise RuntimeError("fixed helper action only")
    result=subprocess.run(["/usr/bin/sudo","-n","/usr/bin/python3","-I","-B",
        str(ROOT/"broker.py"),action,nonce],check=False,capture_output=True,text=True,
        timeout=21630 if action=="acquire" else 30)
    if result.returncode:
        stage='unknown';error_type='UNKNOWN'
        # Only the fixed root broker's tiny structured labels may be forwarded.
        # Provider stderr, config, argv and arbitrary exception text stay private.
        try:
            if len(result.stdout)>4096:raise ValueError('bounded helper labels only')
            value=json.loads(result.stdout)
            if value.get('result')=='BLOCKED':
                if re.fullmatch('[a-z_]{1,48}',str(value.get('stage',''))):stage=value['stage']
                if re.fullmatch('[A-Za-z_]{1,48}',str(value.get('error',''))):error_type=value['error']
        except (ValueError,TypeError,AttributeError):pass
        raise HelperFailure(action,stage,error_type)
    return result


def run_helpers(nonce):
    primary=None
    try:helper('acquire',nonce)
    except BaseException as error:primary=error
    finally:
        try:helper('finish',nonce)
        except BaseException as cleanup:
            if primary is None:primary=cleanup
            elif isinstance(primary,HelperFailure):primary.cleanup_error=type(cleanup).__name__
    if primary is not None:raise primary
    return 0


def trusted_bytes(path):
    for node in (path,*path.parents):
        info=node.lstat()
        if info.st_uid!=0 or stat.S_ISLNK(info.st_mode) or info.st_mode&0o022:
            raise RuntimeError('trusted parent source custody differs')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>65536:
            raise RuntimeError('bounded trusted parent source required')
        raw=os.read(fd,65537);after=os.fstat(fd)
        identity=lambda item:(item.st_dev,item.st_ino,item.st_size,item.st_mtime_ns,item.st_ctime_ns)
        if len(raw)!=before.st_size or identity(before)!=identity(after):raise RuntimeError('parent source changed')
        return raw
    finally:os.close(fd)


def load_hooks():
    manifest=json.loads(trusted_bytes(ROOT/'root-control-manifest.json'))
    raw=trusted_bytes(ROOT/'pi_shared_queue_post_hooks.py')
    if (hashlib.sha256(raw).hexdigest()!=manifest.get('pi_shared_queue_post_hooks.py')
            or hashlib.sha256(trusted_bytes(ROOT/'parent.py')).hexdigest()!=manifest.get('parent.py')):
        raise RuntimeError('trusted parent import closure differs')
    module=types.ModuleType('_plain_parent_verified_hooks')
    module.__file__=str(ROOT/'pi_shared_queue_post_hooks.py')
    exec(compile(raw,module.__file__,'exec'),module.__dict__)
    return module


def main(nonce):
    if (sys.platform!="linux" or os.geteuid()==0 or not re.fullmatch("[0-9a-f]{32}",nonce)
            or Path(__file__).resolve()!=ROOT/"parent.py"):
        raise RuntimeError("fixed installed unprivileged parent required")
    hooks=load_hooks()
    approval,root_json=hooks.approval,hooks.root_json
    authority=approval("ar-local-plain-backup-"+nonce+".service",current=True)
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=authority["parent_sha256"]:
        raise RuntimeError("trusted parent source bytes differ")
    status=dict(line.split(":",1) for line in Path("/proc/self/status").read_text().splitlines())
    if status["NoNewPrivs"].strip()!="0": raise RuntimeError("trusted fixed-helper parent requires NNPfalse")
    plan=root_json(HANDOFF/nonce/"worker.json")
    if plan.get("nonce")!=nonce or plan.get("schema")!="ar-local-plain-backup-worker-v1":
        raise RuntimeError("root-bound worker plan differs")
    fd=os.open("/srv/ar-local/data/state/daily-ingest.lock",os.O_RDONLY|os.O_NOFOLLOW)
    if fd!=3: os.dup2(fd,3,inheritable=True); os.close(fd)
    else: os.set_inheritable(3,True)
    try:
        # Root acquire owns the NNP namespace/monitor. This trusted parent never
        # executes producer source; finish runs even when acquire fails.
        return run_helpers(nonce)
    finally:os.close(3)


def failure_output(error):
    value={'result':'BLOCKED','error':type(error).__name__}
    if isinstance(error,HelperFailure):
        value.update(action=error.action,stage=error.stage,helper_error=error.error_type)
        if error.cleanup_error is not None:value['cleanup_error']=error.cleanup_error
    return value


if __name__=="__main__":
    try:
        if len(sys.argv)!=2: raise RuntimeError("nonce required")
        raise SystemExit(main(sys.argv[1]))
    except Exception as error:
        print(json.dumps(failure_output(error)))
        raise SystemExit(2)
