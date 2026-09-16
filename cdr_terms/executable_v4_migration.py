"""Explicit additive003; retain all prior rows and atomically extend registry views."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from .identity import canonical_json, timestamp
from .executable_v4_contract import ROOT
from .executable_v3_migration import (_execute, _snapshot, _objects, _expected_objects,
                                    _schema_receipt, _verify_predecessor_objects,
                                    ROOT as V3_ROOT, DDL_SHA as V3_SHA)

MIGRATION = '003_savings_activity_v4'
DDL_SHA = '070efdabe942b0b3f6d0abffd4507ed0fda47972e554d0be3315c22b6a6956b1'
VIEWS = {'executable_registry_subjects', 'executable_registry_reviews'}


def _prior_schema(db):
    """Compare frozen002 objects independently of its subsequently upgraded views."""
    from .executable_v2_migration import ROOT as V2_ROOT, ADDED
    _verify_predecessor_objects(db, True)
    ddl = (V3_ROOT / 'storage/002_monetary_wire3.sql').read_bytes()
    if hashlib.sha256(ddl).hexdigest() != V3_SHA:
        raise ValueError('Activity predecessor DDL bytes differ')
    with closing(sqlite3.connect(':memory:')) as expected:
        expected.row_factory = sqlite3.Row
        _execute(expected, Path(__file__).with_name('schema.sql').read_bytes())
        _execute(expected, (V2_ROOT / '001_executable_registry_v2.sql').read_bytes())
        for table in ADDED:
            for operation in ('UPDATE', 'DELETE'):
                expected.execute(f'CREATE TRIGGER "immutable_{table}_{operation}" BEFORE {operation} ON "{table}" '
                                 "BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END")
        _execute(expected, ddl)
        reference = _expected_objects(expected, ddl)
    actual = _objects(db)
    for name, definition in reference.items():
        if name in VIEWS: continue
        if name not in actual or any(actual[name][key] != value for key, value in definition.items()):
            raise ValueError('Activity predecessor installed schema differs: ' + name)


def migrate_activity_registry(store, *, applied_at):
    ddl = (ROOT / 'storage/003_savings_activity_v4.sql').read_bytes()
    if hashlib.sha256(ddl).hexdigest() != DDL_SHA:
        raise ValueError('Activity DDL identity differs')
    db = store.db
    if db.in_transaction or db.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise ValueError('Activity migration requires own transaction and foreign keys')
    try:
        db.execute('BEGIN IMMEDIATE')
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='executable_registry_migrations_v3'").fetchone()
        prior = db.execute("SELECT ddl_sha256 FROM executable_registry_migrations_v3 WHERE migration_id='002_monetary_v3'").fetchone() if exists else None
        if prior is None or prior[0] != V3_SHA:
            raise ValueError('Activity migration requires frozen002 predecessor')
        _prior_schema(db)
        present = db.execute("SELECT 1 FROM sqlite_master WHERE name='executable_registry_migrations_v4'").fetchone()
        if present:
            row = db.execute('SELECT * FROM executable_registry_migrations_v4 WHERE migration_id=?', (MIGRATION,)).fetchone()
            if row is None or row['ddl_sha256'] != DDL_SHA or row['predecessor_ddl_sha256'] != V3_SHA:
                raise ValueError('Activity migration marker differs')
            if _schema_receipt(store, row['schema_receipt_sha256']) != _expected_objects(db, ddl):
                raise ValueError('Activity installed schema differs')
        else:
            before = _snapshot(db)
            _execute(db, ddl)
            after = _snapshot(db, before)
            if before['rows'] != after['rows'] or before['columns'] != after['columns']:
                raise ValueError('Activity migration changed original evidence')
            for name, definition in before['objects'].items():
                if name not in VIEWS and after['objects'][name] != definition:
                    raise ValueError('Activity migration changed original schema')
            preservation = store.put_blob(canonical_json(before).encode('utf8'))
            raw = canonical_json(_expected_objects(db, ddl)).encode('utf8')
            if len(raw) > 1024 * 1024: raise ValueError('Activity schema receipt bound exceeded')
            schema = store.put_blob(raw)
            db.execute('INSERT INTO executable_registry_migrations_v4 VALUES(?,?,?,?,?,?,?)',
                       (MIGRATION, '002_monetary_v3', V3_SHA, DDL_SHA, preservation, schema, timestamp(applied_at)))
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Activity migration foreign key violation')
        db.commit()
    except BaseException:
        db.rollback()
        raise
