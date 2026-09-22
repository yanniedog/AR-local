"""Publication boundary controls, not acceptance business observations."""
import json

import pytest

from cdr_compatibility import classify_fetch_failure
from cdr_finalization import finalize_observation
from tests.test_irreplaceable_finalization import make_export, DATE
from tests.test_app_payload_observation_gate import _load_backfill


def finalized(tmp_path, status='400', alternate=False, *, bounded=False, revision=None):
    exports = tmp_path / ('observations' if alternate else 'runs') / DATE / '_exports'
    if revision:
        exports = tmp_path / 'runs' / DATE / '_revisions' / revision / '_exports'
    failures = 1 if bounded else 47
    make_export(exports, failures=failures)
    status_path = exports / 'ingest-status.json'
    data = json.loads(status_path.read_bytes())
    data['by_status'] = {status: failures}
    data['by_provider_failure_category'] = {'provider-a': {'upstream_rejection': failures}}
    data['provider_states'][0]['failure_categories'] = {'upstream_rejection': failures}
    if bounded:
        data['providers_registered'] = data['providers_attempted'] = 10
        data['provider_states'].extend({'provider_uid': f'provider-{i}', 'state': 'complete',
            'failure_records': 0} for i in range(9))
        cache = exports / 'dashboard-cache/latest.json'
        payload = json.loads(cache.read_bytes())
        payload['banks_counts']['products'] = 200
        cache.write_text(json.dumps(payload), encoding='utf8')
    status_path.write_text(json.dumps(data), encoding='utf8')
    state = tmp_path / 'state'
    marker = finalize_observation(exports, state, state / f'{DATE}{revision or ""}.done.json',
        observation_date=DATE, result={'run_date': DATE, 'banks_counts': {'rates': 7}})
    return exports, state, marker


@pytest.mark.parametrize('status', ['worker_crash', 'unknown', None, -1, 0, 999, True])
def test_internal_and_unknown_failures_are_not_upstream(status):
    assert classify_fetch_failure(status).category == 'unknown_internal'


@pytest.mark.parametrize('fault', ['artifact', 'missing_marker', 'marker_identity', 'unsafe_path', 'internal_status'])
@pytest.mark.parametrize('force', [False, True])
def test_backfill_rejects_unverified_reconciled_contract(tmp_path, fault, force):
    exports, state, marker = finalized(tmp_path,
        status='worker_crash' if fault == 'internal_status' else '400')
    if fault == 'artifact':
        (exports / 'banks.json').write_text('{"modified":true}', encoding='utf8')
    elif fault == 'missing_marker':
        (state / f'{DATE}.done.json').unlink()
    elif fault == 'marker_identity':
        marker['generation_id'] = 'wrong'
        (state / f'{DATE}.done.json').write_text(json.dumps(marker), encoding='utf8')
    elif fault == 'unsafe_path':
        path = state / 'observation-pointers-v2/latest-observation.json'
        pointer = json.loads(path.read_bytes())
        pointer['export_path'] = '../outside'
        path.write_text(json.dumps(pointer), encoding='utf8')
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


@pytest.mark.parametrize('force', [False, True])
def test_bounded_internal_failures_are_withheld_even_when_forced(tmp_path, force):
    _, state, _ = finalized(tmp_path, status='worker_crash', bounded=True)
    assert not _load_backfill().observation_gate(state, DATE, force=force)[0]


def test_daily_bounded_internal_failure_is_withheld(tmp_path, monkeypatch):
    import app_payload
    import pi_daily_sync
    _, state, _ = finalized(tmp_path, status='worker_crash', bounded=True)
    pointer = json.loads((state / 'observation-pointers-v2/latest-observation.json').read_bytes())
    monkeypatch.setenv('AR_LOCAL_APP_PAYLOAD', '1')
    monkeypatch.setattr(pi_daily_sync, 'data_state_root', lambda _: state)
    called = []
    monkeypatch.setattr(app_payload, 'build_and_publish_dual', lambda *a, **k: called.append(a))
    assert pi_daily_sync.maybe_publish_app_payload(tmp_path, pointer) == pi_daily_sync.PUBLISH_WITHHELD
    assert not called


def test_bounded_original_http_failure_is_admitted(tmp_path):
    _, state, _ = finalized(tmp_path, bounded=True)
    assert _load_backfill().observation_gate(state, DATE, force=False)[:2] == (True, 'bounded_partial')


@pytest.mark.parametrize('entry', ['backfill', 'refresh_rolling_latest'])
@pytest.mark.parametrize('later_bad_attempt', [False, True])
def test_repaired_selected_exports_reach_dated_and_rolling_builds(tmp_path, monkeypatch, entry, later_bad_attempt):
    base, state, _ = finalized(tmp_path)
    repaired, _, _ = finalized(tmp_path, bounded=True, revision='repaired')
    if later_bad_attempt:
        finalized(tmp_path, revision='failed-recovery')
    module = _load_backfill()
    monkeypatch.setattr(module, 'iter_valid_export_dates', lambda *a, **k: [(DATE, base)])
    monkeypatch.setattr(module, 'dated_release_already_published', lambda *a: False)
    built = []
    def build(exports, *args, **kwargs):
        built.append(exports)
        return {'files': {'core': {'name': 'core'}, 'details': {'name': 'details'}}}
    monkeypatch.setattr(module.app_payload, 'build_payload', build)
    monkeypatch.setattr(module.app_payload, 'publish_payload', lambda *a, **k: True)
    monkeypatch.setattr(module.app_payload, 'refresh_dates_index', lambda *a, **k: None)
    result = getattr(module, entry)(tmp_path / 'runs')
    assert result is True if entry == 'refresh_rolling_latest' else result[0][0]['published']
    assert built and all(path == repaired for path in built)


@pytest.mark.parametrize('fault', ['invalid_json', 'unsafe_path', 'wrong_type'])
def test_corrupt_selected_pointer_cannot_fall_back_to_a_contract(tmp_path, fault):
    _, state, _ = finalized(tmp_path, bounded=True)
    path = state / 'observation-pointers-v2/latest-observation.json'
    pointer = json.loads(path.read_bytes())
    pointer['export_path'] = '../outside'
    path.write_text({'invalid_json': '{', 'wrong_type': '[]',
        'unsafe_path': json.dumps(pointer)}[fault], encoding='utf8')
    assert not _load_backfill().observation_gate(state, DATE, force=True)[0]


@pytest.mark.parametrize('pointer_mode', ['absent', 'other_date'])
def test_historical_contract_selects_its_revision_exports(tmp_path, pointer_mode):
    repaired, state, _ = finalized(tmp_path, revision='repaired')
    path = state / 'observation-pointers-v2/latest-observation.json'
    if pointer_mode == 'absent':
        path.unlink()
    else:
        pointer = json.loads(path.read_bytes())
        pointer['observation_date'] = '2026-08-15'
        path.write_text(json.dumps(pointer), encoding='utf8')
    allowed, _, _, exports = _load_backfill().publication_candidate(state, DATE, force=False)
    assert allowed and exports == repaired


def test_explicit_wrong_source_cannot_pass_finalized_verification(tmp_path):
    from app_payload_source_verification import verify_reconciled_source
    from app_payload_observation_gate import contract_for_run_date
    _, state, _ = finalized(tmp_path, alternate=True)
    assert not verify_reconciled_source(state, tmp_path / 'runs' / DATE / '_exports',
        DATE, contract_for_run_date(state, DATE))
