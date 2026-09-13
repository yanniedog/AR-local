from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import pytest

import pi_issue_watchdog as watch
from pi_github_alerts import AlertStore


NOW = datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)
DUE = watch.latest_daily_due_utc(NOW)


def units(start=DUE, active=False):
    return {name: {'started_at': start, 'ActiveState': 'active' if active else 'inactive'}
            for name in watch.UNITS[:3]}


def test_missing_scheduled_start_reports_even_if_recovered_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, 'completion', lambda *_: 'COMPLETE')
    store = AlertStore(tmp_path)
    watch.ingest_checks(store, tmp_path, NOW, units(DUE - timedelta(days=1)))
    row = store.read()['incidents']['ingest-schedule:2026-09-13']
    assert row['category'] == 'SCHEDULED_INGEST_NOT_STARTED' and row['active']


def test_active_ingest_is_not_missed_completion(tmp_path):
    store = AlertStore(tmp_path)
    result = watch.ingest_checks(store, tmp_path, DUE + timedelta(minutes=45), units(active=True))
    assert result['status'] == 'RUNNING' and store.read()['incidents'] == {}


def test_stuck_ingest_is_reported(tmp_path):
    store = AlertStore(tmp_path)
    assert watch.ingest_checks(store, tmp_path, DUE + timedelta(hours=7), units(active=True))['status'] == 'STUCK'
    assert store.read()['incidents']['ingest:2026-09-13']['category'] == 'INGEST_RUNTIME_EXCEEDED'


def test_partial_capture_is_not_called_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, 'completion', lambda *_: 'PARTIAL')
    store = AlertStore(tmp_path)
    assert watch.ingest_checks(store, tmp_path, NOW, units())['status'] == 'PARTIAL'
    assert store.read()['incidents']['ingest:2026-09-13']['category'] == 'INGEST_PARTIAL'


def test_grace_does_not_read_or_alert(tmp_path):
    store = AlertStore(tmp_path)
    assert watch.ingest_checks(store, tmp_path, DUE + timedelta(minutes=29), {})['status'] == 'GRACE'
    assert store.read()['incidents'] == {}


def test_rejects_evidence_path_escape(tmp_path):
    try: watch.read_json(tmp_path, '../unexpected')
    except ValueError: pass
    else: raise AssertionError('escape accepted')


def test_boot_day_uses_previous_due_date_before_one_am():
    now = datetime(2026, 9, 12, 14, 40, tzinfo=timezone.utc)
    assert watch.expected_run_date_for_due(watch.latest_daily_due_utc(now)) == '2026-09-12'


def test_invalid_marker_never_counts_as_complete(tmp_path):
    assert watch.completion(tmp_path, '2026-09-13') == 'MISSING'
    directory = tmp_path / 'observation-pointers-v2'; directory.mkdir()
    (directory / 'latest-observation.json').write_text('{broken')
    assert watch.completion(tmp_path, '2026-09-13') == 'INVALID'


def test_read_only_cannot_dispatch_failure_event(monkeypatch):
    monkeypatch.setattr(watch, 'configured_store', lambda: pytest.fail('read-only dispatch created store'))
    with pytest.raises(SystemExit) as error:
        watch.main(['--checks-only', '--failed-unit', 'ar-local-daily.service'])
    assert error.value.code == 2


def test_existing_backup_failure_is_detected_without_new_hook(tmp_path):
    store = AlertStore(tmp_path)
    assert watch.backup_check(store, tmp_path, {'ActiveState': 'failed', 'Result': 'exit-code'})['status'] == 'FAILED'
    assert store.read()['incidents']['drive-backup']['active']


def test_exit_zero_without_verified_backup_never_resolves(tmp_path):
    store = AlertStore(tmp_path)
    store.observe('drive-backup', 'Pi Google Drive backup failed', 'BACKUP_SERVICE_FAILED', healthy=False)
    result = watch.backup_check(store, tmp_path, {'ActiveState': 'inactive', 'Result': 'success', 'ExecMainPID': '12'})
    assert result['status'] == 'NO_CURRENT_VERIFIED_RECOVERY'
    assert store.read()['incidents']['drive-backup']['active']


def test_larger_contract_metadata_uses_bounded_exception(tmp_path):
    import json
    (tmp_path / 'contract.json').write_text(json.dumps({'inventory': 'x' * (2 * 1024 * 1024)}))
    with pytest.raises(watch.EvidenceLimit):
        watch.read_json(tmp_path, 'contract.json')
    assert len(watch.read_json(tmp_path, 'contract.json', maximum=8 * 1024 * 1024)['inventory']) == 2 * 1024 * 1024


def quiet_fixture(tmp_path, identifier='a' * 32):
    started = datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc)  # 01:00 Hobart.
    row = {'ActiveState': 'failed', 'Result': 'exit-code', 'ExecMainStatus': '2',
           'ExecMainPID': '123', 'started_at': started}
    directory = tmp_path / 'resource-runs' / identifier
    directory.mkdir(parents=True)
    request = {'command': 'run', 'supervisor_pid': 123}
    resources = {'schema': 'ar-local-drive-resources-v1', 'result': 'BLOCKED', 'group_clean': True,
                 'reason': 'Blocked: daily ingest quiet window: 00:30-03:30 Australia/Hobart',
                 'samples': 0, 'workload_exit_code': None}
    for name, value in [('request', request), ('resources', resources)]:
        path = directory / (name + '.json'); path.write_text(json.dumps(value))
        os.utime(path, (started.timestamp() + 1,) * 2)
    os.utime(directory, (started.timestamp() + 1,) * 2)
    return row, directory


def test_quiet_admission_defers_without_creating_or_resolving_incident(tmp_path, monkeypatch):
    row, directory = quiet_fixture(tmp_path)
    store = AlertStore(tmp_path / 'alerts')
    assert watch.backup_check(store, tmp_path, row)['status'] == 'QUIET_WINDOW_DEFERRED'
    assert store.read()['incidents'] == {}
    store.observe('drive-backup', 'Pi Google Drive backup failed', 'BACKUP_SERVICE_FAILED', healthy=False)
    before = store.path.read_bytes()
    assert watch.backup_check(store, tmp_path, row)['status'] == 'QUIET_WINDOW_DEFERRED'
    monkeypatch.setattr(watch, 'unit_state', lambda _: row)
    monkeypatch.setenv('AR_LOCAL_DRIVE_BACKUP_SPOOL', str(tmp_path))
    assert watch.failure_event(store, 'ar-local-drive-backup.service', NOW)['status'] == 'QUIET_WINDOW_DEFERRED'
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('fault', ['other_reason', 'dirty_group', 'cleanup_error', 'worker_started',
    'worker_exit', 'wrong_schema', 'wrong_pid', 'wrong_command', 'stale_request', 'outside_window',
    'real_exit1', 'missing_resource', 'oversized_resource', 'ambiguous'])
def test_exit2_and_wall_clock_alone_cannot_suppress_real_failure(tmp_path, fault):
    row, directory = quiet_fixture(tmp_path)
    resource_path = directory / 'resources.json'; request_path = directory / 'request.json'
    resources, request = json.loads(resource_path.read_text()), json.loads(request_path.read_text())
    if fault == 'other_reason': resources['reason'] = 'RuntimeError: host_swap_out_activity'
    elif fault == 'dirty_group': resources['group_clean'] = False
    elif fault == 'cleanup_error': resources['cleanup_error'] = 'RuntimeError'
    elif fault == 'worker_started': resources['samples'] = 1
    elif fault == 'worker_exit': resources['workload_exit_code'] = 2
    elif fault == 'wrong_schema': resources['schema'] = 'unverified'
    elif fault == 'wrong_pid': request['supervisor_pid'] = 124
    elif fault == 'wrong_command': request['command'] = 'init'
    elif fault == 'outside_window': row['started_at'] = row['started_at'] - timedelta(hours=2)
    elif fault == 'real_exit1': row['ExecMainStatus'] = '1'
    elif fault == 'ambiguous': quiet_fixture(tmp_path, 'b' * 32)
    resource_path.write_text(json.dumps(resources)); request_path.write_text(json.dumps(request))
    if fault == 'stale_request': os.utime(request_path, (row['started_at'].timestamp() - 60,) * 2)
    elif fault == 'missing_resource': resource_path.unlink()
    elif fault == 'oversized_resource': resource_path.write_bytes(b'x' * (1024 * 1024 + 1))
    store = AlertStore(tmp_path / 'alerts')
    assert watch.backup_check(store, tmp_path, row)['status'] == 'FAILED'
    assert store.read()['incidents']['drive-backup']['active']


def test_calendar_retry_independent_of_previous_failed_service():
    timer = (Path(__file__).parents[1] / 'deploy/pi/ar-local-issue-watchdog.timer').read_text()
    assert 'OnCalendar=*-*-* *:00/5:00' in timer and 'Persistent=true' in timer
    assert 'OnUnitActiveSec' not in timer


def test_queued_delivery_still_reports_unsuccessful_transport(tmp_path, monkeypatch, capsys):
    import pi_drive_access_probe
    monkeypatch.setattr(watch, 'configured_store', lambda: AlertStore(tmp_path))
    monkeypatch.setattr(watch, 'ingest_checks', lambda *a: {'status': 'COMPLETE'})
    monkeypatch.setattr(watch, 'backup_check', lambda *a: {'status': 'RUNNING'})
    monkeypatch.setattr(pi_drive_access_probe, 'probe', lambda *a: {'status': 'PASS', 'category': 'OK'})
    monkeypatch.setattr(watch, 'deliver', lambda *_: {'result': 'QUEUED', 'category': 'GITHUB_REQUEST_TIMEOUT'})
    assert watch.main([]) == 1
    assert json.loads(capsys.readouterr().out)['delivery']['result'] == 'QUEUED'


@pytest.mark.parametrize('spool_kind', ['absent', 'invalid'])
def test_checks_only_never_opens_alert_store(tmp_path, monkeypatch, capsys, spool_kind):
    import pi_drive_access_probe
    spool = tmp_path / 'absent-alert-spool'
    monkeypatch.setenv('AR_LOCAL_ALERT_SPOOL', str(spool) if spool_kind == 'absent' else 'relative/invalid')
    monkeypatch.setattr(watch, 'ingest_checks', lambda *a: {'status': 'COMPLETE'})
    monkeypatch.setattr(watch, 'backup_check', lambda *a: {'status': 'NO_CURRENT_VERIFIED_RECOVERY'})
    monkeypatch.setattr(pi_drive_access_probe, 'probe', lambda *a: {'status': 'PASS', 'category': 'OK'})
    monkeypatch.setattr(watch, 'deliver', lambda *_: pytest.fail('read-only delivered an issue'))
    assert watch.main(['--checks-only']) == 0
    assert json.loads(capsys.readouterr().out)['delivery']['result'] == 'NOT_REQUESTED'
    assert not spool.exists()


@pytest.mark.parametrize('timestamp,expected', [
    ('Sun 2026-09-13 06:00:00 UTC', NOW),
    ('Sun 2026-09-13 06:00:00.123456 UTC', NOW.replace(microsecond=123456)),
    ('', None), ('n/a', None), ('unexpected timestamp', None),
])
def test_failure_trigger_survives_unknown_start_timestamp(tmp_path, monkeypatch, timestamp, expected):
    from types import SimpleNamespace
    output = ('LoadState=loaded\nActiveState=failed\nResult=exit-code\nExecMainPID=123\n'
              'ExecMainStatus=2\nExecMainStartTimestamp=' + timestamp + '\n')
    monkeypatch.setattr(watch.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=output))
    monkeypatch.setenv('AR_LOCAL_DRIVE_BACKUP_SPOOL', str(tmp_path / 'missing-backup-spool'))
    assert watch.unit_state('ar-local-drive-backup.service')['started_at'] == expected
    store = AlertStore(tmp_path / 'alerts')
    result = watch.failure_event(store, 'ar-local-drive-backup.service', NOW)
    assert result['status'] == 'FAILURE_EVENT_RECORDED'
    assert store.read()['incidents']['drive-backup']['active']


def test_failure_template_loads_same_backup_locations_as_watchdog():
    root = Path(__file__).parents[1] / 'deploy/pi'
    expected = ['EnvironmentFile=-/etc/ar-local/app-payload.env',
                'EnvironmentFile=-/etc/ar-local/drive-backup.env',
                'EnvironmentFile=-/etc/ar-local/issue-alerts.env']
    for name in ('ar-local-issue-watchdog.service', 'ar-local-issue-failure@.service'):
        actual = [line for line in (root / name).read_text().splitlines() if line.startswith('EnvironmentFile=')]
        assert actual == expected
