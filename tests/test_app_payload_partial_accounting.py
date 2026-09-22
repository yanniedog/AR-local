"""Retained September22 counts; resealed mutations are protocol faults only."""
import copy
import json
from pathlib import Path

import pytest

import app_payload_observation_gate as gate
import app_payload_build
import pi_daily_sync
from cdr_export_contract import build_contract, contract_digest, generation_id_for, source_generation_digest


@pytest.fixture
def contract(tmp_path):
    retained = json.loads((Path(__file__).parent / 'fixtures' /
                           'publication-accounting-2026-09-22.json').read_bytes())
    return build_contract(tmp_path, observation_date='2026-09-22',
        observed_at='2026-09-21T15:15:00Z', observation_state='partial',
        source_path='runs/2026-09-22/_exports', completion_marker_path='2026-09-22.done.json',
        coverage=retained['coverage'], provider_states=retained['provider_states'],
        register_hashes=retained['register_hashes'], artifacts=[retained['artifact']],
        normalization_version='protocol-derived-september22-accounting')


def seal(contract):
    contract['source_generation_digest'] = source_generation_digest(contract)
    contract['generation_id'] = generation_id_for(contract['observation_date'],
        contract['source_generation_digest'], contract['prior_ledger_head'])
    contract['contract_digest'] = contract_digest(contract)


def test_september22_classified_partial_is_publishable_without_relabelling(contract):
    original = copy.deepcopy(contract)
    assert not gate.bounded_partial_v1_allowed(contract)  # actual old refusal
    assert gate.publication_allowed(contract) == (True, 'reconciled_partial')
    assert pi_daily_sync._bounded_partial_v1_allowed(contract)
    assert contract == original
    assert gate.contract_coverage(contract)['failure_records'] == 47
    assert gate.contract_coverage(contract)['providers_partial'] == 11
    disclosed = gate.contract_coverage(contract)
    assert disclosed['publication_policy']['severity'] == 'severe'
    # Exercise the actual builder's stable coverage transport with a protocol
    # shell; the real product/rate output is checked separately against Sept22.
    coverage = app_payload_build._stable_payload_coverage({}, {}, '2026-09-22', disclosed)
    assert coverage['publication_policy'] == disclosed['publication_policy']
    assert coverage['counts']['providers_partial'] == 11


@pytest.mark.parametrize('field,value', [
    ('failure_provenance_complete', False), ('register_provenance_complete', False),
    ('corrupt_failure_records', 1), ('unattributed_failure_records', 1),
    ('products_discovered', 0), ('eligible_rate_rows', 0),
    ('providers_registered', 118), ('providers_attempted', 116),
    ('providers_complete', 105), ('providers_partial', 12), ('providers_failed', 1),
    ('failure_records', 48), ('register_sources_complete', 0),
    ('reconciliation_status', 'unknown'), ('products_discovered', True),
])
def test_resealed_incomplete_accounting_stays_blocked(contract, field, value):
    contract['coverage'][field] = value
    seal(contract)
    assert not gate.reconciled_partial_v1_allowed(contract)


@pytest.mark.parametrize('fault', [
    'duplicate_provider', 'missing_provider', 'missing_categories', 'wrong_categories',
    'unknown_category', 'security_failure', 'budget_failure', 'state_conflict',
    'unattempted', 'quarantine', 'no_register',
])
def test_provider_and_provenance_faults_are_not_waived(contract, fault):
    provider = next(p for p in contract['provider_states'] if p['failure_records'])
    if fault == 'duplicate_provider':
        contract['provider_states'][-1] = copy.deepcopy(provider)
    elif fault == 'missing_provider':
        contract['provider_states'].pop()
    elif fault == 'missing_categories':
        del provider['failure_categories']
    elif fault == 'wrong_categories':
        provider['failure_categories'] = {'endpoint_not_found': provider['failure_records'] + 1}
    elif fault in {'unknown_category', 'security_failure', 'budget_failure'}:
        category = {'unknown_category': 'unknown', 'security_failure': 'security_policy',
                    'budget_failure': 'recovery_budget_exhausted'}[fault]
        provider['failure_categories'] = {category: provider['failure_records']}
    elif fault == 'state_conflict':
        provider['state'] = 'complete'
    elif fault == 'unattempted':
        provider['state'] = 'not_attempted'
    elif fault == 'quarantine':
        contract['quarantines'] = [{'reason': 'unresolved protocol control'}]
    else:
        contract['register_hashes'] = []
    seal(contract)
    assert not gate.reconciled_partial_v1_allowed(contract)


@pytest.mark.parametrize('field', ['generation_id', 'contract_digest', 'source_generation_digest'])
def test_unsealed_identity_tampering_is_rejected(contract, field):
    contract[field] = '0' * 64
    assert not gate.reconciled_partial_v1_allowed(contract)


def test_reconciled_high_volume_retains_partial_status(contract):
    provider = next(p for p in contract['provider_states'] if p['failure_records'])
    provider['failure_categories'] = {'transient_upstream': provider['failure_records'] + 1200}
    provider['failure_records'] += 1200
    contract['coverage']['failure_records'] += 1200
    seal(contract)
    assert gate.publication_allowed(contract) == (True, 'reconciled_partial')
    assert contract['observation_state'] == 'partial'


def test_whole_provider_failure_is_disclosed_and_reconciled(contract):
    provider = next(p for p in contract['provider_states'] if p['state'] == 'partial')
    provider['state'] = 'failed'
    contract['coverage']['providers_partial'] -= 1
    contract['coverage']['providers_failed'] += 1
    seal(contract)
    assert gate.publication_allowed(contract) == (True, 'reconciled_partial')
    assert gate.contract_coverage(contract)['providers_failed'] == 1
