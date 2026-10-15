"""Route a contract-bound empty-population anomaly into the existing daily budget."""
from datetime import date

from cdr_compatibility import response_shape_error
from cdr_observation_selection import read_bound_json


def population_recovery_requests(observation, providers):
    contract = observation['contract']
    if not any(row.get('path') == 'sanity-report.json' for row in contract.get('artifacts', [])):
        return []  # Older generations did not produce this comparison evidence.
    report = read_bound_json(observation['export_root'], contract, 'sanity-report.json', max_bytes=512*1024)
    population = report.get('provider_population')
    if population is None:
        return []  # Legacy rate-ladder-only report.
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
    findings = population.get('findings')
    if not isinstance(findings, list) or len(findings) > len(providers):
        raise ValueError('provider population findings are invalid')
    if (population['status'] == 'PASS') != (not findings):
        raise ValueError('provider population result contradicts its findings')
    requests = []
    seen = set()
    for finding in findings:
        provider = finding.get('provider') if isinstance(finding, dict) else None
        prior = finding.get('products_prev') if isinstance(finding, dict) else None
        diagnostic = (observation['status'].get('index_diagnostics') or {}).get(provider) or {}
        if (provider not in providers or provider in seen or finding.get('code') != 'provider_population_disappeared'
                or finding.get('disposition') != 'UNVERIFIED_SOURCE_ABSENCE'
                or finding.get('population_known') is not False or type(prior) is not int or prior <= 0
                or type(finding.get('products_curr')) is not int or finding['products_curr'] != 0
                or type(finding.get('rates_curr')) is not int or finding['rates_curr'] != 0
                or diagnostic.get('pagination_complete') is not True
                or type(diagnostic.get('unique_products')) is not int or diagnostic['unique_products'] != 0):
            raise ValueError('population anomaly lacks a reconciled empty-index identity')
        seen.add(provider)
        requests.append({'provider_dir': provider, 'provider_uid': providers[provider].get('provider_uid'),
            'phase': 'products_index', 'product_id': '', 'url': providers[provider]['endpoint_url'],
            'status': 200, 'failure_category': 'provider_population_unverified'})
    return requests


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
