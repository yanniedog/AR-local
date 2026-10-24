"""Fixed existing-timer callback for both journals; no schedule/start mutation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import types

ROOT=Path('/usr/local/lib/ar-local-plain-backup')
STATE=Path('/var/lib/ar-local-plain-backup-control')
CANARY=Path('/usr/local/libexec/ar-local-canary-control')
CANARY_STATE=Path('/var/lib/ar-local-canary-control')
IMAGE=Path('/usr/local/lib/ar-local-system-recovery')
IMAGE_REGISTRY=Path('/etc/ar-local/system-recovery-reconcile.json')
DISPATCHER=Path('/usr/local/lib/ar-local-drive-reclaim/pi_drive_reclaim.py')
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','HOME':'/root'}


def protected(path):
    for item in (path,*path.parents):
        info=item.lstat()
        if info.st_uid!=0 or stat.S_ISLNK(info.st_mode) or info.st_mode&0o022:
            raise RuntimeError('unprotected root callback source')
    if not path.is_file() or path.stat().st_nlink!=1 or path.stat().st_size>65536:
        raise RuntimeError('invalid bounded root callback source')
    return path.read_bytes()


def load_hook_bytes(raw):
    """Import the captured verified hook without directory or pyc searches."""
    name='pi_shared_queue_post_hooks'
    if name in sys.modules:
        raise RuntimeError('unqualified root callback module cache exists')
    path=str(ROOT/(name+'.py'));module=types.ModuleType(name)
    module.__file__=path;module.__package__='';sys.modules[name]=module
    try:exec(compile(raw,path,'exec'),module.__dict__)
    except BaseException:
        sys.modules.pop(name,None)
        raise


def bootstrap():
    if sys.platform!='linux' or os.geteuid()!=0 or Path(__file__).resolve()!=ROOT/'reconcile.py':
        raise RuntimeError('fixed installed Linux root callback required')
    manifest=json.loads(protected(ROOT/'root-control-manifest.json'))
    bodies={}
    for name in ('reconcile.py','broker.py','pi_shared_queue_post_hooks.py'):
        raw=protected(ROOT/name)
        if hashlib.sha256(raw).hexdigest()!=manifest.get(name):
            raise RuntimeError('root reconciliation source binding differs')
        bodies[name]=raw
    load_hook_bytes(bodies['pi_shared_queue_post_hooks.py'])


def inactive(unit,run):
    result=run(['/usr/bin/systemctl','show',unit,'--no-pager',
        '--property=Id,LoadState,ActiveState,MainPID,ControlPID'],capture_output=True,text=True,timeout=5,env=ENV)
    rows=dict(line.split('=',1) for line in result.stdout.splitlines())
    if rows.get('Id')!=unit or rows.get('MainPID')!='0' or rows.get('ControlPID')!='0': return False
    return rows.get('ActiveState') in ('inactive','failed') and rows.get('LoadState') in ('loaded','not-found')


def reconcile_owned(run=subprocess.run,clock=time.monotonic):
    """One bounded pass; active jobs and ambiguous identities are never stopped."""
    from pi_shared_queue_post_hooks import root_json
    cutoff=clock()+29; actions=[]; failed=False; deferred=False
    try:
        if CANARY_STATE.exists() and (CANARY_STATE/'intent.json').exists():
            intent=root_json(CANARY_STATE/'intent.json')
            if intent.get('restore_required') is True and inactive('ar-local-canary-control.service',run):
                protected(CANARY/'entry.py')
                actions.append(['/usr/bin/python3','-I','-B',str(CANARY/'entry.py'),'recover'])
    except Exception:
        failed=True  # One damaged journal must not starve another owner.
    if STATE.exists():
        entries=list(STATE.iterdir())
        if len(entries)>128: raise RuntimeError('bounded nonce inventory exceeded')
        queue_path=Path('/var/lib/shared-pi-queue/state.json')
        queue=json.loads(queue_path.read_bytes()) if queue_path.exists() and queue_path.stat().st_size<=1048576 else {}
        units={job.get('unit') for job in queue.get('jobs',[]) if isinstance(job,dict)}
        for path in sorted(entries):
            if clock()>=cutoff-6:
                deferred=True
                break
            if not re.fullmatch('[0-9a-f]{32}',path.name): continue
            unit='ar-local-plain-backup-'+path.name+'.service'
            public=Path('/var/lib/ar-local-plain-backup-handoff')/path.name
            if (public/'completion.json').exists() or unit not in units: continue
            try:
                root_json(path/'packet.json')
                if inactive(unit,run):
                    actions.append(['/usr/bin/python3','-I','-B',str(ROOT/'broker.py'),'recover',path.name])
            except Exception:
                failed=True
    failed=failed or deferred
    for argv in actions:
        remaining=cutoff-clock()
        if remaining<=1: return 2
        try:
            result=run(argv,capture_output=True,timeout=min(10,remaining),check=False,env=ENV)
            failed=failed or result.returncode!=0
        except subprocess.TimeoutExpired: failed=True
    return 2 if failed else 0


def reconcile_image(run=subprocess.run):
    """Only the optional fixed root registry can add this bounded callback."""
    try:
        IMAGE_REGISTRY.lstat()
    except FileNotFoundError:
        return 0
    from pi_shared_queue_post_hooks import root_json
    registry=root_json(IMAGE_REGISTRY)
    if (set(registry)!={'schema','callback','callback_sha256','source_closure_sha256','wrapper_sha256'}
            or registry.get('schema')!='ar-local-system-recovery-reconcile-v1'
            or registry.get('callback')!=str(IMAGE/'reconcile.py')
            or not all(re.fullmatch('[0-9a-f]{64}',str(registry.get(key,''))) for key in
                ('callback_sha256','source_closure_sha256','wrapper_sha256'))
            or hashlib.sha256(protected(IMAGE/'reconcile.py')).hexdigest()!=registry['callback_sha256']
            or hashlib.sha256(protected(DISPATCHER)).hexdigest()!=registry['wrapper_sha256']):
        raise RuntimeError('fixed image recovery callback registry differs')
    result=run(['/usr/bin/python3','-I','-S','-B',str(IMAGE/'reconcile.py')],
        capture_output=True,timeout=5,check=False,env=ENV)
    return 0 if result.returncode==0 else 2


def reconcile(run=subprocess.run,clock=time.monotonic):
    # Reserve the image callback's five seconds inside the existing40-second
    # wrapper allocation. A damaged legacy/plain/canary pass must not skip it.
    failed=False
    try:failed=reconcile_owned(run,clock)!=0
    except Exception:failed=True
    try:failed=reconcile_image(run)!=0 or failed
    except Exception:failed=True
    return 2 if failed else 0


def main():
    bootstrap()
    return reconcile()


if __name__=='__main__':
    raise SystemExit(main())
