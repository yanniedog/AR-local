"""Isolated migration controls; never operate on a production archive."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from cdr_terms.executable_v2_migration import _legacy, migrate_registry
from tests.executable_protocol_fixture import protocol, NOW
from cdr_terms.executable_reviews import stage_template


def test_migration_preserves_legacy_and_owns_atomic_transaction(protocol):
    store, template, _, _ = protocol
    stage_template(store, template, interpreter='technical-author', staged_at=NOW)
    before = _legacy(store)
    migrate_registry(store, applied_at=NOW)
    assert _legacy(store) == before
    assert store.db.execute('PRAGMA user_version').fetchone()[0] == 1
    assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    assert store.db.execute('SELECT COUNT(*) FROM executable_registry_subjects').fetchone()[0] == 1
    migrate_registry(store, applied_at=NOW)
    with pytest.raises(sqlite3.IntegrityError, match='append-only'):
        store.db.execute('DELETE FROM executable_registry_migrations')


def test_migration_does_not_commit_existing_transaction(protocol):
    store = protocol[0]
    store.db.execute('BEGIN IMMEDIATE')
    with pytest.raises(ValueError, match='own transaction'):
        migrate_registry(store, applied_at=NOW)
    assert store.db.in_transaction
    store.db.rollback()
    assert not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='executable_registry_migrations'").fetchone()


def test_migration_failure_rolls_back_ddl(protocol, monkeypatch):
    store = protocol[0]
    import cdr_terms.executable_v2_migration as migration
    original, calls = migration._legacy, []
    def altered(current):
        value = original(current)
        calls.append(True)
        return value if len(calls) == 1 else {}
    monkeypatch.setattr(migration, '_legacy', altered)
    with pytest.raises(ValueError, match='changed legacy'):
        migrate_registry(store, applied_at=NOW)
    assert not store.db.in_transaction
    assert not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='executable_scopes_v2'").fetchone()


def test_two_first_initializers_verify_same_committed_migration(protocol):
    store = protocol[0]
    barrier = Barrier(2)
    def initialize():
        db = sqlite3.connect(store.root / 'evidence.sqlite3', timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            barrier.wait(timeout=10)
            migrate_registry(SimpleNamespace(db=db, put_blob=store.put_blob), applied_at=NOW)
            return db.execute('SELECT ddl_sha256 FROM executable_registry_migrations').fetchone()[0]
        finally:
            db.close()
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(initialize) for _ in range(2)]
        first, second = [future.result(timeout=20) for future in futures]
    assert first == second
    assert store.db.execute('SELECT COUNT(*) FROM executable_registry_migrations').fetchone()[0] == 1


def test_oversized_legacy_row_refused_before_fetch(protocol):
    store, template, _, _ = protocol
    with store.db:
        store.db.execute('INSERT INTO executable_templates(template_id,observation_id,product_key,cohort_key,rate_index,interpreter,staged_at,template_json) VALUES(?,?,?,?,?,?,?,?)',
            ('0'*64, template['sourceObservationId'],template['productKey'],'technical',1,'technical',NOW,'x'*(1024*1024+1)))
    with pytest.raises(ValueError, match='verification bound'):
        migrate_registry(store, applied_at=NOW)
    assert not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='executable_scopes_v2'").fetchone()
