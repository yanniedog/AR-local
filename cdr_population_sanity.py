"""Detect absent provider populations without inventing current products or withdrawals."""
from contextlib import closing
from pathlib import Path
import sqlite3
import time


def disappeared_providers(current_products, prior_products, current_rates=None, prior_rates=None):
    """A prior nonempty population becoming empty needs an explicit disposition.

    Prior counts describe the previous observation, not today's missing count.
    Absence is neither confirmed retirement nor permission to carry rows forward.
    """
    findings = []
    for provider, count in sorted(prior_products.items()):
        if count <= 0 or current_products.get(provider, 0) != 0:
            continue
        if current_rates is not None and current_rates.get(provider, 0) != 0:
            continue
        row = {"severity": "HIGH", "code": "provider_population_disappeared",
            "provider": provider, "products_prev": count, "products_curr": 0,
            "population_known": False, "disposition": "UNVERIFIED_SOURCE_ABSENCE"}
        if prior_rates is not None:
            row.update(rates_prev=prior_rates.get(provider, 0), rates_curr=0)
        findings.append(row)
    return findings


def _read_counts(path):
    deadline = time.monotonic() + 4
    if any((sidecar := path.with_name(path.name + suffix)).is_file() and sidecar.stat().st_size > 0
           for suffix in ('-wal', '-journal')):
        raise sqlite3.DatabaseError('retained journal requires a verified private-copy audit')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as connection:
        connection.execute('pragma query_only=on')
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
        return tuple(dict(connection.execute(
            'select provider,count(*) from ' + table + ' group by provider'))
            for table in ('bank_products', 'bank_rates'))


def population_report(current_db: Path, prior_db: Path):
    """Read only the two observed databases; a failed comparison stays unknown."""
    if not current_db.is_file() or not prior_db.is_file():
        return {"status": "UNKNOWN", "reason": "comparison_database_missing", "findings": []}
    try:
        current_products, current_rates = _read_counts(current_db)
        prior_products, prior_rates = _read_counts(prior_db)
        findings = disappeared_providers(current_products, prior_products, current_rates, prior_rates)
    except (OSError, sqlite3.Error):
        return {"status": "UNKNOWN", "reason": "comparison_database_unreadable", "findings": []}
    return {"status": "WARN" if findings else "PASS", "findings": findings,
        "semantics": "Unconfirmed absence; do not infer retirement, fill history, or claim complete provider coverage."}
