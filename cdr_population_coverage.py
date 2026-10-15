"""Carry unresolved population loss into canonical coverage without inventing HTTP failures."""
import json


def apply_population_coverage(export_root, run_date, providers):
    path = export_root / 'sanity-report.json'
    if not path.is_file():
        return []
    if path.stat().st_size > 512*1024:
        raise ValueError('population comparison exceeds metadata budget')
    report = json.loads(path.read_bytes())
    population = report.get('provider_population') or {}
    if population.get('status') != 'WARN':
        return []
    findings = population.get('findings')
    if report.get('run_date') != run_date or not isinstance(findings, list) or not findings:
        raise ValueError('population comparison is not attributable to this observation')
    warnings, seen = [], set()
    for finding in findings:
        name = finding.get('provider') if isinstance(finding, dict) else None
        matches = [p for p in providers if name in {p.get('provider_dir'),p.get('provider_uid')}]
        if (not name or name in seen or len(matches) != 1
                or finding.get('code') != 'provider_population_disappeared'
                or finding.get('population_known') is not False
                or finding.get('disposition') != 'UNVERIFIED_SOURCE_ABSENCE'):
            raise ValueError('population warning does not reconcile to a provider')
        provider = matches[0]
        provider.update(state='failed', population_known=False,
                        population_disposition='UNVERIFIED_SOURCE_ABSENCE')
        seen.add(name)
        warnings.append({'provider':name,'provider_uid':provider['provider_uid'],
            'population_known':False,'disposition':'UNVERIFIED_SOURCE_ABSENCE'})
    return warnings
