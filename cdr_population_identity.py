"""Retain prior holder identity without inventing current register membership."""
from datetime import date


def prior_provider_identity(observation, provider, baseline):
    matches = [row for row in observation['status'].get('provider_states', [])
        if isinstance(row,dict) and provider in {row.get('provider_dir'),row.get('provider_uid'),row.get('brand_name')}]
    row = matches[0] if len(matches) == 1 else {}
    return {'provider':provider,'provider_uid':row.get('provider_uid'),
        'provider_dir':row.get('provider_dir') or provider,
        'identity_status':'verified_prior_register' if row else 'verified_prior_database_name',
        'source_observation':{key:baseline[key] for key in ['observation_date','generation_id',
            'contract_digest','database_sha256','ledger_event_digest']}}


def verified_prior_identity(identity, provider, run_date):
    if not isinstance(identity, dict) or identity.get('provider') != provider:
        return False
    source = identity.get('source_observation') or {}
    try:
        day = source['observation_date']
        if date.fromisoformat(day).isoformat() != day or day >= run_date:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return (identity.get('identity_status') in {'verified_prior_register','verified_prior_database_name'}
        and isinstance(identity.get('provider_dir'), str) and bool(identity['provider_dir'])
        and (identity.get('provider_uid') is None or isinstance(identity['provider_uid'], str))
        and isinstance(source.get('generation_id'), str)
        and source['generation_id'].startswith('obs-'+day+'-')
        and all(isinstance(source.get(key), str) and len(source[key]) == 64
            and all(c in '0123456789abcdef' for c in source[key])
            for key in ['contract_digest','database_sha256','ledger_event_digest']))


def current_provider_matches(provider, identity, providers):
    uid = identity.get('provider_uid') if isinstance(identity, dict) else None
    if uid:
        return [row for row in providers if isinstance(row,dict) and row.get('provider_uid') == uid]
    return [row for row in providers
        if isinstance(row,dict) and provider in {row.get('provider_dir'),row.get('provider_uid'),row.get('brand_name')}]


def population_finding_resolved(finding, status):
    """Only the same holder's complete nonempty index resolves its absence."""
    providers = status.get('provider_states') or []
    diagnostics = status.get('index_diagnostics') or {}
    if not isinstance(providers, list) or not isinstance(diagnostics, dict):
        providers,diagnostics = [],{}
    matches = current_provider_matches(finding['provider'],finding.get('provider_identity'),providers)
    if len(matches) != 1:
        return False
    endpoint = (finding.get('provider_identity') or {}).get('endpoint_url')
    if endpoint is not None and matches[0].get('endpoint_url') != endpoint:
        return False
    name = matches[0].get('provider_dir') or finding['provider']
    diagnostic = diagnostics.get(name) or {}
    return (isinstance(diagnostic, dict) and diagnostic.get('pagination_complete') is True
        and type(diagnostic.get('unique_products')) is int and diagnostic['unique_products'] > 0)


def verified_historical_absence(finding, run_date, compared_against):
    """A reconstructed hold needs a separate, exact-holder zero-day proof."""
    absence = finding.get('historical_absence')
    identity = finding.get('provider_identity')
    if (not isinstance(absence,dict)
            or not verified_prior_identity(identity,finding.get('provider'),run_date)):
        return False
    zero_identity = absence.get('provider_identity')
    if not verified_prior_identity(zero_identity,finding.get('provider'),run_date):
        return False
    source,zero_source = identity['source_observation'],zero_identity['source_observation']
    return (identity.get('identity_status') == zero_identity.get('identity_status') == 'verified_prior_register'
        and bool(identity.get('provider_uid')) and identity['provider_uid'] == zero_identity.get('provider_uid')
        and isinstance(identity.get('endpoint_url'),str) and bool(identity['endpoint_url'])
        and identity['endpoint_url'] == zero_identity.get('endpoint_url')
        and source['observation_date'] < zero_source['observation_date'] <= compared_against
        and all(type(absence.get(key)) is int and absence[key] == 0 for key in ('products','rates')))


def retain_population_uncertainty(population, status):
    """Only a complete nonempty current index resolves this source uncertainty."""
    if population.get('unresolved_prior'):
        population['unresolved_prior'] = [row for row in population['unresolved_prior'] if not population_finding_resolved(row,status)]
    if population['status'] in {'PASS','WARN'}:
        population['findings'] = [row for row in population['findings'] if not population_finding_resolved(row,status)]
        population['status'] = 'WARN' if population['findings'] else 'PASS'
    return population
