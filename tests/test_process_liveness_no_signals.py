"""Liveness probes must leave the probed process and its console alive."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('probe', ['operation_lock', 'dispatcher', 'recovery'])
def test_live_process_probe_returns_without_signalling_console(probe, tmp_path):
    # An unfixed Windows probe can kill its whole console and even return zero.
    # Give the child a separate console, and require an after-probe marker.
    script = '''
import os,sys
from pathlib import Path
from ar_local_operation_lock import _pid_is_alive
from laptop_backup_dispatcher import process_alive
from pi_cdr_recovery import _lock_owner_may_be_active
kind=sys.argv[1]
if kind == 'operation_lock':
    alive=_pid_is_alive(os.getpid())
elif kind == 'dispatcher':
    alive=process_alive(os.getpid())
else:
    lock=Path(sys.argv[2]); lock.write_text('pid='+str(os.getpid())+'\\n')
    alive=_lock_owner_may_be_active(lock)
assert alive
print('LIVENESS_PROBE_COMPLETED',flush=True)
'''
    options = {}
    if os.name == 'nt':
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        options = {'creationflags': subprocess.CREATE_NEW_CONSOLE, 'startupinfo': startup}
    result = subprocess.run([sys.executable, '-c', script, probe, str(tmp_path/'lock')],
                            cwd=ROOT, capture_output=True, text=True, timeout=30, **options)
    assert result.returncode == 0, result.stderr
    assert 'LIVENESS_PROBE_COMPLETED' in result.stdout, result.stderr


def test_nested_production_lock_keeps_live_owner(tmp_path, monkeypatch):
    from ar_local_operation_lock import production_lock

    if os.name == 'nt':
        monkeypatch.setattr(os, 'kill', lambda *args: pytest.fail('Windows must not send signals'))
    lock = tmp_path/'daily.lock'
    with production_lock(lock, 'owner'):
        original = lock.read_bytes()
        with pytest.raises(RuntimeError, match='production lock is active'):
            with production_lock(lock, 'contender'):
                pytest.fail('A live owner must never be replaced')
        assert lock.read_bytes() == original
    assert not lock.exists()


@pytest.mark.parametrize('module,function', [
    ('ar_local_operation_lock', '_pid_is_alive'),
    ('laptop_backup_dispatcher', 'process_alive'),
])
def test_finished_process_is_not_live(module, function, monkeypatch):
    import importlib

    child = subprocess.Popen([sys.executable, '-c', 'pass'])
    child.wait(timeout=10)
    if os.name == 'nt':
        monkeypatch.setattr(os, 'kill', lambda *args: pytest.fail('Windows must not send signals'))
    probe = getattr(importlib.import_module(module), function)
    assert not probe(child.pid)
    assert not probe(0)
    assert not probe(-1)
    if os.name == 'nt':
        assert not probe(0x100000000 + os.getpid())
