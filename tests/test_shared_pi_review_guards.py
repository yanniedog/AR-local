"""Regression coverage for shared-host installation and admission safeguards."""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import threading

import pytest

import ar_local_operation_lock as locks
import pi_runtime_health as health
import pi_shared_network_watchdog as network
import pi_shared_queue_store as queue_store

ROOT = Path(__file__).resolve().parents[1]


def test_scheduled_operation_waits_for_network_watchdog_release(tmp_path, monkeypatch):
    path = tmp_path / 'daily-ingest.lock'
    monkeypatch.setattr(locks, '_current_boot_id', lambda: '')
    with locks.production_lock(path, 'network-watchdog'):
        entered = threading.Event()
        acquired = threading.Event()
        errors = []
        def scheduled():
            entered.set()
            try:
                with locks.production_lock(path, 'daily-ingest'):
                    acquired.set()
            except Exception as exc:
                errors.append(exc)
        task = threading.Thread(target=scheduled)
        task.start()
        assert entered.wait(1)
        assert not acquired.wait(0.05)
    task.join(timeout=2)
    assert not task.is_alive()
    assert acquired.is_set() and not errors
    assert not path.exists()


@pytest.mark.parametrize('partial', ['', 'pid=123\nrole=network-watchdog\nboot_id=partial'])
def test_scheduled_call_waits_for_owner_initialization(tmp_path, monkeypatch, partial):
    import os
    path = tmp_path / 'daily-ingest.lock'
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    os.write(descriptor, partial.encode())
    acquired = threading.Event()
    started = threading.Event()
    errors = []
    monkeypatch.setattr(locks, '_current_boot_id', lambda: '')
    def scheduled():
        started.set()
        try:
            with locks.production_lock(path, 'daily-ingest'):
                acquired.set()
        except Exception as exc:
            errors.append(exc)
    task = threading.Thread(target=scheduled)
    task.start()
    assert started.wait(1)
    assert not acquired.wait(0.1)
    assert path.read_text() == partial
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.write(descriptor, f'pid={os.getpid()}\nrole=network-watchdog\n'.encode())
    assert not acquired.wait(0.1)
    os.close(descriptor)
    path.unlink()
    task.join(timeout=2)
    assert not task.is_alive()
    assert acquired.is_set() and not errors


def test_incomplete_owner_retry_is_bounded_and_preserves_record(tmp_path, monkeypatch):
    path = tmp_path / 'daily-ingest.lock'
    path.write_bytes(b'')
    elapsed = [0.0]
    monkeypatch.setattr(locks.time, 'monotonic', lambda: elapsed[0])
    monkeypatch.setattr(locks.time, 'sleep', lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    with pytest.raises(RuntimeError, match='active'):
        with locks.production_lock(path, 'daily-ingest'):
            pytest.fail('incomplete owner admitted')
    assert 2 <= elapsed[0] < 2.1
    assert path.read_bytes() == b''


def test_unknown_network_lock_schema_remains_fail_closed(tmp_path):
    path = tmp_path / 'daily-ingest.lock'
    path.write_text('pid=123\nrole=network-watchdog\nrecovery=manual\n')
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='active'):
        with locks.production_lock(path, 'daily-ingest'):
            pytest.fail('unknown owner admitted')
    assert path.read_bytes() == before


@pytest.mark.parametrize('running', [False, True])
def test_health_restart_holds_queue_admission_and_defers_non_ar_jobs(tmp_path, monkeypatch, running):
    root = tmp_path / 'queue'
    root.mkdir()
    monkeypatch.setattr(health, 'QUEUE_ROOT', root)
    monkeypatch.setattr(health, 'is_raspberry_pi', lambda: True)
    locked = []
    class Store:
        def __init__(self, path):
            assert path == root
        @contextmanager
        def transaction(self):
            locked.append(True)
            try:
                yield {'jobs': [{'project': 'other', 'resources': ['mining'], 'state': 'running'}] if running else []}
            finally:
                locked.pop()
        def reconcile(self, state):
            return True
    monkeypatch.setattr(queue_store, 'Store', Store)
    calls = []
    def heal(*args, **kwargs):
        assert locked == [True]
        calls.append('restart')
        return 0, ''
    monkeypatch.setattr(health, '_guarded_service_heal', heal)
    assert health._guarded_tailscale_heal(dry_run=False) == (
        (None, 'shared_queue_occupied_or_unavailable') if running else (0, ''))
    assert calls == ([] if running else ['restart'])
    assert not locked


def test_network_guard_refuses_occupied_claims_and_blocks_new_admission(tmp_path, monkeypatch):
    import fcntl
    root = tmp_path / 'queue'
    root.mkdir(mode=0o700)
    (root / 'queue.lock').touch()
    state = root / 'state.json'
    state.write_text(json.dumps({'version': 1, 'next_sequence': 0, 'jobs': []}))
    monkeypatch.setattr(network, 'QUEUE_ROOT', root)
    with network.queue_guard():
        with (root / 'queue.lock').open('r+') as contender:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state.write_text(json.dumps({'version': 1, 'next_sequence': 1, 'jobs': [{'state': 'running'}]}))
    with pytest.raises(RuntimeError, match='occupied'):
        with network.queue_guard():
            pytest.fail('occupied host admitted')


def test_queue_templates_render_only_the_selected_installed_repository():
    spec = importlib.util.spec_from_file_location('render_shared', ROOT / 'scripts/render-shared-pi-units.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ('daily', 'watchdog', 'ingest-now'):
        template = (ROOT / f'deploy/pi/shared-queue-{name}.conf').read_text()
        rendered = module.render(template, Path('/mnt/ar-local-ssd/AR-local'))
        assert '/srv/ar-local/AR-local' not in rendered
        assert '{{' not in rendered
        assert '/mnt/ar-local-ssd/AR-local/pi_daily_' in rendered
    for unsafe in ('relative/path', '/root with spaces', '/root/$USER', '/safe/../wrong'):
        with pytest.raises(ValueError):
            module.render(template, Path(unsafe))


def test_standard_installer_cannot_restore_legacy_global_network_recovery():
    power = (ROOT / 'deploy/pi/install-power-resilience.sh').read_text()
    installer = (ROOT / 'deploy/pi/install-pi-systemd.sh').read_text()
    protected = (ROOT / 'deploy/pi/install-shared-network-watchdog.sh').read_text()
    service = (ROOT / 'deploy/pi/shared-host-network.conf').read_text()
    assert 'systemctl restart NetworkManager' not in power
    assert 'install-shared-network-watchdog.sh' in power
    assert '"$repo_dir" "$data_dir"' in installer
    assert 'ar_local_operation_lock ar_local_backup_policy cdr_file_lock process_safety' in protected
    assert '-o root -g root -m 0555' in protected
    assert '--now' not in protected and 'systemctl enable' not in protected
    assert ' -I -S ' in service and 'AR_LOCAL_REPO=' not in service
    assert '{{AR_LOCAL_DATA_ROOT}}' in service and 'TimeoutStartSec=120s' in service


@pytest.mark.parametrize('sequence', [-1, 2**63, True])
def test_network_guard_rejects_invalid_sequence_metadata(tmp_path, monkeypatch, sequence):
    root = tmp_path / 'queue'
    root.mkdir(mode=0o700)
    (root / 'queue.lock').touch()
    state = root / 'state.json'
    state.write_text(json.dumps({'version': 1, 'next_sequence': sequence, 'jobs': []}))
    monkeypatch.setattr(network, 'QUEUE_ROOT', root)
    with pytest.raises(RuntimeError, match='ownership unavailable'):
        with network.queue_guard():
            pytest.fail('invalid queue admitted')


def test_root_watchdog_never_follows_stale_recovery_symlink(tmp_path):
    path = tmp_path / 'daily-ingest.lock'
    path.write_text('pid=99999999\nrole=daily-ingest\n')
    protected = tmp_path / 'protected'
    protected.write_bytes(b'')
    path.with_name('.daily-ingest.lock.recovery-lock').symlink_to(protected)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        with network.watchdog_operation_lock(path, 'network-watchdog'):
            pytest.fail('existing owner overwritten')
    assert path.read_bytes() == before
    assert protected.read_bytes() == b''


def test_root_watchdog_pins_directory_and_rejects_symlink_components(tmp_path):
    actual = tmp_path / 'actual'
    actual.mkdir()
    linked = tmp_path / 'linked'
    linked.symlink_to(actual, target_is_directory=True)
    with pytest.raises(OSError):
        with network.watchdog_operation_lock(linked / 'daily-ingest.lock', 'network-watchdog'):
            pytest.fail('symlink directory admitted')
    assert not list(actual.iterdir())
    with network.watchdog_operation_lock(actual / 'daily-ingest.lock', 'network-watchdog'):
        moved = tmp_path / 'moved'
        actual.rename(moved)
        actual.mkdir()
        replacement = actual / 'daily-ingest.lock'
        replacement.write_text('another owner')
    assert replacement.read_text() == 'another owner'
    assert not (moved / 'daily-ingest.lock').exists()
