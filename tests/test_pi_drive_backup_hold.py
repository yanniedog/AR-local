"""Operator hold must stop backend access without discarding queued work."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_drive_backup as backup
import pi_drive_backup_controller as controller
import pi_drive_backup_hold as hold


@pytest.fixture
def held(tmp_path, monkeypatch):
    system = tmp_path / 'system-hold.json'
    system.write_bytes(b'')
    monkeypatch.setattr(hold, 'SYSTEM_HOLD', system)
    return SimpleNamespace(spool=tmp_path / 'spool')


@pytest.mark.parametrize('command', ['run', 'init', 'restore', 'readiness'])
def test_hold_precedes_readiness_supervision_and_backend(held, monkeypatch, command):
    def forbidden(*args, **kwargs):
        pytest.fail('hold allowed dispatch work')

    monkeypatch.setattr(backup, 'readiness', forbidden)
    monkeypatch.setattr(controller, 'execute_worker', forbidden)
    with pytest.raises(backup.Blocked, match='explicit operator approval'):
        controller.run_protected(held, command, force=True)
    assert not held.spool.exists()


@pytest.mark.parametrize('command', ['backup', 'check', 'restore', 'init', 'cat'])
def test_direct_backend_calls_cannot_bypass_hold(held, monkeypatch, command):
    monkeypatch.setattr(backup.subprocess, 'Popen', lambda *a, **k: pytest.fail('backend invoked'))
    with pytest.raises(backup.Blocked):
        backup.Restic(held).run(command)


def test_terminal_ingest_can_queue_without_acknowledgement(held):
    marker = backup.request_backup('terminal-observation', spool=held.spool.resolve())
    before = marker.read_bytes()
    with pytest.raises(backup.Blocked):
        controller.run_protected(held, force=True)
    assert marker.read_bytes() == before
    assert not (held.spool / 'latest-verified.json').exists()


def test_direct_worker_and_force_cannot_bypass_hold(held):
    with pytest.raises(backup.Blocked):
        controller.worker_action(held, {'command': 'run', 'force': True})
    with pytest.raises(backup.Blocked):
        backup._run_locked(held, force=True)


def test_spool_marker_and_malformed_markers_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(hold, 'SYSTEM_HOLD', tmp_path / 'absent')
    spool = tmp_path / 'spool'
    spool.mkdir()
    assert hold.hold_reason(spool) is None
    (spool / hold.SPOOL_HOLD_NAME).write_bytes(b'not-json')
    assert hold.hold_reason(spool)


def test_unreadable_hold_check_fails_closed(tmp_path, monkeypatch):
    def denied(_):
        raise PermissionError('unreadable')

    monkeypatch.setattr(hold.os, 'lstat', denied)
    assert 'cannot be checked' in hold.hold_reason(tmp_path)


def test_service_has_persistent_hold_condition():
    service = Path(__file__).resolve().parents[1] / 'deploy/pi/ar-local-drive-backup.service'
    assert 'ConditionPathExists=!/etc/ar-local/drive-write-hold.json' in service.read_text()
@pytest.mark.parametrize('command', ['run', 'init', 'restore'])
def test_real_cli_reports_hold_as_blocked(tmp_path, command):
    import json
    import subprocess
    import sys

    spool = tmp_path / 'spool'
    spool.mkdir()
    (spool / 'write-hold.json').write_bytes(b'')
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'pi_drive_backup.py'),
                             command, '--spool', str(spool), '--data-root', str(tmp_path / 'data')],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)['result'] == 'BLOCKED'
    assert not (spool / 'resource-runs').exists()
