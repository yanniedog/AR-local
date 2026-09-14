"""Late receipt/boot-identity protocol regressions; no backend or live PID calls."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os

import pytest

import ar_local_operation_lock as operations
import pi_drive_backup_hold_activate as activation
from tests.drive_guard_inventory_fixture import installed_fixture


CURRENT_BOOT = 'f67c2221-5510-4f96-84a4-fc2362a6b137'
PRIOR_BOOT = '755c69a0-f0d1-41f6-81ec-cc8ae22b010b'


def test_complete_final_receipt_bound_refuses_before_any_permanent_barrier(tmp_path, monkeypatch):
    installed = installed_fixture(tmp_path, monkeypatch)
    spools = [tmp_path / (f'{index:03d}-' + 's' * (230 - len(str(tmp_path)) - 5))
              for index in range(128)]
    assert all(len(str(path)) == 230 for path in spools)
    for path in spools:
        path.mkdir()
    installed.proof['spools'] = [str(path) for path in spools]
    installed.proof['dispatchers'][0]['spools'] = installed.proof['spools']
    installed.write()
    assert installed.path.stat().st_size <= activation.MAX_PROOF_BYTES
    monkeypatch.setattr(activation, 'require_trusted_runtime', lambda: None)
    error = None
    try:
        activation.activate_hold(spools, 'R' * 4096)
    except (ValueError, RuntimeError) as caught:
        error = caught
    assert error is not None, 'oversized final receipt was accepted'
    assert not (installed.marker.parent / activation.GLOBAL_LOCK_NAME).exists()
    assert not installed.marker.exists()
    assert all(not list(path.iterdir()) for path in spools)
    assert isinstance(error, ValueError) and 'hold receipt exceeds safe bound' in str(error)


def test_truncated_boot_id_cannot_displace_live_owner(tmp_path, monkeypatch):
    lock = tmp_path / 'backup.lock'
    before = f'pid=1234\nrole=backup\nboot_id={CURRENT_BOOT[:12]}\n'.encode()
    lock.write_bytes(before)
    monkeypatch.setattr(operations, '_current_boot_id', lambda: CURRENT_BOOT)
    monkeypatch.setattr(operations, '_pid_is_alive', lambda _: True)
    monkeypatch.setattr(operations, '_boot_epoch', lambda: None)
    with pytest.raises(RuntimeError):
        with operations.production_lock(lock, 'contender'):
            pytest.fail('live owner displaced by malformed boot identity')
    assert lock.read_bytes() == before


@pytest.mark.parametrize('recorded', ['', 'truncated', CURRENT_BOOT[:35], CURRENT_BOOT.upper(),
                                     CURRENT_BOOT.replace('-', ''), '{' + CURRENT_BOOT + '}'])
def test_malformed_boot_field_refuses_before_all_staleness_checks(tmp_path, monkeypatch, recorded):
    lock = tmp_path / 'backup.lock'
    before = f'pid=1234\nrole=backup\nboot_id={recorded}\n'.encode()
    lock.write_bytes(before)
    os.utime(lock, (1, 1))
    def forbidden(*_):
        pytest.fail('malformed boot identity reached a staleness heuristic')
    for name in ('_current_boot_id', '_boot_epoch', '_pid_is_alive'):
        monkeypatch.setattr(operations, name, forbidden)
    assert operations._existing_lock_is_stale(lock) is False
    assert lock.read_bytes() == before


@pytest.mark.parametrize(('recorded', 'alive', 'expected'), [
    (CURRENT_BOOT, True, False), (CURRENT_BOOT, False, True), (PRIOR_BOOT, True, True),
    (None, True, False), (None, False, True),
])
def test_valid_same_prior_and_missing_legacy_boot_identity(tmp_path, monkeypatch, recorded, alive, expected):
    lock = tmp_path / 'backup.lock'
    lock.write_text('pid=1234\nrole=backup\n' + (f'boot_id={recorded}\n' if recorded else ''))
    monkeypatch.setattr(operations, '_current_boot_id', lambda: CURRENT_BOOT)
    monkeypatch.setattr(operations, '_pid_is_alive', lambda _: alive)
    monkeypatch.setattr(operations, '_boot_epoch', lambda: None)
    assert operations._existing_lock_is_stale(lock) is expected


def test_malformed_current_boot_does_not_authorize_prior_boot_recovery(tmp_path, monkeypatch):
    lock = tmp_path / 'backup.lock'
    lock.write_text(f'pid=1234\nrole=backup\nboot_id={PRIOR_BOOT}\n')
    monkeypatch.setattr(operations, '_current_boot_id', lambda: CURRENT_BOOT[:12])
    monkeypatch.setattr(operations, '_pid_is_alive', lambda _: pytest.fail('PID must not be probed'))
    monkeypatch.setattr(operations, '_boot_epoch', lambda: pytest.fail('mtime must not authorize recovery'))
    assert operations._existing_lock_is_stale(lock) is False


def test_actual_coordination_timestamp_cannot_grow_preflight_bytes(tmp_path, monkeypatch):
    installed = installed_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(activation, 'require_trusted_runtime', lambda: None)
    instants = iter([datetime(2026, 9, 14, 14, 30, 0, 0, timezone.utc),
                     datetime(2026, 9, 14, 14, 30, 1, 123456, timezone.utc)])
    class Clock:
        @staticmethod
        def now(_):
            return next(instants)
    monkeypatch.setattr(activation, 'datetime', Clock)
    original, samples = activation.marker_bytes, []
    def capture(value):
        body = original(value)
        samples.append((body, (installed.marker.parent / activation.GLOBAL_LOCK_NAME).exists()))
        return body
    monkeypatch.setattr(activation, 'marker_bytes', capture)
    activation.activate_hold([installed.spool], 'Unicode receipt boundary \U0001f512')
    assert len(samples) == 2 and samples[0][1] is False and samples[1][1] is True
    assert len(samples[0][0]) == len(samples[1][0])
    assert json.loads(samples[0][0])['activated_at'] == '2026-09-14T14:30:00.000000+00:00'
    actual = json.loads(installed.marker.read_bytes())
    assert actual['activated_at'] == '2026-09-14T14:30:01.123456+00:00'
    assert actual['state'] == 'HELD'
