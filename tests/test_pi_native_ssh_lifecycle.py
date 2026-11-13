"""Failure-boundary regressions; no service commands or network access."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_native_ssh as native
from tests.test_pi_native_ssh import approval


def test_keygen_comment_is_normalized_only_at_derivation_boundary():
    key = approval()['host_public_key']
    assert native.derived_host_key(key + ' host comment with spaces\n') == key
    assert native.derived_host_key(key + '\n') == key
    with pytest.raises(ValueError): native.public_key(key + ' comment')
    for value in ('', key + '\n' + key, 'command="x" ' + key, 'ssh-ed25519 bad comment'):
        with pytest.raises(ValueError): native.derived_host_key(value)


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    root = tmp_path / 'owned'; unit = tmp_path / native.SERVICE
    monkeypatch.setattr(native, 'ROOT', root); monkeypatch.setattr(native, 'UNIT', unit)
    bodies = native.render(approval()); events = []
    monkeypatch.setattr(native, 'admit', lambda _: events.append('admit'))
    monkeypatch.setattr(native, 'protected', lambda path, **_: path.read_bytes())
    monkeypatch.setattr(native, 'protected_directory', lambda _: None)
    monkeypatch.setattr(native, 'effective_validate', lambda *_: None)
    monkeypatch.setattr(native, 'create', lambda path, body: (events.append(('create', path)), path.write_bytes(body)))
    monkeypatch.setattr(native, 'sync_directory', lambda path: events.append(('fsync', path)))
    state = {'dropins': '', 'enabled': 'disabled'}

    def command(args, **kwargs):
        events.append(tuple(args))
        if 'unit-paths' in args:
            return SimpleNamespace(stdout=str(tmp_path) + '\n', returncode=0)
        if 'is-enabled' in args:
            return SimpleNamespace(stdout=state['enabled'] + '\n', returncode=1 if state['enabled'] == 'disabled' else 0)
        if args[-1] == '--property=LoadState':
            return SimpleNamespace(stdout='LoadState=not-found\n', returncode=0)
        if args[-1] == '--property=FragmentPath,DropInPaths':
            return SimpleNamespace(stdout=f'FragmentPath={unit if unit.exists() else ""}\nDropInPaths={state["dropins"]}\n')
        return SimpleNamespace(stdout='ActiveState=inactive\nMainPID=0\nControlGroup=\n', returncode=0)

    monkeypatch.setattr(native, 'run', command)
    return root, unit, bodies, events, state, command


def install(lifecycle):
    _, _, bodies, _, _, _ = lifecycle
    assert native.mutate('install', approval(), bodies, b'approval', 1000) == 'INSTALLED_DISABLED'


def test_install_checks_parent_durability_and_disabled_state(lifecycle):
    root, unit, _, events, _, _ = lifecycle
    install(lifecycle)
    assert events.index(('fsync', root.parent)) < events.index(('create', root / 'approval.json'))
    assert events[-1] == ('/usr/bin/systemctl', 'is-enabled', native.SERVICE)
    assert unit.exists()


def test_install_rechecks_admission_after_inventory_before_first_write(lifecycle, monkeypatch):
    root, _, bodies, _, _, _ = lifecycle
    calls = 0
    def admit(_):
        nonlocal calls
        calls += 1
        if calls == 2: raise ValueError('quiet after inventory')
    monkeypatch.setattr(native, 'admit', admit)
    with pytest.raises(ValueError, match='quiet'):
        native.mutate('install', approval(), bodies, b'approval', 1000)
    assert not root.exists()


@pytest.mark.parametrize('dangling', [False, True])
def test_stale_enablement_is_refused_before_creating_any_owned_path(lifecycle, dangling):
    root, unit, bodies, _, _, _ = lifecycle
    wanted = unit.parent / 'multi-user.target.wants'; wanted.mkdir()
    link = wanted / native.SERVICE
    if dangling:
        if os.name == 'nt': pytest.skip('POSIX systemd symlink fixture')
        link.symlink_to(unit)
    else:
        link.write_bytes(b'existing dependency')
    with pytest.raises(ValueError, match='enablement'):
        native.mutate('install', approval(), bodies, b'approval', 1000)
    assert not root.exists() and not unit.exists()
    assert link.exists() or link.is_symlink()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX systemd symlink fixture')
def test_stale_alias_is_refused(lifecycle):
    root, unit, bodies, _, _, _ = lifecycle
    (unit.parent / 'other-name.service').symlink_to(unit)
    with pytest.raises(ValueError, match='alias'):
        native.mutate('install', approval(), bodies, b'approval', 1000)
    assert not root.exists()


def test_start_cannot_bypass_wire_proof_with_existing_enablement(lifecycle):
    _, _, bodies, events, state, _ = lifecycle
    install(lifecycle); events.clear(); state['enabled'] = 'enabled'
    with pytest.raises(ValueError, match='disabled'):
        native.mutate('start', approval(), bodies, b'approval', 1000)
    assert ('/usr/bin/systemctl', 'start', native.SERVICE) not in events


def test_rollback_checks_pending_definition_drift_before_stop(lifecycle):
    _, unit, bodies, events, state, _ = lifecycle
    install(lifecycle); events.clear(); state['dropins'] = '/etc/unreviewed.conf'
    with pytest.raises(ValueError, match='override'):
        native.mutate('rollback', approval(), bodies, b'approval', 1000)
    assert unit.exists()
    assert ('/usr/bin/systemctl', 'disable', '--now', native.SERVICE) not in events


@pytest.mark.parametrize('boundary', ['retired-copy', 'unlink-fsync', 'final-reload'])
def test_interrupted_rollback_retries_only_exact_retained_evidence(lifecycle, monkeypatch, boundary):
    root, unit, bodies, events, _, command = lifecycle
    install(lifecycle)
    retired = root / 'retired-unit.service'
    original_create = native.create
    original_sync = native.sync_directory

    def create(path, body):
        original_create(path, body)
        if boundary == 'retired-copy' and path == retired: raise ValueError('interrupted copy')
    def sync(path):
        original_sync(path)
        if boundary == 'unlink-fsync' and path == unit.parent and not unit.exists():
            raise ValueError('interrupted fsync')
    def run(args, **kwargs):
        if boundary == 'final-reload' and 'daemon-reload' in args and not unit.exists():
            raise ValueError('quiet before final reload')
        return command(args, **kwargs)
    monkeypatch.setattr(native, 'create', create)
    monkeypatch.setattr(native, 'sync_directory', sync)
    monkeypatch.setattr(native, 'run', run)
    with pytest.raises(ValueError): native.mutate('rollback', approval(), bodies, b'approval', 1000)
    assert retired.read_bytes() == bodies['unit']
    monkeypatch.setattr(native, 'create', original_create)
    monkeypatch.setattr(native, 'sync_directory', original_sync)
    monkeypatch.setattr(native, 'run', command)
    assert native.mutate('rollback', approval(), bodies, b'approval', 1000) == 'ROLLED_BACK_EVIDENCE_RETAINED'
    assert not unit.exists() and retired.read_bytes() == bodies['unit']
    assert (root / 'approval.json').read_bytes() == b'approval'
    assert ('/usr/bin/systemctl', 'disable', '--now', native.SERVICE) in events
    assert ('fsync', unit.parent) in events


def test_retired_resume_refuses_changed_evidence(lifecycle):
    root, unit, bodies, events, _, _ = lifecycle
    install(lifecycle)
    (root / 'retired-unit.service').write_bytes(b'changed'); unit.unlink(); events.clear()
    with pytest.raises(ValueError, match='changed'):
        native.mutate('rollback', approval(), bodies, b'approval', 1000)
    assert not any(isinstance(e, tuple) and e[0] == '/usr/bin/systemctl' for e in events)


def test_directory_fsync_operates_on_directory_descriptor(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(native.os, 'O_DIRECTORY', 0x10000, raising=False)
    monkeypatch.setattr(native.os, 'open', lambda path, flags: (events.append(('open', path, flags)), 42)[1])
    monkeypatch.setattr(native.os, 'fsync', lambda fd: events.append(('fsync', fd)))
    monkeypatch.setattr(native.os, 'close', lambda fd: events.append(('close', fd)))
    native.sync_directory(tmp_path)
    assert events == [('open', tmp_path, os.O_RDONLY | os.O_DIRECTORY), ('fsync', 42), ('close', 42)]
