"""Captured provider identities; register ordering/availability are fault controls."""
import copy
import hashlib

import pytest

from cdr_atomic import canonical_json_bytes
from cdr_ingest_support import append_failure
from cdr_recovery_queue import add_recovery_requests
from cdr_reuse_identity import provider_identity
from tests import test_cdr_same_day_reuse as fixture


@pytest.mark.parametrize('unavailable', [False, True])
def test_retained_failure_uses_current_uid_availability_after_directory_change(tmp_path, unavailable):
    original = fixture._record('Defence Bank')
    occupying = fixture._new_identity(original)
    alias = copy.deepcopy(original['state'])
    alias['provider_dir'] = 'Defence Bank_product_defencebank_com_au'
    if unavailable:
        alias.update(state='not_attempted', prd_availability='UNAVAILABLE', population_known=False)
    retained = {**original['state'], 'retained_from_generation_id': 'retained-control'}
    manifest = {'schema_version': 1, 'reconciled': True,
        'providers': {original['provider']: provider_identity(original['state'])},
        'identity_blocks': {original['provider']: {'previous': provider_identity(original['state']),
                                                  'current': provider_identity(occupying['state'])}}}
    status = {'provider_states': [occupying['state'], alias], 'retained_provider_states': [retained],
              'same_day_reuse': {**manifest, 'manifest_sha256': hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()}}
    append_failure(tmp_path, {'bank': original['provider'], 'phase': 'products_index', 'status': 504})
    before = (tmp_path / 'failures.jsonl').read_bytes()
    add_recovery_requests(status, tmp_path, [])
    assert (tmp_path / 'failures.jsonl').read_bytes() == before
    assert status['unresolved_request_sample_count'] == (0 if unavailable else 1)
    if unavailable:
        assert status['unresolved_requests_complete'] is False
    else:
        assert status['unresolved_requests'][0]['provider_uid'] == original['state']['provider_uid']
        assert status['unresolved_requests'][0]['url'] == original['brand']['endpoint_url']
