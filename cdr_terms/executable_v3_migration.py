"""Explicit additive monetary migration; original evidence remains byte-identical."""
import base64
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from .identity import canonical_json, timestamp, require_sha

ROOT = Path(__file__).resolve().parents[1] / 'contracts/product_terms/monetary-v3'
MIGRATION = '002_monetary_v3'
DDL_SHA = '42c6935dfb97f2eb4e91be9dd9878b9340d74c642e804aee8bbbb80e41e477a4'
PREDECESSOR_SHA = '3b7b03fab6df44df146fdede08ad75d8687918e18e17560478323035e7e3c560'
MAX_BYTES = 32 * 1024 * 1024


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _typed(value):
    if value is None:
        return ['null', None]
    if isinstance(value, bytes):
        return ['blob', base64.b64encode(value).decode('ascii')]
    return [type(value).__name__, value]


def _rows(db, name, columns, budget, *, view=False):
    names = ','.join(_quote(c) for c in columns)
    sizes = '+'.join('COALESCE(length(CAST('+_quote(c)+' AS BLOB)),0)' for c in columns)
    table = _quote(name)
    # Preflight lengths without transferring a potentially huge value to Python.
    count = 0
    for (size,) in db.execute('SELECT '+sizes+' FROM '+table):
        count += 1
        budget[0] += size
        if count > 100000 or size > 1024*1024 or budget[0] > MAX_BYTES:
            raise ValueError('Monetary migration preservation bound exceeded')
    checksum = hashlib.sha256()
    order = names if view else 'rowid'
    for row in db.execute('SELECT '+names+' FROM '+table+' ORDER BY '+order):
        body = json.dumps([_typed(v) for v in row],ensure_ascii=False,separators=(',',':')).encode('utf8')
        budget[1] += len(body)
        if len(body)>2*1024*1024 or budget[1]>MAX_BYTES:
            raise ValueError('Monetary migration typed byte bound exceeded')
        checksum.update(len(body).to_bytes(8,'big')); checksum.update(body)
    return {'rows': count, 'sha256': checksum.hexdigest()}


def _objects(db):
    # Bound metadata before transferring SQL definitions into Python.
    counts=db.execute("SELECT count(*),COALESCE(sum(length(CAST(sql AS BLOB))),0),COALESCE(max(length(CAST(sql AS BLOB))),0) FROM sqlite_master").fetchone()
    if counts[0]>4096 or counts[1]>8*1024*1024 or counts[2]>256*1024:
        raise ValueError('Monetary schema metadata bound exceeded')
    objects = {r['name']:dict(r) for r in db.execute("SELECT name,type,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_autoindex%' ORDER BY name")}
    return objects


def _snapshot(db, originals=None):
    objects = _objects(db)
    selected = objects if originals is None else originals['objects']
    budget, rows, columns = [0,0], {}, {}
    for name,obj in selected.items():
        if name not in objects:
            raise ValueError('Original monetary migration object missing')
        if obj['type'] not in ('table','view') or not (name.startswith('executable_') or name=='sqlite_sequence'):
            continue
        cols = ([r['name'] for r in db.execute('PRAGMA table_info('+_quote(name)+')')]
                if originals is None else originals['columns'][name])
        columns[name] = cols
        rows[name] = _rows(db,name,cols,budget,view=obj['type']=='view')
    return {'objects':{n:objects[n] for n in selected},'rows':rows,'columns':columns,
            'rowScope':'existing executable v1/v2 tables and views plus sqlite_sequence; original evidence tables receive no DML'}


def _execute(db, ddl):
    statement = ''
    for line in ddl.decode('utf8').splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement); statement = ''
    if any(line.strip() and not line.lstrip().startswith('--') for line in statement.splitlines()):
        raise ValueError('Incomplete monetary migration statement')


def _expected_objects(db, ddl):
    names = re.findall(r'^CREATE (?:TABLE|INDEX|TRIGGER|VIEW) ([A-Za-z0-9_]+)',ddl.decode('utf8'),re.MULTILINE)
    result, objects = {}, _objects(db)
    for name in names:
        row = objects.get(name)
        if row is None:
            raise ValueError('Monetary migration installed object missing')
        result[name] = {k:row[k] for k in ('type','tbl_name','sql')}
    return result


def _schema_receipt(store, identity):
    require_sha(identity)
    with (store.blobs/identity[:2]/identity).open('rb') as stream:
        raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024 or hashlib.sha256(raw).hexdigest()!=identity:
        raise ValueError('Monetary schema receipt bound/integrity differs')
    return json.loads(raw)


def _verify_predecessor_objects(db, upgraded):
    from .executable_v2_migration import ROOT as PRIOR_ROOT, ADDED
    ddl=(PRIOR_ROOT/'001_executable_registry_v2.sql').read_bytes()
    if hashlib.sha256(ddl).hexdigest()!=PREDECESSOR_SHA:raise ValueError('Frozen001 DDL bytes changed')
    with closing(sqlite3.connect(':memory:')) as expected:
        expected.row_factory=sqlite3.Row
        _execute(expected,Path(__file__).with_name('schema.sql').read_bytes())
        _execute(expected,ddl)
        for table in ADDED:
            for operation in ('UPDATE','DELETE'):
                expected.execute(f'CREATE TRIGGER "immutable_{table}_{operation}" BEFORE {operation} ON "{table}" '
                    "BEGIN SELECT RAISE(ABORT,'terms evidence is append-only'); END")
        reference=_expected_objects(expected,ddl)
        objects=_objects(expected)
        for table in ADDED:
            for operation in ('UPDATE','DELETE'):
                name=f'immutable_{table}_{operation}'
                reference[name]={k:objects[name][k] for k in ('type','tbl_name','sql')}
    actual=_objects(db)
    for name,definition in reference.items():
        if upgraded and name in ('executable_registry_subjects','executable_registry_reviews'):continue
        if name not in actual or any(actual[name][key]!=value for key,value in definition.items()):
            raise ValueError('Frozen001 installed schema differs: '+name)


def migrate_monetary_registry(store, *, applied_at):
    ddl = (ROOT/'storage/002_monetary_wire3.sql').read_bytes()
    if hashlib.sha256(ddl).hexdigest()!=DDL_SHA:
        raise ValueError('Frozen monetary DDL bytes changed')
    db = store.db
    if db.in_transaction or db.execute('PRAGMA foreign_keys').fetchone()[0]!=1:
        raise ValueError('Monetary migration requires own transaction and foreign keys')
    try:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute("SELECT ddl_sha256 FROM executable_registry_migrations WHERE migration_id='001_scoped_eligibility_v2'").fetchone()
        if prior is None or prior[0]!=PREDECESSOR_SHA:
            raise ValueError('Frozen001 predecessor required')
        present = db.execute("SELECT 1 FROM sqlite_master WHERE name='executable_registry_migrations_v3' AND type='table'").fetchone()
        _verify_predecessor_objects(db,bool(present))
        if present:
            row = db.execute('SELECT * FROM executable_registry_migrations_v3 WHERE migration_id=?',(MIGRATION,)).fetchone()
            if row is None or row['ddl_sha256']!=DDL_SHA or row['predecessor_ddl_sha256']!=PREDECESSOR_SHA:
                raise ValueError('Monetary migration marker differs')
            expected = _schema_receipt(store,row['schema_receipt_sha256'])
            if expected != _expected_objects(db,ddl) or db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Monetary installed schema differs')
            db.commit(); return
        before = _snapshot(db)
        _execute(db,ddl)
        after = _snapshot(db,before)
        for name,obj in before['objects'].items():
            if obj['type']!='view' and after['objects'][name]!=obj:
                raise ValueError('Monetary migration changed original schema')
        if before['rows']!=after['rows'] or before['columns']!=after['columns'] or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Monetary migration changed original evidence')
        preservation = store.put_blob(canonical_json(before).encode('utf8'))
        schema_raw = canonical_json(_expected_objects(db,ddl)).encode('utf8')
        if len(schema_raw)>1024*1024: raise ValueError('Monetary schema receipt bound exceeded')
        schema = store.put_blob(schema_raw)
        db.execute('INSERT INTO executable_registry_migrations_v3 VALUES(?,?,?,?,?,?,?)',
            (MIGRATION,'001_scoped_eligibility_v2',PREDECESSOR_SHA,DDL_SHA,preservation,schema,timestamp(applied_at)))
        db.commit()
    except BaseException:
        db.rollback(); raise
