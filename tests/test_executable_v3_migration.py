"""Isolated additive002 compatibility and resource controls."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import pytest
from cdr_terms.executable_v3_migration import migrate_monetary_registry, _snapshot
from cdr_terms.executable_v2_migration import migrate_registry
from cdr_terms.executable_registry import stage_subject, lookup_subject
from tests.executable_protocol_fixture import protocol, NOW
from tests.test_executable_v2_sources import v2_protocol


def prepared(protocol,v2_protocol):
    store,template,_,_=protocol
    stage_subject(store,template,interpreter='technical',staged_at=NOW)
    migrate_registry(store,applied_at=NOW)
    subject=v2_protocol[1]
    stage_subject(store,subject,interpreter='technical',staged_at=NOW)
    return store,template,subject


def test002_preserves_original_rows_and_dispatch(protocol,v2_protocol):
    store,template,subject=prepared(protocol,v2_protocol)
    before=_snapshot(store.db)
    migrate_monetary_registry(store,applied_at=NOW)
    after=_snapshot(store.db,before)
    assert before['rows']==after['rows']
    assert lookup_subject(store,template['id'])==template
    assert lookup_subject(store,subject['id'])==subject
    assert store.db.execute('PRAGMA user_version').fetchone()[0]==1
    migrate_monetary_registry(store,applied_at=NOW)
    with pytest.raises(sqlite3.IntegrityError,match='append-only'):
        store.db.execute('DELETE FROM executable_registry_migrations_v3')


def test002_installed_object_drift_refused(protocol,v2_protocol):
    store,_,_=prepared(protocol,v2_protocol)
    migrate_monetary_registry(store,applied_at=NOW)
    store.db.execute('DROP TRIGGER executable_subjects_v3_cas')
    with pytest.raises(ValueError,match='object missing'):
        migrate_monetary_registry(store,applied_at=NOW)


def test002_failure_rolls_back_views(protocol,v2_protocol,monkeypatch):
    store,_,_=prepared(protocol,v2_protocol)
    before=_snapshot(store.db)
    import cdr_terms.executable_v3_migration as module
    original=module._execute
    def fail(db,ddl):
        original(db,ddl)
        raise ValueError('technical rollback control')
    monkeypatch.setattr(module,'_execute',fail)
    with pytest.raises(ValueError,match='rollback control'):
        migrate_monetary_registry(store,applied_at=NOW)
    assert _snapshot(store.db)==before


def test002_two_initializers_observe_one_install(protocol,v2_protocol):
    store,_,_=prepared(protocol,v2_protocol)
    barrier=Barrier(2)
    def install():
        db=sqlite3.connect(store.root/'evidence.sqlite3',timeout=10)
        db.row_factory=sqlite3.Row; db.execute('PRAGMA foreign_keys=ON')
        try:
            barrier.wait(timeout=10)
            migrate_monetary_registry(SimpleNamespace(db=db,blobs=store.blobs,put_blob=store.put_blob,read_blob=store.read_blob),applied_at=NOW)
            return db.execute('SELECT ddl_sha256 FROM executable_registry_migrations_v3').fetchone()[0]
        finally: db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(install) for _ in range(2)]
        assert jobs[0].result(timeout=20)==jobs[1].result(timeout=20)


def test002_does_not_scan_unrelated_evidence_rows(protocol,v2_protocol):
    store,_,_=prepared(protocol,v2_protocol)
    # Synthetic unrelated history exceeds the executable row budget; no corpus read.
    store.db.execute('CREATE TABLE unrelated_history (value TEXT)')
    with store.db:
        store.db.execute("INSERT INTO unrelated_history VALUES(?)",('x'*(33*1024*1024),))
    statements=[];store.db.set_trace_callback(statements.append)
    try: migrate_monetary_registry(store,applied_at=NOW)
    finally: store.db.set_trace_callback(None)
    assert not any('FROM "unrelated_history"' in sql for sql in statements)


def test002_executable_row_byte_bound_still_refuses(protocol,v2_protocol):
    store,_,_=prepared(protocol,v2_protocol)
    store.db.execute('CREATE TABLE executable_technical_oversize (value TEXT)')
    with store.db: store.db.execute('INSERT INTO executable_technical_oversize VALUES(?)',('x'*(1024*1024+1),))
    with pytest.raises(ValueError,match='preservation bound'):
        migrate_monetary_registry(store,applied_at=NOW)
    assert store.db.execute("SELECT 1 FROM sqlite_master WHERE name='executable_subjects_v3'").fetchone() is None


def test002_keyboard_interrupt_rolls_back_without_signal(protocol,v2_protocol,monkeypatch):
    store,_,_=prepared(protocol,v2_protocol)
    before=_snapshot(store.db)
    import cdr_terms.executable_v3_migration as module
    original=module._execute
    def interrupt(db,ddl):
        original(db,ddl)
        raise KeyboardInterrupt('injected, no process signal')
    monkeypatch.setattr(module,'_execute',interrupt)
    with pytest.raises(KeyboardInterrupt):migrate_monetary_registry(store,applied_at=NOW)
    assert not store.db.in_transaction
    assert _snapshot(store.db)==before
