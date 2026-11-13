import json

import pytest

from app_payload_participation import public_participation_cessations
from tests.test_cdr_provider_participation import captured_population, captured_status, DAY
from cdr_population_lifecycle import reconcile_participation


def test_public_disclosure_is_explicit_without_internal_provenance(tmp_path):
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


@pytest.mark.parametrize('field,value', [('provider', {'endpoint': 'https://private.example'}),
                                       ('product_withdrawal_confirmed', True), ('disposition', 'unknown')])
def test_bad_lifecycle_metadata_cannot_be_misrepresented(tmp_path, field, value):
    population = reconcile_participation(captured_population(), captured_status(tmp_path), tmp_path, DAY)
    rows = population['participation_cessations']
    rows[0][field] = value
    with pytest.raises(ValueError):
        public_participation_cessations(rows)
