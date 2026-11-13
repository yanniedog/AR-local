"""Prospective, evidence-backed CDR departures without changing product history."""
from copy import deepcopy

from cdr_atomic import atomic_write_bytes
from cdr_export_contract import read_json
from cdr_population_identity import verified_prior_identity
from cdr_provider_participation_evidence import (
    EVIDENCE_ROOT, current_register, load_cessation_evidence,
    matching_registration, observed_day,
)


def reconcile_participation(population, status, export_root, run_date):
    """Unknown evidence keeps the original hold; never probes the network."""
    if population.get('status') not in {'PASS', 'WARN'}:
        return population
    result = deepcopy(population)
    findings = result.get('findings', [])
    for previous in result.pop('participation_cessations', []):
        original = previous['unresolved_finding']
        if not any(row.get('provider') == original.get('provider') for row in findings):
            findings.append(original)
    result['findings'] = findings
    result['status'] = 'WARN' if findings else 'PASS'
    if not findings:
        return result
    try:
        evidence = load_cessation_evidence()
        current, register = current_register(export_root, status, run_date)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        return result
    remaining, cessations = [], []
    for finding in findings:
        identity = finding.get('provider_identity')
        matches = [entry for entry in evidence if isinstance(identity, dict)
                   and entry['provider_uid'] == identity.get('provider_uid')]
        if len(matches) != 1 or not _confirmed(finding, matches[0], current, run_date):
            remaining.append(finding)
            continue
        entry = matches[0]
        sources = {}
        for kind in ('prior_register', 'cessation_register', 'response'):
            source = entry['evidence'][kind]
            relative = f"provider-participation-evidence/{source['sha256']}.json"
            atomic_write_bytes(export_root / relative, (EVIDENCE_ROOT / source['path']).read_bytes(),
                               create_once=True)
            sources[kind] = dict(source, path=relative)
        cessations.append({'provider': finding['provider'], 'provider_uid': entry['provider_uid'],
            'disposition': 'CDR_PARTICIPATION_CEASED', 'observed_at': entry['observed_at'],
            'applicable_observation_date': run_date, 'current_register_membership': 'absent',
            'product_withdrawal_confirmed': False, 'current_register': register, 'sources': sources,
            'unresolved_finding': finding})
    result.update(findings=remaining, status='WARN' if remaining else 'PASS')
    if cessations:
        result['participation_cessations'] = cessations
    return result


def _confirmed(finding, entry, current, run_date):
    identity = finding.get('provider_identity')
    return (verified_prior_identity(identity, finding.get('provider'), run_date)
        and identity.get('identity_status') == 'verified_prior_register'
        and finding.get('population_known') is False
        and finding.get('disposition') == 'UNVERIFIED_SOURCE_ABSENCE'
        and not finding.get('products_curr') and not finding.get('rates_curr')
        and identity.get('endpoint_url', entry['endpoint_url']) == entry['endpoint_url']
        and run_date >= observed_day(entry['observed_at'])
        and not any(matching_registration(row, entry['prior_registration']) for row in current))


def participation_coverage(export_root, status, run_date):
    path = export_root / 'provider-population-report.json'
    if not path.is_file():
        return []
    try:
        report = read_json(path, max_bytes=512 * 1024)
        population = report.get('provider_population') or {}
        if not isinstance(population, dict):
            return []
    except (OSError, ValueError, AttributeError):
        return []  # Unusable comparison grants no new lifecycle authority.
    recorded = population.get('participation_cessations', [])
    if not recorded:
        return []
    if population.get('status') not in {'PASS', 'WARN'} or not isinstance(recorded, list):
        raise ValueError('participation disposition requires a verified population comparison')
    # Recheck current raw registration and every captured source before sealing.
    verified = reconcile_participation(population, status, export_root, run_date)
    if report.get('run_date') != run_date or verified.get('participation_cessations') != recorded:
        raise ValueError('participation disposition no longer reconciles to its evidence')
    return recorded
