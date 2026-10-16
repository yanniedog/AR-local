"""Carry unresolved population loss into canonical coverage without inventing HTTP failures."""
import json
from cdr_population_identity import current_provider_matches,verified_prior_identity


def apply_population_coverage(export_root, run_date, providers):
    path = export_root / 'provider-population-report.json'
    if not path.is_file():
        return []
    try:
        if path.is_symlink() or path.stat().st_size > 512*1024:
            return []
        report = json.loads(path.read_bytes())
        if not isinstance(report, dict):
            return []
    except (OSError, ValueError):
        return []  # Unusable evidence grants no new population authority.
    population = report.get('provider_population') or {}
    if not isinstance(population, dict):
        return []
    inherited = population.get('unresolved_prior') if population.get('status') == 'UNKNOWN' else None
    if population.get('status') != 'WARN' and not inherited:
        return []
    findings = ([{**row,'code':'provider_population_disappeared'} for row in inherited]
        if inherited else population.get('findings'))
    if report.get('run_date') != run_date or not isinstance(findings, list) or not findings:
        raise ValueError('population comparison is not attributable to this observation')
    warnings, seen = [], set()
    for finding in findings:
        name = finding.get('provider') if isinstance(finding, dict) else None
        identity = finding.get('provider_identity') if isinstance(finding,dict) else None
        matches = current_provider_matches(name,identity,providers)
        if (not name or name in seen or len(matches) > 1
                or (not matches and not verified_prior_identity(identity,name,run_date))
                or finding.get('code') != 'provider_population_disappeared'
                or finding.get('population_known') is not False
                or finding.get('disposition') != 'UNVERIFIED_SOURCE_ABSENCE'):
            raise ValueError('population warning does not reconcile to a provider')
        if matches:
            provider = matches[0]
            provider.update(state='failed', population_known=False,
                            population_disposition='UNVERIFIED_SOURCE_ABSENCE')
        else:
            provider = identity  # Prior identity is disclosed, never a current attempt.
        seen.add(name)
        warnings.append({'provider':name,'provider_uid':provider['provider_uid'],
            'population_known':False,'disposition':'UNVERIFIED_SOURCE_ABSENCE',
            **({'provider_identity':identity} if identity else {}),
            **({'current_register_membership':'absent'} if not matches else {}),
            **({'last_nonempty':finding['last_nonempty']} if 'last_nonempty' in finding else {})})
    return warnings
