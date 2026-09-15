"""Transactional additive registry migration; never reinterpret old approvals."""
import json
import hashlib
import sqlite3

from .executable_v2_contract import ROOT
from .identity import byte_digest, timestamp

MIGRATION = '001_scoped_eligibility_v2'
LEGACY = ('executable_templates', 'executable_template_terms', 'executable_template_documents',
          'executable_reviews', 'executable_review_predecessors', 'executable_publications')
ADDED = ('executable_registry_migrations', 'executable_scopes_v2', 'executable_subjects_v2',
         'executable_subject_terms_v2', 'executable_subject_documents_v2', 'executable_reviews_v2', 'executable_publications_v2')


def _legacy(store):
    result, size = {}, 0
    for table in LEGACY:
        columns = [r['name'] for r in store.db.execute('PRAGMA table_info(' + table + ')')]
        lengths = '+'.join('COALESCE(length(CAST("' + name + '" AS BLOB)),0)' for name in columns)
        checksum, count = hashlib.sha256(b'['), 0
        for pointer in store.db.execute('SELECT rowid AS rid,' + lengths + ' AS size FROM ' + table + ' ORDER BY rowid'):
            if count >= 100000 or pointer['size'] > 1024 * 1024 or size + pointer['size'] > 16 * 1024 * 1024:
                raise ValueError('Executable migration legacy verification bound exceeded')
            row = dict(store.db.execute('SELECT * FROM ' + table + ' WHERE rowid=?', (pointer['rid'],)).fetchone())
            body = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf8')
            size += len(body) + 1
            if size > 16 * 1024 * 1024:
                raise ValueError('Executable migration legacy byte bound exceeded')
            if count:
                checksum.update(b',')
            checksum.update(body)
            count += 1
        checksum.update(b']')
        result[table] = {'rows': count, 'sha256': checksum.hexdigest()}
    return result


def migrate_registry(store, *, applied_at):
    ddl = (ROOT / '001_executable_registry_v2.sql').read_bytes()
    identity = byte_digest(ddl)
    if store.db.in_transaction:
        raise ValueError('Executable migration needs its own transaction')
    try:
        store.db.execute('BEGIN IMMEDIATE')
        present = store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='executable_registry_migrations'").fetchone()
        if present:
            marker = store.db.execute('SELECT * FROM executable_registry_migrations WHERE migration_id=?', (MIGRATION,)).fetchone()
            if marker is None or marker['ddl_sha256'] != identity:
                raise ValueError('Executable registry migration identity mismatch')
            store.db.commit()
            return
        before = _legacy(store)
        statement = ''
        for line in ddl.decode('utf8').splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                store.db.execute(statement)
                statement = ''
        for table in ADDED:
            for operation in ('UPDATE', 'DELETE'):
                store.db.execute(f'CREATE TRIGGER "immutable_{table}_{operation}" BEFORE {operation} ON "{table}" '
                                 "BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END")
        if store.db.execute('PRAGMA foreign_key_check').fetchone() or _legacy(store) != before:
            raise ValueError('Executable registry migration changed legacy evidence')
        receipt = store.put_blob(json.dumps({'legacy': before, 'ddlSha256': identity}, sort_keys=True).encode())
        store.db.execute('INSERT INTO executable_registry_migrations VALUES (?,?,?,?)',
                         (MIGRATION, identity, timestamp(applied_at), receipt))
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise
