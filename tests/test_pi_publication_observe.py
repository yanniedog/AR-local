"""A hung publication read must yield UNKNOWN before systemd kills the observer."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pi_ingest_observe import observe, observation_failed
import pi_publication_observe as check

DAY = '2026-10-15'


def current():
    return {'publication_current': True, 'manifest_run_date': DAY,
            'dates_index_latest_date': DAY, 'manifest_error': None,
            'dates_index_error': None, 'publication_issues': []}


def test_hung_network_check_returns_unknown_and_keeps_capture_evidence():
    def run(command, **kwargs):
        assert command[-2:] == ['--check', DAY]
        assert kwargs['timeout'] == 35
        assert kwargs['stderr'] == subprocess.DEVNULL
        assert kwargs['check'] is False
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    watch = SimpleNamespace(REPO_ROOT=Path('/readonly'), service_active=lambda: False,
        payload_publication_pending=lambda _: False)
    result = observe(watch, datetime(2026, 10, 15, 12, tzinfo=timezone.utc),
        lambda _: {'generation_id': 'retained'},
        publication_check=lambda day: check.bounded_publication_check(day, run=run))
    assert result['capture_finalized'] is True
    assert result['repair_started'] is False
    assert result['publication']['status'] == 'UNKNOWN'
    assert result['publication']['error_category'] == 'PublicationCheckTimeout'
    assert observation_failed(result)
    service = (Path(__file__).parents[1]/'deploy/pi/ar-local-daily-watchdog-observe.conf').read_text()
    assert 'TimeoutStartSec=60s' in service  # No service budget expansion.


def test_successful_and_stale_results_survive_the_boundary():
    for value in [current(), {**current(), 'publication_current': False,
                              'publication_issues': ['manifest_stale']}]:
        run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(value).encode()))
        assert check.bounded_publication_check(DAY, run=run) == value
        assert run.call_count == 1


def test_current_publication_preserves_real_historical_gap_diagnostics():
    from pi_payload_freshness import check_publication
    from tests.test_pi_payload_freshness import documents

    def fetch(url):
        if 'dates-index' in url:
            return {'schema_version': 1, 'dates': ['2026-10-12', DAY],
                    'latest_date': DAY, 'count': 2}
        return documents(DAY, DAY)(url)

    value = check_publication(DAY, fetch=fetch)
    assert value['publication_current'] is True
    assert value['publication_continuous'] is False
    assert value['publication_healthy'] is False
    assert value['missing_dates'] == ['2026-10-13', '2026-10-14']
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(value).encode()))
    bounded = check.bounded_publication_check(DAY, run=run)
    assert bounded == value
    assert not observation_failed({'publication_due': True, 'publication': bounded})
    run.assert_called_once()


@pytest.mark.parametrize('fault', ['exit', 'oversize', 'invalid_json', 'array', 'missing_flag',
    'not_bool', 'wrong_manifest_day', 'wrong_index_day', 'manifest_error', 'index_error', 'issues',
    'contradictory_continuity', 'mixed_historical_and_current_issues'])
def test_invalid_or_contradictory_child_cannot_report_recovery(fault):
    value = current(); code = 0
    if fault == 'exit': code = 1
    elif fault == 'array': value = []
    elif fault == 'missing_flag': value.pop('publication_current')
    elif fault == 'not_bool': value['publication_current'] = 1
    elif fault == 'wrong_manifest_day': value['manifest_run_date'] = '2026-10-14'
    elif fault == 'wrong_index_day': value['dates_index_latest_date'] = '2026-10-14'
    elif fault == 'manifest_error': value['manifest_error'] = 'TimeoutError'
    elif fault == 'index_error': value['dates_index_error'] = 'TimeoutError'
    elif fault == 'issues': value['publication_issues'] = ['manifest_stale']
    elif fault == 'contradictory_continuity':
        value.update(publication_issues=['dates_index_calendar_gaps'], publication_continuous=True)
    elif fault == 'mixed_historical_and_current_issues':
        value.update(publication_issues=['dates_index_calendar_gaps', 'manifest_stale'],
                     publication_continuous=False)
    raw = json.dumps(value).encode()
    if fault == 'oversize': raw = b'x' * (check.MAX_RESULT_BYTES+1)
    elif fault == 'invalid_json': raw = b'{broken'
    result = check.bounded_publication_check(DAY,
        run=lambda *a, **kw: SimpleNamespace(returncode=code, stdout=raw))
    assert result['status'] == 'UNKNOWN' and result['publication_current'] is False


def test_failure_has_one_attempt_and_no_private_error_text():
    run = Mock(side_effect=OSError('private endpoint or credential text'))
    result = check.bounded_publication_check(DAY, run=run)
    assert run.call_count == 1
    assert 'private' not in json.dumps(result)


def test_real_stalled_child_is_killed_and_reaped_before_result(monkeypatch):
    original_run = subprocess.run
    monkeypatch.setattr(check, 'CHECK_SECONDS', 0.2)
    def stalled_child(command, **kwargs):
        return original_run([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
    started = time.monotonic()
    result = check.bounded_publication_check(DAY, run=stalled_child)
    assert result['error_category'] == 'PublicationCheckTimeout'
    assert time.monotonic()-started < 3


@pytest.mark.parametrize('day', ['2026-2-01', 'bad', '2026-02-30'])
def test_invalid_dates_never_start_worker(day):
    run = Mock()
    assert check.bounded_publication_check(day, run=run)['status'] == 'UNKNOWN'
    run.assert_not_called()
