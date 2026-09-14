"""Lock-boundary regressions; no Drive calls or simulated banking data."""
from pathlib import Path

import pytest

import pi_drive_backup_hold_activate as activation
from ar_local_operation_lock import production_lock


@pytest.fixture
def locations(tmp_path, monkeypatch):
    spool = tmp_path / 'spool'
    spool.mkdir()
    marker = tmp_path / 'system' / 'drive-write-hold.json'
    monkeypatch.setattr(activation, 'SYSTEM_HOLD', marker)
    return spool, marker


def test_inflight_acceptance_prevents_activating_hold(locations):
    spool, marker = locations
    with production_lock(spool / 'backup.lock', 'in-flight-acceptance'):
        with pytest.raises(RuntimeError, match='active'):
            activation.activate_hold([spool], 'Preserve accepted fallback')
        assert not marker.exists()
    result = activation.activate_hold([spool], 'Preserve accepted fallback')
    assert result['result'] == 'HELD'
    assert marker.is_file()


def test_all_spools_must_be_idle_and_locks_are_released_on_failure(locations):
    spool, marker = locations
    other = spool.parent / 'second-spool'
    other.mkdir()
    with production_lock(other / 'backup.lock', 'other-operation'):
        with pytest.raises(RuntimeError, match='active'):
            activation.activate_hold([spool, other], 'Preserve accepted fallback')
        assert not marker.exists()
        assert not (spool / 'backup.lock').exists()


def test_existing_marker_bytes_are_preserved(locations):
    spool, marker = locations
    marker.parent.mkdir()
    marker.write_bytes(b'')
    assert activation.activate_hold([spool], 'Preserve fallback')['result'] == 'ALREADY_HELD'
    assert marker.read_bytes() == b''


def test_marker_write_occurs_under_every_acceptance_lock(locations, monkeypatch):
    import pi_drive_backup

    spool, marker = locations
    write = pi_drive_backup.atomic_json

    def locked_write(*args, **kwargs):
        assert (spool / 'backup.lock').exists()
        return write(*args, **kwargs)

    monkeypatch.setattr(pi_drive_backup, 'atomic_json', locked_write)
    activation.activate_hold([spool], 'Preserve fallback')
    assert marker.is_file()
    assert not (spool / 'backup.lock').exists()


@pytest.mark.parametrize('reason', ['', '  '])
def test_empty_reason_refused(locations, reason):
    spool, marker = locations
    with pytest.raises(ValueError):
        activation.activate_hold([spool], reason)
    assert not marker.exists()


def test_relative_or_unknown_spool_refused(locations):
    spool, marker = locations
    for paths in ([], [Path('relative')], [spool / 'missing']):
        with pytest.raises(ValueError):
            activation.activate_hold(paths, 'Preserve fallback')
    assert not marker.exists()
