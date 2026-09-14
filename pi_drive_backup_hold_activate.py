"""Standalone root-installed hold activation; no repository or third-party imports.

Invoke only the protected installed copy with /usr/bin/python3 -I -S. An
in-flight or unreconciled lock refuses activation without waiting or recovery.
No Drive access, process signaling, stale-lock reclamation or release command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SYSTEM_HOLD = Path('/etc/ar-local/drive-write-hold.json')
TRUSTED_HELPER = Path('/usr/local/libexec/ar-local-drive-hold/activate.py')
GLOBAL_LOCK_NAME = '.drive-write-hold-activation.lock'
MAX_MARKER_BYTES = 64 * 1024


def fsync_directory(path: Path) -> None:
    if os.name == 'nt':  # Pure filesystem protocol tests; CLI is Linux-only.
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def root_owned_chain(path: Path, *, file: bool = False) -> None:
    """Reject mutable installation/control ancestors, not just the leaf."""
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('root-owned path must be absolute and contain no symbolic links')
    for current in (path, *path.parents):
        info = os.lstat(current)
        regular = current == path and file
        if (info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022
                or (not stat.S_ISREG(info.st_mode) if regular else not stat.S_ISDIR(info.st_mode))
                or (regular and (info.st_nlink != 1 or info.st_gid != 0
                                 or stat.S_IMODE(info.st_mode) != 0o555))):
            raise ValueError('installation and control paths must be root-owned and non-writable by others')


def require_trusted_runtime() -> None:
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ValueError('activation requires the root operator on the Pi')
    if not sys.flags.isolated or not sys.flags.no_site:
        raise ValueError('use the trusted system Python with -I -S')
    installed = Path(__file__).absolute()
    if installed != TRUSTED_HELPER:
        raise ValueError('never execute the activation helper from a mutable checkout')
    root_owned_chain(installed, file=True)
    root_owned_chain(SYSTEM_HOLD.parent)


@contextmanager
def exclusive_lock(path: Path, role: str, *, context: dict | None = None):
    """Create a permanent reconciliation record; never unlink a lock pathname.

    Even successful activation retains the record. No portable atomic
    compare-and-unlink operation exists for a service-writable spool directory.
    """
    payload = (f'protocol=ar-drive-hold-activation-v2\nrecovery=manual\npid={os.getpid()}\n'
               f'role={role}\nnonce={uuid.uuid4().hex}\n'
               f'context_json={json.dumps(context or {}, ensure_ascii=True, sort_keys=True)}\n').encode('ascii')
    if len(payload) > MAX_MARKER_BYTES:
        raise ValueError('activation record exceeds safe bound')
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError as error:
        raise RuntimeError('unreconciled lock already exists: ' + str(path)) from error
    try:
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError('incomplete lock write')
        os.fsync(descriptor)
        fsync_directory(path.parent)
        yield
    finally:
        os.close(descriptor)


def spool_hold_lock(path: Path, control: Path) -> None:
    """An atomic symlink is refused by old and current Linux backup workers.

    Old workers ignore new payload flags, but explicitly refuse symlinks before
    PID/boot/age recovery. O_EXCL refuses even a dangling symlink on Linux. A
    directory is unsafe: old recovery can rename it before unlink fails.
    """
    try:
        os.symlink(control, path)
    except FileExistsError as error:
        raise RuntimeError('unreconciled lock already exists: ' + str(path)) from error
    fsync_directory(path.parent)


def existing_hold(path: Path) -> dict | None:
    """Existence protects Drive; malformed bytes never establish coordination."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_MARKER_BYTES:
        raise ValueError('existing hold requires independent marker reconciliation')
    with path.open('rb') as handle:
        body = handle.read(MAX_MARKER_BYTES + 1)
    if len(body) > MAX_MARKER_BYTES:
        raise ValueError('existing hold exceeds marker bound')
    value = None
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            value = parsed
    except (ValueError, UnicodeError):
        pass
    return {'result': 'ALREADY_HELD', 'path': str(path),
            'existing_marker_sha256': hashlib.sha256(body).hexdigest(),
            'existing_marker': value, 'coordination': 'PRESERVED_EXISTING_MARKER_NOT_REATTESTED'}


def install_marker(path: Path, value: dict) -> None:
    """Fully flushed bytes become visible atomically; never replace a marker."""
    body = (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    if len(body) > MAX_MARKER_BYTES:
        raise ValueError('hold receipt exceeds safe bound')
    temporary = path.with_name('.' + path.name + '.tmp-' + uuid.uuid4().hex)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)  # Atomic no-replace, including another writer's marker.
        temporary.unlink()
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def activate_hold(spools: list[Path], reason: str) -> dict:
    require_trusted_runtime()
    if not spools or not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
        raise ValueError('inventoried spools and a bounded operator reason are required')
    if (not SYSTEM_HOLD.is_absolute() or SYSTEM_HOLD.resolve() != SYSTEM_HOLD
            or SYSTEM_HOLD.is_symlink() or not SYSTEM_HOLD.parent.is_dir()):
        raise ValueError('preinstalled canonical system hold directory required')
    paths = sorted(set(spools))
    if len(paths) > 128:
        raise ValueError('spool inventory exceeds safe bound')
    for spool in paths:
        if not spool.is_absolute() or spool.resolve() != spool or not spool.is_dir():
            raise ValueError('every inventoried spool must be an existing canonical directory')
    previous = existing_hold(SYSTEM_HOLD)
    if previous is not None:
        return previous  # Preserve the earlier receipt; no re-attestation or new locks.
    # The protected global lock serializes different spool inventories too.
    # It deliberately has no stale recovery; crashed activation needs review.
    control = SYSTEM_HOLD.parent / GLOBAL_LOCK_NAME
    context = {'reason': reason.strip(), 'coordinated_spools': [str(path) for path in paths]}
    with exclusive_lock(control, 'drive-hold-global-activation', context=context):
        for spool in paths:
            spool_hold_lock(spool / 'backup.lock', control)
        previous = existing_hold(SYSTEM_HOLD)
        if previous is not None:
            return previous
        value = {'schema_version': 1, 'state': 'HELD',
                 'activated_at': datetime.now(timezone.utc).isoformat(),
                 'reason': reason.strip(), 'explicit_operator_resume_required': True,
                 'coordinated_spools': [str(path) for path in paths],
                 'activation_lock_protocol': 'ar-drive-hold-activation-v2',
                 'retained_activation_record': str(control),
                 'retained_spool_locks': [str(path / 'backup.lock') for path in paths],
                 'lock_reconciliation': 'MANUAL_ONLY_AFTER_EXPLICIT_OPERATOR_RESUME'}
        try:
            install_marker(SYSTEM_HOLD, value)
        except FileExistsError:
            previous = existing_hold(SYSTEM_HOLD)
            if previous is None:
                raise RuntimeError('hold marker changed during activation')
            return previous
        return {'result': 'HELD', 'path': str(SYSTEM_HOLD), **value}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spool', action='append', type=Path, required=True)
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    try:
        result = activate_hold(args.spool, args.reason)
    except (OSError, RuntimeError, ValueError):
        print(json.dumps({'result': 'BLOCKED', 'reason': 'trusted_installation_lock_or_path_unavailable'}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
