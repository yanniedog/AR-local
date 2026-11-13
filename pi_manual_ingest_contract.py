"""Read-only installed stop-hook proof for the manual service definition fence."""
from hashlib import sha256
from pathlib import Path
import shlex

RESTORE_PATH = '/usr/local/lib/ar-local-manual-ingest/pi_manual_ingest_restore.py'
QUEUE_STOP_PATH = '/usr/local/lib/shared-pi-queue/pi_shared_queue_stop_hook.py'


def restore_argv(data):
    return ['/usr/bin/python3', '-I', '-S', RESTORE_PATH, '--data-root', data]


def source_digest(queued=False):
    name = 'pi_shared_queue_stop_hook.py' if queued else 'pi_manual_ingest_restore.py'
    # Git's checked-in LF bytes, including on CRLF Windows worktrees.
    body = Path(__file__).with_name(name).read_bytes().replace(b'\r\n', b'\n')
    return sha256(body).hexdigest()


def installed_proof_script():
    """Inline stdlib only: never execute the file being attested."""
    code = '''import hashlib,os,pathlib,stat
for key,name in %r:
    try:
        path=pathlib.Path(name)
        for parent in reversed(path.parents):
            info=parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
                raise ValueError('unprotected parent')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or info.st_mode&0o022 or info.st_size>131072:
                raise ValueError('unprotected helper')
            body=os.read(fd,131073)
            after=os.fstat(fd)
            if len(body)!=info.st_size or (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise ValueError('helper changed')
            current=path.lstat()
            if (info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino): raise ValueError('helper replaced')
            value=hashlib.sha256(body).hexdigest()
        finally: os.close(fd)
    except (OSError,ValueError): value='unverified'
    print(key+'='+value)
''' % [('MANUAL_RESTORE_SHA256', RESTORE_PATH), ('MANUAL_QUEUE_STOP_SHA256', QUEUE_STOP_PATH)]
    return '/usr/bin/python3 -I -S -c ' + shlex.quote(code) + '; '
