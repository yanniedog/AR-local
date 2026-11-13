"""Public lifecycle disclosure without archived transport or historical identities."""
from typing import Mapping


def public_participation_cessations(rows):
    if not isinstance(rows, list):
        raise ValueError('invalid provider participation dispositions')
    result = []
    required = ('provider', 'provider_uid', 'disposition', 'observed_at')
    optional = ('applicable_observation_date', 'current_register_membership')
    for row in rows:
        if (not isinstance(row, Mapping)
                or any(not isinstance(row.get(key), str) or not row[key] for key in required)
                or row['disposition'] != 'CDR_PARTICIPATION_CEASED'
                or row.get('product_withdrawal_confirmed') is not False):
            raise ValueError('unverified provider participation disposition')
        public = {key: row[key] for key in required}
        public.update({key: row[key] for key in optional if isinstance(row.get(key), str)})
        public['product_withdrawal_confirmed'] = False
        result.append(public)
    return result
