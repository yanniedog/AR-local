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


def _read_counts(path, run_date=None, *, deadline=None):
    deadline = min(time.monotonic()+4, deadline) if deadline is not None else time.monotonic()+4
    if time.monotonic() >= deadline:
        raise sqlite3.OperationalError('population count verification budget exhausted')
    if any((sidecar := path.with_name(path.name + suffix)).is_file() and sidecar.stat().st_size > 0
           for suffix in ('-wal', '-journal')):
        raise sqlite3.DatabaseError('retained journal requires a verified private-copy audit')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as connection:
        connection.execute('pragma query_only=on')
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
        return tuple(dict(connection.execute(
            'select provider,count(*) from ' + table
            + (' where run_date=?' if run_date is not None else '') + ' group by provider',
            (run_date,) if run_date is not None else ()))
            for table in ('bank_products', 'bank_rates'))


def compare_population_counts(current, prior, unresolved_prior=()):
    """Compare observed count maps; carried holds do not become current rows."""
    current_products, current_rates = current
    prior_products, prior_rates = prior
    findings = disappeared_providers(current_products, prior_products, current_rates, prior_rates)
    seen = {row['provider'] for row in findings}
    for previous in unresolved_prior:
        provider = previous['provider']
        continuation = {'carried_unresolved':True,
            **{key:previous[key] for key in ('last_nonempty','provider_identity','historical_baseline','historical_absence')
               if key in previous}}
        if provider in seen:
            # A partial return did not resolve the earlier hold. A new zero
            # must retain its original provenance and endpoint restrictions.
            next(row for row in findings if row['provider']==provider).update(continuation)
            continue
        findings.append({'severity':'HIGH','code':'provider_population_disappeared',
            'provider':provider,'products_prev':prior_products.get(provider,0),
            'products_curr':current_products.get(provider,0),
            'rates_prev':prior_rates.get(provider,0),'rates_curr':current_rates.get(provider,0),
            'population_known':False,'disposition':'UNVERIFIED_SOURCE_ABSENCE',
            **continuation})
        seen.add(provider)
    return {"status": "WARN" if findings else "PASS", "findings": findings,
        "semantics": "Unconfirmed absence; do not infer retirement, fill history, or claim complete provider coverage."}


def population_report(current_db: Path, prior_db: Path, *, unresolved_prior=(),current_date=None,prior_date=None):
    """Read only the two observed databases; a failed comparison stays unknown."""
    if not current_db.is_file() or not prior_db.is_file():
        return {"status": "UNKNOWN", "reason": "comparison_database_missing", "findings": []}
    try:
        return compare_population_counts(_read_counts(current_db,current_date),
            _read_counts(prior_db,prior_date),unresolved_prior)
    except (OSError, sqlite3.Error):
        return {"status": "UNKNOWN", "reason": "comparison_database_unreadable", "findings": []}
