"""Fixed dispatcher compatibility wrapper; original reviewed bytes are preserved.

Installed atomically at the existing loaded entry path only after independently
proving no active legacy reclaim journal. No timer schedule/start changes occur.
"""
from pathlib import Path
import hashlib
import json
import os
import stat
import subprocess
import sys

ENTRY=Path('/usr/local/lib/ar-local-drive-reclaim/pi_drive_reclaim.py')
ORIGINAL=ENTRY.with_name('pi_drive_reclaim.original.py')
ROOT=Path('/usr/local/lib/ar-local-plain-backup')


def bounded_root(path):
    for node in (path,*path.parents):
        info=node.lstat()
        if info.st_uid!=0 or stat.S_ISLNK(info.st_mode) or info.st_mode&0o022:
            raise RuntimeError('root dispatcher source not protected')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>1048576:
        raise RuntimeError('invalid bounded root dispatcher source')
    return path.read_bytes()


def bootstrap():
    if sys.platform!='linux' or os.geteuid()!=0 or Path(__file__).resolve()!=ENTRY:
        raise RuntimeError('fixed installed existing root dispatcher required')
    bindings=json.loads(bounded_root(ROOT/'reconcile-wrapper-manifest.json'))
    paths={'original_sha256':ORIGINAL,'wrapper_sha256':ENTRY,'callback_sha256':ROOT/'reconcile.py',
           'root_control_manifest_sha256':ROOT/'root-control-manifest.json'}
    if set(bindings)!=set(paths):raise RuntimeError('existing dispatcher closure differs')
    for key,path in paths.items():
        if hashlib.sha256(bounded_root(path)).hexdigest()!=bindings[key]:
            raise RuntimeError('existing dispatcher hash differs')
    return bounded_root(ORIGINAL)


def legacy_main(raw):
    # Original main's fixed-entry invariant remains the actual dispatcher. The
    # exact preserved bytes are compiled with their real filename for tracebacks.
    namespace={'__name__':'_reviewed_original_drive_reclaim','__file__':str(ENTRY)}
    exec(compile(raw,str(ORIGINAL),'exec'),namespace)
    namespace['main']()


def bounded_legacy_reconcile(raw):
    # Original logic runs in the same root service cgroup with a bounded parent
    # wait, leaving enough of the existing90-second service budget for callbacks.
    result=subprocess.run(['/usr/bin/python3','-I','-B',str(ENTRY),'reconcile-original'],
        capture_output=True,timeout=40,check=False,
        env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','HOME':'/root'})
    if result.returncode:raise RuntimeError('original reconciliation failed')


def dispatch(action,raw,*,legacy=None,run=subprocess.run):
    if action not in ('acquire','finish','reconcile'):raise RuntimeError('fixed original verbs only')
    error=None
    try:(legacy or (bounded_legacy_reconcile if action=="reconcile" else legacy_main))(raw)
    except BaseException as failure:error=failure
    callback_status=0
    if action=='reconcile':
        try:
            result=run(['/usr/bin/python3','-I','-B',str(ROOT/'reconcile.py')],
                capture_output=True,timeout=40,check=False,
                env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','HOME':'/root'})
            callback_status=result.returncode
        except Exception:callback_status=2
    # Every component ran before failure is reported. Original evidence writing
    # remains in the unmodified legacy implementation; no secrets are printed.
    if error is not None:raise error
    return 0 if callback_status==0 else 2


def main():
    if len(sys.argv)!=2:raise RuntimeError('one fixed original verb required')
    raw=bootstrap()
    if sys.argv[1]=='reconcile-original':
        # Internal fixed child verb has exactly the original reconcile scope.
        sys.argv[1]='reconcile'
        legacy_main(raw)
        return 0
    return dispatch(sys.argv[1],raw)


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'result':'BLOCKED','error_type':type(error).__name__}))
        raise SystemExit(2)
