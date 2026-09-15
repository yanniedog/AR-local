"""Transport/worker admission and current-source scheduling protocol controls."""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdr_terms.ingest import registry_context

import pi_terms_acquire
from cdr_terms import acquisition as http
from cdr_terms import acquisition_batch as batch
from cdr_terms.acquisitions_queue import AcquisitionQueue
from cdr_terms.identity import digest
from cdr_terms.store import EvidenceStore
from pi_terms_codex import write_receipt
from tests.test_cdr_terms_acquisition_batch import BOM, FIXTURES, add_source, clock, replay, retained, run
from tests.test_cdr_terms_graph import Connection, Response


def test_each_redirect_checks_runtime_guard_before_next_connection(monkeypatch):
    connections, requests, guards = [], [], []
    def guard():
        guards.append(True)
        return None if len(guards) == 1 else 'publication_pending'
    def connect(*args):
        connections.append(args[0])
        return Connection(Response(302, {'Location': '/redirected'}), requests)
    monkeypatch.setattr(http, '_connection', connect)
    with pytest.raises(http.FetchFailure, match='operational_guard:publication_pending'):
        http.fetch_document('https://www.bankofmelbourne.com.au/', policy=http.FetchPolicy(request_guard=guard))
    assert len(guards) == 2 and len(connections) == 1


def test_guard_exception_fails_closed_before_connection(monkeypatch):
    monkeypatch.setattr(http, '_connection', lambda *a: pytest.fail('no connection'))
    def guard():
        raise OSError('protocol unavailable')
    with pytest.raises(http.FetchFailure, match='operational_guard_unavailable'):
        http.fetch_document('https://www.bankofmelbourne.com.au/', policy=http.FetchPolicy(request_guard=guard))


def test_current_document_recheck_does_not_jump_ahead_of_never_attempted_urls(retained, clock, monkeypatch):
    replay(monkeypatch, clock)
    value = run(retained, clock, limits=batch.BatchLimits(attempts=1))
    first = value['items'][0]
    document = retained.db.execute('SELECT document_id FROM acquisition_checks WHERE check_id=?', (first['check_id'],)).fetchone()[0]
    source = retained.db.execute('SELECT o.* FROM observations o JOIN acquisition_bindings b USING(observation_id) WHERE b.request_id=?', (first['request_id'],)).fetchone()
    record = json.loads(retained.read_blob(source['source_sha256']))
    path = next(path for path in FIXTURES.glob('*-null-detail.json') if json.loads(path.read_bytes())['data']['productId'] == record['data']['productId'])
    add_source(retained, path, ingest='next-current', observed='2026-09-08T00:00:00Z')
    next_request = AcquisitionQueue(retained).next_due(fair=True)
    assert next_request['document_id'] != document
    # An orphan check cannot falsely update fair accepted-attempt history.
    retained.record_check(document_id=next_request['document_id'], check_id='orphan-fairness-control',
                           checked_at=clock.now(), status='failed', error_code='isolated-orphan')
    assert AcquisitionQueue(retained).next_due(fair=True)['request_id'] == next_request['request_id']


def test_shared_document_preserves_unsuperseded_product_binding(tmp_path, clock):
    with EvidenceStore(tmp_path / 'shared') as store:
        first = add_source(store)
        other_path = Path(__file__).parent / 'fixtures/cdr-document-graph-2026-05-19/bom-variable.json'
        second = add_source(store, other_path)
        shared = store.db.execute('SELECT request_id FROM acquisition_bindings WHERE observation_id IN (?,?) '
                                  'GROUP BY request_id HAVING COUNT(*)=2 LIMIT 1', (first, second)).fetchone()
        assert shared is not None  # Two real products share the retained bank URL.
        add_source(store, ingest='next-current', observed='2026-09-08T00:00:00Z')
        request = dict(store.db.execute('SELECT * FROM acquisition_requests WHERE request_id=?', (shared[0],)).fetchone())
        observations, hosts, proof = batch.request_scope(store, request)
        assert observations == [second] and hosts and proof == {}
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_bindings WHERE request_id=?', (shared[0],)).fetchone()[0] == 2


def test_parent_deadline_is_not_reset_after_child_startup(retained, clock, monkeypatch, tmp_path):
    operation = tmp_path / 'operation'
    operation.mkdir(mode=0o700)
    write_receipt(operation / 'input.json', {'evidence_root': str(retained.root), 'registry_context': registry_context(), 'admission_deadline': 105})
    clock.advance(106)
    monkeypatch.setattr(pi_terms_acquire, 'runtime_guard', lambda *a: lambda: None)
    monkeypatch.setattr(http, 'fetch_document', lambda *a, **k: pytest.fail('expired parent admission cannot fetch'))
    value = pi_terms_acquire.run(operation)
    assert value['stop_reason'] == 'admission_deadline' and value['attempts'] == 0
    assert value['remaining']['due'] == 24


def test_runtime_guard_reuses_host_rss_and_window_thresholds(monkeypatch, tmp_path):
    import pi_cdr_quality_resources as resources
    import pi_terms_worker as worker
    from tests.test_cdr_quality_resources import host
    monkeypatch.setattr(worker, 'priority_guard', lambda *a: None)
    window = [True]
    monkeypatch.setattr(worker, 'operating_window', lambda *a: window[0])
    monkeypatch.setattr(resources, 'host_sample', host)
    monkeypatch.setattr(resources, 'own_cgroup', lambda: tmp_path)
    usage = {'rss_bytes': 100, 'swap_bytes': 0}
    monkeypatch.setattr(resources, 'aggregate', lambda _: usage)
    guard = pi_terms_acquire.runtime_guard(tmp_path, tmp_path)
    assert guard() is None
    usage['rss_bytes'] = resources.Limits().workload_bytes - resources.Limits().margin_bytes
    assert guard() == 'aggregate_rss_early_stop'
    window[0] = False
    assert guard() == 'outside_analysis_window'


def test_obsolete_maintenance_is_bounded_and_keeps_every_old_request(tmp_path, clock, monkeypatch):
    with EvidenceStore(tmp_path / 'obsolete') as store:
        add_source(store)
        add_source(store, ingest='next', observed='2026-09-08T00:00:00Z')
        calls = replay(monkeypatch, clock)
        value = run(store, clock, limits=batch.BatchLimits(maintenance=1))
        assert len(value['dispositions']) == 1 and value['stop_reason'] == 'maintenance_budget'
        assert len(calls) == 0
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_requests').fetchone()[0] == 6
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_dispositions').fetchone()[0] == 1
        value = run(store, clock)
        assert len(calls) == 3 and len(value['dispositions']) == 2


def test_128_dispositions_fit_bounded_batch_and_small_transport_receipts(tmp_path, clock, monkeypatch):
    from pi_terms_worker import read_acquisition_batch
    evidence, operation = tmp_path / 'proofs', tmp_path / 'operation'
    operation.mkdir(mode=0o700)
    with EvidenceStore(evidence) as store:
        for index in range(44):
            # Repeated source observations test generation accounting only.
            observed = (datetime(2026, 9, 7, tzinfo=timezone.utc) + timedelta(minutes=index)).isoformat()
            add_source(store, ingest='protocol-generation-' + str(index), observed=observed)
    write_receipt(operation / 'input.json', {'evidence_root': str(evidence), 'registry_context': registry_context(), 'admission_deadline': 105})
    monkeypatch.setattr(pi_terms_acquire, 'runtime_guard', lambda *_: lambda: None)
    monkeypatch.setattr(http, 'fetch_document', lambda *_a, **_k: pytest.fail('maintenance bound stops before current capture'))
    value = pi_terms_acquire.run(operation)
    assert len(value['dispositions']) == 128 and value['stop_reason'] == 'maintenance_budget'
    assert (operation / 'acquisition.json').stat().st_size < 16 * 1024
    assert 16 * 1024 < (operation / 'batch.json').stat().st_size < 64 * 1024
    assert read_acquisition_batch(operation) == value
    with EvidenceStore(evidence) as store:
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_requests').fetchone()[0] == 132
        for item in value['dispositions']:
            proof = json.loads(store.db.execute('SELECT evidence_json FROM acquisition_dispositions WHERE request_id=?', (item['request_id'],)).fetchone()[0])
            assert digest(proof) == item['disposition_sha256'] and proof['obsolete']
    body = (operation / 'batch.json').read_bytes()
    (operation / 'batch.json').write_bytes(body + b' ')
    with pytest.raises(ValueError, match='bound acquisition batch'):
        read_acquisition_batch(operation)


def test_acquisition_artifact_rejects_links_reparse_and_oversize_before_read(tmp_path, monkeypatch):
    from pi_terms_worker import read_acquisition_file
    root = tmp_path / 'operation'
    root.mkdir(mode=0o700)
    artifact = root / 'batch.json'
    artifact.write_bytes(b'{}')
    os.link(artifact, root / 'linked.json')
    with pytest.raises(ValueError, match='unlinked'):
        read_acquisition_file(root, 'batch.json', 64 * 1024)
    (root / 'linked.json').unlink()
    with pytest.raises(ValueError, match='unlinked'):
        read_acquisition_file(root, 'batch.json', 1)
    original = Path.lstat
    def reparse(path):
        return SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=1, st_size=2, st_file_attributes=0x400) if path == artifact else original(path)
    monkeypatch.setattr(Path, 'lstat', reparse)
    with pytest.raises(ValueError, match='unlinked'):
        read_acquisition_file(root, 'batch.json', 64 * 1024)


def test_acquisition_artifact_rejects_changed_identity_and_missing_file(tmp_path, monkeypatch):
    from pi_terms_worker import read_acquisition_file
    root = tmp_path / 'operation'
    root.mkdir(mode=0o700)
    with pytest.raises(OSError):
        read_acquisition_file(root, 'batch.json', 64 * 1024)
    artifact = root / 'batch.json'
    artifact.write_bytes(b'{}')
    original = os.fstat
    def changed(descriptor):
        info = original(descriptor)
        return SimpleNamespace(st_mode=info.st_mode, st_nlink=1, st_size=info.st_size, st_dev=info.st_dev,
                               st_ino=info.st_ino + 1, st_mtime_ns=info.st_mtime_ns)
    monkeypatch.setattr(os, 'fstat', changed)
    with pytest.raises(ValueError, match='changed before read'):
        read_acquisition_file(root, 'batch.json', 64 * 1024)
