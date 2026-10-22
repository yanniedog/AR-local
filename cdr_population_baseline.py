"""Attest the exact finalized prior database before deriving recovery work."""
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
import time

from cdr_export_contract import hash_file
from cdr_observation_selection import load_pointer_observation, safe_child
from cdr_population_sanity import _read_counts, compare_population_counts


def _baseline_observation(state, pointer):
    marker_path = safe_child(state, pointer['marker_path'])
    if marker_path.stat().st_size > 65536:
        raise ValueError('baseline marker exceeds metadata budget')
    marker = json.loads(marker_path.read_bytes())
    contract_path = safe_child(state, marker['export_contract_path'])
    if contract_path.stat().st_size > 16*1024*1024:
        raise ValueError('baseline contract exceeds metadata budget')
    return load_pointer_observation(state, pointer)


def _verified_baseline(state, pointer, budget, observation=None, *, deadline=None):
    budget()
    if observation is None:
        observation = _baseline_observation(state, pointer)
    marker = observation['marker']
    contract = observation['contract']
    prior_db = observation['export_root'] / 'local-cdr.sqlite'
    if prior_db.is_symlink() or safe_child(observation['export_root'], prior_db.name) != prior_db.resolve():
        raise ValueError('baseline database escaped its finalized root')
    records = [row for row in contract['artifacts'] if row['path'] == prior_db.name]
    if len(records) != 1 or records[0]['bytes'] != prior_db.stat().st_size:
        raise ValueError('baseline database not uniquely bound')
    if hash_file(prior_db, budget=budget) != records[0]['sha256']:
        raise ValueError('baseline database changed after finalization')
    baseline = {'observation_date':contract['observation_date'],
        'generation_id':contract['generation_id'], 'contract_digest':contract['contract_digest'],
        'database_sha256':records[0]['sha256'], 'ledger_event_digest':marker['ledger_event_digest']}
    budget()
    counts = _read_counts(prior_db, contract['observation_date'], deadline=deadline)
    budget()
    return observation, baseline, counts


def _with_history(result, latest, current_counts, state, run_date, budget, deadline):
    from cdr_population_history import LOOKBACK_DAYS, bootstrap_verified, historical_findings
    from cdr_population_identity import prior_provider_identity
    observation, baseline, prior_counts = latest
    for finding in result['findings']:
        if not finding.get('provider_identity'):
            finding['provider_identity'] = prior_provider_identity(observation,
                finding['provider'],result['baseline'])
        if not finding.get('carried_unresolved'):
            finding['last_nonempty'] = {'observation_date':baseline['observation_date'],
                'products':finding['products_prev'],'rates':finding.get('rates_prev',0)}
    yesterday = (date.fromisoformat(run_date)-timedelta(days=1)).isoformat()
    bootstrapped = baseline['observation_date'] == yesterday and bootstrap_verified(observation)
    budget()
    if bootstrapped:
        result['bootstrap_history'] = {'status':'COMPLETE', 'lookback_days':LOOKBACK_DAYS,
            'inherited_from':dict(baseline)}
        return result
    findings, history = historical_findings(current_counts,latest,state,run_date,
        lambda p:_verified_baseline(state,p,budget,deadline=deadline),budget)
    result['bootstrap_history'] = history
    seen = {row['provider'] for row in result['findings']}
    result['findings'].extend(row for row in findings if row['provider'] not in seen)
    if history['status'] != 'COMPLETE' and not result['findings']:
        return {'status':'UNKNOWN', 'reason':'population_bootstrap_incomplete',
                'findings':[], 'bootstrap_history':history}
    result['status'] = 'WARN' if result['findings'] else 'PASS'
    return result


def finalized_population_report(current_db, state_dir, *, run_date):
    """An unfinalized/path-only database is diagnostic evidence, not authority."""
    unresolved = []
    try:
        state = Path(state_dir)
        deadline = time.monotonic()+8
        def budget(**unused):
            if time.monotonic() > deadline:
                raise ValueError('baseline verification budget exhausted')
        # Selection can name a repaired revision, not the primary date export.
        path = state / 'observation-pointers-v2/latest-observation.json'
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError('invalid baseline pointer')
        pointer = json.loads(path.read_bytes())
        day = pointer['observation_date']
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('invalid baseline date')
        observation = _baseline_observation(state, pointer)
        contract = observation['contract']
        unresolved = contract['coverage'].get('provider_population_unverified', [])
        if not isinstance(unresolved, list) or any(not isinstance(row, dict)
                or not isinstance(row.get('provider'), str) for row in unresolved):
            raise ValueError('invalid prior population disposition')
        if date.fromisoformat(run_date).isoformat() != run_date or day >= run_date:
            raise ValueError('selected observation is not a prior day')
        observation, baseline, prior_counts = _verified_baseline(state, pointer, budget, observation,
                                                                deadline=deadline)
        current_counts = _read_counts(current_db, run_date, deadline=deadline)
        budget()
        result = compare_population_counts(current_counts, prior_counts, unresolved)
        if result['status'] == 'UNKNOWN' and unresolved:
            result['unresolved_prior'] = unresolved
        if result['status'] in {'PASS','WARN'}:
            result['baseline'] = dict(baseline, unresolved_provider_populations=unresolved)
            unresolved = result['findings']
            return _with_history(result,(observation,baseline,prior_counts),current_counts,
                                 state,run_date,budget,deadline)
        return result
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        return {'status':'UNKNOWN','reason':'baseline_not_finalized_or_verified','findings':[],
            **({'unresolved_prior':unresolved} if isinstance(unresolved,list) and unresolved else {})}
