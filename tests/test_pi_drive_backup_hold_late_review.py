"""Reachable late-review failures and old-worker lock compatibility fixtures."""
import hashlib
import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import ar_local_operation_lock as operations
import pi_drive_backup_hold_activate as activation


@pytest.fixture
def old_operations():
    fixture = json.loads((Path(__file__).parent / 'fixtures/operation-lock-before-hold-v2.json').read_bytes())
    assert fixture['source_commit'] == '4ee90f76b7ddf300e5f963cf20eb15b81af34886'
    assert hashlib.sha256(fixture['source_text'].encode()).hexdigest() == fixture['source_sha256']
    module = ModuleType('exact_old_operation_lock')
    exec(compile(fixture['source_text'], fixture['source_path'], 'exec'), module.__dict__)
    return module


@pytest.fixture
def paths(tmp_path, monkeypatch):
    spool, system = tmp_path / 'spool', tmp_path / 'system'
    spool.mkdir()
    system.mkdir()
    marker = system / 'drive-write-hold.json'
    monkeypatch.setattr(activation, 'SYSTEM_HOLD', marker)
    monkeypatch.setattr(activation, 'verify_guard_inventory', lambda _: {'protocol': activation.GUARD_PROTOCOL})
    return spool, marker


def test_imported_activation_enforces_runtime_before_filesystem_changes(paths, monkeypatch):
    spool, marker = paths
    def blocked():
        raise ValueError('untrusted imported runtime')
    monkeypatch.setattr(activation, 'require_trusted_runtime', blocked)
    with pytest.raises(ValueError, match='untrusted imported runtime'):
        activation.activate_hold([spool], 'fixture request')
    assert not list(spool.iterdir()) and not list(marker.parent.iterdir())


@pytest.mark.parametrize('permissions', [0o755, 0o744, 0o700, 0o644, 0o4555, 0o555])
def test_installed_leaf_requires_exact_0555(tmp_path, monkeypatch, permissions):
    helper = tmp_path / 'activate.py'
    helper.write_text('fixture')
    real = os.lstat
    def metadata(path, *args, **kwargs):
        info = real(path, *args, **kwargs)
        mode = stat.S_IFMT(info.st_mode) | (permissions if Path(path) == helper else 0o755)
        return SimpleNamespace(st_mode=mode, st_uid=0, st_gid=0, st_nlink=1)
    monkeypatch.setattr(activation.os, 'lstat', metadata)
    if permissions == 0o555:
        activation.root_owned_chain(helper, file=True)
    else:
        with pytest.raises(ValueError):
            activation.root_owned_chain(helper, file=True)


def test_replacement_between_identity_check_and_close_is_never_unlinked(tmp_path, monkeypatch):
    lock = tmp_path / 'backup.lock'
    original_close = os.close
    armed, swapped = False, False
    def replace_after_close(descriptor):
        nonlocal swapped
        original_close(descriptor)
        if armed and not swapped:
            swapped = True
            lock.rename(tmp_path / 'displaced-owned-lock')
            lock.write_bytes(b'replacement-owner-must-survive')
    monkeypatch.setattr(activation.os, 'close', replace_after_close)
    with activation.exclusive_lock(lock, 'drive-hold-activation'):
        armed = True
    assert swapped
    assert lock.read_bytes() == b'replacement-owner-must-survive'


def test_oversized_record_is_rejected_before_opening_lock(tmp_path):
    lock = tmp_path / 'activation.lock'
    with pytest.raises(ValueError, match='exceeds safe bound'):
        with activation.exclusive_lock(lock, 'drive-hold-global-activation',
                                       context={'oversized': 'x' * activation.MAX_MARKER_BYTES}):
            pytest.fail('oversized record was accepted')
    assert not lock.exists()


@pytest.mark.parametrize('body', [
    b'pid=99999999\nrole=drive-hold-activation\n',
    b'pid=99999999\nrole=backup\nrecovery=manual\n',
    b'', b'broken', b'pid=0\nrole=backup\n',
])
def test_current_worker_never_reclaims_hold_or_unknown_records(tmp_path, monkeypatch, body):
    lock = tmp_path / 'backup.lock'
    lock.write_bytes(body)
    os.utime(lock, (1, 1))
    monkeypatch.setattr(operations, '_pid_is_alive', lambda _: False)
    monkeypatch.setattr(operations, '_current_boot_id', lambda: 'current')
    monkeypatch.setattr(operations, '_boot_epoch', lambda: 100)
    with pytest.raises(RuntimeError):
        with operations.production_lock(lock, 'backup'):
            pytest.fail('unreconciled lock was acquired')
    assert lock.read_bytes() == body


def test_unreadable_record_never_ages_into_permission_to_recover(tmp_path, monkeypatch):
    lock = tmp_path / 'backup.lock'
    lock.write_bytes(b'root-only hold record')
    os.utime(lock, (1, 1))
    original = Path.open
    def unreadable(path, *args, **kwargs):
        if path == lock:
            raise PermissionError('fixture service user cannot read root record')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', unreadable)
    monkeypatch.setattr(operations, '_boot_epoch', lambda: 100)
    assert operations._existing_lock_is_stale(lock) is False


def test_old_regular_hold_record_is_recoverable_proving_compatibility_hazard(tmp_path, monkeypatch, old_operations):
    lock = tmp_path / 'backup.lock'
    lock.write_text('pid=99999999\nrole=drive-hold-activation\nrecovery=manual\n')
    monkeypatch.setattr(old_operations, '_pid_is_alive', lambda _: False)
    monkeypatch.setattr(old_operations, '_boot_epoch', lambda: None)
    monkeypatch.setattr(old_operations, '_current_boot_id', lambda: '')
    assert old_operations._existing_lock_is_stale(lock) is True


def test_old_unreadable_regular_record_ages_out_but_new_reader_fails_closed(tmp_path, monkeypatch, old_operations):
    lock = tmp_path / 'backup.lock'
    lock.write_bytes(b'pid=99999999\nrole=drive-hold-activation\n')
    os.utime(lock, (1, 1))
    original = Path.open
    def unreadable(path, *args, **kwargs):
        if path == lock:
            raise PermissionError('fixture unprivileged service reader')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', unreadable)
    for module in (old_operations, operations):
        monkeypatch.setattr(module, '_boot_epoch', lambda: None)
        monkeypatch.setattr(module, '_current_boot_id', lambda: '')
    assert old_operations._existing_lock_is_stale(lock) is True
    assert operations._existing_lock_is_stale(lock) is False


@pytest.mark.parametrize('target_state', ['dead_record', 'unreadable', 'dangling'])
def test_old_worker_refuses_actual_symlink_hold_regardless_of_target(tmp_path, monkeypatch, old_operations, target_state):
    target, lock = tmp_path / 'root-control-record', tmp_path / 'backup.lock'
    if target_state != 'dangling':
        target.write_text('pid=99999999\nrole=drive-hold-activation\nrecovery=manual\n')
        os.utime(target, (1, 1))
    os.symlink(target, lock)
    if target_state == 'unreadable':
        def unreadable(_):
            raise AssertionError('symlink refusal must precede record reads')
        monkeypatch.setattr(old_operations, '_lock_values', unreadable)
    monkeypatch.setattr(old_operations, '_pid_is_alive', lambda _: False)
    monkeypatch.setattr(old_operations, '_boot_epoch', lambda: 100)
    assert old_operations._existing_lock_is_stale(lock) is False
    if os.name == 'nt' and target_state == 'dangling':
        pytest.skip('Windows O_EXCL follows dangling links; activation runtime is Linux-only')
    before = os.lstat(lock)
    before_target = os.readlink(lock)
    with pytest.raises(RuntimeError, match='production lock is active'):
        with old_operations.production_lock(lock, 'backup'):
            pytest.fail('old worker admitted a held spool')
    assert lock.is_symlink() and os.readlink(lock) == before_target
    assert os.lstat(lock).st_ino == before.st_ino
    assert list(tmp_path.glob('.*.stale-*')) == []


def test_crashed_activation_before_marker_blocks_old_and_current_workers(paths, monkeypatch, old_operations):
    spool, marker = paths
    monkeypatch.setattr(activation, 'require_trusted_runtime', lambda: None)
    def interrupted(*_):
        raise RuntimeError('fixture interrupted before marker installation')
    monkeypatch.setattr(activation, 'install_marker', interrupted)
    with pytest.raises(RuntimeError, match='fixture interrupted'):
        activation.activate_hold([spool], 'retain fixture fallback')
    lock = spool / 'backup.lock'
    assert lock.is_symlink() and not marker.exists()
    for module in (old_operations, operations):
        monkeypatch.setattr(module, '_pid_is_alive', lambda _: False)
        monkeypatch.setattr(module, '_boot_epoch', lambda: 100)
        with pytest.raises(RuntimeError):
            with module.production_lock(lock, 'backup'):
                pytest.fail('backup could run after activation interruption')
    assert lock.is_symlink()


def test_actual_fixture_process_death_retains_old_worker_barrier(paths, old_operations):
    spool, marker = paths
    program = '''
import sys,time
from pathlib import Path
import pi_drive_backup_hold_activate as helper
helper.SYSTEM_HOLD = Path(sys.argv[2])
helper.require_trusted_runtime = lambda: None  # Isolated filesystem fixture only.
helper.verify_guard_inventory = lambda _: {'protocol': helper.GUARD_PROTOCOL}
def pause_before_marker(*args):
    print('SPOOL_LOCKS_DURABLE', flush=True)
    while True:
        time.sleep(0.1)
helper.install_marker = pause_before_marker
helper.activate_hold([Path(sys.argv[1])], 'isolated crash fixture')
'''
    # The Windows venv redirector can launch a grandchild with another PID.
    # This child imports only stdlib/helper code, so use the actual base runtime.
    executable = getattr(sys, '_base_executable', sys.executable)
    child = subprocess.Popen([executable, '-c', program, str(spool), str(marker)],
                             cwd=Path(activation.__file__).parent, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    with ThreadPoolExecutor(max_workers=1) as reader:
        try:
            line = reader.submit(child.stdout.readline).result(timeout=10)
            assert line.strip() == 'SPOOL_LOCKS_DURABLE'
            assert not marker.exists()
            assert (spool / 'backup.lock').is_symlink()
        finally:
            child.terminate()  # Dedicated fixture child handle; never signal-zero.
            child.wait(timeout=10)
            child.stdout.close()
            child.stderr.close()
    for module in (old_operations, operations):
        with pytest.raises(RuntimeError, match='production lock is active'):
            with module.production_lock(spool / 'backup.lock', 'fixture-backup'):
                pytest.fail('backup was admitted after fixture process death')
    assert not marker.exists()
    assert (spool / 'backup.lock').is_symlink()
    record = (marker.parent / activation.GLOBAL_LOCK_NAME).read_text()
    assert f'pid={child.pid}\n' in record
    assert 'isolated crash fixture' in record
