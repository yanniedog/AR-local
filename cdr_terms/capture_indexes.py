"""Bounded optional maintenance for exact-version capture lookups."""
import logging
import sqlite3
import time


INDEX = 'acquisition_version_observed'


def install(db):
    # Called only on a newly opened archive after the standard schema script,
    # before any caller transaction. Failure changes no evidence or authority.
    if db.in_transaction:
        raise ValueError('Capture index maintenance requires an idle connection')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (INDEX,)).fetchone():
        return
    busy = db.execute('PRAGMA busy_timeout').fetchone()[0]
    deadline = time.monotonic() + 5
    try:
        db.execute('PRAGMA busy_timeout=100')
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        # Document-first indexes cannot serve this version filter/latest order.
        db.execute('CREATE INDEX IF NOT EXISTS acquisition_version_observed '
                   'ON acquisition_checks(document_version_id, checked_at DESC, sequence DESC)')
    except sqlite3.OperationalError as error:
        logging.getLogger(__name__).warning('Optional capture index unavailable: %s', type(error).__name__)
    finally:
        db.set_progress_handler(None, 0)
        db.execute(f'PRAGMA busy_timeout={int(busy)}')
