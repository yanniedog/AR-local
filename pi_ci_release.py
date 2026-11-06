"""Root-only immutable release materialization; standard library, never root Git.

Staging is independently approved and root controlled before this module runs.
Only regular, hash-bound files are copied. The entire old directory, including
untracked work and Git metadata, survives an atomic directory exchange.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

HEX = re.compile('[0-9a-f]{64}')
COMMIT = re.compile('[0-9a-f]{40}')
SAFE_GIT_CONFIG = (b'[core]\nrepositoryformatversion = 0\nbare = false\nfilemode = true\nhooksPath = /dev/null\nfsmonitor = false\n'
                   b'[remote "origin"]\nurl = https://github.com/yanniedog/AR-local.git\nfetch = +refs/heads/main:refs/remotes/origin/main\n')


def unique(pairs):
    value = {}
    for key, entry in pairs:
        if key in value:
            raise ValueError('duplicate trusted JSON field')
        value[key] = entry
    return value


def canonical(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path or str(path) != os.path.normpath(path):
        raise ValueError('canonical non-symlink path required')
    return path


def protected(path, *, readonly=True, directory=False):
    path = canonical(path)
    for entry in (*reversed(path.parents), path):
        info = entry.lstat()
        leaf = entry == path
        if (info.st_uid != 0 or stat.S_ISLNK(info.st_mode)
                or info.st_mode & (0o222 if leaf and readonly and not directory else 0o022)):
            raise ValueError('path must be exclusively root controlled')
        if leaf and not directory:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('trusted file must be regular with one link')
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('trusted ancestor must be a directory')
    return path


def relative(value):
    if (not isinstance(value, str) or not value or value == '.' or '\\' in value or '\x00' in value
            or len(value.encode()) > 4096 or value.startswith('/') or str(PurePosixPath(value)) != value
            or any(p in ('.', '..') for p in PurePosixPath(value).parts)):
        raise ValueError('unsafe release path')
    return value


def sha(path, guard=lambda: None):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            guard(); value.update(block)
    return value.hexdigest()


def read(path, expected=None, *, maximum=16 * 1024 * 1024):
    path = protected(path)
    with path.open('rb') as stream:
        body = stream.read(maximum + 1)
    if len(body) > maximum or expected is not None and (not HEX.fullmatch(expected) or hashlib.sha256(body).hexdigest() != expected):
        raise ValueError('protected JSON size/digest differs')
    return json.loads(body, object_pairs_hook=unique)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write(path, value):
    body = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())
    sync_directory(Path(path).parent)


def identity(path):
    info = Path(path).lstat()
    if not stat.S_ISDIR(info.st_mode) or Path(path).resolve() != Path(path):
        raise ValueError('release root is not a real directory')
    return [info.st_dev, info.st_ino]


def descriptor(value, target, source_files):
    if (not isinstance(value, dict) or set(value) != {'schema', 'commit', 'files'}
            or value['schema'] != 'ar-local-ci-release-v1' or value['commit'] != target
            or not COMMIT.fullmatch(target) or not isinstance(value['files'], dict)
            or not 1 <= len(value['files']) <= 50000):
        raise ValueError('invalid complete immutable release descriptor')
    code = {}
    for name, row in value['files'].items():
        relative(name)
        if (not isinstance(row, dict) or set(row) != {'sha256', 'bytes', 'mode'}
                or not isinstance(row['sha256'], str) or not HEX.fullmatch(row['sha256'])
                or type(row['bytes']) is not int or not 0 <= row['bytes'] <= 2**31
                or row['mode'] not in (0o444, 0o555)):
            raise ValueError('invalid immutable file descriptor')
        if not name.startswith('.git/'):
            code[name] = row['sha256']
        elif not (name in ('.git/HEAD', '.git/config', '.git/index', '.git/packed-refs')
                  or re.fullmatch(r'\.git/objects/(?:[0-9a-f]{2}/[0-9a-f]{38}|pack/pack-[0-9a-f]{40}\.(?:pack|idx))', name)
                  or re.fullmatch(r'\.git/refs/(?:heads|remotes/origin)/[A-Za-z0-9_.-]+', name)):
            raise ValueError('Git hooks, alternates, worktrees and external configuration are forbidden')
    if code != source_files or not source_files:
        raise ValueError('release code differs from the sealed canary full inventory')
    if not {'.git/HEAD', '.git/config', '.git/index'} <= set(value['files']):
        raise ValueError('complete sanitized Git metadata is required')
    config = value['files']['.git/config']
    if config['sha256'] != hashlib.sha256(SAFE_GIT_CONFIG).hexdigest():
        raise ValueError('release Git configuration is not the fixed safe configuration')
    if value['files']['.git/HEAD']['sha256'] != hashlib.sha256((target + '\n').encode()).hexdigest():
        raise ValueError('release HEAD must be detached at the approved exact commit')
    return value


def verify_tree(root, value, guard, *, trusted=True):
    canonical(root)
    if trusted:
        protected(root, directory=True)
    seen = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        guard()
        for name in dirs:
            path = Path(directory) / name
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or path.resolve() != path or trusted and (info.st_uid != 0 or info.st_mode & 0o022):
                raise ValueError('unsafe immutable release directory')
        for name in files:
            path = Path(directory) / name; logical = path.relative_to(root).as_posix()
            row = value['files'].get(logical); info = path.lstat()
            if (row is None or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.resolve() != path
                    or info.st_size != row['bytes'] or sha(path, guard) != row['sha256']
                    or trusted and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != row['mode'])):
                raise ValueError('immutable release has missing, extra, changed or writable files')
            seen.add(logical)
    if seen != set(value['files']):
        raise ValueError('immutable release file inventory is incomplete')


def materialize(stage, destination, value, guard):
    verify_tree(stage, value, guard)
    canonical(destination)
    protected(destination.parent, directory=True)
    destination.mkdir(mode=0o700)
    for name, row in sorted(value['files'].items()):
        guard(); source, target = stage / name, destination / name
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        descriptor_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with source.open('rb') as incoming, os.fdopen(descriptor_fd, 'wb') as outgoing:
            for block in iter(lambda: incoming.read(1024 * 1024), b''):
                guard(); outgoing.write(block)
            outgoing.flush(); os.fsync(outgoing.fileno()); os.fchmod(outgoing.fileno(), row['mode'])
    os.chmod(destination, 0o755)
    for directory, _, _ in os.walk(destination, topdown=False):
        os.chmod(directory, 0o755)
        sync_directory(directory)
    verify_tree(destination, value, guard)
    sync_directory(destination.parent)
    return identity(destination)


def exchange(first, second, expected_first, expected_second):
    if identity(first) != expected_first or identity(second) != expected_second:
        raise ValueError('directory identity changed before release exchange')
    if expected_first[0] != expected_second[0]:
        raise ValueError('atomic release exchange requires the same filesystem')
    library = ctypes.CDLL(None, use_errno=True)
    method = library.renameat2
    method.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    method.restype = ctypes.c_int
    if method(-100, os.fsencode(first), -100, os.fsencode(second), 2):
        raise OSError(ctypes.get_errno(), 'atomic release exchange failed')
    sync_directory(first.parent)
    if second.parent != first.parent:
        sync_directory(second.parent)
    if identity(first) != expected_second or identity(second) != expected_first:
        raise RuntimeError('atomic release exchange identity readback failed')


def stage_input(source, destination, value, guard):
    """Copy approved input bytes without executing Git/config/hooks as root.

    The caller obtains ``value`` from a separately hash-approved protected plan.
    Input may be Pi-owned. Open each component relative to held directory FDs;
    a path race can only cause rejection, never follow an outside symlink/FIFO.
    """
    descriptor(value, value['commit'], {name: row['sha256'] for name, row in value['files'].items()
                                      if not name.startswith('.git/')})
    source, destination = canonical(source), canonical(destination)
    protected(destination.parent, directory=True)
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('staging input and output must be separate')
    if len(value.get('files', {})) > 50000:
        raise ValueError('staging file inventory exceeds bound')
    destination.mkdir(mode=0o700)
    root = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name, row in sorted(value['files'].items()):
            guard(); relative(name)
            target = destination / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            opened = []; parent = root
            try:
                parts = PurePosixPath(name).parts
                for part in parts[:-1]:
                    parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    opened.append(parent)
                incoming = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                with os.fdopen(incoming, 'rb') as reader:
                    initial = os.fstat(reader.fileno())
                    if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1 or initial.st_size != row['bytes']:
                        raise ValueError('input object is not the approved bounded regular file')
                    output = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
                    digest = hashlib.sha256(); count = 0
                    with os.fdopen(output, 'wb') as writer:
                        while block := reader.read(min(1024 * 1024, row['bytes'] + 1 - count)):
                            guard(); count += len(block)
                            if count > row['bytes']: raise ValueError('input grew beyond approved size')
                            writer.write(block); digest.update(block)
                        after = os.fstat(reader.fileno())
                        identity_fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
                        if (count != row['bytes'] or digest.hexdigest() != row['sha256']
                                or any(getattr(initial, x) != getattr(after, x) for x in identity_fields)):
                            raise ValueError('input bytes changed or differ from independent approval')
                        writer.flush(); os.fsync(writer.fileno()); os.fchmod(writer.fileno(), row['mode'])
            finally:
                for fd in reversed(opened): os.close(fd)
    finally:
        os.close(root)
    # No readable output is published before the whole source is hash-verified.
    verify_tree(destination, value, guard)
    for directory, _, _ in os.walk(destination, topdown=False):
        os.chmod(directory, 0o755); sync_directory(directory)
    sync_directory(destination.parent)
    return identity(destination)
