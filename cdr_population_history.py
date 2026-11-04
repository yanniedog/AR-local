"""Bounded bootstrap of population holds across legacy report-less observations."""
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from cdr_export_contract import read_json
from cdr_observation_selection import read_bound_json, safe_child
from cdr_population_identity import current_provider_matches, population_finding_resolved, prior_provider_identity
from cdr_population_sanity import disappeared_providers

LOOKBACK_DAYS = 7
MAX_GENERATIONS_PER_DAY = 8
MAX_DECISIONS_PER_DAY = 16
BOOTSTRAP_SEMANTICS_VERSION = 2


def bootstrap_verified(observation, *, budget=None):
    """A missing/failed first comparison cannot suppress tomorrow's bootstrap."""
    contract = observation['contract']
    if not any(row['path'] == 'provider-population-report.json' for row in contract['artifacts']):
        return False
    report = read_bound_json(observation['export_root'], contract,
                            'provider-population-report.json', max_bytes=512*1024, budget=budget)
    population = report.get('provider_population')
    if not isinstance(population, dict) or population.get('status') not in {'PASS','WARN'}:
        return False
    history = population.get('bootstrap_history')
    if not isinstance(history, dict):
        return False
    return (report.get('run_date') == contract['observation_date']
            and history.get('status') == 'COMPLETE' and history.get('lookback_days') == LOOKBACK_DAYS
            and history.get('semantics_version') == BOOTSTRAP_SEMANTICS_VERSION)


def _bounded_metadata(directory, maximum, max_bytes, budget):
    if not directory.is_dir():
        return []
    paths = []
    for path in directory.iterdir():
        budget()
        if path.suffix != '.json':
            continue
        if path.is_symlink() or not path.is_file() or len(paths) >= maximum or path.stat().st_size > max_bytes:
            raise ValueError('population history exceeds metadata budget')
        paths.append(path)
    return paths


def historical_pointer(state, day, budget):
    """Use immutable selection decisions, never primary paths or filename order."""
    from app_payload_historical_source import historical_contract
    paths = _bounded_metadata(state/'export-contracts-v2'/day, MAX_GENERATIONS_PER_DAY,
                              16*1024*1024, budget)
    if not paths:
        return None
    decisions = _bounded_metadata(state/'observation-selections-v1'/day,
                                  MAX_DECISIONS_PER_DAY, 65536, budget)
    contract = historical_contract(state, day, paths=paths, decision_paths=decisions,budget=budget)
    budget()
    if not contract:
        raise ValueError('population history selection is unavailable')
    marker_path = safe_child(state, contract['completion_marker_path'])
    if marker_path.stat().st_size > 65536:
        raise ValueError('population history marker exceeds metadata budget')
    marker = read_json(marker_path, budget=budget, max_bytes=65536)
    return {'schema_version':2, 'observation_date':day,
        'generation_id':contract['generation_id'], 'observation_state':contract['observation_state'],
        'ledger_event_digest':marker['ledger_event_digest'],
        'marker_path':contract['completion_marker_path'], 'export_path':contract['source_path']}


def _historical_finding(finding, observation, baseline, latest):
    provider = finding['provider']
    identity = prior_provider_identity(observation, provider, baseline)
    if identity.get('identity_status') != 'verified_prior_register' or not identity.get('provider_uid'):
        raise ValueError('population history holder lacks registered identity')
    matches = current_provider_matches(provider, identity,
        latest['status'].get('provider_states') or [])
    if len(matches) != 1:
        raise ValueError('population history holder identity changed or is ambiguous')
    original = next(row for row in observation['status']['provider_states']
                    if row.get('provider_uid') == identity['provider_uid'])
    if (not isinstance(original.get('endpoint_url'),str) or not original['endpoint_url']
            or original['endpoint_url'] != matches[0].get('endpoint_url')):
        raise ValueError('population history holder endpoint changed')
    identity['endpoint_url'] = original['endpoint_url']
    return dict(finding, provider_identity=identity, historical_baseline=baseline,
        last_nonempty={'observation_date':baseline['observation_date'],
                       'products':finding['products_prev'], 'rates':finding.get('rates_prev',0)})


def _gap_finding(provider, observation, baseline, counts, newer, latest, current):
    """Find an actual older zero gap; ordinary positive declines are not gaps."""
    finding = disappeared_providers({provider:0},{provider:counts[0][provider]},
                                   {provider:0},{provider:counts[1].get(provider,0)})[0]
    candidate = None
    for index,(zero,zero_baseline,zero_counts) in reversed(list(enumerate(newer))):
        if zero_counts[0].get(provider,0) or zero_counts[1].get(provider,0):
            continue
        candidate = _historical_finding(finding,observation,baseline,latest)
        # Prove the gap belongs to the same registered UID/endpoint as its
        # nonempty source, rather than a renamed key or an unrelated holder.
        _historical_finding(finding,observation,baseline,zero)
        row = current_provider_matches(provider,candidate['provider_identity'],
                                       zero['status']['provider_states'])[0]
        names = {provider,row.get('provider_dir'),row.get('brand_name'),row.get('provider_uid')}
        if any(zero_counts[0].get(name,0) or zero_counts[1].get(name,0) for name in names):
            candidate = None
            continue
        identity = dict(candidate['provider_identity'],source_observation=dict(zero_baseline),
                        provider_dir=row.get('provider_dir') or provider)
        candidate.update(products_curr=current[0].get(provider,0),rates_curr=current[1].get(provider,0),
                         historical_absence={'provider_identity':identity,'products':0,'rates':0})
        if any(population_finding_resolved(candidate,item[0]['status']) for item in newer[:index]):
            return None,True  # A later verified complete index already resolved this gap.
        return candidate,True
    return None,False


def _retain_gap_findings(findings, seen, gaps_seen, observation, baseline, counts, newer, latest, current, budget):
    for provider,count in counts[0].items():
        budget()
        if count <= 0 or provider in gaps_seen:
            continue
        gap,found = _gap_finding(provider,observation,baseline,counts,newer,latest,current)
        if not found:
            continue
        if gap is None:
            gaps_seen.add(provider)  # A complete index closes every still-older gap.
            continue
        previous = next((row for row in findings if row['provider']==provider),None)
        if previous is None:
            findings.append(gap)
            seen.add(provider)
        elif (not previous.get('carried_unresolved') and
                ((previous.get('historical_absence') and
                  gap['historical_absence']['provider_identity']['source_observation']['observation_date'] <
                  previous['historical_absence']['provider_identity']['source_observation']['observation_date'])
                 or (not previous.get('historical_absence') and
                     previous['last_nonempty']['observation_date'] >
                     gap['historical_absence']['provider_identity']['source_observation']['observation_date']))):
            # Keep adjacent-day counts, but recover the original loss proof
            # rather than relabelling a partial return as the old baseline.
            previous.update({key:gap[key] for key in
                ('provider_identity','historical_baseline','historical_absence','last_nonempty')})


def historical_findings(current_counts, latest, state, run_date, load_verified, budget):
    """Return only verified older absence evidence; an incomplete scan stays unknown.

    Counts are historical diagnostics. No product/rate row is carried forward.
    The newest selected nonempty population for each exact holder wins.
    """
    current_products, current_rates = current_counts
    latest_observation, latest_baseline, _ = latest
    start = date.fromisoformat(run_date)-timedelta(days=1)
    history = {'status':'RUNNING', 'lookback_days':LOOKBACK_DAYS,
        'semantics_version':BOOTSTRAP_SEMANTICS_VERSION,
        'interval_start':(start-timedelta(days=LOOKBACK_DAYS-1)).isoformat(),
        'interval_end':start.isoformat(), 'scanned_dates':[], 'missing_dates':[],
        'shared_deadline_seconds':8,
        'max_generations_per_day':MAX_GENERATIONS_PER_DAY,
        'max_decisions_per_day':MAX_DECISIONS_PER_DAY}
    findings, seen, gaps_seen, newer = [], set(), set(), []
    try:
        for offset in range(LOOKBACK_DAYS):
            budget()
            day = (start-timedelta(days=offset)).isoformat()
            if day == latest_baseline['observation_date']:
                observation, baseline, counts = latest
            else:
                pointer = historical_pointer(Path(state), day, budget)
                if pointer is None:
                    history['missing_dates'].append(day)
                    continue
                observation, baseline, counts = load_verified(pointer)
            history['scanned_dates'].append(day)
            for finding in disappeared_providers(current_products, counts[0], current_rates, counts[1]):
                provider = finding['provider']
                if provider in seen:
                    continue
                findings.append(_historical_finding(finding, observation, baseline, latest_observation))
                seen.add(provider)
            _retain_gap_findings(findings,seen,gaps_seen,observation,baseline,counts,newer,
                                 latest_observation,current_counts,budget)
            newer.append((observation,baseline,counts))
        if history['missing_dates']:
            raise ValueError('population history contains unavailable dates')
        budget()
        history['status'] = 'COMPLETE'
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        history['status'] = 'INCOMPLETE'
        history['reason'] = 'verification_unavailable_or_limit'
    return findings, history
