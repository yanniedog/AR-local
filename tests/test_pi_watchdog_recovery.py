"""Retained timeout -> later success, with capture kept independently partial."""
from datetime import datetime, timedelta, timezone

import pytest

import pi_github_alerts as alerts
import pi_issue_watchdog as watch

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
FAILED = datetime(2026, 10, 15, 5, 56, 56, tzinfo=timezone.utc)
KEY = "ingest-watchdog:2026-10-15"


def failed_store(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts, "utc", lambda: FAILED.isoformat())
    store = alerts.AlertStore(tmp_path)
    store.observe(KEY, "Pi ingest watchdog failed: 2026-10-15", "INGEST_WATCHDOG_FAILED", healthy=False)
    state = store.read()
    state['incidents'][KEY].update(issue_number=936, delivered_revision=1)
    store.write(state)
    monkeypatch.setattr(alerts, "utc", lambda: NOW.isoformat())
    return store


def successful_units():
    rows = {unit: {'started_at': watch.latest_daily_due_utc(NOW), 'ActiveState': 'inactive'}
            for unit in watch.UNITS[:3]}
    rows[watch.UNITS[2]] = {'ActiveState': 'inactive', 'Result': 'success',
        'ExecMainStatus': '0', 'ExecMainPID': '3948723',
        'started_at': datetime(2026, 10, 15, 6, 11, 57, tzinfo=timezone.utc),
        'finished_at': datetime(2026, 10, 15, 6, 12, 36, tzinfo=timezone.utc)}
    return rows


def test_later_success_recovers_same_watchdog_issue_but_keeps_partial_capture(tmp_path, monkeypatch):
    store = failed_store(tmp_path, monkeypatch)
    monkeypatch.setattr(watch, 'completion', lambda *_: 'PARTIAL')
    assert watch.ingest_checks(store, tmp_path, NOW, successful_units())['status'] == 'PARTIAL'
    rows = store.read()['incidents']
    row = rows[KEY]
    assert row['active'] is False and row['issue_number'] == 936
    assert row['revision'] == 2 and row['delivered_revision'] == 1
    assert row['last_failure_at'] == FAILED.isoformat()
    assert row['recovered_at'] == NOW.isoformat()
    assert rows['ingest:2026-10-15']['active'] is True
    before = store.path.read_bytes()
    watch.ingest_checks(store, tmp_path, NOW, successful_units())
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('fault', ['running', 'failed', 'nonzero', 'no_pid', 'bad_pid',
    'missing_start', 'missing_finish', 'naive_start', 'naive_finish', 'old_day',
    'future_finish', 'reverse_times', 'pre_failure_success'])
def test_uncertain_or_older_run_cannot_recover(tmp_path, monkeypatch, fault):
    store = failed_store(tmp_path, monkeypatch)
    row = successful_units()[watch.UNITS[2]]
    if fault == 'running': row['ActiveState'] = 'activating'
    elif fault == 'failed': row['Result'] = 'timeout'
    elif fault == 'nonzero': row['ExecMainStatus'] = '1'
    elif fault == 'no_pid': row['ExecMainPID'] = '0'
    elif fault == 'bad_pid': row['ExecMainPID'] = 'unknown'
    elif fault == 'missing_start': row.pop('started_at')
    elif fault == 'missing_finish': row.pop('finished_at')
    elif fault == 'naive_start': row['started_at'] = row['started_at'].replace(tzinfo=None)
    elif fault == 'naive_finish': row['finished_at'] = row['finished_at'].replace(tzinfo=None)
    elif fault == 'old_day': row['started_at'] -= timedelta(days=1); row['finished_at'] -= timedelta(days=1)
    elif fault == 'future_finish': row['finished_at'] = NOW + timedelta(seconds=1)
    elif fault == 'reverse_times': row['finished_at'] = row['started_at'] - timedelta(seconds=1)
    else: row['started_at'] = FAILED - timedelta(minutes=5); row['finished_at'] = FAILED - timedelta(minutes=4)
    before = store.path.read_bytes()
    watch.watchdog_recovery(store, row, watch.latest_daily_due_utc(NOW), NOW)
    assert store.path.read_bytes() == before


def test_repeated_failure_advances_atomic_fence_without_duplicate_delivery(tmp_path, monkeypatch):
    store = failed_store(tmp_path, monkeypatch)
    later_failure = NOW - timedelta(minutes=1)
    monkeypatch.setattr(alerts, 'utc', lambda: later_failure.isoformat())
    monkeypatch.setattr(watch, 'unit_state', lambda _: successful_units()[watch.UNITS[2]])
    watch.failure_event(store, watch.UNITS[2], NOW)
    row = store.read()['incidents'][KEY]
    assert row['revision'] == row['delivered_revision'] == 1
    assert row['last_failure_at'] == later_failure.isoformat()
    watch.watchdog_recovery(store, successful_units()[watch.UNITS[2]], watch.latest_daily_due_utc(NOW), NOW)
    assert store.read()['incidents'][KEY]['active'] is True


def test_success_does_not_create_incident_or_resolve_historical_date(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts, 'utc', lambda: FAILED.isoformat())
    store = alerts.AlertStore(tmp_path)
    old_key = 'ingest-watchdog:2026-10-14'
    store.observe(old_key, 'Pi ingest watchdog failed: 2026-10-14', 'INGEST_WATCHDOG_FAILED', healthy=False)
    before = store.path.read_bytes()
    watch.watchdog_recovery(store, successful_units()[watch.UNITS[2]], watch.latest_daily_due_utc(NOW), NOW)
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('bad', ['unknown', '2026-10-15T05:56:56', None])
def test_unknown_failure_time_keeps_alert_open(tmp_path, monkeypatch, bad):
    store = failed_store(tmp_path, monkeypatch)
    state = store.read(); state['incidents'][KEY]['last_failure_at'] = bad; store.write(state)
    before = store.path.read_bytes()
    watch.watchdog_recovery(store, successful_units()[watch.UNITS[2]], watch.latest_daily_due_utc(NOW), NOW)
    assert store.path.read_bytes() == before


def test_exit_timestamp_is_parsed_from_actual_unit_readback(monkeypatch):
    from types import SimpleNamespace
    output = ('LoadState=loaded\nActiveState=inactive\nResult=success\nExecMainPID=3948723\n'
              'ExecMainStatus=0\nExecMainStartTimestamp=Thu 2026-10-15 06:11:57 UTC\n'
              'ExecMainExitTimestamp=Thu 2026-10-15 06:12:36 UTC\n')
    monkeypatch.setattr(watch.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=output))
    row = watch.unit_state(watch.UNITS[2])
    assert row['finished_at'] == successful_units()[watch.UNITS[2]]['finished_at']
