"""Real public fixtures; injected clocks/transports verify admission protocol only."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import cdr_public_rates_budget as budget
import cdr_public_rates_collector as collector
from cdr_atomic import canonical_json_bytes
from cdr_public_rates_sources import reviewed_register, source_inventory
from cdr_public_rates_cdr import inventory_from_compiled
from cdr_public_rates_cdr import compile_record
from cdr_public_rates_warning import read_source_state
from cdr_terms import acquisition, acquisition_batch
from cdr_terms.acquisitions_queue import AcquisitionQueue
from cdr_terms.identity import digest
from cdr_terms.public_rates_store import PublicRateStore
from cdr_terms.store import EvidenceStore
from tests.test_public_rate_evidence_store import CDF, WHEN, retained_product, retain_reference_check


class Clock:
    elapsed = 0.0

    def advance(self, seconds):
        self.elapsed += seconds

    def now(self):
        return (datetime.fromisoformat(WHEN.replace('Z', '+00:00')) + timedelta(seconds=self.elapsed)).isoformat().replace('+00:00', 'Z')


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setenv(collector.COLLECT_ENV, '1')
    monkeypatch.setattr(budget.time, 'monotonic', lambda: value.elapsed)
    for module in (budget, collector, acquisition, acquisition_batch):
        monkeypatch.setattr(module, 'utc_now', value.now)
    monkeypatch.setattr('cdr_terms.acquisitions_queue.utc_now', value.now)
    return value


def test_reservations_survive_crash_restart_and_atomic_multi_connection_admission(tmp_path, clock):
    root = tmp_path / 'evidence'
    with EvidenceStore(root) as first:
        retained_product(first)
        first_claim = budget.reserve(first, 'retained-public-fixture', kind='capture')
        with EvidenceStore(root) as second:
            second_claim = budget.reserve(second, 'retained-public-fixture', kind='candidate')
            assert first_claim.reserved_ms == second_claim.reserved_ms == 120000
            with pytest.raises(budget.BudgetDeferred, match='ingest_time_budget'):
                budget.reserve(first, 'retained-public-fixture', kind='source', body_bytes=16 * 1024**2)
        with pytest.raises(sqlite3.IntegrityError, match='append-only'):
            first.db.execute('DELETE FROM public_rate_budget_reservations')
    with EvidenceStore(root) as restarted:
        assert budget.usage(restarted, 'retained-public-fixture')['milliseconds'] == 240000
        assert budget.reason(restarted, 'retained-public-fixture') == 'public_rate_ingest_time_budget'


def test_exact_settlement_refunds_unused_reservation_but_cannot_be_repeated(tmp_path, clock):
    with EvidenceStore(tmp_path / 'evidence') as store:
        retained_product(store)
        fetched = budget.reserve(store, 'retained-public-fixture', kind='source', body_bytes=16 * 1024**2)
        clock.advance(2)
        fetched.settle(body_bytes=len(CDF.read_bytes()))
        unchanged = budget.reserve(store, 'retained-public-fixture', kind='source', body_bytes=16 * 1024**2)
        clock.advance(1)
        unchanged.settle(body_bytes=0)
        assert budget.usage(store, 'retained-public-fixture') == {'bytes': len(CDF.read_bytes()), 'milliseconds': 3000}
        with pytest.raises(ValueError, match='already_settled'):
            fetched.settle(body_bytes=0)


def test_registered_sources_share_the_ingest_byte_ceiling_across_batches_and_do_not_starve_next_ingest(tmp_path, clock, monkeypatch):
    calls = []
    def partial(url, **kwargs):
        calls.append(url)
        raise acquisition.FetchFailure('transport_error')
    monkeypatch.setattr(acquisition, 'fetch_document', partial)
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, item, _ = retained_product(store)
        holders = sorted({source['providerAliases'][0] for source in reviewed_register()['sources']})
        inventory = source_inventory(inventory_from_compiled({'products': [item['product']], 'programmes': item['programmes']}, holders))
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        requests = public.queue_sources(register, ingest_id='retained-public-fixture', now=WHEN)
        assert len(requests) >= 6
        first = acquisition_batch.run_batch(store, registry_context={}, deadline=clock.elapsed + 105, guard=lambda: None)
        assert first['attempts'] == 4 and first['charged_bytes'] == 64 * 1024**2
        second = acquisition_batch.run_batch(store, registry_context={}, deadline=clock.elapsed + 105, guard=lambda: None)
        assert second['attempts'] == 0 and len(calls) == 4
        assert AcquisitionQueue(store).next_due(fair=True) is None
        assert store.db.execute("SELECT COUNT(*) FROM acquisition_events e WHERE status='queued' AND sequence="
            "(SELECT MAX(sequence) FROM acquisition_events WHERE request_id=e.request_id)").fetchone()[0] >= 2
        assert budget.reason(store, 'retained-public-fixture', need_bytes=True) == 'public_rate_ingest_byte_budget'
        clock.advance(1)
        retained_product(store, generation='next-public-ingest', observed_at=clock.now())
        public.queue_sources(register, ingest_id='next-public-ingest', now=clock.now())
        assert AcquisitionQueue(store).next_due(fair=True)['ingest_id'] == 'next-public-ingest'
        third = acquisition_batch.run_batch(store, registry_context={}, deadline=clock.elapsed + 105, guard=lambda: None)
        assert third['attempts'] == 4 and len(calls) == 8
        assert budget.usage(store, 'retained-public-fixture')['bytes'] == 64 * 1024**2


def test_sql_preparation_is_interrupted_by_the_same_reserved_deadline(tmp_path, clock):
    with EvidenceStore(tmp_path / 'evidence') as store:
        retained_product(store)
        token = budget.reserve(store, 'retained-public-fixture', kind='candidate', seconds=1)
        def tick(value):
            clock.advance(0.2)
            return value
        store.db.create_function('budget_protocol_tick', 1, tick)
        with pytest.raises(budget.BudgetDeferred, match='slice_deadline'):
            with token:
                store.db.execute('WITH RECURSIVE numbers(v) AS (VALUES(1) UNION ALL SELECT v+1 FROM numbers WHERE v<10000) '
                                 'SELECT SUM(budget_protocol_tick(v)) FROM numbers').fetchone()
        token.settle(body_bytes=0)
        assert store.db.execute('SELECT 1').fetchone()[0] == 1


def test_small_remaining_batch_does_not_lease_or_truncate_a_registered_document(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(acquisition, 'fetch_document', lambda *args, **kwargs: pytest.fail('no network before full document admission'))
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        public.queue_sources(register, ingest_id='retained-public-fixture', now=WHEN)
        result = acquisition_batch.run_batch(store, registry_context={}, deadline=clock.elapsed + 105, guard=lambda: None,
                                             limits=acquisition_batch.BatchLimits(body_bytes=1024))
        assert result['attempts'] == 0 and result['stop_reason'] == 'registered_source_batch_byte_deferred'
        assert AcquisitionQueue(store).next_due() is not None
        assert store.db.execute("SELECT COUNT(*) FROM acquisition_events WHERE status='running'").fetchone()[0] == 0
        assert budget.usage(store, 'retained-public-fixture') == {'bytes': 0, 'milliseconds': 0}


def test_accepted_check_crash_wakes_a_fresh_candidate_and_replays_without_network(tmp_path, clock, monkeypatch):
    from tests.test_public_rate_sources import capture
    monkeypatch.setenv(collector.COLLECT_ENV, '1')
    monkeypatch.setattr(acquisition, 'fetch_document', lambda *args, **kwargs: pytest.fail('replay uses retained source bytes'))
    monkeypatch.setattr('cdr_terms.acquisitions_queue.enqueue_interpretation', lambda *args, **kwargs: pytest.fail('deterministic pricing never queues models'))
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        with store.db:
            store.db.execute("INSERT INTO public_rate_candidate_events(event_id,ingest_id,register_id,status,observed_at) VALUES (?,?,?,?,?)",
                             (digest(['public-transport-initial']), 'retained-public-fixture', register, 'dirty', WHEN))
        collector.write_candidate(store, generation='retained-public-fixture', run_date=WHEN[:10], register_id=register, as_of=WHEN)
        assert collector.pending_candidate(store) is None
        public.queue_sources(register, ingest_id='retained-public-fixture', now=WHEN)
        queue = AcquisitionQueue(store)
        request = queue.claim(now=WHEN)
        body, context = capture('nab-indicator')
        check_id = digest([request['request_id'], request['lease_id']])
        store.record_check(document_id=request['document_id'], check_id=check_id, checked_at=WHEN, status='fetched', body=body,
                           media_type='application/pdf', http_status=200, metadata={'final_url': context['sourceUrl']})
        queue.finish(request, check_id, now=WHEN)
        assert store.db.execute('SELECT COUNT(*) FROM public_rate_checks').fetchone()[0] == 0
        assert acquisition_batch.has_work(store)
        result = collector.refresh_one_pending_candidate(store, deadline=clock.elapsed + 105, guard=lambda: None)
        assert result['status'] == 'candidate_written'
        assert public.pending_interpretations('retained-public-fixture') == []
        assert len(public.catalogue_inputs(register, ingest_id='retained-public-fixture', as_of=WHEN)['referenceRates']) == 106
        assert collector.pending_candidate(store) is None


def test_partial_compilation_resumes_original_context_after_raw_stage_cleanup(tmp_path, clock, monkeypatch):
    monkeypatch.setenv(collector.COLLECT_ENV, '1')
    sources = [CDF, Path(__file__).parent / 'fixtures/public_rates/anz-progress-saver-cdr-20261014.json']
    root = tmp_path / 'run'
    banks = root / 'banks'
    generation = 'retained-compilation-budget'
    with EvidenceStore(tmp_path / 'evidence') as store:
        with store.db:
            store.db.execute('INSERT INTO ingest_capture_attempts VALUES (?,?,?,?)', (generation, WHEN, WHEN, '{}'))
        entries = []
        for index, fixture in enumerate(sources):
            body = fixture.read_bytes()
            envelope = json.loads(body)
            record = envelope['data']
            provider = 'NAB' if index == 0 else 'ANZ'
            key = provider + '|' + record['productId']
            observation = store.observe(provider=provider, product_key=key, record=envelope, source_bytes=body, observed_at=WHEN, ingest_id=generation)
            path = banks / provider / 'public-product' / 'product-detail.json'
            path.parent.mkdir(parents=True)
            path.write_bytes(body)
            stamp = datetime.fromisoformat(WHEN.replace('Z', '+00:00')).timestamp()
            os.utime(path, (stamp, stamp))
            base = {'provider': provider, 'product_id': record['productId'], 'product_key': key}
            collector.retain_compile_input(store, path, banks, base, body, observation)
            entries.append({'relative_path': path.relative_to(root).as_posix(), 'sha256': store.put_blob(body), 'observation_id': observation, 'product_key': key})
        receipt = {'generation_id': generation, 'source_run_date': WHEN[:10], 'captured_at': WHEN, 'sources': entries}
        with store.db:
            store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,?)', (generation, store.put_blob(canonical_json_bytes(receipt)), WHEN, 2))
        queued = collector.capture_public_rates(store, root, receipt)
        assert queued['candidate']['reasonCode'] == 'deterministic_compilation_queued'
        assert store.db.execute('SELECT COUNT(*) FROM public_rate_product_versions').fetchone()[0] == 0
        original = collector.compile_record
        count = 0
        def slow(*args, **kwargs):
            nonlocal count
            count += 1
            clock.advance(60 if count == 1 else 45)
            return original(*args, **kwargs)
        monkeypatch.setattr(collector, 'compile_record', slow)
        partial = collector.refresh_one_pending_candidate(store, deadline=clock.elapsed + 105, guard=lambda: None)
        assert partial['status'] == 'deferred'
        assert store.db.execute('SELECT COUNT(*) FROM public_rate_product_versions').fetchone()[0] == 1
        assert collector.pending_candidate(store) is not None
        before = [row[0] for row in store.db.execute('SELECT context_json FROM public_rate_compile_inputs ORDER BY observation_id')]
        for entry in entries:
            (root / entry['relative_path']).unlink()
        monkeypatch.setattr(collector, 'compile_record', original)
        resumed = collector.refresh_one_pending_candidate(store, deadline=clock.elapsed + 105, guard=lambda: None)
        assert resumed['status'] == 'candidate_written' and resumed['products'] == 2
        assert collector.pending_candidate(store) is None
        after = [row[0] for row in store.db.execute('SELECT context_json FROM public_rate_compile_inputs ORDER BY observation_id')]
        assert before == after
        # This capture has original bytes and an observation time, but no
        # resource-specific successful HTTP receipt. Replay must not add one.
        assert all(json.loads(context)['checkedAt'] == '' for context in after)
        assert store.db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0] == 0


def test_stale_candidate_cannot_replace_a_newer_failed_check_snapshot_or_queue_its_callback(tmp_path, clock, monkeypatch):
    queued = []
    monkeypatch.setattr('cdr_public_rates_runtime.queue_candidate_update', lambda root, result: queued.append(result['sha256']) or {'status': 'disabled'})
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store, generation='prior-public-ingest', observed_at='2026-10-13T11:50:00Z')
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at='2026-10-13T11:50:00Z')
        retain_reference_check(store, register, generation='prior-public-ingest', now='2026-10-13T11:50:00Z')
        retained_product(store)
        public.queue_sources(register, ingest_id='retained-public-fixture', now=WHEN)
        original = collector.write_chunks
        newest = None
        def raced(*args, **kwargs):
            nonlocal newest
            if newest is None:
                queue = AcquisitionQueue(store)
                failed = queue.claim(now=WHEN)
                check_id = digest([failed['request_id'], failed['lease_id']])
                store.record_check(document_id=failed['document_id'], check_id=check_id, checked_at=WHEN,
                                   status='failed', error_code='http_error', http_status=503)
                queue.finish(failed, check_id, now=WHEN, terminal=True)
                assert store.db.execute('SELECT COUNT(*) FROM public_rate_checks WHERE ingest_id=?',
                                        ('retained-public-fixture',)).fetchone()[0] == 0
                monkeypatch.setattr(collector, 'write_chunks', original)
                newest = collector.write_candidate(store, generation='retained-public-fixture', run_date=WHEN[:10], register_id=register, as_of=WHEN)
                monkeypatch.setattr(collector, 'write_chunks', raced)
            return original(*args, **kwargs)
        monkeypatch.setattr(collector, 'write_chunks', raced)
        old = collector.write_candidate(store, generation='retained-public-fixture', run_date=WHEN[:10], register_id=register, as_of=WHEN)
        assert old['status'] == 'deferred' and old['reasonCode'] == 'candidate_snapshot_superseded'
        pointer = json.loads((store.root / 'public-rate-catalogue-candidate.json').read_bytes())
        assert pointer['sha256'] == newest['sha256'] and queued == [newest['sha256']]
        assert Path(old['file']).is_file()


@pytest.mark.parametrize('observed_at', ['2026-10-13T11:50:00Z', WHEN])
def test_older_or_equal_ambiguous_generation_preserves_current_pointer(tmp_path, clock, monkeypatch, observed_at):
    monkeypatch.setattr('cdr_public_rates_runtime.selected_public_generation', lambda root: None)
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        current = collector.write_candidate(store, generation='retained-public-fixture', run_date=WHEN[:10], register_id=register, as_of=WHEN)
        retained_product(store, generation='other-source-generation', observed_at=observed_at)
        older = collector.write_candidate(store, generation='other-source-generation', run_date=observed_at[:10], register_id=register, as_of=WHEN)
        assert older['status'] == 'deferred'
        assert older['reasonCode'] in {'candidate_generation_superseded', 'candidate_generation_order_ambiguous'}
        assert json.loads((store.root / 'public-rate-catalogue-candidate.json').read_bytes())['sha256'] == current['sha256']
        assert Path(older['file']).is_file()


def test_only_selected_generation_can_promote_even_when_its_source_clock_is_newer(tmp_path, clock, monkeypatch):
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        current = collector.write_candidate(store, generation='retained-public-fixture', run_date=WHEN[:10], register_id=register, as_of=WHEN)
        retained_product(store, generation='unselected-newer-source', observed_at='2026-10-15T11:50:00Z')
        monkeypatch.setattr('cdr_public_rates_runtime.selected_public_generation', lambda root: 'retained-public-fixture')
        newer = collector.write_candidate(store, generation='unselected-newer-source', run_date='2026-10-15', register_id=register, as_of=WHEN)
        assert newer['reasonCode'] == 'candidate_generation_not_selected'
        assert json.loads((store.root / 'public-rate-catalogue-candidate.json').read_bytes())['sha256'] == current['sha256']


def test_unit_product_name_alias_dates_are_bounded_observations_not_effective_dates(tmp_path):
    # Deliberate name-change unit contract, not a public lender-rate fixture.
    dates = ['2026-10-11T11:50:00Z', '2026-10-12T11:50:00Z',
             '2026-10-13T11:50:00Z', '2026-10-14T11:50:00Z', '2026-10-15T11:50:00Z']
    names = ['Unit former name', 'Unit former name', 'Unit current name', 'Unit current name', 'Unit future name']
    with EvidenceStore(tmp_path / 'evidence') as store:
        public = PublicRateStore(store)
        programme_ids = []
        for index, (observed_at, name) in enumerate(zip(dates, names)):
            generation = 'unit-name-observation-' + str(index)
            record = {'productId': 'unit-stable-product', 'name': name, 'depositRates': []}
            body = canonical_json_bytes(record)
            observation = store.observe(provider='Unit provider', product_key='unit-name-contract', record=record,
                source_bytes=body, observed_at=observed_at, ingest_id=generation)
            compiled = compile_record(record, provider_name='Unit provider', section='Savings',
                source_url='', source_sha256=store.put_blob(body), checked_at=observed_at, product_key='unit-name-contract')
            programme_ids.append(compiled['product']['productId'])
            if index == 3:
                compiled['product']['aliases'] = [{'name': name, 'effectiveFrom': '2026-09-01'}]
            public.record_compiled(observation, compiled)
            with store.db:
                store.db.execute('INSERT INTO ingest_capture_attempts VALUES (?,?,?,?)', (generation, observed_at, observed_at, '{}'))
        assert len(set(programme_ids)) == 1
        products = collector.compiled_generation(store, 'unit-name-observation-3')['products']
        assert len(products) == 1
        aliases = {alias['name']: alias for alias in products[0]['aliases']}
        assert set(aliases) == {'Unit former name', 'Unit current name'}
        assert aliases['Unit former name'] == {'name': 'Unit former name',
            'firstObservedAt': '2026-10-11T11:50:00.000000Z', 'lastObservedAt': '2026-10-12T11:50:00.000000Z'}
        assert aliases['Unit current name'] == {'name': 'Unit current name', 'effectiveFrom': '2026-09-01',
            'firstObservedAt': '2026-10-13T11:50:00.000000Z', 'lastObservedAt': '2026-10-14T11:50:00.000000Z'}


def test_unaccepted_registered_source_completions_do_not_dirty_candidates(tmp_path, clock):
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        public.queue_sources(register, ingest_id='retained-public-fixture', now=WHEN)
        queue = AcquisitionQueue(store)
        request = queue.claim(now=WHEN)
        check_id = digest([request['request_id'], request['lease_id']])
        store.record_check(document_id=request['document_id'], check_id=check_id, checked_at=WHEN,
                           status='failed', error_code='http_error', http_status=503)
        with pytest.raises(ValueError, match='stale completion rejected'):
            queue.finish({**request, 'lease_id': 'unaccepted-lease'}, check_id, now=WHEN)
        assert store.db.execute('SELECT COUNT(*) FROM public_rate_candidate_events').fetchone()[0] == 0
        queue.finish(request, check_id, now=WHEN, terminal=True)
        event = store.db.execute('SELECT * FROM public_rate_candidate_events').fetchall()
        assert len(event) == 1 and event[0]['status'] == 'dirty'
        with pytest.raises(ValueError, match='stale completion rejected'):
            queue.finish(request, check_id, now=WHEN)
        assert store.db.execute('SELECT COUNT(*) FROM public_rate_candidate_events').fetchone()[0] == 1


def test_warning_callback_runs_after_committed_acceptance_and_failure_preserves_dirty_work(tmp_path, clock, monkeypatch):
    callbacks = []
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        public.queue_sources(register, ingest_id='retained-public-fixture', now=WHEN)
        queue = AcquisitionQueue(store)
        request = queue.claim(now=WHEN)
        check_id = digest([request['request_id'], request['lease_id']])
        store.record_check(document_id=request['document_id'], check_id=check_id, checked_at=WHEN,
                           status='failed', error_code='http_error', http_status=503)
        def unavailable(root):
            assert not store.db.in_transaction
            with EvidenceStore(root) as independent:
                assert independent.db.execute('SELECT COUNT(*) FROM public_rate_candidate_events WHERE status=\'dirty\'').fetchone()[0] == 1
            callbacks.append(root)
            raise OSError('unit unavailable publication path')
        monkeypatch.setattr('cdr_public_rates_runtime.queue_source_warning', unavailable)
        queue.finish(request, check_id, now=WHEN, terminal=True)
        assert callbacks == [store.root]
        assert store.db.execute('SELECT status FROM acquisition_events ORDER BY sequence DESC LIMIT 1').fetchone()[0] == 'blocked'
        assert store.db.execute('SELECT COUNT(*) FROM public_rate_candidate_events').fetchone()[0] == 1


def test_collection_off_defers_registered_sources_without_starving_generic_documents(tmp_path, clock, monkeypatch):
    from tests.test_cdr_terms_acquisition_batch import add_source, BOM
    monkeypatch.setenv(collector.COLLECT_ENV, '0')
    calls = []
    monkeypatch.setattr('cdr_terms.acquisitions_queue.enqueue_interpretation',
                        lambda *args, **kwargs: pytest.fail('capture cannot run model interpretation'))
    def replay(url, **kwargs):
        calls.append(url)
        return {'status': 'fetched', 'http_status': 200, 'body': BOM.read_bytes(),
                'media_type': 'application/json', 'metadata': {'final_url': url}}
    monkeypatch.setattr(acquisition, 'fetch_document', replay)
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        requests = public.queue_sources(register, ingest_id='retained-public-fixture', now=WHEN)
        assert not acquisition_batch.has_work(store)
        assert AcquisitionQueue(store).next_due() is not None  # Explicit unit APIs remain usable.
        generic = add_source(store, ingest='generic-document-ingest', observed=WHEN)
        assert acquisition_batch.has_work(store)
        result = acquisition_batch.run_batch(store, registry_context={}, deadline=clock.elapsed + 105, guard=lambda: None)
        assert result['attempts'] > 0 and len(calls) == result['attempts']
        assert all(item['request_id'] not in requests for item in result['items'])
        assert not store.db.execute('SELECT 1 FROM acquisition_events WHERE request_id=? AND status!=\'queued\'', (requests[0],)).fetchone()
        assert budget.usage(store, 'retained-public-fixture') == {'bytes': 0, 'milliseconds': 0}
        assert store.db.execute('SELECT COUNT(*) FROM public_rate_checks').fetchone()[0] == 0
        assert store.db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0] == 0
        assert not collector.pending_candidate(store)


@pytest.mark.parametrize('publication_authority', [True, False])
def test_late_old_ingest_failure_dirties_active_shared_document_only(tmp_path, clock, monkeypatch, publication_authority):
    g0, g1, g2 = 'historical-shared-source', 'late-shared-source', 'active-shared-source'
    monkeypatch.setattr('cdr_public_rates_runtime.selected_public_generation', lambda root: g2 if publication_authority else None)
    warnings = []
    monkeypatch.setattr('cdr_public_rates_runtime.queue_source_warning', lambda root: warnings.append(read_source_state(root, g2)) or {'status': 'disabled'})
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store, generation=g0, observed_at='2026-10-13T11:50:00Z')
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at='2026-10-13T11:50:00Z')
        retain_reference_check(store, register, generation=g0, now='2026-10-13T11:50:00Z')
        retained_product(store, generation=g1, observed_at='2026-10-14T11:48:00Z')
        public.queue_sources(register, ingest_id=g1, now='2026-10-14T11:48:00Z')
        queue = AcquisitionQueue(store)
        late = queue.claim(now='2026-10-14T11:48:00Z')
        assert late['ingest_id'] == g1
        retained_product(store, generation=g2)
        retain_reference_check(store, register, generation=g2, now=WHEN)
        current = collector.write_candidate(store, generation=g2, run_date=WHEN[:10], register_id=register, as_of=WHEN)
        assert read_source_state(store.root, g2) is None
        history = store.db.execute('SELECT MAX(sequence) FROM public_rate_candidate_events WHERE ingest_id=?', (g0,)).fetchone()[0]
        unrelated = source_inventory(inventory_from_compiled({'products': [], 'programmes': []}, ['ANZ']))
        unrelated_register = public.register(unrelated, observed_at=WHEN)
        public.queue_sources(unrelated_register, ingest_id=g2, now=WHEN)
        clock.advance(1)
        check_id = digest([late['request_id'], late['lease_id']])
        store.record_check(document_id=late['document_id'], check_id=check_id, checked_at=clock.now(),
                           status='failed', error_code='http_error', http_status=503)
        queue.finish(late, check_id, now=clock.now(), terminal=True)
        assert read_source_state(store.root, g2)['events'][0]['status'] == 'dirty'
        assert warnings[-1]['generationId'] == g2
        latest = store.db.execute('SELECT event_id FROM public_rate_candidate_events WHERE ingest_id=? ORDER BY sequence DESC LIMIT 1', (g2,)).fetchone()[0]
        assert latest == digest([g2, register, check_id, 'dirty'])
        assert store.db.execute('SELECT MAX(sequence) FROM public_rate_candidate_events WHERE ingest_id=?', (g0,)).fetchone()[0] == history
        assert not store.db.execute('SELECT 1 FROM public_rate_candidate_events WHERE ingest_id=? AND register_id=?', (g2, unrelated_register)).fetchone()
        assert json.loads((store.root / 'public-rate-catalogue-candidate.json').read_bytes())['sha256'] == current['sha256']


def test_generic_accepted_failure_for_registered_document_invalidates_selected_generation(tmp_path, clock, monkeypatch):
    selected = 'selected-public-source'
    monkeypatch.setattr('cdr_public_rates_runtime.selected_public_generation', lambda root: selected)
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store, generation=selected)
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at=WHEN)
        retain_reference_check(store, register, generation=selected, now=WHEN)
        collector.write_candidate(store, generation=selected, run_date=WHEN[:10], register_id=register, as_of=WHEN)
        assert read_source_state(store.root, selected) is None
        # Deliberate generic-document protocol input, not a pricing fixture.
        record = {'productId': 'unit-generic-source', 'name': 'Unit generic document scope',
                  'additionalInformation': {'overviewUri': inventory['sources'][0]['url']}}
        origin = 'unit-generic-origin'
        body = canonical_json_bytes(record)
        observation = store.observe(provider='Unit provider', product_key='unit-generic-document', record=record,
                                    source_bytes=body, observed_at=WHEN, ingest_id=origin)
        with store.db:
            store.db.execute('INSERT INTO ingest_capture_attempts VALUES (?,?,?,?)', (origin, WHEN, WHEN, '{}'))
            store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,?)', (origin, store.put_blob(body), WHEN, 1))
        queue = AcquisitionQueue(store)
        queue.enqueue(observation, ingest_id=origin, now=WHEN)
        request = queue.claim(now=WHEN)
        assert request['ingest_id'] == origin
        assert not store.db.execute('SELECT 1 FROM public_rate_request_bindings WHERE request_id=?', (request['request_id'],)).fetchone()
        check_id = digest([request['request_id'], request['lease_id']])
        clock.advance(1)
        store.record_check(document_id=request['document_id'], check_id=check_id, checked_at=clock.now(),
                           status='failed', error_code='http_error', http_status=503)
        queue.finish(request, check_id, now=clock.now(), terminal=True)
        assert read_source_state(store.root, selected)['events'][0]['status'] == 'dirty'
        assert not store.db.execute('SELECT 1 FROM public_rate_candidate_events WHERE ingest_id=?', (origin,)).fetchone()
        assert store.db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0] == 0


def test_old_ingest_interpretation_after_active_snapshot_ack_wakes_active_generation_again(tmp_path, clock, monkeypatch):
    from tests.test_public_rate_sources import capture
    origin, selected = 'late-interpreted-source', 'selected-before-interpretation'
    monkeypatch.setattr('cdr_public_rates_runtime.selected_public_generation', lambda root: selected)
    with EvidenceStore(tmp_path / 'evidence') as store:
        _, _, inventory = retained_product(store, generation=origin, observed_at='2026-10-14T11:48:00Z')
        public = PublicRateStore(store)
        register = public.register(inventory, observed_at='2026-10-14T11:48:00Z')
        public.queue_sources(register, ingest_id=origin, now='2026-10-14T11:48:00Z')
        queue = AcquisitionQueue(store)
        request = queue.claim(now='2026-10-14T11:48:00Z')
        retained_product(store, generation=selected)
        public.queue_sources(register, ingest_id=selected, now=WHEN)
        body, context = capture('nab-indicator')
        check_id = digest([request['request_id'], request['lease_id']])
        store.record_check(document_id=request['document_id'], check_id=check_id, checked_at=WHEN,
                           status='fetched', body=body, media_type='application/pdf', http_status=200,
                           metadata={'final_url': context['sourceUrl']})
        queue.finish(request, check_id, now=WHEN)
        assert read_source_state(store.root, selected)['events'][0]['status'] == 'dirty'
        binding = public.bindings(request['document_id'], selected)[0]
        assert public.source_freshness(binding, ingest_id=selected, as_of=WHEN)['state'] == 'deferred'
        interim = collector.write_candidate(store, generation=selected, run_date=WHEN[:10], register_id=register, as_of=WHEN)
        assert interim['references'] == 0
        assert read_source_state(store.root, selected) is None
        acknowledged = store.db.execute('SELECT MAX(sequence) FROM public_rate_candidate_events WHERE ingest_id=?', (selected,)).fetchone()[0]
        check = dict(store.db.execute('SELECT * FROM acquisition_checks WHERE check_id=?', (check_id,)).fetchone())
        outcomes = public.record_check(request, check)
        assert len(outcomes) == 1 and outcomes[0]['status'] == 'validated'
        state = read_source_state(store.root, selected)
        assert state['events'][0]['status'] == 'dirty' and state['events'][0]['sequence'] > acknowledged
        assert state['events'][0]['eventId'] == digest([selected, register, check_id, 'interpretation_complete', binding['binding_id']])
        sequence = state['events'][0]['sequence']
        public.record_check(request, check)  # A repeated interpretation ack is idempotent.
        assert read_source_state(store.root, selected)['events'][0]['sequence'] == sequence
        completed = collector.write_candidate(store, generation=selected, run_date=WHEN[:10], register_id=register, as_of=WHEN)
        assert completed['references'] == 106 and read_source_state(store.root, selected) is None
        assert public.source_freshness(binding, ingest_id=selected, as_of=WHEN)['state'] == 'current'
        assert store.db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0] == 0
