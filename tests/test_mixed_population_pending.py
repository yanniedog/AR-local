"""Mixed pending queues preserve source identity, upload state and retry budgets."""
import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import pi_daily_sync as sync
import pi_daily_watchdog as watchdog
from cdr_atomic import atomic_write_json
from cdr_population_pending import population_queue
from cdr_population_recovery import population_pending_recovery_allowed
from pi_daily_repair_work import repair
from pi_payload_retry_policy import publication_source_key
from tests.test_population_publication_lifecycle import runtime
from tests.test_pi_recovery_publication_priority import pointer
from tests.test_pi_same_day_recovery import DATE, NOW


def historical(day):
    value = pointer(day)
    value['ledger_event_digest'] = hashlib.sha256(day.encode()).hexdigest()
    return value


def mix(previous, current, position=1):
    rows = [historical('2026-09-03'), historical('2026-09-05')]
    rows.insert(position, current)
    return {**previous, 'pointer': rows[0], 'run_date': rows[0]['observation_date'],
            'queued_pointers': rows[1:]}


@pytest.mark.parametrize('position', [0, 1, 2])
@pytest.mark.parametrize('outcome', ['published', 'failed', 'withheld', 'interrupted'])
@pytest.mark.parametrize('already_queued', [False, True])
def test_mixed_successor_keeps_history_and_never_claims_upload(tmp_path, monkeypatch, position, outcome, already_queued):
    state, previous, old, new = runtime(tmp_path, monkeypatch, replacement_held=outcome == 'withheld')
    previous = mix(previous, old['pointer'], position)
    if already_queued:
        previous['queued_pointers'].append(new['pointer'])
    atomic_write_json(sync.payload_publication_pending_path(tmp_path), previous)
    ledger = {p: p.read_bytes() for p in (state/'ledger-v2').rglob('*.json')}
    history = [p for p in [previous['pointer'], *previous['queued_pointers']]
               if p not in (old['pointer'], new['pointer'])]
    sync.mark_payload_publication_pending(tmp_path, 'selected_population_recovery', new['pointer'], allow_policy_supersession=True)
    pending = sync.read_payload_publication_pending(tmp_path)
    expected = [new['pointer'] if p == old['pointer'] else p
                for p in [previous['pointer'], *previous['queued_pointers']] if p != new['pointer']]
    assert [pending['pointer'], *pending['queued_pointers']] == expected
    assert pending['run_date'] == expected[0]['observation_date']
    receipt_path = state/pending['policy_supersession_receipt']
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt['previous_pending'] == previous and receipt['publication_confirmed'] is False
    before = sync.payload_publication_pending_path(tmp_path).read_bytes()
    sync.mark_payload_publication_pending(tmp_path, 'retry', new['pointer'], allow_policy_supersession=True)
    assert sync.payload_publication_pending_path(tmp_path).read_bytes() == before
    def publish(repo, target):
        assert target == new['pointer']
        if outcome == 'interrupted':
            raise KeyboardInterrupt
        return outcome
    monkeypatch.setattr(sync, 'maybe_publish_app_payload', publish)
    args = ['--publish-existing-payload', '--publication-source-key', publication_source_key({'pointer': new['pointer']})]
    if outcome == 'interrupted':
        with pytest.raises(KeyboardInterrupt):
            sync.main(args)
    else:
        assert sync.main(args) == 0
    remaining = sync.read_payload_publication_pending(tmp_path)
    assert [remaining['pointer'], *remaining['queued_pointers']] == (history if outcome == 'published' else expected)
    assert remaining['run_date'] == remaining['pointer']['observation_date']
    assert all(p.read_bytes() == raw for p, raw in ledger.items())
    assert len(list((state/'population-publication-supersessions-v1').glob('*.json'))) == 1


@pytest.mark.parametrize('fault', ['duplicate_current', 'duplicate_old_identity', 'other_current', 'future',
                                  'malformed', 'unhashable_state', 'selection_retry', 'head_date', 'not_selected'])
def test_ambiguous_mixed_sources_refuse_recovery_and_supersession(tmp_path, monkeypatch, fault):
    state, previous, old, new = runtime(tmp_path, monkeypatch)
    previous = mix(previous, old['pointer'])
    if fault == 'duplicate_current':
        previous['queued_pointers'].append(dict(old['pointer'], extra='same source'))
    elif fault == 'duplicate_old_identity':
        previous['queued_pointers'].append(dict(previous['pointer'], extra='same source'))
    elif fault == 'other_current':
        previous['queued_pointers'].append(dict(old['pointer'], generation_id='obs-'+DATE+'-'+'c'*16, ledger_event_digest='d'*64))
    elif fault == 'future':
        previous['queued_pointers'].append(historical('2026-09-08'))
    elif fault == 'malformed':
        previous['queued_pointers'].append({})
    elif fault == 'unhashable_state':
        previous['pointer']['observation_state'] = []
    elif fault == 'selection_retry':
        previous['selection_retry'] = {}
    elif fault == 'head_date':
        previous['run_date'] = DATE
    else:
        old = copy.deepcopy(old);old['pointer']['generation_id'] = 'different'
    assert not population_pending_recovery_allowed(previous, old)
    if fault != 'not_selected':
        atomic_write_json(sync.payload_publication_pending_path(tmp_path), previous)
        sync.mark_payload_publication_pending(tmp_path, 'new', new['pointer'], allow_policy_supersession=True)
        assert sync.pending_publication_pointer(tmp_path) == previous['pointer']
        assert not (state/'population-publication-supersessions-v1').exists()


def test_daily_mixed_hold_uses_original_recovery_budget_then_targets_only_successor(tmp_path, monkeypatch):
    state, previous, old, new = runtime(tmp_path, monkeypatch)
    previous = mix(previous, old['pointer'])
    import pi_population_publication
    monkeypatch.setattr(pi_population_publication, 'reconcile_selected_population_pending', lambda *a: False)
    worker = SimpleNamespace(REPO_ROOT=tmp_path, run_payload_retry=Mock(), run_recovery_ingest=Mock())
    recovery = Mock();recovery.recovery_block_reason.return_value = '';recovery.selected_observation.return_value = old
    before = copy.deepcopy(previous)
    repair(worker, recovery, DATE, NOW, read_pending=lambda _: previous, execution_deadline=1100)
    recovery.run_same_day_recovery.assert_called_once_with(tmp_path, now_utc=NOW, dry_run=False,
        launch=worker.run_recovery_ingest, daily_pass=True, execution_deadline=1100)
    worker.run_payload_retry.assert_not_called();assert previous == before
    pending = mix(previous, new['pointer'])
    recovery.selected_observation.return_value = new;recovery.run_same_day_recovery.reset_mock()
    repair(worker, recovery, DATE, NOW, read_pending=lambda _: pending)
    worker.run_payload_retry.assert_called_once_with(False, source_key=publication_source_key({'pointer': new['pointer']}))
    recovery.run_same_day_recovery.assert_not_called()


@pytest.mark.parametrize('condition', ['cooldown', 'absent', 'ready'])
def test_targeted_retry_never_falls_back_to_historical_source(monkeypatch, condition):
    old, current = historical('2026-09-03'), historical(DATE)
    pending = {'pointer': old, 'run_date': old['observation_date'], 'queued_pointers': [] if condition == 'absent' else [current]}
    key = publication_source_key({'pointer': current})
    monkeypatch.setattr(watchdog, '_app_payload_enabled', lambda: True)
    monkeypatch.setattr(watchdog, 'read_payload_publication_pending', lambda _: pending)
    admission = Mock(return_value={'status': 'ready', 'source_key': key} if condition == 'ready'
                     else {'status': 'deferred', 'reason': 'publication_retry_cooldown'})
    monkeypatch.setattr(watchdog, 'retry_admission', admission)
    launch = Mock();monkeypatch.setattr(watchdog, 'run_ingest_process_group', launch)
    monkeypatch.setattr(watchdog, 'payload_publication_pending', lambda _: True)
    finish = Mock();monkeypatch.setattr(watchdog, 'finish_retry', finish)
    result = watchdog.run_payload_retry(False, source_key=key)
    assert admission.call_count == int(condition != 'absent')
    if admission.called:
        assert admission.call_args.args[1]['pointer'] == current
    if condition == 'ready':
        assert launch.call_args.args[0][-2:] == ['--publication-source-key', key]
        assert result['status'] == 'failed'  # Mock launch did not settle the actual source.
        assert finish.call_args.kwargs['succeeded'] is False
    else:
        launch.assert_not_called();finish.assert_not_called()
        assert result['status'] == 'deferred'


def test_mixed_hold_reaches_guarded_probe_without_settling_queue_or_claiming_success(tmp_path, monkeypatch):
    import pi_cdr_recovery as recovery
    from tests.test_cdr_population_recovery import bound_population
    from tests.test_pi_same_day_recovery import stage, PROVIDER
    state, observation = stage(monkeypatch, tmp_path)
    bound_population(tmp_path, observation)
    observation['pointer'] = {'schema_version': 2, 'observation_date': DATE, 'generation_id': 'g1'}
    observation['contract']['coverage'] = {'provider_population_unverified': [{
        'provider': PROVIDER['provider_dir'], 'provider_uid': PROVIDER['provider_uid'],
        'population_known': False, 'disposition': 'UNVERIFIED_SOURCE_ABSENCE'}]}
    observation['status']['index_diagnostics'][PROVIDER['provider_dir']]['pagination_complete'] = False
    observation['status']['unresolved_requests'] = [{'provider_dir': PROVIDER['provider_dir'],
        'phase': 'products_index', 'product_id': '', 'url': PROVIDER['endpoint_url'],
        'status': 422, 'failure_category': 'upstream_rejection'}]
    pending = mix({}, observation['pointer'])
    monkeypatch.setattr(sync, 'data_state_root', lambda _: state)
    atomic_write_json(sync.payload_publication_pending_path(tmp_path), pending)
    before = sync.payload_publication_pending_path(tmp_path).read_bytes()
    seen = []
    def probe(root, selected, providers, requests, *args, **kwargs):
        seen.extend(requests)
        return [], [{'ok': False, 'failure_category': 'upstream_rejection'}]
    monkeypatch.setattr(recovery, '_probe_due', probe)
    launch = Mock()
    result = recovery.run_same_day_recovery(tmp_path, now_utc=NOW, dry_run=False, launch=launch)
    assert result['status'] == 'upstream_gaps_remain'
    assert seen and any(row.get('requires_nonempty_population') is True for row in seen)
    launch.assert_not_called()
    assert sync.payload_publication_pending_path(tmp_path).read_bytes() == before


def test_mixed_receipt_crash_preserves_pending_and_retries_idempotently(tmp_path, monkeypatch):
    import pi_population_publication as policy
    state, previous, old, new = runtime(tmp_path, monkeypatch)
    previous = mix(previous, old['pointer'])
    atomic_write_json(sync.payload_publication_pending_path(tmp_path), previous)
    before = sync.payload_publication_pending_path(tmp_path).read_bytes()
    write = policy.atomic_write_json
    def interrupted(*args, **kwargs):
        write(*args, **kwargs)
        raise OSError('after receipt')
    with monkeypatch.context() as fault:
        fault.setattr(policy, 'atomic_write_json', interrupted)
        with pytest.raises(OSError, match='after receipt'):
            sync.mark_payload_publication_pending(tmp_path, 'recovered', new['pointer'], allow_policy_supersession=True)
    assert sync.payload_publication_pending_path(tmp_path).read_bytes() == before
    sync.mark_payload_publication_pending(tmp_path, 'recovered', new['pointer'], allow_policy_supersession=True)
    after = sync.read_payload_publication_pending(tmp_path)
    assert after['pointer'] == previous['pointer']
    assert after['queued_pointers'] == [new['pointer'], previous['queued_pointers'][1]]
    assert len(list((state/'population-publication-supersessions-v1').glob('*.json'))) == 1
