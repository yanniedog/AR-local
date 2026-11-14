"""Recovery scheduling controls; retained DDH error, no synthetic financial rows."""
import json
from pathlib import Path

import pytest

import cdr_ingest_lib as ingest
import cdr_ingest_support as support
from cdr_ingest_recovery import recover_transient_providers

BODY = (Path(__file__).parent / 'fixtures/cdr-index-failures-20261012/ddh-index-error.json').read_text()


def setup_failures(root, names):
    rows = [{'bank': name, 'phase': 'products_index', 'status': 504, 'retryable': True}
            for name in names]
    (root / 'failures.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return [({'endpoint_url': f'https://{position}.example/cds-au/v1/banking/products'}, name)
            for position, name in enumerate(names)]


def test_slow_providers_leave_actual_ingest_deadline_time_for_later_holder(tmp_path, monkeypatch):
    names = ['Cairns bank', 'Thriday', 'DDH Graham']
    work = setup_failures(tmp_path, names)
    clock = [0.0]
    calls, entered = [], []
    def sleep(seconds): clock[0] += seconds
    def http(url, headers, *, timeout):
        calls.append((url, clock[0], timeout, headers['x-v']))
        if '2.example' in url:
            return 401, BODY, None
        clock[0] += timeout
        return 504, '', None
    monkeypatch.setattr(support.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(support.time, 'sleep', sleep)
    monkeypatch.setattr(support, 'http_request', http)
    def run_one(item, *, recovery_deadline):
        entered.append((item[1], clock[0], recovery_deadline))
        # The production recovery callback uses these same sequential/resume
        # parameters and passes its deadline through to ingest_brand/fetch.
        ingest.ingest_brand(item[0], date_root=tmp_path, resume=True, sleep_ms=0,
            timeout=30, max_retries=1, max_pages=None, max_products=None,
            fetch_unknown_detail=False, bank_dir_name=item[1], detail_workers=1,
            log=lambda _: None, deadline=recovery_deadline)
    result = recover_transient_providers(tmp_path, work, run_one, log=lambda _: None,
        clock=lambda: clock[0], sleep=sleep)
    assert result['result'] == 'completed' and result['attempted'] == names
    assert result['eligible_providers'] == sorted(names) and result['unattempted'] == []
    assert clock[0] <= 180 and entered[0][2] < entered[1][2] < entered[2][2] == 180
    assert [row[1] for row in entered][1:] == pytest.approx([entered[0][2], entered[1][2]])
    assert any('2.example' in call[0] for call in calls)
    rows = [json.loads(line) for line in (tmp_path / 'failures.jsonl').read_text().splitlines()]
    assert result['remaining_failures'] == len(rows) == 3
    assert all(row['status'] == 504 for row in rows if row['bank'] != 'DDH Graham')
    assert next(row for row in rows if row['bank'] == 'DDH Graham')['failure_category'] == 'upstream_dependency_failure'
    assert all(row['phase'] == 'products_index' for row in rows)  # No worker_crash or swallowed exception.


def test_unused_share_redistributes_without_extending_global_deadline(tmp_path):
    work = setup_failures(tmp_path, ['Arab', 'Cairns', 'DDH', 'Thriday'])
    clock = [0.0]
    deadlines = []
    def run(item, *, recovery_deadline):
        deadlines.append(recovery_deadline)
        clock[0] += 10 if len(deadlines) == 1 else recovery_deadline - clock[0]
    result = recover_transient_providers(tmp_path, work, run, log=lambda _: None,
        clock=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert deadlines == pytest.approx([48.75, 70, 125, 180])
    assert result['result'] == 'completed' and len(result['attempted']) == 4
    assert result['remaining_failures'] == 4  # Scheduler progress is not successful capture.


def test_all_eligible_providers_and_unattempted_cap_reasons_are_recorded(tmp_path):
    names = [f'provider-{n:02}' for n in range(14)]
    work = setup_failures(tmp_path, names)
    result = recover_transient_providers(tmp_path, work[:-1], lambda *a, **k: None,
        log=lambda _: None, clock=lambda: 0, sleep=lambda _: None)
    assert result['eligible_providers'] == names and len(result['attempted']) == 12
    assert result['unattempted'] == [
        {'provider': names[12], 'reason': 'provider_limit'},
        {'provider': names[13], 'reason': 'provider_not_scheduled'}]


def test_disabled_recovery_discloses_unattempted_without_rewriting_evidence(tmp_path):
    work = setup_failures(tmp_path, ['DDH'])
    original = (tmp_path / 'failures.jsonl').read_bytes()
    def forbidden(*args, **kwargs): pytest.fail('disabled recovery must not run')
    result = recover_transient_providers(tmp_path, work, forbidden, log=forbidden, budget_seconds=0)
    assert result['result'] == 'not_needed' and result['eligible_providers'] == ['DDH']
    assert result['unattempted'] == [{'provider': 'DDH', 'reason': 'recovery_disabled'}]
    assert (tmp_path / 'failures.jsonl').read_bytes() == original


def test_global_deadline_overrun_is_reported_without_starting_later_provider(tmp_path):
    work = setup_failures(tmp_path, ['Cairns', 'DDH'])
    clock = [0]
    def late_callback(*args, **kwargs): clock[0] = 181
    result = recover_transient_providers(tmp_path, work, late_callback, log=lambda _: None,
        clock=lambda: clock[0], sleep=lambda _: None)
    assert result['result'] == 'budget_exhausted' and result['attempted'] == ['Cairns']
    assert result['unattempted'] == [{'provider': 'DDH', 'reason': 'budget_exhausted'}]


def test_attributed_worker_crash_remains_failed_without_blocking_unrelated_provider(tmp_path):
    work = setup_failures(tmp_path, ['Cairns', 'DDH'])
    def run(item, **kwargs):
        if item[1] == 'Cairns':
            # Production run_one catches a holder exception and records its
            # attribution. This is failure evidence, not a corrupt journal.
            support.append_failure(tmp_path, {'phase': 'holder', 'bank': 'Cairns',
                'status': 'worker_crash', 'error': 'retained transport control'})
    result = recover_transient_providers(tmp_path, work, run, log=lambda _: None,
        clock=lambda: 0, sleep=lambda _: None)
    assert result['result'] == 'completed' and result['attempted'] == ['Cairns', 'DDH']
    rows = [json.loads(line) for line in (tmp_path / 'failures.jsonl').read_text().splitlines()]
    assert result['remaining_failures'] == len(rows) == 3
    assert {row['status'] for row in rows if row['bank'] == 'Cairns'} == {504, 'worker_crash'}


@pytest.mark.parametrize('failure', ['crash', 'corrupt', 'foreign'])
def test_fair_shares_do_not_continue_after_ambiguous_journal(tmp_path, failure):
    work = setup_failures(tmp_path, ['Cairns', 'DDH'])
    def run(item, **kwargs):
        if failure == 'crash': raise RuntimeError('interrupted')
        with (tmp_path / 'failures.jsonl').open('a') as stream:
            stream.write('{invalid' if failure == 'corrupt' else json.dumps({'bank': 'other'}))
    result = recover_transient_providers(tmp_path, work, run, log=lambda _: None,
        clock=lambda: 0, sleep=lambda _: None)
    assert result['attempted'] == ['Cairns']
    assert result['result'] == ('invalid_failure_evidence' if failure == 'corrupt' else 'recovery_error')
    assert result['unattempted'] == [{'provider': 'DDH', 'reason': result['result']}]
