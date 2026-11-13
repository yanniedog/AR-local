import json

import pytest

from app_payload_participation import public_participation_cessations
from tests.test_cdr_provider_participation import captured_population, captured_status, DAY
from cdr_population_lifecycle import reconcile_participation


def test_public_disclosure_is_explicit_without_internal_provenance(tmp_path):
    from app_payload_observation_gate import contract_coverage
    from app_payload_build import _stable_payload_coverage
    population = reconcile_participation(captured_population(), captured_status(tmp_path), tmp_path, DAY)
    receipts = population['participation_cessations']
    public = public_participation_cessations(receipts)
    assert public[0]['provider'] == 'Wise'
    assert public[0]['observed_at'].startswith('2026-11-13T')
    assert public[0]['disposition'] == 'CDR_PARTICIPATION_CEASED'
    assert public[0]['product_withdrawal_confirmed'] is False
    assert not {'sources', 'unresolved_finding', 'current_register'} & public[0].keys()
    assert 'https://' not in json.dumps(public)
    assert 'sources' in receipts[0]  # Internal audit remains intact.
    internal = {'provider_participation_ceased': receipts}
    disclosed = contract_coverage({'coverage': internal, 'observation_state': 'complete'})
    assert disclosed['provider_participation_ceased'] == public
    for incoming in (internal, disclosed):
        built = _stable_payload_coverage({}, {}, DAY, incoming)
        assert built['provider_participation_ceased'] == public
        assert 'https://' not in json.dumps(built['provider_participation_ceased'])


@pytest.mark.parametrize('field,value', [('provider', {'endpoint': 'https://private.example'}),
                                       ('product_withdrawal_confirmed', True), ('disposition', 'unknown')])
def test_bad_lifecycle_metadata_cannot_be_misrepresented(tmp_path, field, value):
    population = reconcile_participation(captured_population(), captured_status(tmp_path), tmp_path, DAY)
    rows = population['participation_cessations']
    rows[0][field] = value
    with pytest.raises(ValueError):
        public_participation_cessations(rows)


def test_financial_scope_partial_publication_preserves_both_safe_disclosures(tmp_path):
    """Integration: real register scope plus both formerly conflicting projections."""
    from app_payload_observation_gate import contract_coverage, publication_allowed
    from app_payload_build import _stable_payload_coverage
    from tests.test_app_payload_retained_policy import retained_accounting
    from tests.test_app_payload_partial_accounting import seal

    status = captured_status(tmp_path)
    assert status['providers_registered'] == 306  # 115 banks + 191 NBL in captured register.
    population = reconcile_participation(captured_population(), status, tmp_path, DAY)
    contract = retained_accounting(tmp_path, DAY)
    contract['coverage']['provider_participation_ceased'] = population['participation_cessations']
    # Protocol-only uncertainty metadata; no product/rate observation is invented.
    contract['coverage']['provider_population_unverified'] = [{
        'provider': 'Westpac', 'population_known': False, 'disposition': 'UNVERIFIED_SOURCE_ABSENCE',
        'provider_identity': {'endpoint_url': 'https://transport.example/private-context'},
    }]
    seal(contract)
    assert publication_allowed(contract) == (True, 'retained_partial')
    built = _stable_payload_coverage({}, {}, DAY, contract_coverage(contract))
    assert built['observation_state'] == 'partial'
    assert built['publication_policy']['absence_is_removal'] is False
    assert built['provider_population_unverified'][0]['provider'] == 'Westpac'
    assert built['provider_participation_ceased'][0]['provider'] == 'Wise'
    assert built['provider_participation_ceased'][0]['product_withdrawal_confirmed'] is False
    assert 'https://' not in json.dumps(built)
