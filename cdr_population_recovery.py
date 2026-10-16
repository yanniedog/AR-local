"""Route a contract-bound empty-population anomaly into the existing daily budget."""
from datetime import date

from cdr_compatibility import response_shape_error
from cdr_observation_selection import read_bound_json
from cdr_population_identity import current_provider_matches,verified_prior_identity


def population_recovery_requests(observation, providers):
    contract = observation['contract']
    if not any(row.get('path') == 'provider-population-report.json' for row in contract.get('artifacts', [])):
        return []  # Older generations did not produce this comparison evidence.
    report = read_bound_json(observation['export_root'], contract, 'provider-population-report.json', max_bytes=512*1024)
    population = report.get('provider_population')
    if population is None:
        return []  # Legacy rate-ladder-only report.
    if isinstance(population, dict) and population.get('status') == 'UNKNOWN':
        return []  # No derived authority; independent bound HTTP failures stay eligible.
    if not isinstance(population, dict) or population.get('status') not in {'PASS', 'WARN'}:
        raise ValueError('provider population comparison is unverified')
    try:
        current = date.fromisoformat(report['run_date'])
        prior = date.fromisoformat(report['compared_against'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('provider population comparison dates are invalid') from exc
    if (current.isoformat() != report['run_date'] or prior.isoformat() != report['compared_against']
            or report['run_date'] != contract['observation_date'] or prior >= current):
        raise ValueError('provider population comparison is not for this observation')
    baseline = population.get('baseline')
    if (not isinstance(baseline, dict) or baseline.get('observation_date') != report['compared_against']
            or not isinstance(baseline.get('generation_id'), str)
            or not baseline['generation_id'].startswith('obs-'+report['compared_against']+'-')
            or any(not isinstance(baseline.get(key), str) or len(baseline[key]) != 64
                or any(c not in '0123456789abcdef' for c in baseline[key])
                for key in ['contract_digest','database_sha256','ledger_event_digest'])):
        raise ValueError('provider population baseline lacks finalization proof')
    findings = population.get('findings')
    if not isinstance(findings, list) or len(findings) > 1024:
        raise ValueError('provider population findings are invalid')
    if (population['status'] == 'PASS') != (not findings):
        raise ValueError('provider population result contradicts its findings')
    requests = []
    seen = set()
    for finding in findings:
        provider = finding.get('provider') if isinstance(finding, dict) else None
        prior = finding.get('products_prev') if isinstance(finding, dict) else None
        carried = (isinstance(finding, dict) and finding.get('carried_unresolved') is True
            and any(isinstance(row, dict) and row.get('provider') == provider
                and row.get('population_known') is False
                and row.get('disposition') == 'UNVERIFIED_SOURCE_ABSENCE'
                for row in baseline.get('unresolved_provider_populations', [])))
        identity = finding.get('provider_identity') if isinstance(finding,dict) else None
        identity_verified = verified_prior_identity(identity,provider,report['run_date'])
        if (not isinstance(provider, str) or provider in seen
                or (provider not in providers and not identity_verified)
                or (identity is not None and not identity_verified)
                or finding.get('code') != 'provider_population_disappeared'
                or finding.get('disposition') != 'UNVERIFIED_SOURCE_ABSENCE'
                or finding.get('population_known') is not False or type(prior) is not int
                or prior < 0 or (prior == 0 and not carried)
                or type(finding.get('products_curr')) is not int or finding['products_curr'] < 0
                or type(finding.get('rates_curr')) is not int or finding['rates_curr'] < 0
                or ((finding['products_curr'] or finding['rates_curr']) and not carried)):
            raise ValueError('population anomaly lacks a reconciled empty-index identity')
        seen.add(provider)
        if finding['products_curr'] or finding['rates_curr']:
            continue  # A partial return with an unresolved prior hold grants no new probe.
        matches = current_provider_matches(provider,identity,
            [dict(row,provider_dir=name) for name,row in providers.items()])
        if not matches:
            continue  # A prior identity is not authority to probe an unregistered holder.
        if len(matches) != 1:
            raise ValueError('population provider identity is ambiguous')
        target = matches[0]['provider_dir']
        diagnostic = (observation['status'].get('index_diagnostics') or {}).get(target) or {}
        if (not isinstance(diagnostic, dict) or diagnostic.get('pagination_complete') is not True
                or type(diagnostic.get('unique_products')) is not int or diagnostic['unique_products'] != 0):
            # Retain carried holds but add no derived request on an incomplete
            # or nonempty index. The independent bound HTTP queue stays eligible.
            continue
        requests.append({'provider_dir': target, 'provider_uid': providers[target].get('provider_uid'),
            'phase': 'products_index', 'product_id': '', 'url': providers[target]['endpoint_url'],
            'status': 200, 'failure_category': 'provider_population_unverified'})
    return requests


def population_pending_recovery_allowed(pending, observation):
    """Retain a matching withheld marker while permitting its prerequisite repair.

    This grants no extra claim or budget and settles no outstanding upload.
    """
    from app_payload_observation_gate import publication_allowed
    pointer = observation.get('pointer')
    return (isinstance(pointer, dict) and bool(pointer)
        and pending.get('pointer') == pointer
        and pending.get('run_date') == observation['contract']['observation_date']
        and pending.get('queued_pointers', []) == [] and 'selection_retry' not in pending
        and publication_allowed(observation['contract']) == (False, 'unverified_provider_population'))


def guard_population_index_requests(observation,providers,requests):
    """Annotate local work, retaining original queue identity and failure category."""
    flags=(observation['contract'].get('coverage') or {}).get('provider_population_unverified') or []
    if not isinstance(flags,list) or len(flags)>1024:
        raise ValueError('invalid population coverage guard')
    guarded=set()
    for flag in flags:
        if (not isinstance(flag,dict) or flag.get('population_known') is not False
                or flag.get('disposition')!='UNVERIFIED_SOURCE_ABSENCE'):
            raise ValueError('unverified population coverage guard')
        identity=flag.get('provider_identity') or {'provider_uid':flag.get('provider_uid')}
        matches=current_provider_matches(flag.get('provider'),identity,
            [dict(row,provider_dir=name) for name,row in providers.items()])
        if len(matches)>1:
            raise ValueError('ambiguous population coverage guard')
        guarded.update(row['provider_dir'] for row in matches)
    return [dict(row,requires_nonempty_population=True)
        if row.get('phase')=='products_index' and row['provider_dir'] in guarded else dict(row)
        for row in requests]


def population_probe_has_progress(report):
    """Another valid empty response cannot spend a capture reservation."""
    if not report.get('ok'):
        return False
    partial = report.get('partial_index')
    if isinstance(partial, dict):
        return type(partial.get('unique_products')) is int and partial['unique_products'] > 0
    data = report.get('data')
    if response_shape_error(data, phase='products_index') is not None:
        return False
    inner = data.get('data')
    products = inner.get('products') if isinstance(inner, dict) else inner
    return len(products) > 0
