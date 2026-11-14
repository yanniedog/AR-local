"""Health-state persistence cannot race a protected shared-queue workload."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
from unittest.mock import Mock

import pytest

import ar_local_operation_lock as locks
import pi_runtime_health as health
import pi_shared_queue_store as queue


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    data = tmp_path / 'data'; data.mkdir()
    state = data / 'state'
    queue_root = tmp_path / 'queue'; queue_root.mkdir(mode=0o700)
    monkeypatch.setattr(health, 'QUEUE_ROOT', queue_root)
    monkeypatch.setattr(health, 'data_state_root', lambda _: state)
    monkeypatch.setattr(health, 'is_raspberry_pi', lambda: True)
    monkeypatch.setattr(health, '_production_activity_block_reason', Mock(return_value=''))
    monkeypatch.setattr(locks, '_current_boot_id', lambda: 'f67c2221-5510-4f96-84a4-fc2362a6b137')
    monkeypatch.setattr(locks, '_boot_epoch', lambda: None)
    monkeypatch.setattr(locks, '_pid_is_alive', lambda _: True)
    return data, state, queue_root


def snapshot(root):
    def info(path):
        value = path.stat()
        return value.st_ino, value.st_mtime_ns, value.st_ctime_ns
    return {'root': info(root), 'entries': {p.relative_to(root).as_posix():
            (info(p), p.read_bytes() if p.is_file() else None) for p in root.rglob('*')}}


def controlled_queue(monkeypatch, *, running=False, trusted=True):
    phases = []; active = {'held': False}
    class Store:
        def __init__(self, _root): pass
        @contextmanager
        def transaction(self):
            assert not active['held']
            active['held'] = True; phases.append('enter')
            try: yield {'jobs': [{'state': 'running'}] if running else []}
            finally: active['held'] = False; phases.append('exit')
        def reconcile(self, _state): return trusted
    monkeypatch.setattr(queue, 'Store', Store)
    return active, phases


@pytest.mark.parametrize('running,trusted', [(True, True), (False, False), (True, False)])
def test_occupied_or_unknown_queue_changes_no_protected_bytes_or_directories(isolated, monkeypatch, capsys, running, trusted):
    data, state, _ = isolated
    controlled_queue(monkeypatch, running=running, trusted=trusted)
    probe = Mock(side_effect=AssertionError('write probe ran under occupied queue'))
    native = Mock(side_effect=AssertionError('native lease attempted under occupied queue'))
    monkeypatch.setattr(health, 'ensure_runtime_data_writable', probe)
    monkeypatch.setattr(health, 'production_lock', native)
    before = snapshot(data)
    assert health.save_state({'http_fail_streak': 1}) is False
    assert snapshot(data) == before and not state.exists()
    probe.assert_not_called(); native.assert_not_called()
    health._production_activity_block_reason.assert_not_called()
    assert 'state persistence deferred' in capsys.readouterr().out


def test_busy_native_owner_defers_before_probe_and_preserves_state(isolated, monkeypatch, capsys):
    data, state, _ = isolated; state.mkdir()
    original = b'{"http_fail_streak":2}\n'
    (state / health.STATE_NAME).write_bytes(original)
    controlled_queue(monkeypatch)
    probe = Mock(side_effect=AssertionError('busy owner must prevent write probe'))
    monkeypatch.setattr(health, 'ensure_runtime_data_writable', probe)
    with locks.production_lock(state / 'daily-ingest.lock', 'ingest'):
        before = snapshot(data)
        assert health.save_state({'http_fail_streak': 3}) is False
        assert snapshot(data) == before
    probe.assert_not_called()
    assert (state / health.STATE_NAME).read_bytes() == original
    assert 'state persistence deferred' in capsys.readouterr().out


@pytest.mark.parametrize('inside_lease', [False, True])
def test_activity_before_or_after_native_lease_prevents_probe(isolated, monkeypatch, inside_lease):
    _, state, _ = isolated
    controlled_queue(monkeypatch)
    def activity(*, include_ingest_lock=True):
        if include_ingest_lock and inside_lease: return ''
        return 'backup_source_active'
    monkeypatch.setattr(health, '_production_activity_block_reason', activity)
    probe = Mock(side_effect=AssertionError('activity must prevent write probe'))
    monkeypatch.setattr(health, 'ensure_runtime_data_writable', probe)
    assert health.save_state({'http_fail_streak': 3}) is False
    probe.assert_not_called()
    assert not (state / health.STATE_NAME).exists()
    assert not (state / 'daily-ingest.lock').exists()


def test_idle_persist_holds_queue_and_native_lease_through_atomic_replace(isolated, monkeypatch):
    _, state, _ = isolated
    active, phases = controlled_queue(monkeypatch)
    def check_guard():
        assert active['held']
        assert b'role=runtime-health' in (state / 'daily-ingest.lock').read_bytes()
    monkeypatch.setattr(health, 'ensure_runtime_data_writable', lambda _: check_guard())
    original_replace = Path.replace
    def replace(path, target):
        if path.name == 'runtime_health.tmp': check_guard(); phases.append('replace')
        return original_replace(path, target)
    monkeypatch.setattr(Path, 'replace', replace)
    expected = {'http_fail_streak': 4, 'tailscale_fail_streak': 2, 'last_check_at': '2026-11-14T00:00:00Z'}
    assert health.save_state(expected) is True
    assert health.load_state() == expected
    assert phases == ['enter', 'replace', 'exit']
    assert not (state / 'runtime_health.tmp').exists()
    assert not (state / 'daily-ingest.lock').exists()


@pytest.mark.parametrize('where', ['probe', 'write', 'replace'])
def test_real_write_errors_propagate_and_release_guards(isolated, monkeypatch, where):
    _, state, _ = isolated
    active, _ = controlled_queue(monkeypatch)
    monkeypatch.setattr(health, 'ensure_runtime_data_writable', lambda _: None)
    def fail(*_args, **_kwargs): raise OSError('controlled disk failure')
    if where == 'probe': monkeypatch.setattr(health, 'ensure_runtime_data_writable', fail)
    elif where == 'write': monkeypatch.setattr(Path, 'write_text', fail)
    else: monkeypatch.setattr(Path, 'replace', fail)
    with pytest.raises(OSError, match='controlled disk failure'):
        health.save_state({'http_fail_streak': 1})
    assert not active['held'] and not (state / 'daily-ingest.lock').exists()


@pytest.mark.skipif(os.name != 'posix', reason='production queue uses Linux flock')
def test_actual_queue_transaction_blocks_racing_admission_until_state_saved(isolated, monkeypatch):
    _, state, queue_root = isolated
    attempted, admitted = threading.Event(), threading.Event()
    errors = []; threads = []
    def admission():
        attempted.set()
        try:
            with queue.Store(queue_root).transaction(): admitted.set()
        except BaseException as error: errors.append(error)
    def probe(_):
        assert (state / 'daily-ingest.lock').exists()
        thread = threading.Thread(target=admission, daemon=True); threads.append(thread); thread.start()
        assert attempted.wait(2)
        assert not admitted.wait(0.1), 'queue admission entered during state write'
    monkeypatch.setattr(health, 'ensure_runtime_data_writable', probe)
    try:
        assert health.save_state({'http_fail_streak': 5}) is True
    finally:
        for thread in threads: thread.join(3)
    assert not errors and admitted.is_set() and all(not thread.is_alive() for thread in threads)
    assert json.loads((state / health.STATE_NAME).read_text())['http_fail_streak'] == 5
