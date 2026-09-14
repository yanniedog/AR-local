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
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

GUARD_PROTOCOL = 'ar-drive-global-dispatch-guard-v1'
GUARD_INVENTORY_NAME = 'drive-write-guard-inventory.json'
MAX_PROOF_BYTES = 64 * 1024
MAX_INSTALLED_FILES = 1024
MAX_INSTALLED_BYTES = 64 * 1024 * 1024
MAX_INSTALLED_FILE_BYTES = 16 * 1024 * 1024
VERIFICATION_SECONDS = 30


def check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ValueError('installed guard verification deadline exceeded')


def exact_keys(value: object, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('installed guard proof has unknown or missing fields')


def hex_identity(value: object, length: int) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(char in '0123456789abcdef' for char in value))


def unique_object(pairs: list) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate installed guard proof key')
        value[key] = item
    return value


def protected_metadata(path: Path, *, mode: int | None = None):
    """Read only protected regular files; never execute an installed artifact."""
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('installed artifact must be canonical without symbolic links')
    root_owned_chain(path.parent)
    info = os.lstat(path)
    permissions = stat.S_IMODE(info.st_mode)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != 0 or info.st_gid != 0
            or permissions & 0o7022 or (mode is not None and permissions != mode)):
        raise ValueError('installed artifact must be protected root:root regular bytes')
    return info


def file_identity(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_installed(path: Path, limit: int, deadline: float, *, mode=None,
                   keep_bytes: bool = False) -> tuple[str, int, bytes]:
    check_deadline(deadline)
    before = protected_metadata(path, mode=mode)
    if before.st_size > limit:
        raise ValueError('installed artifact exceeds byte bound')
    hasher, count, pieces = hashlib.sha256(), 0, []
    with path.open('rb') as handle:
        if file_identity(os.fstat(handle.fileno())) != file_identity(before):
            raise ValueError('installed artifact changed before opening')
        while True:
            check_deadline(deadline)
            chunk = handle.read(min(1024 * 1024, limit - count + 1))
            check_deadline(deadline)
            if not chunk:
                break
            count += len(chunk)
            if count > limit:
                raise ValueError('installed artifact exceeds byte bound')
            hasher.update(chunk)
            if keep_bytes:
                pieces.append(chunk)
        after = protected_metadata(path, mode=mode)
        if (count != before.st_size or file_identity(after) != file_identity(before)
                or file_identity(os.fstat(handle.fileno())) != file_identity(before)):
            raise ValueError('installed artifact changed during verification')
    check_deadline(deadline)
    return hasher.hexdigest(), count, b''.join(pieces)


def absolute_path(value: object) -> Path:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError('invalid installed path')
    path = Path(value)
    if not path.is_absolute() or str(path) != value or path.resolve() != path:
        raise ValueError('installed path must be canonical and absolute')
    return path


def distinct_paths(values: object) -> list[Path]:
    if not isinstance(values, list) or not values or len(values) > 128:
        raise ValueError('bounded nonempty path inventory required')
    paths = [absolute_path(value) for value in values]
    if len(set(paths)) != len(paths):
        raise ValueError('duplicate inventory path')
    return paths


def bundle_files(root: Path, deadline: float) -> set[str]:
    root_owned_chain(root)
    pending, files, entries = [root], set(), 0
    while pending:
        directory = pending.pop()
        check_deadline(deadline)
        with os.scandir(directory) as children:
            for child in children:
                check_deadline(deadline)
                entries += 1
                if entries > MAX_INSTALLED_FILES * 2:
                    raise ValueError('installed bundle directory bound exceeded')
                path = Path(child.path)
                if child.is_symlink():
                    raise ValueError('installed bundle cannot contain symbolic links')
                if child.is_dir(follow_symlinks=False):
                    root_owned_chain(path)
                    pending.append(path)
                elif child.is_file(follow_symlinks=False):
                    files.add(path.relative_to(root).as_posix())
                    if len(files) > MAX_INSTALLED_FILES:
                        raise ValueError('installed bundle file bound exceeded')
                else:
                    raise ValueError('installed bundle contains nonregular entries')
    check_deadline(deadline)
    return files


def verify_file(record: dict, path: Path, deadline: float, budget: dict, *, mode=None) -> dict:
    size = record['bytes']
    if (type(size) is not int or not 0 <= size <= MAX_INSTALLED_FILE_BYTES
            or not hex_identity(record['sha256'], 64)):
        raise ValueError('invalid installed artifact identity')
    budget['files'] += 1
    budget['bytes'] += size
    if budget['files'] > MAX_INSTALLED_FILES or budget['bytes'] > MAX_INSTALLED_BYTES:
        raise ValueError('installed guard verification budget exceeded')
    digest, count, _ = read_installed(path, size, deadline, mode=mode)
    if digest != record['sha256'] or count != size:
        raise ValueError('installed artifact differs from approved identity')
    return {'path': str(path), 'sha256': digest, 'bytes': count}


def verify_bundle(bundle: dict, deadline: float, budget: dict) -> list[dict]:
    exact_keys(bundle, {'root', 'files'})
    root = absolute_path(bundle['root'])
    records = bundle['files']
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_INSTALLED_FILES:
        raise ValueError('bounded complete installed bundle manifest required')
    names, verified = set(), []
    for record in records:
        exact_keys(record, {'path', 'bytes', 'sha256'})
        name = record['path']
        if (not isinstance(name, str) or not name or '\\' in name
                or Path(name).is_absolute() or any(part in ('', '.', '..') for part in name.split('/'))):
            raise ValueError('invalid installed bundle relative path')
        if name in names:
            raise ValueError('duplicate installed bundle path')
        names.add(name)
        path = root / name
        if path.resolve() != path or not path.is_relative_to(root):
            raise ValueError('installed bundle path escapes its root')
        verified.append(verify_file(record, path, deadline, budget))
    required = {'pi_drive_backup_hold.py', 'pi_drive_backup.py',
                'pi_drive_backup_controller.py', 'ar_local_operation_lock.py'}
    if not required <= names or bundle_files(root, deadline) != names:
        raise ValueError('installed bundle manifest is incomplete or contains unlisted files')
    return verified


def verify_dispatchers(proof: dict, artifacts: dict[Path, str], spools: list[Path]) -> None:
    dispatchers = proof['dispatchers']
    if not isinstance(dispatchers, list) or not 1 <= len(dispatchers) <= 128:
        raise ValueError('bounded authorized dispatcher inventory required')
    ids, covered, used = set(), set(), {TRUSTED_HELPER}
    for dispatcher in dispatchers:
        exact_keys(dispatcher, {'id', 'launcher', 'controls', 'spools', 'isolation'})
        identifier = dispatcher['id']
        if (not isinstance(identifier, str) or not 1 <= len(identifier) <= 128
                or identifier in ids):
            raise ValueError('invalid or duplicate dispatcher identity')
        ids.add(identifier)
        if dispatcher['isolation'] != 'REVIEWED_NO_MUTABLE_IMPORT_OR_STARTUP_PATH':
            raise ValueError('reviewed isolated launch closure required')
        launcher = absolute_path(dispatcher['launcher'])
        controls = distinct_paths(dispatcher['controls'])
        selected = distinct_paths(dispatcher['spools'])
        if (artifacts.get(launcher) != 'launcher'
                or any(artifacts.get(path) != 'dispatch_control' for path in controls)
                or not set(selected) <= set(spools)):
            raise ValueError('dispatcher does not bind approved artifacts and spools')
        used.update([launcher, *controls])
        covered.update(selected)
    if covered != set(spools) or used != set(artifacts):
        raise ValueError('dispatcher/artifact inventory has missing or unbound scope')


def verify_guard_inventory(spools: list[Path]) -> dict:
    """Verify protected operator-reviewed closure, not an automatic OS inventory."""
    deadline = time.monotonic() + VERIFICATION_SECONDS
    path = SYSTEM_HOLD.parent / GUARD_INVENTORY_NAME
    proof_sha, _, body = read_installed(path, MAX_PROOF_BYTES, deadline, mode=0o444, keep_bytes=True)
    proof = json.loads(body, object_pairs_hook=unique_object)
    exact_keys(proof, {'schema_version', 'protocol', 'approved_commit', 'review_receipt_sha256',
                       'attestation', 'spools', 'bundle', 'artifacts', 'dispatchers'})
    if (type(proof['schema_version']) is not int or proof['schema_version'] != 1
            or proof['protocol'] != GUARD_PROTOCOL
            or not hex_identity(proof['approved_commit'], 40)
            or not hex_identity(proof['review_receipt_sha256'], 64)):
        raise ValueError('unsupported installed guard proof identity')
    attestation = proof['attestation']
    exact_keys(attestation, {'all_authorized_dispatch_paths_enumerated',
                            'unguarded_dispatch_paths_disabled',
                            'isolated_launch_and_dependency_closure_reviewed',
                            'all_backend_and_acceptance_work_uses_inventoried_spool_lock'})
    if any(value is not True for value in attestation.values()):
        raise ValueError('complete operator-reviewed dispatch closure required')
    if set(distinct_paths(proof['spools'])) != set(spools):
        raise ValueError('installed guard proof does not cover exact requested spools')
    budget = {'files': 0, 'bytes': 0}
    verified = verify_bundle(proof['bundle'], deadline, budget)
    records, roles = proof['artifacts'], {}
    if not isinstance(records, list) or not 3 <= len(records) <= MAX_INSTALLED_FILES:
        raise ValueError('protected helper/launcher/control artifacts required')
    for record in records:
        exact_keys(record, {'role', 'path', 'bytes', 'sha256'})
        artifact = absolute_path(record['path'])
        role = record['role']
        if role not in ('helper', 'launcher', 'dispatch_control') or artifact in roles:
            raise ValueError('unknown or duplicate installed artifact role/path')
        if role == 'helper' and artifact != TRUSTED_HELPER:
            raise ValueError('helper proof must bind this exact trusted installation')
        roles[artifact] = role
        verified.append(verify_file(record, artifact, deadline, budget,
                                    mode=0o555 if role in ('helper', 'launcher') else None))
    if roles.get(TRUSTED_HELPER) != 'helper':
        raise ValueError('installed helper identity is missing')
    verify_dispatchers(proof, roles, spools)
    check_deadline(deadline)
    return {'proof_path': str(path), 'proof_sha256': proof_sha,
            'protocol': GUARD_PROTOCOL, 'approved_commit': proof['approved_commit'],
            'review_receipt_sha256': proof['review_receipt_sha256'],
            'authority': 'OPERATOR_REVIEWED_AUTHORIZED_DISPATCH_CLOSURE',
            'verified_files': budget['files'], 'verified_bytes': budget['bytes'],
            'installed_artifacts_sha256': hashlib.sha256(json.dumps(
                verified, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}

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


class ActivationPending(RuntimeError):
    """The permanent admission barrier exists; spool coordination is incomplete."""


def pending_result(control: Path) -> dict:
    return {'result': 'ACTIVATION_PENDING', 'path': str(control),
            'coordination': 'INCOMPLETE_REQUIRES_MANUAL_RECONCILIATION',
            'new_dispatch': 'BLOCKED_ONLY_ON_VERIFIED_GLOBAL_GUARD_PATHS',
            'explicit_operator_resume_required': True}


def _coordinate_spools(paths: list[Path], reason: str, proof: dict) -> dict:
    control = SYSTEM_HOLD.parent / GLOBAL_LOCK_NAME
    context = {'state': 'ACTIVATION_PENDING', 'reason': reason.strip(),
               'requested_spools': [str(path) for path in paths], 'installed_guard': proof}
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
                 'installed_guard': proof,
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
    control = SYSTEM_HOLD.parent / GLOBAL_LOCK_NAME
    try:
        os.lstat(control)
    except FileNotFoundError:
        pass
    else:
        return pending_result(control)  # No parsing, cleanup or re-attestation.
    proof = verify_guard_inventory(paths)  # Must precede the first durable barrier.
    try:
        return _coordinate_spools(paths, reason, proof)
    except (OSError, RuntimeError, ValueError) as error:
        # Once created, even interrupted/empty record bytes block new admission.
        # Existing spool owners are never recovered, waited on or signalled.
        try:
            os.lstat(control)
        except FileNotFoundError:
            raise error
        raise ActivationPending(str(error)) from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spool', action='append', type=Path, required=True)
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    try:
        result = activate_hold(args.spool, args.reason)
    except ActivationPending:
        print(json.dumps(pending_result(SYSTEM_HOLD.parent / GLOBAL_LOCK_NAME)))
        return 2
    except (OSError, RuntimeError, ValueError):
        print(json.dumps({'result': 'BLOCKED', 'reason': 'trusted_installation_lock_or_path_unavailable'}))
        return 2
    print(json.dumps(result))
    return 2 if result['result'] == 'ACTIVATION_PENDING' else 0


if __name__ == '__main__':
    raise SystemExit(main())
