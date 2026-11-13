"""Root-installed, isolated stdlib cleanup for the direct manual unit only.

No repository imports, caller-selected executable, sudo or scheduler changes.
The queued unit uses its existing claim-aware stop hook instead.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import uuid
from zoneinfo import ZoneInfo

UNIT = 'ar-local-ingest-now.service'
DASHBOARD = 'ar-local-dashboard.service'
QUEUE_ROOT = Path('/var/lib/shared-pi-queue')
LOCK = 'daily-ingest.lock'
START_SECONDS = 10
TOTAL_SECONDS = 35  # Below the direct unit's 45-second stop timeout.
PROPERTIES = ('Id', 'LoadState', 'ActiveState', 'SubState', 'MainPID',
              'ControlPID', 'ExecMainPID', 'InvocationID', 'ControlGroup', 'User')


def bounded_read(path, limit=65536):
    with open(path, 'rb') as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError('oversized ownership evidence')
    return body.decode('utf-8')


def command(*args, timeout=4):
    result = subprocess.run(['/usr/bin/systemctl', *args], check=True,
                            capture_output=True, text=True, timeout=timeout,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if len(result.stdout) > 1024 * 1024:
        raise ValueError('oversized service evidence')
    return result.stdout


def window_allowed(now=None):
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Australia/Hobart'))
    if time(0, 30) <= local.time() < time(3, 30):
        return False
    close = datetime.combine(local.date(), time(0, 30), local.tzinfo)
    if local >= close:
        close += timedelta(days=1)
    return (close.astimezone(timezone.utc) - local.astimezone(timezone.utc)).total_seconds() > TOTAL_SECONDS


def parse_context(body, invocation, pid, cgroup):
    rows = [line.partition('=') for line in body.splitlines()]
    if (any(not sep for _, sep, _ in rows) or len(rows) != len(PROPERTIES)
            or {key for key, _, _ in rows} != set(PROPERTIES)):
        raise ValueError('incomplete manual stop context')
    values = {key: value for key, _, value in rows}
    expected = {'Id': UNIT, 'LoadState': 'loaded', 'ActiveState': 'deactivating',
                'SubState': 'stop-post', 'MainPID': '0', 'ControlPID': str(pid),
                'InvocationID': invocation, 'ControlGroup': cgroup}
    if (not re.fullmatch('[0-9a-f]{32}', invocation)
            or cgroup != '/system.slice/' + UNIT
            or any(values[key] != value for key, value in expected.items())
            or not re.fullmatch('[1-9][0-9]{0,9}', values['ExecMainPID'])
            or not re.fullmatch('[A-Za-z_][A-Za-z0-9_-]*', values['User'])):
        raise ValueError('not this exact manual stop invocation')
    return values


def context():
    import pwd  # POSIX runtime only; portable contract tests import this module.
    group = bounded_read('/proc/self/cgroup')
    expected = '0::/system.slice/' + UNIT + '\n'
    if group != expected:
        raise ValueError('unexpected manual cgroup')
    details = parse_context(command('show', UNIT, '--property=' + ','.join(PROPERTIES)),
                            os.environ.get('INVOCATION_ID', ''), os.getpid(), expected[3:].strip())
    account = pwd.getpwnam(details['User'])
    if account.pw_uid == 0:
        raise ValueError('non-root producer required')
    group_root = Path('/sys/fs/cgroup') / details['ControlGroup'].lstrip('/')
    found, count = set(), 0
    def unreadable(error):
        raise error
    for root, dirs, _ in os.walk(group_root, followlinks=False, onerror=unreadable):
        count += 1
        if count > 64 or any((Path(root) / name).is_symlink() for name in dirs):
            raise ValueError('ambiguous descendant cgroup')
        raw = bounded_read(Path(root) / 'cgroup.procs')
        if any(not token.isdigit() for token in raw.split()):
            raise ValueError('invalid descendant process')
        found.update(int(token) for token in raw.split())
    if not count or found != {os.getpid()}:
        raise ValueError('manual producer descendants still present')
    return details, account


def other_owners_idle():
    services = json.loads(command('list-units', '--all', '--type=service',
                                  '--output=json', 'ar-local-*.service'))
    if not isinstance(services, list) or len(services) > 1024:
        raise ValueError('invalid legacy service inventory')
    ignored = {UNIT, DASHBOARD, 'ar-local-runtime-health.service',
               'ar-local-deploy-watchdog.service', 'ar-local-net-watchdog.service'}
    names = set()
    for item in services:
        if (not isinstance(item, dict) or not {'unit', 'active', 'sub'} <= item.keys()
                or not isinstance(item['unit'], str) or item['unit'] in names
                or not re.fullmatch(r'ar-local-[A-Za-z0-9_.@-]+\.service', item['unit'])):
            raise ValueError('ambiguous legacy service inventory')
        names.add(item['unit'])
        if item['unit'] not in ignored and item['active'] not in ('inactive', 'failed'):
            return False
    return True


def checked_file(fd, uid, limit):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_nlink != 1
            or info.st_mode & 0o022 or info.st_size > limit):
        raise ValueError('unsafe ownership file')
    body = os.read(fd, limit + 1)
    if len(body) > limit:
        raise ValueError('oversized ownership file')
    return info, body


@contextmanager
def directory(path):
    """Pin every component without following links; writes stay relative to fd."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('canonical absolute directory required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def queue_guard(uid):
    import fcntl
    if not QUEUE_ROOT.exists() and not QUEUE_ROOT.is_symlink():
        yield
        return
    with directory(QUEUE_ROOT) as root:
        info = os.fstat(root)
        if info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('unsafe shared queue root')
        lock = os.open('queue.lock', os.O_RDWR | os.O_NOFOLLOW, dir_fd=root)
        try:
            checked_file(lock, uid, 16384)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd = os.open('state.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root)
            try:
                _, body = checked_file(fd, uid, 1024 * 1024)
            finally:
                os.close(fd)
            state = json.loads(body)
            if (not isinstance(state, dict) or set(state) != {'version', 'next_sequence', 'jobs'}
                    or type(state['version']) is not int or state['version'] != 1
                    or type(state['next_sequence']) is not int
                    or not 0 <= state['next_sequence'] < 2**63 or state['jobs'] != []):
                raise ValueError('shared queue occupied or unknown')
            yield
        finally:
            os.close(lock)


def same_inode(root, name, info):
    current = os.stat(name, dir_fd=root, follow_symlinks=False)
    return (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino)


def retain_own_stale(root, details, uid, boot):
    """Only the just-ended producer's exact ordinary lease may be reclaimed."""
    fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root)
    try:
        info, body = checked_file(fd, uid, 16384)
        expected = f"pid={details['ExecMainPID']}\nrole=ingest\nboot_id={boot}\n".encode()
        if (body != expected or Path('/proc', details['ExecMainPID']).exists()
                or not same_inode(root, LOCK, info)):
            raise ValueError('another or ambiguous native lease retained')
        # Preserve the exact stale bytes; never overwrite a prior recovery record.
        retained = '.' + LOCK + '.stale-' + str(uuid.uuid4())
        os.link(LOCK, retained, src_dir_fd=root, dst_dir_fd=root, follow_symlinks=False)
        if not same_inode(root, LOCK, info):
            raise ValueError('native lease changed during recovery')
        os.unlink(LOCK, dir_fd=root)
        os.fsync(root)
    finally:
        os.close(fd)


@contextmanager
def native_lease(data, details, account):
    import fcntl
    boot = bounded_read('/proc/sys/kernel/random/boot_id').strip()
    if str(uuid.UUID(boot)) != boot:
        raise ValueError('invalid boot identity')
    with directory(Path(data) / 'state') as root:
        owner = os.fstat(root)
        if owner.st_uid != account.pw_uid or owner.st_mode & 0o022:
            raise ValueError('unsafe native state directory')
        guard = os.open('.' + LOCK + '.recovery-lock',
                        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=root)
        try:
            # Only a newly root-created, empty recovery mutex needs ownership set.
            info = os.fstat(guard)
            if info.st_uid == 0 and info.st_size == 0 and info.st_nlink == 1:
                os.fchown(guard, account.pw_uid, account.pw_gid)
            checked_file(guard, account.pw_uid, 16384)
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                os.stat(LOCK, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                retain_own_stale(root, details, account.pw_uid, boot)
            fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
            try:
                info = os.fstat(fd)
                os.fchown(fd, account.pw_uid, account.pw_gid)
                os.write(fd, f'pid={os.getpid()}\nrole=manual-dashboard-restore\nboot_id={boot}\n'.encode())
                os.fsync(fd)
                os.fsync(root)
                yield
            finally:
                try:
                    if same_inode(root, LOCK, info):
                        os.unlink(LOCK, dir_fd=root)
                        os.fsync(root)
                finally:
                    os.close(fd)
        finally:
            os.close(guard)


def recover(data):
    if os.geteuid() != 0:
        raise ValueError('root-installed privileged stop hook required')
    if (os.environ.get('AR_LOCAL_DATA_ROOT') != data or str(PurePosixPath(data)) != data
            or not data.startswith('/') or data.startswith('//') or '..' in PurePosixPath(data).parts):
        raise ValueError('manual data root differs from unit binding')
    if not window_allowed():
        return False
    details, account = context()
    with queue_guard(account.pw_uid), native_lease(data, details, account):
        if not other_owners_idle():
            return False
        current, _ = context()
        if current != details or not window_allowed():
            return False
        command('start', DASHBOARD, timeout=START_SECONDS)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    args = parser.parse_args()
    def expired(*_):
        raise TimeoutError('manual dashboard restoration deadline')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(TOTAL_SECONDS)
    try:
        restored = recover(args.data_root)
        print(json.dumps({'dashboard_recovered': restored}))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('manual dashboard restoration deferred: ownership/window not proved')
        return 0
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    raise SystemExit(main())
