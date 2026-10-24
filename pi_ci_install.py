"""Explicit root-only immutable helper commissioning; default validates only.

The operator verifies this installer's hash before invoking Python -I. A separate
protected approval binds every staged module and the effective runtime profile.
No candidate imports, Git, service transitions, keys or schedules occur here.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

MODULES = {'pi_ci_release.py', 'pi_ci_resources.py', 'pi_ci_activate.py', 'pi_ci_snapshot.py', 'pi_ci_worker.py', 'pi_ci_access.py'}
LIB = Path('/usr/local/lib/ar-local-ci')
RUNTIME = Path('/etc/ar-local/ci-runtime.json')
STATE = Path('/var/lib/ar-local-ci')
LOGIN = Path('/usr/local/sbin/ar-local-ci-login')
CONTROL = Path('/usr/local/sbin/ar-local-ci-control')


def protected_bytes(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path or str(path) != os.path.normpath(path):
        raise ValueError('canonical protected staging required')
    for item in (*reversed(path.parents), path):
        info = item.lstat(); leaf = item == path
        if info.st_uid != 0 or info.st_mode & (0o222 if leaf else 0o022) or stat.S_ISLNK(info.st_mode):
            raise ValueError('staging must be read-only and exclusively root controlled')
        if (leaf and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2**20)
                or not leaf and not stat.S_ISDIR(info.st_mode)):
            raise ValueError('invalid staging object')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        after = os.fstat(stream.fileno())
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
            raise ValueError('staging changed during read')
        return stream.read(2**20 + 1)


def checked(path, digest):
    body = protected_bytes(path)
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest) or hashlib.sha256(body).hexdigest() != digest:
        raise ValueError('independently reviewed staging hash differs')
    return body


def validate(staging, approval_path, approval_sha256, recovery_path, recovery_sha256):
    approval = json.loads(checked(approval_path, approval_sha256))
    if (set(approval) != {'schema', 'source_commit', 'files', 'runtime_sha256'}
            or approval['schema'] != 'ar-local-ci-commission-v1'
            or not re.fullmatch('[0-9a-f]{40}', str(approval['source_commit']))
            or set(approval['files']) != MODULES):
        raise ValueError('complete independently approved coordinator source is required')
    bodies = {name: checked(staging / name, digest) for name, digest in approval['files'].items()}
    profile_body = checked(staging / 'runtime.json', approval['runtime_sha256'])
    # Only after every byte is independently root-approved may trusted helper
    # modules execute. The candidate/production checkout is never imported.
    modules = {}
    for name in ('pi_ci_release', 'pi_ci_resources', 'pi_ci_activate', 'pi_ci_access'):
        spec = importlib.util.spec_from_file_location(name, staging / (name + '.py'))
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        exec(compile(bodies[name + '.py'], str(staging / (name + '.py')), 'exec'), module.__dict__)
        modules[name] = module
    profile = json.loads(profile_body, object_pairs_hook=modules['pi_ci_release'].unique)
    expected = {name: hashlib.sha256(body).hexdigest() for name, body in bodies.items() if name != 'pi_ci_access.py'}
    if profile.get('modules') != expected or profile.get('queue_contract') != 'ci-retained-v1':
        raise ValueError('runtime profile differs from independently approved closure')
    modules['pi_ci_activate'].check_profile(profile)
    control = modules['pi_ci_access']
    control.validate_recovery(checked(recovery_path, recovery_sha256))
    required_queue = {'pi_shared_queue.py', 'pi_shared_queue_native.py', 'pi_shared_queue_store.py',
                      'pi_shared_queue_policy.py', 'pi_shared_queue_post_hooks.py', 'pi_shared_queue_stop_hook.py'}
    if not required_queue <= set(profile.get('queue_files', {})):
        raise ValueError('complete retained queue integration closure required')
    for name, digest in profile['queue_files'].items():
        if not re.fullmatch(r'pi_shared_queue(?:_[a-z_]+)?\.py', name):
            raise ValueError('unsupported fixed queue module')
        checked(Path('/usr/local/lib/shared-pi-queue') / name, digest)
    return bodies, profile_body, modules['pi_ci_release']


def install(bodies, profile, release):
    """Root destinations must be absent; ambiguous upgrades are never replaced."""
    paths = [LIB / name for name in bodies if name != 'pi_ci_access.py'] + [RUNTIME]
    login = LOGIN; control = CONTROL
    for path in (*paths, login, control):
        release.protected(path.parent, directory=True)
        if path in (login, control):
            # Foundation account helpers may be upgraded only if both are exact
            # root-controlled identical bytes; preserve those bytes first.
            release.protected(path)
        elif path.exists() or path.is_symlink():
            raise ValueError('refusing replacement of commissioned runtime paths')
    old = protected_bytes(login)
    if protected_bytes(control) != old:
        raise ValueError('foundation login/control bytes differ')
    release.protected(STATE, directory=True)
    backup = STATE / 'pre-immutable-control.py'
    if backup.exists(): raise ValueError('previous commissioning attempt retained; inspect manually')
    state_paths = {name: STATE / name for name in ('staging', 'transactions', 'releases', 'accepted', 'completed', 'authority')}
    if any(path.exists() or path.is_symlink() for path in state_paths.values()):
        raise ValueError('commissioning state already exists')
    def create(path, body, mode=0o444):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, 'wb') as output:
            output.write(body); output.flush(); os.fsync(output.fileno())
        release.sync_directory(path.parent)
    create(backup, old, 0o400)
    for name, body in bodies.items():
        if name != 'pi_ci_access.py': create(LIB / name, body)
    for name, path in state_paths.items():
        path.mkdir(mode=0o755 if name in ('completed', 'authority') else 0o700)
        release.sync_directory(STATE)
    # Runtime profile is published last, after both fixed entrypoints. A crash
    # beforehand leaves activation unavailable; staged evidence remains intact.
    for path in (login, control):
        temporary = path.with_name(path.name + '.immutable-new')
        create(temporary, bodies['pi_ci_access.py'], 0o555)
        os.replace(temporary, path); release.sync_directory(path.parent)
    create(RUNTIME, profile)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staging', type=Path, required=True)
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--approval-sha256', required=True)
    parser.add_argument('--recovery', type=Path, required=True)
    parser.add_argument('--recovery-sha256', required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args(argv)
    if os.geteuid() != 0: raise ValueError('root commissioning required')
    bodies, profile, release = validate(args.staging, args.approval, args.approval_sha256,
                                        args.recovery, args.recovery_sha256)
    if args.install: install(bodies, profile, release)
    print(json.dumps({'result': 'INSTALLED' if args.install else 'VALIDATED',
                      'services_changed': False, 'schedules_changed': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
