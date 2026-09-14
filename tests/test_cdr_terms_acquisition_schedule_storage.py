"""Private SQLite scheduling protocol, using retained CDR identities only.

Bulk terminal rows test selection/migration, not bank evidence or legal coverage.
No original database is opened. Production records remain append-only.
"""
import json
import sqlite3
import pytest

from cdr_terms.acquisition_processing import ProcessingQueue, SCHEDULE_DUE_SQL
from cdr_terms.acquisitions_queue import AcquisitionQueue, _after
from cdr_terms.identity import digest
from cdr_terms.store import EvidenceStore, DERIVED_MUTABLE_TABLES
from tests.test_cdr_terms_graph import retained
from tests.test_cdr_terms_acquisition_batch import clock, add_source
from tests.test_cdr_terms_acquisition_scheduling import capture


def ready(store, queue, clock):
    request = queue.claim()
    check = capture(store, queue, request, clock, defer=True)
    identity = digest([request['request_id'], check['check_id'], None])
    return request, check, identity


def terminal_rows(store, request, check, clock, count):
    parser = ProcessingQueue(store)
    with store.db:
        for i in range(count):
            identity = digest(['terminal-storage-protocol', i])
            store.db.execute('INSERT INTO acquisition_processing VALUES (?,?,?,?,?)',
                (identity, request['request_id'], check['check_id'], None, clock.now()))
            parser._event(identity, 'blocked', clock.now(), {'reason':'protocol_terminal_row'})


def test_terminal_volume_and_future_retries_use_selective_index(retained, clock, record_property):
    store, _, queue = retained
    request, check, active = ready(store, queue, clock)
    terminal_rows(store, request, check, clock, 2500)
    parser = ProcessingQueue(store)
    with store.db:
        # Make all old terminal hints priority0; partial index excludes them.
        store.db.execute("UPDATE acquisition_processing_schedule SET priority=0 WHERE status='blocked'")
        for i in range(250):
            identity = digest(['future-storage-protocol', i])
            store.db.execute('INSERT INTO acquisition_processing VALUES (?,?,?,?,?)',
                (identity, request['request_id'], check['check_id'], None, clock.now()))
            parser._event(identity, 'retry_wait', clock.now(), {}, retry_after=_after(clock.now(), 3600))
    vm_calls = []
    # Caller owns this handler. Scheduling must not replace or remove it.
    store.db.set_progress_handler(lambda: vm_calls.append(True) or 0, 1)
    try:
        task = parser.due()
        measured = len(vm_calls)
        store.db.execute('SELECT 1').fetchone()
        assert len(vm_calls) > measured
    finally:
        store.db.set_progress_handler(None, 0)
    assert task['processing_id'] == active and measured < 500
    plan = ' '.join(str(tuple(row)) for row in store.db.execute('EXPLAIN QUERY PLAN ' + SCHEDULE_DUE_SQL, (0,clock.now())))
    assert 'acquisition_processing_schedule_due' in plan and 'due_at<?' in plan
    assert 'TEMP B-TREE' not in plan
    record_property('due_query_vm_steps', measured)
    record_property('due_query_plan', plan)
    record_property('excluded_terminal_rows', 2500)
    record_property('future_retry_rows', 250)
    # Future priority0 rows cannot hide ready priority1/2 work either.
    with store.db:
        store.db.execute('UPDATE acquisition_processing_schedule SET priority=1 WHERE processing_id=?', (active,))
    assert parser.due()['processing_id'] == active


def test_existing_database_migration_is_incremental_resumable_and_idempotent(tmp_path, clock, monkeypatch):
    root = tmp_path/'old-private-store'
    with EvidenceStore(root) as store:
        add_source(store)
        request, check, active = ready(store, AcquisitionQueue(store), clock)
        terminal_rows(store, request, check, clock, 130)
        evidence_before = [tuple(row) for row in store.db.execute('SELECT * FROM acquisition_processing_events ORDER BY sequence')]
        # Remove only NEW derived caches in this disposable fixture to present
        # the exact pre-projection table layout on the next real Store reopen.
        with store.db:
            for name in DERIVED_MUTABLE_TABLES:
                store.db.execute('DROP TABLE ' + name)
    with EvidenceStore(root) as store:
        parser = ProcessingQueue(store)
        assert parser.schedule_incomplete() and parser.has_work()
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_processing_schedule').fetchone()[0] == 0
        with store.db:
            parser._backfill_schedule()
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_processing_schedule').fetchone()[0] == 64
        cursor = tuple(store.db.execute('SELECT * FROM acquisition_processing_schedule_migration').fetchone())
        original = parser._refresh_schedule
        calls=[]
        def crash(identity):
            result = original(identity)
            calls.append(identity)
            if len(calls) == 2:
                raise RuntimeError('isolated migration interruption')
            return result
        monkeypatch.setattr(parser, '_refresh_schedule', crash)
        with pytest.raises(RuntimeError, match='interruption'):
            with store.db:
                parser._backfill_schedule()
        assert tuple(store.db.execute('SELECT * FROM acquisition_processing_schedule_migration').fetchone()) == cursor
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_processing_schedule').fetchone()[0] == 64
    with EvidenceStore(root) as store:
        parser = ProcessingQueue(store)
        assert tuple(store.db.execute('SELECT * FROM acquisition_processing_schedule_migration').fetchone()) == cursor
        while parser.schedule_incomplete():
            before = store.db.execute('SELECT COUNT(*) FROM acquisition_processing_schedule').fetchone()[0]
            with store.db:
                parser._backfill_schedule()
            after = store.db.execute('SELECT COUNT(*) FROM acquisition_processing_schedule').fetchone()[0]
            assert 0 <= after-before <= 64
        assert after == 131
        assert parser.due()['processing_id'] == active
        assert [tuple(row) for row in store.db.execute('SELECT * FROM acquisition_processing_events ORDER BY sequence')] == evidence_before
    with EvidenceStore(root) as store:
        assert not ProcessingQueue(store).schedule_incomplete()
        assert store.db.execute('SELECT COUNT(*) FROM acquisition_processing_schedule').fetchone()[0] == 131


@pytest.mark.parametrize('mismatch', ['event','priority','due','created','evidence'])
def test_projection_mismatch_is_reconciled_against_authority(retained, clock, mismatch):
    store, _, queue = retained
    _, _, identity = ready(store, queue, clock)
    parser = ProcessingQueue(store)
    if mismatch == 'event':
        old = store.db.execute('SELECT event_id FROM acquisition_processing_schedule WHERE processing_id=?',(identity,)).fetchone()[0]
        with store.db:
            parser._event(identity, 'blocked', clock.now(), {'reason':'explicit_protocol_terminal'})
            store.db.execute("UPDATE acquisition_processing_schedule SET event_id=?,status='queued' WHERE processing_id=?",(old,identity))
        assert parser.claim() is None
        assert store.db.execute("SELECT COUNT(*) FROM acquisition_processing_events WHERE processing_id=? AND status='running'",(identity,)).fetchone()[0] == 0
    else:
        column, value = {'priority':('priority',1),'due':('due_at','2000-01-01T00:00:00.000000Z'),
                         'created':('created_at','2000-01-01T00:00:00.000000Z'),'evidence':('evidence_json','{}')}[mismatch]
        with store.db:
            store.db.execute('UPDATE acquisition_processing_schedule SET '+column+'=? WHERE processing_id=?',(value,identity))
        task = parser.claim()
        assert task['status']=='running' and task['processing_id']==identity
        # Running event uses a new exact projection; tampered hint was not used.
        projected = store.db.execute('SELECT * FROM acquisition_processing_schedule WHERE processing_id=?',(identity,)).fetchone()
        event = store.db.execute('SELECT * FROM acquisition_processing_events WHERE processing_id=? ORDER BY sequence DESC LIMIT 1',(identity,)).fetchone()
        assert projected['event_id']==event['event_id'] and projected['status']=='running'


def test_projection_failure_cannot_commit_a_new_event_even_if_caller_catches(retained, clock, monkeypatch):
    store, _, queue = retained
    _, _, identity=ready(store,queue,clock)
    parser=ProcessingQueue(store)
    before=[tuple(row) for row in store.db.execute('SELECT * FROM acquisition_processing_events WHERE processing_id=?',(identity,))]
    hint=tuple(store.db.execute('SELECT * FROM acquisition_processing_schedule WHERE processing_id=?',(identity,)).fetchone())
    def failed(*args):
        raise RuntimeError('isolated projection failure')
    monkeypatch.setattr(parser,'_refresh_schedule',failed)
    with store.db:
        with pytest.raises(RuntimeError, match='projection failure'):
            parser._event(identity,'blocked',clock.now(),{'reason':'must_rollback'})
    assert [tuple(row) for row in store.db.execute('SELECT * FROM acquisition_processing_events WHERE processing_id=?',(identity,))]==before
    assert tuple(store.db.execute('SELECT * FROM acquisition_processing_schedule WHERE processing_id=?',(identity,)).fetchone())==hint


def test_capture_and_processing_projection_commit_together(retained, clock, monkeypatch):
    store, _, queue=retained
    request=queue.claim()
    check_id=digest([request['request_id'],request['lease_id']])
    from tests.test_cdr_terms_acquisition_batch import BOM
    store.record_check(document_id=request['document_id'],check_id=check_id,checked_at=clock.now(),
                       status='fetched',body=BOM.read_bytes(),media_type='application/json')
    original=ProcessingQueue._refresh_schedule
    def failed(*args):
        raise RuntimeError('isolated schedule write failure')
    monkeypatch.setattr(ProcessingQueue,'_refresh_schedule',failed)
    with pytest.raises(RuntimeError,match='schedule write failure'):
        queue.finish(request,check_id,defer_processing=True)
    event=store.db.execute('SELECT * FROM acquisition_events WHERE request_id=? ORDER BY sequence DESC LIMIT 1',(request['request_id'],)).fetchone()
    assert event['status']=='running' and event['lease_id']==request['lease_id']
    for table in ('acquisition_processing','acquisition_processing_events','acquisition_processing_schedule'):
        assert store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
    monkeypatch.setattr(ProcessingQueue,'_refresh_schedule',original)
    queue.finish(request,check_id,defer_processing=True)
    assert ProcessingQueue(store).due()['check_id']==check_id


def test_orphan_capture_cannot_confer_changed_current_priority(retained, clock):
    store, _, queue=retained
    request=queue.claim()
    from tests.test_cdr_terms_acquisition_batch import BOM
    store.record_check(document_id=request['document_id'],check_id='protocol-orphan',checked_at=clock.now(),
                       status='fetched',body=BOM.read_bytes(),media_type='application/json')
    check=capture(store,queue,request,clock,defer=True)
    task=ProcessingQueue(store).due()
    assert task['check_id']==check['check_id'] and task['schedule_priority']==0


def test_equal_priority_due_and_created_are_ordered_by_processing_identity(retained, clock):
    store, _, queue=retained
    ids=[]
    while queue.next_due():
        request, check, identity=ready(store,queue,clock)
        ids.append(identity)
    parser=ProcessingQueue(store)
    assert parser.due()['processing_id']==min(ids)
    first=parser.claim()
    assert first['processing_id']==min(ids)
    ids.remove(first['processing_id'])
    assert parser.due()['processing_id']==min(ids)


def test_only_explicit_derived_tables_are_mutable(retained, clock):
    store, _, queue=retained
    _, _, identity=ready(store,queue,clock)
    assert DERIVED_MUTABLE_TABLES == {'acquisition_processing_schedule','acquisition_processing_schedule_migration'}
    tables=[row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    triggers={row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    for table in tables:
        for operation in ('UPDATE','DELETE'):
            assert ('immutable_'+table+'_'+operation in triggers) == (table not in DERIVED_MUTABLE_TABLES)
    with pytest.raises(sqlite3.IntegrityError,match='append-only'):
        store.db.execute('DELETE FROM acquisition_processing WHERE processing_id=?',(identity,))
