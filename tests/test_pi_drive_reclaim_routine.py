"""Routine control regressions; temporary transport/files only, no Pi acceptance."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest

import pi_drive_reclaim as lease
from tests.test_pi_drive_reclaim import state  # shared host-control fixture

ROOT = Path(__file__).resolve().parents[1]


def test_persistent_reboot_fault_keeps_first_and_bounded_latest(state, monkeypatch):
    current = lease.acquire(state)
    state.boot_id = '22222222-2222-2222-2222-222222222222'
    monkeypatch.setattr(lease, 'Host', lambda: state)
    monkeypatch.setattr(lease, 'HELPER', Path(lease.__file__).resolve())
    monkeypatch.setattr(lease.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setattr(sys, 'argv', ['reclaim', 'reconcile'])
    first = lease.STATE / (current['id'] + '.reconcile.failure.json')
    original = None
    for count in range(40):
        state.clock += timedelta(seconds=30)
        with pytest.raises(ValueError, match='after reboot'):
            lease.main()
        original = original or first.read_bytes()
        assert first.read_bytes() == original
        assert state.setting == 0 and lease.load_current() is not None
    latest = json.loads((lease.STATE / (current['id'] + '.reconcile.failure-latest.json')).read_text())
    assert latest['attempts'] == 40 and latest['first_sha256'] == hashlib.sha256(original).hexdigest()
    assert len(list(lease.STATE.glob('*failure*.json'))) == 2
    assert not list(lease.STATE.glob('*.restored.json')) and not list(lease.STATE.glob('.write-*'))


def test_failure_summary_preserves_first_cause_and_current_last_cause(state):
    lease.record_failure(state, 'reconcile', ValueError('first cause'))
    first = (lease.STATE / 'unattributed.reconcile.failure.json').read_bytes()
    lease.record_failure(state, 'reconcile', OSError('latest cause'))
    last = json.loads((lease.STATE / 'unattributed.reconcile.failure-latest.json').read_bytes())
    assert (lease.STATE / 'unattributed.reconcile.failure.json').read_bytes() == first
    assert last['reason'] == 'latest cause' and last['error_type'] == 'OSError' and last['attempts'] == 2


def test_failed_receipt_publication_does_not_accumulate_staging_files(state, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('controlled publication failure')
    monkeypatch.setattr(lease.os, 'link', fail)
    for _ in range(4):
        with pytest.raises(OSError, match='publication failure'):
            lease.record_failure(state, 'reconcile', ValueError('original'))
    assert list(lease.STATE.iterdir()) == []


def test_corrupt_failure_summary_does_not_overwrite_first_evidence(state):
    lease.record_failure(state, 'reconcile', ValueError('first'))
    first = lease.STATE / 'unattributed.reconcile.failure.json'
    before = first.read_bytes()
    latest = lease.STATE / 'unattributed.reconcile.failure-latest.json'
    data = json.loads(latest.read_bytes())
    latest.write_text(json.dumps({**data, 'first_sha256': '0' * 64}))
    with pytest.raises(ValueError, match='binding differs'):
        lease.record_failure(state, 'reconcile', ValueError('second'))
    assert first.read_bytes() == before


def test_reclaim_control_sources_are_frozen_and_restored_byte_for_byte(tmp_path, monkeypatch):
    import pi_drive_backup as backup
    import pi_drive_backup_source as source
    template = (ROOT / 'deploy/pi/ar-local-drive-backup.service').read_text()
    command = next(line for line in template.splitlines() if line.startswith('ExecStart='))
    tokens = shlex.split(command.partition('=')[2].replace('{{AR_LOCAL_REPO}}', ROOT.as_posix()))
    controls = [Path(tokens[i + 1]) for i, token in enumerate(tokens[:-1]) if token == '--control-file']
    expected = {ROOT / 'pi_drive_reclaim.py', *(ROOT / 'deploy/pi' / name for name in
        (lease.LEASE, lease.RECONCILE, lease.TIMER))}
    assert expected.issubset(controls) and len(controls) == len(set(controls)) == 10
    data, stage, restored = (tmp_path / name for name in ('data', 'stage', 'restored'))
    (data / 'state').mkdir(parents=True)
    (data / 'runs').mkdir()
    manifest = source.freeze(data, stage, controls=controls, guard=lambda: None)
    try:
        rows = [row for row in manifest['files'] if row['logical_path'].startswith('control/')]
        assert len(rows) == 10
        for row in rows:
            target = restored / backup.restore_relative(row['backup_path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(row['backup_path'], target)
        assert source.verify_restore(restored, rows)['files_verified'] == 10
        for path in expected:
            row = next(row for row in rows if row['source_path'] == path.as_posix())
            assert row['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    finally:
        backup.close_manifest(manifest)


def test_backup_timers_never_persist_missed_quiet_window_triggers():
    for name in ('ar-local-drive-backup.timer', 'ar-local-drive-backup-queue.timer'):
        text = (ROOT / 'deploy/pi' / name).read_text()
        assert 'Persistent=false' in text and 'Persistent=true' not in text


@pytest.mark.skipif(not shutil.which('systemd-analyze'), reason='native systemd calendar parser requires Linux')
@pytest.mark.parametrize('base,expected', [
    ('2026-09-12 23:59:00', '2026-09-13 03:30:00'),
    ('2026-09-13 00:00:00', '2026-09-13 03:30:00'),
    ('2026-09-13 00:25:00', '2026-09-13 03:30:00'),
    ('2026-09-13 01:00:00', '2026-09-13 03:30:00'),
    ('2026-09-13 03:29:00', '2026-09-13 03:30:00'),
    ('2026-09-13 03:31:00', '2026-09-13 04:00:00'),
    ('2026-09-13 23:29:00', '2026-09-13 23:30:00'),
    ('2026-09-13 23:31:00', '2026-09-14 03:30:00')])
def test_actual_systemd_queue_calendar_stays_inside_eligible_hours(base, expected):
    text = (ROOT / 'deploy/pi/ar-local-drive-backup-queue.timer').read_text()
    expressions = [line.partition('=')[2] for line in text.splitlines() if line.startswith('OnCalendar=')]
    next_times = []
    hobart = ZoneInfo('Australia/Hobart')
    base_epoch = int(datetime.fromisoformat(base).replace(tzinfo=hobart).timestamp())
    for expression in expressions:
        # Epoch input and UTC output avoid dependence on the runner's local zone
        # or named-zone timestamp syntax. Evaluate the actual Hobart unit calendar.
        result = subprocess.run(['systemd-analyze', 'calendar', '--utc', '--base-time=@' + str(base_epoch), expression],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, 'TZ': 'UTC', 'LC_ALL': 'C'})
        assert result.returncode == 0, result.stderr + result.stdout
        match = re.search(r'Next elapse: \w+ (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC', result.stdout)
        assert match, result.stdout
        next_times.append(datetime.fromisoformat(match[1]).replace(tzinfo=timezone.utc))
    assert min(next_times) == datetime.fromisoformat(expected).replace(tzinfo=hobart)
