"""Standalone lock protocol regressions; no sudo, Drive or process signaling."""
import ast
import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

import pi_drive_backup_hold_activate as activation


@pytest.fixture
def locations(tmp_path, monkeypatch):
    spool = tmp_path / 'spool'
    spool.mkdir()
    marker = tmp_path / 'system' / 'drive-write-hold.json'
    marker.parent.mkdir(mode=0o700)
    monkeypatch.setattr(activation, 'SYSTEM_HOLD', marker)
    # Filesystem protocol fixture only; entrypoint guards are tested separately.
    monkeypatch.setattr(activation, 'require_trusted_runtime', lambda: None)
    monkeypatch.setattr(activation, 'verify_guard_inventory', lambda _: {'protocol': activation.GUARD_PROTOCOL})
    return spool, marker


def test_inflight_acceptance_prevents_activating_hold(locations):
    spool, marker = locations
    original = b'pid=1234\nrole=in-flight-acceptance\n'
    (spool / 'backup.lock').write_bytes(original)
    with pytest.raises(RuntimeError, match='unreconciled lock'):
        activation.activate_hold([spool], 'Preserve accepted fallback')
    assert not marker.exists()
    assert (spool / 'backup.lock').read_bytes() == original
    assert (marker.parent / activation.GLOBAL_LOCK_NAME).is_file()


def test_partial_activation_retains_new_and_preexisting_locks_on_failure(locations):
    spool, marker = locations
    other = spool.parent / 'z-second-spool'
    other.mkdir()
    before = b'pid=1234\nrole=other-operation\n'
    (other / 'backup.lock').write_bytes(before)
    with pytest.raises(RuntimeError, match='unreconciled lock'):
        activation.activate_hold([spool, other], 'Preserve accepted fallback')
    assert not marker.exists() and (spool / 'backup.lock').is_symlink()
    assert (other / 'backup.lock').read_bytes() == before
    assert (marker.parent / activation.GLOBAL_LOCK_NAME).is_file()


@pytest.mark.parametrize('body', [b'', b'pid=99999999\nrole=old-backup\n', b'not-a-lock-record'])
def test_stale_or_unreadable_lock_is_never_recovered_or_modified(locations, body):
    spool, marker = locations
    lock = spool / 'backup.lock'
    lock.write_bytes(body)
    os.utime(lock, (1, 1))
    before = lock.stat()
    with pytest.raises(activation.ActivationPending, match='unreconciled lock'):
        activation.activate_hold([spool], 'Preserve fallback')
    after = lock.stat()
    assert lock.read_bytes() == body
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert not marker.exists()


def test_crashed_global_activation_lock_requires_reconciliation(locations):
    spool, marker = locations
    lock = marker.parent / activation.GLOBAL_LOCK_NAME
    lock.write_bytes(b'pid=99999999\nrole=old-activation\n')
    before = lock.read_bytes()
    result = activation.activate_hold([spool], 'Preserve fallback')
    assert result['result'] == 'ACTIVATION_PENDING'
    assert lock.read_bytes() == before and not marker.exists()
    assert not (spool / 'backup.lock').exists()


@pytest.mark.parametrize('body', [b'', b'{broken', b'{"reason":"original","coordinated_spools":["original-only"]}'])
def test_existing_marker_bytes_reason_and_inventory_are_preserved(locations, body):
    spool, marker = locations
    marker.write_bytes(body)
    result = activation.activate_hold([spool], 'New reason must not overwrite original')
    assert result['result'] == 'ALREADY_HELD'
    assert result['coordination'] == 'PRESERVED_EXISTING_MARKER_NOT_REATTESTED'
    assert 'coordinated_spools' not in result
    assert marker.read_bytes() == body


def test_success_holds_every_distinct_spool_and_global_lock_during_marker_install(locations, monkeypatch):
    spool, marker = locations
    paths = [spool, spool.parent / 'second-spool', spool.parent / 'third-spool']
    for path in paths[1:]:
        path.mkdir()
    install = activation.install_marker
    seen = []
    def locked_write(path, value):
        assert (marker.parent / activation.GLOBAL_LOCK_NAME).is_file()
        assert all((item / 'backup.lock').is_file() for item in paths)
        seen.append(value['coordinated_spools'])
        install(path, value)
    monkeypatch.setattr(activation, 'install_marker', locked_write)
    result = activation.activate_hold([paths[2], paths[0], paths[1], paths[0]], 'Preserve fallback')
    expected = sorted(str(path) for path in paths)
    assert seen == [expected] and result['coordinated_spools'] == expected
    assert json.loads(marker.read_bytes())['coordinated_spools'] == expected
    assert all((path / 'backup.lock').is_symlink() for path in paths)
    assert (marker.parent / activation.GLOBAL_LOCK_NAME).is_file()
    assert result['lock_reconciliation'] == 'MANUAL_ONLY_AFTER_EXPLICIT_OPERATOR_RESUME'


def test_disjoint_spool_activations_serialize_global_marker_and_preserve_first_inventory(locations, monkeypatch):
    spool, marker = locations
    other = spool.parent / 'other-spool'
    other.mkdir()
    entered, release = Event(), Event()
    install = activation.install_marker
    def pause(path, value):
        entered.set()
        assert release.wait(5)
        install(path, value)
    monkeypatch.setattr(activation, 'install_marker', pause)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(activation.activate_hold, [spool], 'first operator reason')
        try:
            assert entered.wait(5)
            assert activation.activate_hold([other], 'different operator reason')['result'] == 'ACTIVATION_PENDING'
            assert not (other / 'backup.lock').exists()
        finally:
            release.set()
        assert first.result(timeout=5)['result'] == 'HELD'
    before = marker.read_bytes()
    result = activation.activate_hold([other], 'different operator reason')
    assert result['result'] == 'ALREADY_HELD' and marker.read_bytes() == before
    assert result['existing_marker']['reason'] == 'first operator reason'
    assert result['existing_marker']['coordinated_spools'] == [str(spool)]


def test_atomic_marker_install_cannot_replace_uncoordinated_writer(locations, monkeypatch):
    spool, marker = locations
    install = activation.install_marker
    original = b'{"reason":"existing external marker"}'
    def race(path, value):
        path.write_bytes(original)
        install(path, value)
    monkeypatch.setattr(activation, 'install_marker', race)
    assert activation.activate_hold([spool], 'must not replace')['result'] == 'ALREADY_HELD'
    assert marker.read_bytes() == original
    assert list(marker.parent.glob('.*.tmp-*')) == []


@pytest.mark.parametrize('reason', ['', '  ', 'x' * 4097])
def test_invalid_reason_refused(locations, reason):
    spool, marker = locations
    with pytest.raises(ValueError):
        activation.activate_hold([spool], reason)
    assert not marker.exists()


def test_relative_unknown_spools_and_missing_control_directory_refused(locations):
    spool, marker = locations
    for paths in ([], [Path('relative')], [spool / 'missing']):
        with pytest.raises(ValueError):
            activation.activate_hold(paths, 'Preserve fallback')
    marker.parent.rmdir()
    with pytest.raises(ValueError, match='preinstalled'):
        activation.activate_hold([spool], 'Preserve fallback')
    assert not marker.parent.exists()


def test_helper_imports_only_standard_library_and_has_no_recovery_or_signal_dependency():
    body = Path(activation.__file__).read_text()
    tree = ast.parse(body)
    modules = {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert modules <= {'__future__', 'argparse', 'hashlib', 'json', 'os', 'stat', 'sys', 'time', 'uuid', 'contextlib', 'datetime', 'pathlib'}
    assert 'production_lock' not in body and 'os.kill' not in body


def test_isolated_help_does_not_import_poisoned_working_directory(tmp_path, monkeypatch):
    for name in ('json.py', 'argparse.py', 'sitecustomize.py'):
        (tmp_path / name).write_text('raise RuntimeError("MUTABLE_IMPORT_EXECUTED")\n')
    monkeypatch.setenv('PYTHONPATH', str(tmp_path))
    result = subprocess.run([sys.executable, '-I', '-S', activation.__file__, '--help'], cwd=tmp_path,
                             capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0 and 'usage:' in result.stdout
    assert 'MUTABLE_IMPORT_EXECUTED' not in result.stderr


def test_root_runtime_refuses_nonisolated_and_checkout_invocations(monkeypatch):
    monkeypatch.setattr(activation.sys, 'platform', 'linux')
    monkeypatch.setattr(activation.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setattr(activation.sys, 'flags', SimpleNamespace(isolated=0, no_site=0))
    with pytest.raises(ValueError, match='-I -S'):
        activation.require_trusted_runtime()
    monkeypatch.setattr(activation.sys, 'flags', SimpleNamespace(isolated=1, no_site=1))
    with pytest.raises(ValueError, match='mutable checkout'):
        activation.require_trusted_runtime()


@pytest.mark.parametrize('fault', ['writable_ancestor', 'foreign_owner', 'hardlinked_helper'])
def test_protected_installation_checks_entire_owner_mode_and_link_chain(tmp_path, monkeypatch, fault):
    directory = tmp_path / 'installed'
    directory.mkdir()
    helper = directory / 'activate.py'
    helper.write_text('pass\n')
    real_lstat = os.lstat
    broken = False
    def metadata(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        current = Path(path)
        mode = stat.S_IFMT(info.st_mode) | (0o755 if stat.S_ISDIR(info.st_mode) else 0o555)
        uid, links = 0, 1
        if broken and fault == 'writable_ancestor' and current == directory:
            mode |= 0o020
        if broken and fault == 'foreign_owner' and current == helper:
            uid = 1000
        if broken and fault == 'hardlinked_helper' and current == helper:
            links = 2
        return SimpleNamespace(st_mode=mode, st_uid=uid, st_gid=0, st_nlink=links)
    monkeypatch.setattr(activation.os, 'lstat', metadata)
    activation.root_owned_chain(helper, file=True)
    broken = True
    with pytest.raises(ValueError, match='root-owned and non-writable'):
        activation.root_owned_chain(helper, file=True)
