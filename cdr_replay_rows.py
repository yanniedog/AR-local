"""Private, finite disk replay for export facts/changes; never authoritative data."""
from contextlib import closing
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sqlite3
import stat
import time
import uuid


class ReplayLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplayLimits:
    version: int = 1
    database_bytes: int = 8 * 1024**3
    disk_bytes: int = 16 * 1024**3
    rows: int = 8_000_000
    row_bytes: int = 32 * 1024**2
    read_bytes: int = 128 * 1024**3
    seconds: float = 21600

    def validate(self):
        if type(self.version) is not int or self.version != 1 or any(type(getattr(self, key)) is not int or getattr(self, key) <= 0
                for key in ('database_bytes', 'disk_bytes', 'rows', 'row_bytes', 'read_bytes')):
            raise ValueError('invalid replay limits v1')
        if type(self.seconds) not in (int, float) or not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError('invalid replay lifetime')
        if self.database_bytes < 4096 or self.disk_bytes < self.database_bytes:
            raise ValueError('invalid replay disk limits')


def encoded(value):
    # ASCII escapes preserve even isolated surrogate/control codepoints until the
    # unchanged consumer applies its existing JSON/UTF-8 acceptance rules.
    return json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode('ascii')


def sort_blob(value):
    """SQLite BLOB order equals Python str order, including surrogate/control values."""
    return str(value).encode('utf-32-be', errors='surrogatepass')


class ReplayRows:
    def __init__(self, store, table):
        self.store, self.table = store, table
        self.count = 0
        self.sealed = False

    def __len__(self): return self.count

    def extend(self, rows):
        for row in rows: self.append(row)

    def append(self, row):
        if self.table != 'facts': raise TypeError('changes require an explicit sort key')
        self.store.append_fact(row)

    def seal(self):
        self.store.check(disk=True)
        with self.store.database_boundary(): self.store.connection.commit()
        self.sealed = True

    def __iter__(self):
        if not self.sealed: raise RuntimeError('replay table is not sealed')
        order = 'seq' if self.table == 'facts' else 'k1,k2,k3,k4,k5,k6,seq'
        yield from self.store.read_rows(f'SELECT payload FROM {self.table} ORDER BY {order}')

    def product_presence(self):
        if self.table != 'facts' or not self.sealed: raise RuntimeError('fact identities are not sealed')
        for key in self.store.read_rows('SELECT identity FROM presence ORDER BY identity'): yield tuple(key)


class ReplayStore:
    """One owned scratch directory; all iterators share the original finite budget."""
    FILES = {'rows.sqlite', 'rows.sqlite-journal', 'rows.sqlite-wal', 'rows.sqlite-shm', 'failure.json'}

    def __init__(self, parent, *, key_of, validate_fact, limits=ReplayLimits()):
        limits.validate()
        parent = Path(parent).absolute()
        if any(p.is_symlink() for p in (parent, *parent.parents)): raise ValueError('symlink replay parent')
        parent.mkdir(parents=True, exist_ok=True)
        from pi_plain_backup_restore import private_workspace
        self.root = parent / ('.cdr-facts-' + uuid.uuid4().hex)
        # Create with its final private DACL/mode, before opening any data file.
        private_workspace(self.root)
        self.identity = self.root.stat().st_dev, self.root.stat().st_ino
        self.limits, self.key_of, self.validate_fact = limits, key_of, validate_fact
        self.deadline = time.monotonic() + limits.seconds
        self.read_bytes = self.written_rows = 0
        self.exhausted = False
        self.write_failed = False
        self._progress_error = None
        self.cleanup_receipt = None
        self._last_product = self._last_presence = None
        self.closed = False
        self.connection = None
        self.facts, self.changes = ReplayRows(self, 'facts'), ReplayRows(self, 'changes')
        try:
            self.connection = sqlite3.connect(self.root / 'rows.sqlite')
            self.connection.execute('PRAGMA page_size=4096')
            self.connection.execute('PRAGMA cache_size=-8192')
            self.connection.execute('PRAGMA mmap_size=0')
            self.connection.execute('PRAGMA temp_store=FILE')
            self.connection.execute('PRAGMA journal_mode=DELETE')
            self.connection.execute('PRAGMA synchronous=FULL')
            # Bound both database pages and worst-case rollback page copies,
            # including journal per-page/header overhead, before SQLite writes.
            pages = min(limits.database_bytes // 4096, (limits.disk_bytes - 131072) // 8200)
            if pages < 16: raise ValueError('replay disk budget cannot hold private schema')
            self.connection.execute(f'PRAGMA max_page_count={pages}')
            self.connection.executescript('''
                CREATE TABLE products(id INTEGER PRIMARY KEY, identity BLOB UNIQUE NOT NULL,
                    k1 BLOB, k2 BLOB, k3 BLOB, first_seq INTEGER, matched INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX products_order ON products(k1,k2,k3,first_seq);
                CREATE TABLE presence(identity BLOB PRIMARY KEY);
                CREATE TABLE previous_keys(identity BLOB PRIMARY KEY);
                CREATE TABLE facts(seq INTEGER PRIMARY KEY, product INTEGER NOT NULL, payload BLOB NOT NULL);
                CREATE INDEX facts_product ON facts(product,seq);
                CREATE TABLE changes(seq INTEGER PRIMARY KEY,k1 BLOB,k2 BLOB,k3 BLOB,k4 INTEGER,k5 BLOB,k6 BLOB,payload BLOB NOT NULL);
                CREATE INDEX changes_order ON changes(k1,k2,k3,k4,k5,k6,seq);
            ''')
            self.check(disk=True)
            self.connection.set_progress_handler(self._progress, 10000)
        except BaseException:
            self.close(failed=True)
            raise

    def __enter__(self): return self

    def __exit__(self, kind, value, traceback):
        if value is not None and hasattr(value, 'add_note'):
            value.add_note(f'Unfinalized private replay scratch retained: {self.root}')
        self.close(failed=kind is not None)

    def _progress(self):
        try: self.check()
        except ReplayLimitError as error:
            self._progress_error = error
            return 1
        return 0

    @contextmanager
    def database_boundary(self):
        try:
            yield
        except sqlite3.Error as error:
            if self._progress_error is not None:
                raise self._progress_error from error
            raise

    def _disk_bytes(self):
        info = self.root.lstat()
        if (info.st_dev, info.st_ino) != self.identity or not stat.S_ISDIR(info.st_mode):
            raise ReplayLimitError('owned replay directory identity changed')
        total = 0
        for index, path in enumerate(self.root.iterdir()):
            if index >= len(self.FILES) or path.name not in self.FILES: raise ReplayLimitError('unknown file in replay directory')
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise ReplayLimitError('unsafe replay file')
            total += info.st_size
        return total

    def check(self, *, read=0, disk=False):
        if self.closed: raise RuntimeError('replay store is closed')
        if self.write_failed: raise ReplayLimitError('replay v1 SQLite write failed; store cannot be reused')
        self.read_bytes += read
        if (self.exhausted or time.monotonic() >= self.deadline or self.read_bytes > self.limits.read_bytes
                or self.written_rows > self.limits.rows):
            self.exhausted = True
            raise ReplayLimitError('replay v1 lifetime/read/row budget exhausted')
        if disk and self._disk_bytes() > self.limits.disk_bytes:
            self.exhausted = True
            raise ReplayLimitError('replay v1 owned disk budget exhausted')

    def _append_bytes(self, table, row):
        if getattr(self, table).sealed: raise RuntimeError('cannot append to sealed replay table')
        self.check()
        raw = encoded(row)
        if len(raw) > self.limits.row_bytes:
            self.exhausted = True
            raise ReplayLimitError('replay v1 row byte budget exhausted')
        # Reserve database plus possible rollback-page writes before insertion.
        if self._disk_bytes() + 2 * (len(raw) + 65536) > self.limits.disk_bytes:
            self.exhausted = True
            raise ReplayLimitError('replay v1 disk write reservation exhausted')
        self.written_rows += 1; self.check()
        return raw

    def append_fact(self, row):
        key = self.key_of(row); self.validate_fact(row)
        raw = self._append_bytes('facts', row)
        # Existing suppression uses raw canonical fields without the diff's
        # whitespace trimming or aliases; preserve that distinct contract.
        presence = (str(row.get('provider') or '').casefold(), str(row.get('product_id') or ''), str(row.get('dataset') or ''))
        try:
            with self.database_boundary():
                self._insert_fact(key, presence, raw)
        except sqlite3.Error:
            # SQLITE_FULL/ROLLBACK can invalidate earlier rows and cached IDs.
            self._last_product = self._last_presence = None
            self.write_failed = True
            raise
        except ReplayLimitError:
            self._last_product = self._last_presence = None
            raise
        self.facts.count += 1
        self._last_presence = presence
        self.check(disk=True)

    def _insert_fact(self, key, presence, raw):
        con = self.connection
        if self._last_product is not None and self._last_product[0] == key:
            number = self._last_product[1]
        else:
            ident = encoded(key)
            con.execute('INSERT OR IGNORE INTO products(identity,k1,k2,k3,first_seq) VALUES(?,?,?,?,?)',
                        (ident, sort_blob(key[0].casefold()), sort_blob(key[1]), sort_blob(key[2]), self.facts.count))
            number = con.execute('SELECT id FROM products WHERE identity=?', (ident,)).fetchone()[0]
        if self._last_presence != presence:
            con.execute('INSERT OR IGNORE INTO presence(identity) VALUES(?)', (encoded(presence),))
        con.execute('INSERT INTO facts(product,payload) VALUES(?,?)', (number, raw))
        self._last_product = (key, number)

    def append_change(self, row, key):
        raw = self._append_bytes('changes', row)
        keys = tuple(value if i == 3 else sort_blob(value) for i, value in enumerate(key))
        try:
            with self.database_boundary():
                self.connection.execute('INSERT INTO changes(k1,k2,k3,k4,k5,k6,payload) VALUES(?,?,?,?,?,?,?)', (*keys, raw))
        except sqlite3.Error:
            self._last_product = self._last_presence = None
            self.write_failed = True
            raise
        except ReplayLimitError:
            self._last_product = self._last_presence = None
            raise
        self.changes.count += 1; self.check(disk=True)

    def read_rows(self, query, args=()):
        self.check()
        with self.database_boundary(), closing(self.connection.execute(query, args)) as cursor:
            for (raw,) in cursor:
                self.check(read=len(raw))
                yield json.loads(raw)
        self.check(disk=True)

    def product_keys(self, *, unmatched=False):
        clause = 'WHERE matched=0' if unmatched else ''
        for key in self.read_rows(f'SELECT identity FROM products {clause} ORDER BY k1,k2,k3,first_seq'):
            yield tuple(key)

    def take_product(self, key):
        self.check(disk=True); ident = encoded(key)
        with self.database_boundary():
            try: self.connection.execute('INSERT INTO previous_keys(identity) VALUES(?)', (ident,))
            except sqlite3.IntegrityError as error: raise ValueError(f'prior product group repeated: {key!r}') from error
            row = self.connection.execute('SELECT id FROM products WHERE identity=?', (ident,)).fetchone()
            if row is None: return None
            self.connection.execute('UPDATE products SET matched=1 WHERE id=?', row)
            return list(self.read_rows('SELECT payload FROM facts WHERE product=? ORDER BY seq', row))

    def product(self, key):
        self.check()
        with self.database_boundary():
            row = self.connection.execute('SELECT id FROM products WHERE identity=?', (encoded(key),)).fetchone()
            return list(self.read_rows('SELECT payload FROM facts WHERE product=? ORDER BY seq', row))

    def product_count(self):
        self.check()
        with self.database_boundary(): return self.connection.execute('SELECT COUNT(*) FROM products').fetchone()[0]

    def close(self, *, failed=False):
        if self.closed: return
        failed = failed or self.exhausted or self.write_failed
        if self.connection is not None:
            self.connection.set_progress_handler(None, 0)
            self.connection.close(); self.connection = None
        self.closed = True
        if failed:
            # Never overwrite a prior diagnostic or remove unrelated files.
            try:
                self._disk_bytes()
                with (self.root / 'failure.json').open('x', encoding='ascii') as stream:
                    json.dump(dict(schema='cdr-replay-failure-v1', row_reservations=self.written_rows,
                                   read_bytes=self.read_bytes, finalized=False), stream)
            except (OSError, ReplayLimitError): pass
            return
        try:
            retained_bytes = self._disk_bytes()
            from cdr_replay_cleanup import cleanup
            self.cleanup_receipt = cleanup(self.root, self.identity, self.FILES)
            if self.cleanup_receipt['state'].startswith('RETAINED_'):
                self.cleanup_receipt['bytes'] = retained_bytes
        except BaseException as error:
            self.cleanup_receipt = dict(state='RETAINED_CLEANUP_REFUSED', path=str(self.root),
                reason=type(error).__name__ + ': ' + str(error), finalized=False)
            if hasattr(error, 'add_note'):
                error.add_note(f'Private replay cleanup refused; retained scratch: {self.root}')
            raise
