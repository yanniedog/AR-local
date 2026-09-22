"""Publication boundary controls, not acceptance business observations."""
import json

import pytest

from cdr_compatibility import classify_fetch_failure
from cdr_finalization import finalize_observation
from tests.test_irreplaceable_finalization import make_export, DATE
from tests.test_app_payload_observation_gate import _load_backfill


def finalized(tmp_path, status='400', alternate=False):
    exports = tmp_path / ('observations' if alternate else 'runs') / DATE / '_exports'
    make_export(exports, failures=47)
    status_path = exports / 'ingest-status.json'
    data = json.loads(status_path.read_bytes())
    data['by_status'] = {status: 47}
    data['by_provider_failure_category'] = {'provider-a': {'upstream_rejection': 47}}
    data['provider_states'][0]['failure_categories'] = {'upstream_rejection': 47}
    status_path.write_text(json.dumps(data), encoding='utf8')
    state = tmp_path / 'state'
    marker = finalize_observation(exports, state, state / f'{DATE}.done.json',
        observation_date=DATE, result={'run_date': DATE, 'banks_counts': {'rates': 7}})
    return exports, state, marker


@pytest.mark.parametrize('status', ['worker_crash', 'unknown', None, -1, 0, 999, True])
def test_internal_and_unknown_failures_are_not_upstream(status):
    assert classify_fetch_failure(status).category == 'unknown_internal'


@pytest.mark.parametrize('fault', ['artifact', 'missing_marker', 'marker_identity', 'source_path', 'internal_status'])
@pytest.mark.parametrize('force', [False, True])
def test_backfill_rejects_unverified_reconciled_contract(tmp_path, fault, force):
    exports, state, marker = finalized(tmp_path,
        status='worker_crash' if fault == 'internal_status' else '400', alternate=fault == 'source_path')
    if fault == 'artifact':
        (exports / 'banks.json').write_text('{"modified":true}', encoding='utf8')
    elif fault == 'missing_marker':
        (state / f'{DATE}.done.json').unlink()
    elif fault == 'marker_identity':
        marker['generation_id'] = 'wrong'
        (state / f'{DATE}.done.json').write_text(json.dumps(marker), encoding='utf8')
    allowed, _, _ = _load_backfill().observation_gate(state, DATE, force=force)
    assert not allowed


def test_backfill_admits_original_ledger_bound_http_failure(tmp_path):
    _, state, _ = finalized(tmp_path)
    assert _load_backfill().observation_gate(state, DATE, force=False)[:2] == (True, 'reconciled_partial')


@pytest.mark.parametrize('entry', ['backfill', 'refresh_rolling_latest'])
def test_unverified_sources_never_reach_builder_or_publisher(tmp_path, monkeypatch, entry):
    exports, state, _ = finalized(tmp_path, status='worker_crash')
    module = _load_backfill()
    monkeypatch.setattr(module, 'iter_valid_export_dates', lambda *a, **k: [(DATE, exports)])
    def forbidden(*args, **kwargs):
        pytest.fail('Unverified source reached payload builder or publisher')
    monkeypatch.setattr(module.app_payload, 'build_payload', forbidden)
    monkeypatch.setattr(module.app_payload, 'publish_payload', forbidden)
    result = getattr(module, entry)(tmp_path / 'runs', force=True)
    assert result is False if entry == 'refresh_rolling_latest' else result[0][0]['skipped']
    assert not (state / 'daily-ingest.lock').exists()


@pytest.mark.parametrize('entry', ['backfill', 'refresh_rolling_latest'])
def test_backfill_preserves_another_live_ingest_lock(tmp_path, entry):
    from ar_local_operation_lock import production_lock
    lock = tmp_path / 'state/daily-ingest.lock'
    with production_lock(lock, 'test-ingest-owner'):
        original = lock.read_bytes()
        with pytest.raises(RuntimeError, match='production lock is active'):
            getattr(_load_backfill(), entry)(tmp_path / 'runs')
        assert lock.read_bytes() == original


def test_daily_publication_rejects_old_fallback_classified_worker_crash(tmp_path, monkeypatch):
    import app_payload
    import pi_daily_sync
    _, state, _ = finalized(tmp_path, status='worker_crash')
    pointer = json.loads((state / 'observation-pointers-v2/latest-observation.json').read_bytes())
    monkeypatch.setenv('AR_LOCAL_APP_PAYLOAD', '1')
    monkeypatch.setattr(pi_daily_sync, 'data_state_root', lambda _: state)
    def forbidden(*args, **kwargs):
        pytest.fail('Daily builder reached an internally failed observation')
    monkeypatch.setattr(app_payload, 'build_and_publish_dual', forbidden)
    assert pi_daily_sync.maybe_publish_app_payload(tmp_path, pointer) == pi_daily_sync.PUBLISH_WITHHELD


def test_new_ingest_retains_internal_failure_category(tmp_path):
    from cdr_ingest_support import summarize_failures
    (tmp_path / 'failures.jsonl').write_text(json.dumps({
        'phase': 'product_detail', 'bank': 'provider-a', 'status': 'worker_crash'}) + '\n', encoding='utf8')
    summary = summarize_failures(tmp_path)
    assert summary['by_provider_failure_category'] == {'provider-a': {'unknown_internal': 1}}


def test_backfill_holds_one_lock_through_dated_and_rolling_builds(tmp_path, monkeypatch):
    from ar_local_operation_lock import production_lock
    exports, state, _ = finalized(tmp_path)
    module = _load_backfill()
    lock = state / 'daily-ingest.lock'
    phases = []
    monkeypatch.setattr(module, 'iter_valid_export_dates', lambda *a, **k: [(DATE, exports)])
    monkeypatch.setattr(module, 'dated_release_already_published', lambda *a: False)
    def build(*args, **kwargs):
        with pytest.raises(RuntimeError, match='production lock is active'):
            with production_lock(lock, 'concurrent-writer'):
                pytest.fail('Writer entered during publication')
        phases.append(kwargs['tag'])
        return {'files': {'core': {'name': 'protocol-core'}, 'details': {'name': 'protocol-details'}}}
    def publish(*args, **kwargs):
        assert lock.is_file()
        return True
    monkeypatch.setattr(module.app_payload, 'build_payload', build)
    monkeypatch.setattr(module.app_payload, 'publish_payload', publish)
    monkeypatch.setattr(module.app_payload, 'refresh_dates_index', lambda *a, **k: None)
    results, rolling = module.backfill(tmp_path / 'runs')
    assert results[0]['published'] and rolling
    assert phases == ['app-payload-' + DATE, 'app-payload-latest']
    assert not lock.exists()
