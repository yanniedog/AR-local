"""Global admission barriers use private protocol fixtures, never a backend."""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

import ar_local_operation_lock as operations
import pi_drive_backup as backup
import pi_drive_backup_controller as controller
import pi_drive_backup_hold as hold
import pi_drive_backup_hold_activate as activation
from tests.drive_guard_inventory_fixture import installed_fixture


def test_global_intent_blocks_untouched_spool_before_readiness(tmp_path, monkeypatch):
    marker = tmp_path / 'system' / 'drive-write-hold.json'
    marker.parent.mkdir()
    (marker.parent / activation.GLOBAL_LOCK_NAME).write_bytes(b'partial record')
    monkeypatch.setattr(hold, 'SYSTEM_HOLD', marker)
    config = SimpleNamespace(spool=tmp_path / 'untouched-spool')
    monkeypatch.setattr(backup, 'readiness', lambda *_: pytest.fail('readiness reached'))
    with pytest.raises(backup.Blocked):
        controller.run_protected(config, force=True)
    assert not config.spool.exists() and not marker.exists()


def test_unknown_lock_field_cannot_authorize_stale_recovery(tmp_path, monkeypatch):
    lock = tmp_path / 'backup.lock'
    body = b'pid=999999\nrole=backup\nowner=unknown\n'
    lock.write_bytes(body)
    monkeypatch.setattr(operations, '_pid_is_alive', lambda _: False)
    monkeypatch.setattr(operations, '_current_boot_id', lambda: '')
    monkeypatch.setattr(operations, '_boot_epoch', lambda: None)
    with pytest.raises(RuntimeError):
        with operations.production_lock(lock, 'backup'):
            pytest.fail('unknown lock was replaced')
    assert lock.read_bytes() == body


def test_missing_installed_guard_proof_refuses_before_global_record(tmp_path, monkeypatch):
    marker = tmp_path / 'system' / 'drive-write-hold.json'
    marker.parent.mkdir()
    spool = tmp_path / 'spool'
    spool.mkdir()
    monkeypatch.setattr(activation, 'SYSTEM_HOLD', marker)
    monkeypatch.setattr(activation, 'require_trusted_runtime', lambda: None)
    with pytest.raises((OSError, ValueError)):
        activation.activate_hold([spool], 'Preserve fallback')
    assert not list(marker.parent.iterdir()) and not list(spool.iterdir())


@pytest.fixture
def interrupted(tmp_path, monkeypatch):
    installed = installed_fixture(tmp_path, monkeypatch)
    second = tmp_path / 'z-untouched-spool'
    second.mkdir()
    installed.proof['spools'].append(str(second))
    installed.proof['dispatchers'][0]['spools'].append(str(second))
    installed.write()
    monkeypatch.setattr(activation, 'require_trusted_runtime', lambda: None)
    monkeypatch.setattr(hold, 'SYSTEM_HOLD', installed.marker)
    original = activation.spool_hold_lock
    def stop_before_second(path, control):
        if path.parent == second:
            raise RuntimeError('interrupted before second spool link')
        original(path, control)
    monkeypatch.setattr(activation, 'spool_hold_lock', stop_before_second)
    with pytest.raises(activation.ActivationPending, match='second spool'):
        activation.activate_hold([installed.spool, second], 'private interruption fixture')
    assert (installed.spool / 'backup.lock').is_symlink()
    assert not (second / 'backup.lock').exists() and not installed.marker.exists()
    assert hold.hold_state(second)['state'] == 'ACTIVATION_PENDING'
    return installed, SimpleNamespace(spool=second)


@pytest.mark.parametrize('command', ['run', 'init', 'restore', 'readiness'])
def test_partial_activation_blocks_every_controller_and_worker_route(interrupted, monkeypatch, command):
    installed, config = interrupted
    def forbidden(*_args, **_kwargs):
        pytest.fail('partial global barrier allowed backend or worker admission')
    monkeypatch.setattr(backup, 'readiness', forbidden)
    monkeypatch.setattr(controller, 'execute_worker', forbidden)
    with pytest.raises(backup.Blocked):
        controller.run_protected(config, command, force=True)
    with pytest.raises(backup.Blocked):
        controller.worker_action(config, {'command': command, 'force': True})
    with pytest.raises(backup.Blocked):
        backup._run_locked(config, force=True)
    assert not list(config.spool.iterdir())
    assert not installed.marker.exists()


@pytest.mark.parametrize('command', ['backup', 'check', 'restore', 'init', 'cat'])
def test_partial_activation_blocks_direct_backend_admission(interrupted, monkeypatch, command):
    _, config = interrupted
    monkeypatch.setattr(backup.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('backend invoked'))
    with pytest.raises(backup.Blocked):
        backup.Restic(config).run(command)


def test_pre_admitted_lock_and_accepted_fallback_are_preserved(tmp_path, monkeypatch):
    installed = installed_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(activation, 'require_trusted_runtime', lambda: None)
    monkeypatch.setattr(hold, 'SYSTEM_HOLD', installed.marker)
    accepted = installed.spool / 'latest-verified.json'
    accepted.write_bytes(b'exact pre-existing receipt protocol bytes')
    request = backup.request_backup('held-terminal', spool=installed.spool)
    with operations.production_lock(installed.spool / 'backup.lock', 'in-flight-acceptance'):
        before = (installed.spool / 'backup.lock').read_bytes()
        with pytest.raises(activation.ActivationPending):
            activation.activate_hold([installed.spool], 'preserve pre-admitted operation')
        assert (installed.spool / 'backup.lock').read_bytes() == before
        assert hold.hold_state(installed.spool)['state'] == 'ACTIVATION_PENDING'
    assert accepted.read_bytes() == b'exact pre-existing receipt protocol bytes'
    assert request.is_file() and not installed.marker.exists()
    assert activation.activate_hold([installed.spool], 'no automatic retry')['result'] == 'ACTIVATION_PENDING'


def test_success_binds_verified_proof_and_distinguishes_coordinated_hold(tmp_path, monkeypatch):
    installed = installed_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(activation, 'require_trusted_runtime', lambda: None)
    monkeypatch.setattr(hold, 'SYSTEM_HOLD', installed.marker)
    proof = activation.verify_guard_inventory([installed.spool])
    result = activation.activate_hold([installed.spool], 'private coordination fixture')
    assert result['result'] == 'HELD' and result['installed_guard'] == proof
    assert json.loads(installed.marker.read_bytes())['installed_guard'] == proof
    record = (installed.marker.parent / activation.GLOBAL_LOCK_NAME).read_text()
    context = json.loads(next(line.split('=', 1)[1] for line in record.splitlines()
                              if line.startswith('context_json=')))
    assert context['state'] == 'ACTIVATION_PENDING' and context['installed_guard'] == proof
    assert hold.hold_state(installed.spool)['state'] == 'HELD'
    assert hold.hold_state(installed.spool)['coordination'] == 'NOT_ATTESTED_BY_EXISTENCE_CHECK'


@pytest.mark.parametrize('form', ['empty', 'malformed', 'dangling', 'directory'])
def test_global_existence_alone_refuses_without_parsing(tmp_path, monkeypatch, form):
    marker = tmp_path / 'drive-write-hold.json'
    global_record = marker.parent / activation.GLOBAL_LOCK_NAME
    if form == 'directory': global_record.mkdir()
    elif form == 'dangling': os.symlink(tmp_path / 'missing', global_record)
    else: global_record.write_bytes(b'' if form == 'empty' else b'incomplete')
    monkeypatch.setattr(hold, 'SYSTEM_HOLD', marker)
    monkeypatch.setattr(Path, 'open', lambda *_a, **_k: pytest.fail('record parsed for admission'))
    assert hold.hold_state(tmp_path / 'alternate')['state'] == 'ACTIVATION_PENDING'


@pytest.mark.parametrize('trigger', ['dead_pid', 'prior_boot', 'old_mtime'])
def test_unknown_keys_refuse_before_any_stale_owner_heuristic(tmp_path, monkeypatch, trigger):
    lock = tmp_path / 'backup.lock'
    body = b'pid=999999\nrole=backup\nboot_id=prior\nprotocol=unrecognized\n'
    lock.write_bytes(body)
    os.utime(lock, (1, 1))
    def forbidden(*_args):
        pytest.fail('unknown schema reached stale-owner heuristic: ' + trigger)
    monkeypatch.setattr(operations, '_pid_is_alive', forbidden)
    monkeypatch.setattr(operations, '_current_boot_id', forbidden)
    monkeypatch.setattr(operations, '_boot_epoch', forbidden)
    assert operations._existing_lock_is_stale(lock) is False
    assert lock.read_bytes() == body


def test_service_checks_both_permanent_global_and_final_markers():
    source = Path(activation.__file__).parent / 'deploy/pi/ar-local-drive-backup.service'
    body = source.read_text()
    assert 'ConditionPathExists=!/etc/ar-local/drive-write-hold.json' in body
    assert 'ConditionPathExists=!/etc/ar-local/.drive-write-hold-activation.lock' in body


def test_actual_child_death_before_any_spool_link_keeps_global_refusal(tmp_path, monkeypatch):
    spool, system = tmp_path / 'spool', tmp_path / 'system'
    spool.mkdir()
    system.mkdir()
    marker = system / 'drive-write-hold.json'
    program = '''
import sys,time
from pathlib import Path
import pi_drive_backup_hold_activate as helper
helper.SYSTEM_HOLD = Path(sys.argv[2])
helper.require_trusted_runtime = lambda: None  # Private filesystem protocol only.
helper.verify_guard_inventory = lambda _: {'protocol': helper.GUARD_PROTOCOL}
def pause_before_any_spool_link(*args):
    print('GLOBAL_RECORD_DURABLE', flush=True)
    while True:
        time.sleep(0.1)
helper.spool_hold_lock = pause_before_any_spool_link
helper.activate_hold([Path(sys.argv[1])], 'isolated global crash fixture')
'''
    child = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-c', program,
                              str(spool), str(marker)], cwd=Path(activation.__file__).parent,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    with ThreadPoolExecutor(max_workers=1) as reader:
        try:
            assert reader.submit(child.stdout.readline).result(timeout=10).strip() == 'GLOBAL_RECORD_DURABLE'
        finally:
            child.terminate()  # Dedicated private child handle; never signal-zero.
            child.wait(timeout=10)
            child.stdout.close()
            child.stderr.close()
    assert not list(spool.iterdir()) and not marker.exists()
    assert (system / activation.GLOBAL_LOCK_NAME).is_file()
    monkeypatch.setattr(hold, 'SYSTEM_HOLD', marker)
    monkeypatch.setattr(backup, 'readiness', lambda *_: pytest.fail('worker admitted after crash'))
    with pytest.raises(backup.Blocked):
        controller.run_protected(SimpleNamespace(spool=spool), force=True)
    assert hold.hold_state(spool)['state'] == 'ACTIVATION_PENDING'
