"""Register-v2 PRD unavailability is source absence, never product withdrawal."""
from __future__ import annotations


def validate_prd_dispositions(payload, status, event, uid_for, *, allow_filtered=False):
    """Reconcile new dispositions only after the caller verifies the raw event.

    Old observations without this field retain their historical interpretation.
    The request selects v2; an absent response x-v is tolerated, a conflicting
    response version is not. Future/unknown versions cannot authorize absence.
    """
    if 'providers_prd_unavailable' not in status:
        return []
    from cdr_ingest_support import allocate_bank_dir, iter_banking_brands_from_payload, REGISTER_URL_SUMMARY
    providers = status['provider_states']
    count = status['providers_prd_unavailable']
    if type(count) is not int or count < 0:
        raise ValueError('invalid PRD availability count')
    attempted = sum(row.get('state') != 'not_attempted' for row in providers)
    if (status['providers_attempted'] != attempted
            or (not allow_filtered and len(providers) != status['providers_registered'])
            or attempted + count != len(providers)):
        raise ValueError('PRD availability counts do not reconcile')
    request, response = event['request'], event['response']
    if not count and status['register_attempts'][0].get('version') != 2:
        return []  # Explicit historical/unknown-version compatibility path.
    if (request['headers'].get('x-v') != '2'
            or response['headers'].get('x-v') not in (None, '2')
            or event['context'].get('cdr_version') != 2
            or status['register_attempts'][0].get('version') != 2):
        raise ValueError('PRD unavailability requires captured register v2')
    expected = {}
    observed = {row['provider_uid'] for row in providers}
    brands = {uid_for(brand): brand for brand in iter_banking_brands_from_payload(payload, register_version=2)}
    seen_directories, directories = set(), {}
    # Discovery filters before its stable name sort and directory allocation.
    selected = sorted((brand for uid, brand in brands.items() if uid in observed),
                      key=lambda brand: (brand['brand_name'] or brand['legal_entity_name'] or '').lower())
    for brand in selected:
        directory = allocate_bank_dir(brand['brand_name'], brand['legal_entity_name'],
                                      brand['endpoint_url'], seen_directories)
        directories[uid_for(brand)] = directory
    for provider in providers:
        brand = brands[provider['provider_uid']]
        if (provider.get('provider_dir') != directories[provider['provider_uid']]
                or any((provider.get(key) or '') != (brand.get(key) or '')
                       for key in ('brand_name', 'legal_entity_name', 'endpoint_url'))):
            raise ValueError('PRD provider directory differs from verified registration')
    for brand in brands.values():
        if brand.get('prd_availability') != 'UNAVAILABLE':
            continue
        if allow_filtered and uid_for(brand) not in observed:
            continue
        expected[uid_for(brand)] = {
            'register_version': 2, 'register_body_sha256': response['body_sha256'],
            'registration_id': brand.get('registration_id'), 'source_url': REGISTER_URL_SUMMARY,
        }
    found = []
    for provider in providers:
        uid = provider['provider_uid']
        if uid not in expected:
            if provider.get('state') == 'not_attempted' or provider.get('prd_availability') == 'UNAVAILABLE':
                raise ValueError('unattempted provider lacks register PRD evidence')
            continue
        if (provider.get('state') != 'not_attempted' or provider.get('population_known') is not False
                or provider.get('prd_availability') != 'UNAVAILABLE'
                or provider.get('prd_availability_evidence') != expected[uid]
                or provider.get('failure_records') != 0 or provider.get('failure_categories') != {}):
            raise ValueError('register PRD disposition does not match provider state')
        found.append({'provider': provider['brand_name'], 'provider_uid': uid,
                      'disposition': 'PRD_UNAVAILABLE', 'population_known': False,
                      'product_withdrawal_confirmed': False,
                      'register_body_sha256': response['body_sha256'],
                      'registration_id': expected[uid]['registration_id']})
    if len(found) != len(expected) or len(found) != count:
        raise ValueError('register PRD unavailability population differs')
    return found
