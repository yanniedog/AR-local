"""Existing publication-lane controls against retained public pricing cases.

Generation clocks, approvals and source-change faults here are test controls;
they do not constitute natural shadowing, activation or Pi acceptance.
"""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from cdr_atomic import atomic_write_json
from cdr_public_rates_candidate import read_candidate
from cdr_public_rates_publication import sha256
from cdr_public_rates_warning import PENDING_REASON, read_source_state, validate_warning_candidate
from cdr_terms.identity import digest
import cdr_public_rates_runtime as runtime
import pi_daily_sync as sync
from pi_payload_retry_policy import publication_retry_candidates, publication_source_key
from tests.test_public_rate_publication import COMMIT, packet


def retained(root, candidate, *, discovery=True):
    path = root / 'public-rate-candidates' / digest(candidate['generationId']) / (sha256(candidate) + '.json')
    atomic_write_json(path, candidate, create_once=True)
    if discovery:
        atomic_write_json(root / 'public-rate-catalogue-candidate.json', {
            'schemaVersion': 1, 'candidateFile': path.relative_to(root).as_posix(), 'sha256': sha256(candidate)})
    return {'file': str(path), 'sha256': sha256(candidate)}


def pointer(candidate):
    day = candidate['runDate']
    return {'schema_version': 2, 'generation_id': candidate['generationId'], 'observation_date': day,
            'observation_state': 'complete', 'marker_path': day + '.done.json',
            'export_path': f'runs/{day}/_exports', 'ledger_event_digest': 'a' * 64}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    evidence, state = tmp_path / 'evidence', tmp_path / 'state'
    evidence.mkdir()
    from cdr_terms.store import EvidenceStore
    with EvidenceStore(evidence) as store:
        pass  # Actual additive schema; no acquisition checks or business prices.
    monkeypatch.setenv(runtime.FLAG, '1')
    monkeypatch.setenv('AR_LOCAL_TERMS_ROOT', str(evidence))
    monkeypatch.setenv('AR_LOCAL_PAYLOAD_REVISIONS', '1')
    monkeypatch.setenv('AR_APP_REVISION_CONSUMER_SHA', COMMIT)
    monkeypatch.delenv(runtime.TEMPLATE, raising=False)
    monkeypatch.setattr(sync, 'data_state_root', lambda _: state)
    monkeypatch.setattr('ar_local_pi_runtime.data_state_root', lambda _: state)
    candidate, report, receipt, approval, identity = packet(tmp_path, monkeypatch)
    result = retained(evidence, candidate)
    captured = pointer(candidate)
    atomic_write_json(state / 'observation-pointers-v2/latest-complete.json', captured)
    return evidence, state, candidate, report, receipt, approval, identity, result, captured


def test_disabled_runtime_does_not_read_evidence_approval_or_queue(tmp_path, monkeypatch):
    monkeypatch.delenv(runtime.FLAG, raising=False)
    monkeypatch.setenv('AR_LOCAL_TERMS_ROOT', str(tmp_path / 'does-not-exist'))
    monkeypatch.setenv(runtime.TEMPLATE, str(tmp_path / 'missing-approval'))
    original = {'generation_id': 'unchanged-control'}
    assert runtime.enrich_publication_pointer(tmp_path, original) == original
    assert runtime.publication_kwargs(tmp_path, {}, {}) == {}
    assert runtime.queue_candidate_update(tmp_path, {}) == {'status': 'disabled'}
    assert runtime.queue_source_warning(tmp_path) == {'status': 'disabled'}
    assert not list(tmp_path.iterdir())


def test_daily_and_queued_publication_bind_exact_immutable_candidate(setup, tmp_path):
    evidence, _, candidate, _, _, _, _, result, captured = setup
    frozen = runtime.enrich_publication_pointer(tmp_path, captured)
    assert frozen[runtime.CANDIDATE_POINTER]['sha256'] == result['sha256']
    assert sync.current_publication_pointer(tmp_path) == frozen
    kwargs = runtime.publication_kwargs(tmp_path, captured, frozen)
    assert kwargs['public_rates_root'] == Path(result['file']) and kwargs['public_rates_receipt'] is None
    with kwargs['pre_promotion_fence']():
        assert kwargs['pre_promotion_guard']() is None
    later = copy.deepcopy(candidate)
    later['programmes'][0]['components'][0]['value'] = '0.0002'  # Deliberate public-source price-update control.
    retained(evidence, later)
    # A queued retry never silently switches bytes. The newer complete snapshot
    # settles it as superseded before it could restore earlier current claims.
    with pytest.raises(runtime.SupersededCandidate):
        runtime.publication_kwargs(tmp_path, captured, frozen)
    assert read_candidate(Path(result['file']))['programmes'][0]['components'][0]['value'] != later['programmes'][0]['components'][0]['value']
    with pytest.raises(ValueError, match='contract_generation'):
        runtime.publication_kwargs(tmp_path, {**captured, 'generation_id': 'another-generation'}, frozen)


def test_late_success_or_failure_snapshot_queues_unique_existing_lane_work(setup, tmp_path):
    evidence, _, candidate, _, _, _, _, first, captured = setup
    one = runtime.queue_candidate_update(evidence, first, repo_root=tmp_path)
    assert one['status'] == 'queued'
    assert runtime.queue_candidate_update(evidence, first, repo_root=tmp_path) == one
    later = copy.deepcopy(candidate)
    later['programmes'][0]['freshness']['state'] = 'failed'
    later['programmes'][0]['freshness']['reasonCodes'] = ['source_check_failed']
    second = retained(evidence, later)
    two = runtime.queue_candidate_update(evidence, second, repo_root=tmp_path)
    assert two['status'] == 'queued' and two['sourceKey'] != one['sourceKey']
    pending = sync.read_payload_publication_pending(tmp_path)
    assert len(publication_retry_candidates(pending)) == 2
    original = pending['pointer']
    sync.clear_payload_publication_pending(tmp_path, original)
    assert sync.pending_publication_pointer(tmp_path)[runtime.CANDIDATE_POINTER]['sha256'] == second['sha256']
    assert sync.current_publication_pointer(tmp_path) == sync.pending_publication_pointer(tmp_path)
    assert publication_source_key({'pointer': original}) == one['sourceKey']
    assert runtime.queue_candidate_update(evidence, first, repo_root=tmp_path)['status'] == 'superseded'


def test_incomplete_and_unselected_generations_do_not_queue(setup, tmp_path):
    evidence, _, candidate, _, _, _, _, _, _ = setup
    assert runtime.queue_candidate_update(evidence, {'status': 'deferred'}, repo_root=tmp_path)['status'] == 'deferred'
    other = copy.deepcopy(candidate)
    other['generationId'] = 'unselected-generation-control'
    result = retained(evidence, other, discovery=False)
    assert runtime.queue_candidate_update(evidence, result, repo_root=tmp_path)['status'] == 'deferred'
    assert not sync.payload_publication_pending(tmp_path)


def test_candidate_path_hash_and_revision_guards_fail_closed(setup, tmp_path, monkeypatch):
    evidence, _, candidate, _, _, _, _, result, captured = setup
    with pytest.raises(ValueError, match='hash_mismatch'):
        runtime.queue_candidate_update(evidence, {**result, 'sha256': '0' * 64}, repo_root=tmp_path)
    with pytest.raises(ValueError, match='candidate_path'):
        runtime.publication_kwargs(tmp_path, captured, {**captured, runtime.CANDIDATE_POINTER: {
            'file': '../outside.json', 'sha256': result['sha256']}})
    candidate['enabledProgrammeIds'] = [candidate['programmes'][0]['programmeId']]
    retained(evidence, candidate)
    with pytest.raises(ValueError, match='selected_immutable_generation'):
        runtime.enrich_publication_pointer(tmp_path, captured)
    monkeypatch.setenv('AR_LOCAL_PAYLOAD_REVISIONS', '0')
    with pytest.raises(ValueError, match='immutable_revision_publisher'):
        runtime.publication_kwargs(tmp_path, captured, captured)


def test_original_and_explicit_price_update_templates_keep_all_reviewed_bindings(setup, tmp_path, monkeypatch):
    evidence, _, candidate, _, receipt, approval, identity, _, captured = setup
    monkeypatch.setenv(runtime.TEMPLATE, str(approval))
    assert runtime.publication_kwargs(tmp_path, captured, captured)['public_rates_receipt'] == approval
    receipt['allowsValidatedPriceUpdates'] = True
    atomic_write_json(approval, receipt)
    changed = copy.deepcopy(candidate)
    changed['programmes'][0]['components'][0]['value'] = '0.0002'
    current = retained(evidence, changed)
    selected = runtime.publication_kwargs(tmp_path, captured, captured)
    derived = json.loads(selected['public_rates_receipt'].read_bytes())
    assert derived['candidateSha256'] == current['sha256']
    assert derived['publicationMode'] == 'validated_update'
    assert derived['approvedShadowCandidate']['candidateSha256'] == receipt['candidateSha256']
    for key in ('policySha256', 'consumerRelease', 'operatorApprovalSha256', 'canaryReceiptSha256', 'programmeIds'):
        assert derived[key] == receipt[key]
    assert runtime.authorised_programmes(read_candidate(Path(current['file'])), selected['public_rates_receipt']) == {identity}
    before = selected['public_rates_receipt'].read_bytes()
    replay = runtime.publication_kwargs(tmp_path, captured, captured)
    assert replay['public_rates_root'] == selected['public_rates_root']
    assert replay['public_rates_receipt'] == selected['public_rates_receipt']
    assert selected['public_rates_receipt'].read_bytes() == before


def test_price_updates_need_explicit_permission_and_structure_changes_are_suspended(setup, tmp_path, monkeypatch):
    evidence, _, candidate, _, receipt, approval, _, _, captured = setup
    monkeypatch.setenv(runtime.TEMPLATE, str(approval))
    changed = copy.deepcopy(candidate)
    changed['programmes'][0]['components'][0]['value'] = '0.0002'
    retained(evidence, changed)
    with pytest.raises(ValueError, match='explicit_operator_template_permission'):
        runtime.publication_kwargs(tmp_path, captured, captured)
    receipt['allowsValidatedPriceUpdates'] = True
    atomic_write_json(approval, receipt)
    changed['programmes'][0]['components'][0]['unit'] = 'percentage_points'
    retained(evidence, changed)
    suspended = runtime.publication_kwargs(tmp_path, captured, captured)
    decision = runtime.authorised_programmes(read_candidate(suspended['public_rates_root']), suspended['public_rates_receipt'])
    assert not decision
    identity = candidate['programmes'][0]['programmeId']
    assert decision.suspensions[identity]['reasonCodes'] == ['public_pricing_structure_changed_requires_review']
    monkeypatch.setenv('AR_APP_REVISION_CONSUMER_SHA', 'f' * 40)
    with pytest.raises(ValueError, match='selected_shipped_consumer'):
        runtime.publication_kwargs(tmp_path, captured, captured)


def test_selected_generation_authority_is_read_only_and_disabled_for_other_roots(setup, tmp_path, monkeypatch):
    evidence, _, candidate, _, _, _, _, _, _ = setup
    before = {path: path.read_bytes() for path in evidence.rglob('*') if path.is_file()}
    assert runtime.selected_public_generation(evidence) == candidate['generationId']
    assert runtime.selected_public_generation(tmp_path / 'another-evidence-root') is None
    monkeypatch.delenv(runtime.FLAG)
    assert runtime.selected_public_generation(evidence) is None
    assert all(path.read_bytes() == body for path, body in before.items())


def test_pending_queue_serialises_concurrent_candidate_updates(setup, tmp_path):
    _, _, _, _, _, _, _, _, captured = setup
    first = {**captured, runtime.CANDIDATE_POINTER: {'file': 'a.json', 'sha256': 'a' * 64}}
    sync.mark_payload_publication_pending(tmp_path, 'initial-control', first)
    updates = [{**captured, runtime.CANDIDATE_POINTER: {'file': f'{index}.json', 'sha256': f'{index:064x}'}}
               for index in range(1, 17)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda p: sync.mark_payload_publication_pending(tmp_path, 'source-control', p), updates))
    pending = sync.read_payload_publication_pending(tmp_path)
    assert pending['pointer'] == first
    assert {publication_source_key({'pointer': item}) for item in pending['queued_pointers']} == {
        publication_source_key({'pointer': item}) for item in updates}


@pytest.mark.parametrize('body', [b'truncated', b'[]', b'{}'])
def test_source_update_preserves_unreadable_or_ambiguous_pending_marker(setup, tmp_path, body):
    evidence, _, _, _, _, _, _, result, _ = setup
    pending = sync.payload_publication_pending_path(tmp_path)
    pending.write_bytes(body)
    with pytest.raises(ValueError, match='pending_state_unreadable'):
        runtime.queue_candidate_update(evidence, result, repo_root=tmp_path)
    assert pending.read_bytes() == body


def test_existing_publisher_passes_the_capability_to_immutable_dual_builder(setup, tmp_path, monkeypatch):
    _, state, _, _, _, _, _, result, captured = setup
    monkeypatch.setenv('AR_LOCAL_APP_PAYLOAD', '1')
    exports = tmp_path / 'exports'
    exports.mkdir()
    atomic_write_json(state / captured['marker_path'], {})
    monkeypatch.setattr(sync, '_exports_from_pointer', lambda *_: exports)
    monkeypatch.setattr(sync, 'verify_completion_marker', lambda *_: True)
    monkeypatch.setattr(sync, '_contract_from_completion', lambda *_: captured)
    builder = Mock(side_effect=RuntimeError('stop_before_any_network_control'))
    monkeypatch.setattr('app_payload.build_and_publish_dual', builder)
    assert sync.maybe_publish_app_payload(tmp_path, sync.current_publication_pointer(tmp_path)) == sync.PUBLISH_FAILED
    assert builder.call_args.kwargs['public_rates_root'] == Path(result['file'])
    assert builder.call_args.kwargs['public_rates_receipt'] is None


def test_superseded_worker_settles_only_old_pointer_and_keeps_new_warning_pending(setup, tmp_path, monkeypatch):
    evidence, state, candidate, _, _, _, _, first, captured = setup
    frozen = runtime.enrich_publication_pointer(tmp_path, captured)
    sync.mark_payload_publication_pending(tmp_path, 'original-control', frozen)
    updated = copy.deepcopy(candidate)
    updated['programmes'][0]['freshness']['state'] = 'failed'
    newer = retained(evidence, updated)
    runtime.queue_candidate_update(evidence, newer, repo_root=tmp_path)
    monkeypatch.setenv('AR_LOCAL_APP_PAYLOAD', '1')
    monkeypatch.setattr(sync, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(sync, 'ensure_runtime_data_writable', lambda _: None)
    monkeypatch.setattr(sync, 'payload_retry_window_reason', lambda: '')
    monkeypatch.setattr(sync, 'queue_drive_backup', lambda *_: pytest.fail('no source was published'))
    exports = tmp_path / 'exports'
    exports.mkdir()
    atomic_write_json(state / captured['marker_path'], {})
    monkeypatch.setattr(sync, '_exports_from_pointer', lambda *_: exports)
    monkeypatch.setattr(sync, 'verify_completion_marker', lambda *_: True)
    monkeypatch.setattr(sync, '_contract_from_completion', lambda *_: captured)
    builder = Mock(side_effect=AssertionError('superseded bytes must never be built or promoted'))
    monkeypatch.setattr('app_payload.build_and_publish_dual', builder)
    assert sync.main(['--publish-existing-payload', '--publication-source-key',
                      publication_source_key({'pointer': frozen})]) == 0
    builder.assert_not_called()
    remaining = sync.read_payload_publication_pending(tmp_path)
    assert len(publication_retry_candidates(remaining)) == 1
    assert remaining['pointer'][runtime.CANDIDATE_POINTER]['sha256'] == newer['sha256']
    assert first['sha256'] != newer['sha256']


def test_source_failure_during_archive_readback_cannot_advance_selected_head(setup, tmp_path):
    from tests.test_app_payload_revisions import MemoryStore, build_payload, CONSUMER, REPO
    from app_payload_revisions import publish_revision_bundle
    evidence, _, candidate, _, _, _, _, _, captured = setup
    selected = runtime.publication_kwargs(tmp_path, captured, captured)
    payload = tmp_path / 'revision-payload'
    build_payload(payload)
    store = MemoryStore()
    archive = store.archive

    def complete_then_check_fails(tag, paths):
        archive(tag, paths)
        newer = copy.deepcopy(candidate)
        newer['programmes'][0]['freshness']['state'] = 'failed'
        with runtime.public_snapshot_fence(evidence):
            retained(evidence, newer)

    store.archive = complete_then_check_fails
    with pytest.raises(runtime.SupersededCandidate):
        publish_revision_bundle(payload, state_dir=tmp_path / 'revisions', repo=REPO,
                                consumer_commit=CONSUMER, enabled=True, store=store,
                                pre_promotion_guard=selected['pre_promotion_guard'],
                                pre_promotion_fence=selected['pre_promotion_fence'])
    assert store.promotions == 0
    assert ('app-payload-latest', 'dates-index.json') not in store.objects
    assert any(tag.endswith('-r000001') for tag, _ in store.objects)  # Retained staging is not acceptance.


def test_source_failure_during_alias_asset_upload_cannot_replace_the_manifest(setup, tmp_path, monkeypatch):
    from types import SimpleNamespace
    import app_payload
    import app_payload_publish as publisher
    from app_payload_revisions_github import GitHubRevisionStore
    from tests.test_app_payload_revisions import build_payload, REPO
    evidence, _, candidate, _, _, _, _, _, captured = setup
    selected = runtime.publication_kwargs(tmp_path, captured, captured)
    payload = tmp_path / 'alias-payload'
    manifest = build_payload(payload)
    # Publication identity is control metadata, independent of public prices.
    manifest['payload_revision'] = {'schema_version': 1, 'revision': 1, 'generation_id': 'revision-control',
                                    'bundle_sha256': '1' * 64, 'parent_revision': None}
    atomic_write_json(payload / 'manifest.json', manifest)
    uploads = []

    def asset_upload(args, **kwargs):
        uploads.append(args)
        assert not any(Path(name).name == 'manifest.json' for name in args[4:args.index('--repo')])
        newer = copy.deepcopy(candidate)
        newer['programmes'][0]['freshness']['state'] = 'failed'
        with runtime.public_snapshot_fence(evidence):
            retained(evidence, newer)

    monkeypatch.setattr(publisher, 'publication_key', lambda: bytes(range(32)))
    monkeypatch.setattr(publisher, 'secure_upload', asset_upload)
    monkeypatch.setattr(app_payload, '_gh_available', lambda: 'gh')
    monkeypatch.setattr(app_payload, '_gh_authed', lambda _: True)
    monkeypatch.setattr(app_payload, '_live_manifest_status', lambda *_: ('missing', None))
    monkeypatch.setattr(app_payload.subprocess, 'run', lambda *_a, **_k: SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.setattr(GitHubRevisionStore, 'read', lambda _self, _tag, name, *_a, **_k: (payload / name).read_bytes())
    monkeypatch.setattr('app_payload_v2_archive.preserve_current_v2', lambda *_a, **_k: None)
    with pytest.raises(runtime.SupersededCandidate):
        publisher.publish_payload(payload, repo=REPO, pre_promotion_guard=selected['pre_promotion_guard'],
                                  pre_promotion_fence=selected['pre_promotion_fence'])
    assert len(uploads) == 1


def source_event(evidence, candidate, status='dirty', *, label='accepted-source-status-control'):
    """Committed journal state is a fault control, not a fabricated rate/check."""
    from cdr_terms.store import EvidenceStore
    from cdr_terms.public_rates_store import PublicRateStore
    with EvidenceStore(evidence) as store:
        register = PublicRateStore(store).register({'schemaVersion': 1, 'publicOnly': True,
            'registerVersion': 'source-status-test-control', 'sources': []}, observed_at=candidate['runDate'] + 'T12:00:00Z')
        with store.db:
            store.db.execute('INSERT OR IGNORE INTO public_rate_candidate_events '
                '(event_id,ingest_id,register_id,status,observed_at) VALUES (?,?,?,?,?)',
                (digest([register, label, status]), candidate['generationId'], register, status,
                 candidate['runDate'] + 'T12:30:00Z'))
        return store.db.execute('SELECT count(*) FROM public_rate_budget_reservations').fetchone()[0]


def catalogue_controls(setup, tmp_path, monkeypatch):
    """Add actual public discovery/evidence to the controlled approval packet."""
    from tests.test_app_payload_public_rates import candidate as public_catalogue
    from cdr_public_rates_cdr import inventory_from_compiled
    from cdr_public_rates_publication import programme_structure_sha256
    evidence, state, candidate, report, receipt, approval, identity, _, captured = setup
    public = public_catalogue.__wrapped__()
    product = copy.deepcopy(next(p for p in public['products'] if p['section'] == 'Savings'))
    product['programmeIds'] = [identity]
    base = candidate['programmes'][0]['components'][0]
    reference = {'referenceId': base['componentId'], 'providerId': product['providerId'],
        'name': product['name'], 'value': base['value'], 'unit': base['unit'],
        'freshness': copy.deepcopy(candidate['programmes'][0]['freshness']), 'evidenceIds': base['evidenceIds']}
    product['referenceIds'] = [reference['referenceId']]
    candidate.update(products=[product], referenceRates=[reference], evidence=public['evidence'])
    candidate['coverage'] = inventory_from_compiled(candidate)
    for row in candidate['coverage']:
        row.update(referenceSourceStatus='current', sourceAcquisition='fetched', extraction='validated', costCompleteness='complete')
    result = retained(evidence, candidate)
    report['cycles'][-1]['candidateSha256'] = result['sha256']
    atomic_write_json(tmp_path / 'shadow.json', report)
    policy = {'schemaVersion': 1, 'reviewedProgrammes': [{'programmeId': identity,
        'shadowReportSha256': sha256(report), 'consumerCommit': COMMIT,
        'programmeStructureSha256': programme_structure_sha256(candidate['programmes'][0])}]}
    monkeypatch.setattr('cdr_public_rates_publication.reviewed_policy', lambda: (policy, sha256(policy)))
    receipt.update(candidateSha256=result['sha256'], policySha256=sha256(policy), allowsValidatedPriceUpdates=True,
                   shadowReport={'file': 'shadow.json', 'sha256': sha256(report)})
    atomic_write_json(approval, receipt)
    monkeypatch.setenv(runtime.TEMPLATE, str(approval))
    return evidence, state, candidate, receipt, approval, identity, result, captured


def test_pending_public_source_publishes_warnings_without_another_collector_lease(setup, tmp_path, monkeypatch):
    from tests.test_app_payload_public_rates import package
    from app_payload_public_rates import validate_local_catalogue
    evidence, _, original, receipt, _, identity, original_file, captured = catalogue_controls(setup, tmp_path, monkeypatch)
    frozen = runtime.enrich_publication_pointer(tmp_path, captured)
    old = runtime.publication_kwargs(tmp_path, captured, frozen)
    assert source_event(evidence, original) == 0
    with old['pre_promotion_fence'](), pytest.raises(runtime.SupersededCandidate):
        old['pre_promotion_guard']()
    one = runtime.queue_source_warning(evidence, repo_root=tmp_path)
    assert one['status'] == 'queued' and one['candidateSha256'] != original_file['sha256']
    assert runtime.queue_source_warning(evidence, repo_root=tmp_path) == one
    selected_pointer = sync.pending_publication_pointer(tmp_path)
    selected = runtime.publication_kwargs(tmp_path, captured, selected_pointer)
    warning = read_candidate(selected['public_rates_root'])
    validate_warning_candidate(warning)
    assert warning['programmes'] == original['programmes']  # No new price computation.
    assert warning['referenceRates'][0]['value'] == original['referenceRates'][0]['value']
    assert warning['referenceRates'][0]['freshness']['lastSuccessAt'] == original['referenceRates'][0]['freshness']['lastSuccessAt']
    assert warning['referenceRates'][0]['freshness']['state'] == 'deferred'
    assert warning['products'][0]['sourceEvidence'] == original['products'][0]['sourceEvidence']
    assert read_candidate(evidence / 'public-rate-catalogue-candidate.json') == original
    decision = runtime.authorised_programmes(warning, selected['public_rates_receipt'])
    assert not decision and decision.suspensions[identity]['reasonCodes'] == [PENDING_REASON]
    update = json.loads(selected['public_rates_receipt'].read_bytes())
    assert update['warningSnapshotSha256'] == sha256(warning['warningSnapshot'])
    for key in ('operatorApprovalSha256', 'canaryReceiptSha256', 'consumerRelease', 'policySha256'):
        assert update[key] == receipt[key]
    with selected['pre_promotion_fence']():
        selected['pre_promotion_guard']()
    output = tmp_path / 'warning-public-transport'
    manifest = package(output, warning, selected['public_rates_receipt'])
    manifest['source_observation']['generation_id'] = warning['generationId']
    decoded = validate_local_catalogue(manifest, output)
    assert decoded['products'][0]['programmeIds'] == []
    assert PENDING_REASON in decoded['products'][0]['reasonCodes']
    assert all(row['referenceSourceStatus'] == 'deferred' and row['sourceAcquisition'] == 'deferred'
               and row['extraction'] == 'pending' and row['costCompleteness'] == 'unknown' for row in decoded['index']['coverage'])
    assert any(row['publicationStatus'] == 'published_with_suspensions' for row in decoded['index']['coverage'])
    assert source_event(evidence, original, label='accepted-source-status-control') == 0


def test_warning_prices_and_exact_source_state_cannot_be_overridden(setup, tmp_path, monkeypatch):
    evidence, _, original, _, _, _, _, captured = catalogue_controls(setup, tmp_path, monkeypatch)
    source_event(evidence, original)
    frozen = runtime.enrich_publication_pointer(tmp_path, captured)
    selected = runtime.publication_kwargs(tmp_path, captured, frozen)
    warning = read_candidate(selected['public_rates_root'])
    changed = copy.deepcopy(dict(warning))
    changed['referenceRates'][0]['value'] = '0.99'  # Ad hoc price override fault.
    forged = retained(evidence, changed, discovery=False)
    with pytest.raises(ValueError, match='cannot_override_observed_pricing'):
        runtime.authorised_programmes(read_candidate(Path(forged['file'])), None)
    source_event(evidence, original, label='next-accepted-source-status-control')
    with selected['pre_promotion_fence'](), pytest.raises(runtime.SupersededCandidate, match='source_state_superseded'):
        selected['pre_promotion_guard']()
    newer = runtime.queue_source_warning(evidence, repo_root=tmp_path)
    assert newer['candidateSha256'] != frozen[runtime.CANDIDATE_POINTER]['sha256']


def test_warning_dry_run_and_success_acknowledgement_are_idempotent(setup, tmp_path, monkeypatch):
    evidence, _, original, _, _, _, _, captured = catalogue_controls(setup, tmp_path, monkeypatch)
    source_event(evidence, original)
    # SQLite's read-only WAL snapshot may create shared-memory sidecars; the
    # persistent evidence and publication-control files must remain unchanged.
    def persistent_paths():
        return sorted(str(path) for path in evidence.rglob('*') if not path.name.endswith(('sqlite3-shm', 'sqlite3-wal')))
    before = persistent_paths()
    assert runtime.queue_source_warning(evidence, repo_root=tmp_path, dry_run=True)['status'] == 'dry_run'
    assert persistent_paths() == before
    assert not sync.payload_publication_pending(tmp_path)
    runtime.queue_source_warning(evidence, repo_root=tmp_path)
    selected = runtime.publication_kwargs(tmp_path, captured, sync.pending_publication_pointer(tmp_path))
    warning = read_candidate(selected['public_rates_root'])
    verified = {'run_date': warning['runDate'], 'payload_revision': {'bundle_sha256': '3' * 64},
                'public_rate_catalogue': {'generationId': warning['generationId']}}
    runtime.acknowledge_warning_publication(selected['public_rates_root'], verified)
    runtime.acknowledge_warning_publication(selected['public_rates_root'], verified)
    sync.clear_payload_publication_pending(tmp_path)
    assert runtime.queue_source_warning(evidence, repo_root=tmp_path)['status'] == 'already_published'
    assert not sync.payload_publication_pending(tmp_path)
    assert read_source_state(evidence, original['generationId']) is not None  # Publishing never acknowledges compilation.
    source_event(evidence, original, 'fresh')
    assert runtime.queue_source_warning(evidence, repo_root=tmp_path)['status'] == 'not_due'
    with pytest.raises(runtime.SupersededCandidate):
        selected['pre_promotion_guard']()


def test_selected_new_generation_only_publishes_previous_prices_as_dated_history(setup, tmp_path, monkeypatch):
    from tests.test_app_payload_public_rates import package
    from app_payload_public_rates import load_candidate, validate_local_catalogue
    evidence, state, original, _, _, identity, original_file, captured = catalogue_controls(setup, tmp_path, monkeypatch)
    next_selected = {**captured, 'generation_id': 'selected-next-generation-control', 'observation_date': '2026-10-15',
                     'marker_path': '2026-10-15.done.json', 'export_path': 'runs/2026-10-15/_exports'}
    atomic_write_json(state / 'observation-pointers-v2/latest-complete.json', next_selected)
    source_event(evidence, {'generationId': next_selected['generation_id'], 'runDate': next_selected['observation_date']})
    queued = runtime.queue_source_warning(evidence, repo_root=tmp_path)
    assert queued['status'] == 'queued' and queued['generationId'] == next_selected['generation_id']
    selected = runtime.publication_kwargs(tmp_path, next_selected, sync.pending_publication_pointer(tmp_path))
    warning = read_candidate(selected['public_rates_root'])
    assert warning['generationId'] == next_selected['generation_id'] and warning['runDate'] == '2026-10-15'
    assert warning['warningSnapshot']['sourceCandidateSha256'] == original_file['sha256']
    assert warning['warningSnapshot']['sourceGenerationId'] == original['generationId']
    assert warning['programmes'] == [] and warning['programmeChunks'] == [] and warning['evidenceChunks'] == []
    assert warning['products'][0]['programmeIds'] == [] and warning['products'][0]['suppressedProgrammeCount'] == 1
    assert warning['products'][0]['sourceEvidence'] == original['products'][0]['sourceEvidence']
    reference = warning['referenceRates'][0]
    assert reference['value'] == original['referenceRates'][0]['value']
    assert reference['freshness']['lastSuccessAt'] == original['referenceRates'][0]['freshness']['lastSuccessAt']
    assert reference['freshness']['state'] == 'deferred'
    assert 'public_pricing_previous_generation_history' in reference['freshness']['reasonCodes']
    decision = runtime.authorised_programmes(warning, selected['public_rates_receipt'])
    assert not decision and identity in decision.suspensions
    assert load_candidate(selected['public_rates_root'], source_observation=next_selected,
                          run_date=next_selected['observation_date']) == warning
    with pytest.raises(ValueError, match='another ingest generation'):
        load_candidate(Path(original_file['file']), source_observation=next_selected, run_date=next_selected['observation_date'])
    manifest = package(tmp_path / 'generation-boundary-transport', warning, selected['public_rates_receipt'])
    # These core/date containers are control metadata; retained lender prices
    # and evidence above are unchanged and no historical executable is shipped.
    manifest.update(run_date=warning['runDate'], source_observation={'generation_id': warning['generationId']})
    decoded = validate_local_catalogue(manifest, tmp_path / 'generation-boundary-transport')
    assert decoded['products'][0]['programmeIds'] == [] and decoded['products'][0]['suppressedProgrammeCount'] == 1
    with selected['pre_promotion_fence']():
        selected['pre_promotion_guard']()
    completed = copy.deepcopy(dict(original))
    completed.update(generationId=next_selected['generation_id'], runDate=next_selected['observation_date'])
    retained(evidence, completed)
    with pytest.raises(runtime.SupersededCandidate):
        selected['pre_promotion_guard']()
