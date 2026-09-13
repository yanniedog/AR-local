from datetime import datetime, timedelta, timezone
from pathlib import Path
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
