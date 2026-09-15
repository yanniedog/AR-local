import json
import gzip

import pytest

from cdr_terms.executable_eligibility import verify_eligibility
from cdr_terms.executable_inputs import validate_instantiated_input
from cdr_terms.executable_reviews import source_snapshot
from cdr_terms.executable_benchmarks import validate_result
from tests.test_executable_actual_bridge import BRIDGE
from tests.executable_protocol_fixture import protocol  # noqa: F401

VECTORS = json.loads(gzip.decompress(BRIDGE.with_name('eligibility-oracle-v1.json.gz').read_bytes()))


@pytest.mark.parametrize('case', VECTORS['cases'], ids=lambda item: item['name'])
def test_actual_typescript_eligibility_vectors(case):
    assert verify_eligibility(case['rule'], case['facts']) == case['result']


@pytest.mark.parametrize('principal', ['1e3', ' 1000', '+1000', '01000', 'NaN', 'Infinity', '1000', '1000.0', '1000.000'])
@pytest.mark.parametrize('field', ['contract', 'scenario', 'confirmation'])
def test_adapter_invalid_principal_spelling_is_refused(field, principal):
    record = json.loads(BRIDGE.with_name('actual-v8-bridge.json').read_bytes())['records'][0]
    inputs = record['instantiatedInput']
    if field == 'contract':
        inputs['contract']['tdLifecycle']['investmentAmount'] = principal
    elif field == 'scenario':
        inputs['scenario']['openingBalance'] = principal
    else:
        inputs['scenario']['tdConfirmation']['principal'] = principal
    with pytest.raises(ValueError):
        validate_instantiated_input(record['template'], inputs)


def test_snapshot_builds_current_product_projection_once(protocol, monkeypatch):
    store, template, *_ = protocol
    import cdr_terms.executable_sources as sources
    original, calls = sources.build_product_asset, []
    def counted(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(sources, 'build_product_asset', counted)
    source_snapshot(store, template)
    assert len(calls) == 1


@pytest.mark.parametrize('facts', [{}, {'protocol_amount': None}])
def test_fabricated_complete_eligibility_is_refused(facts):
    record = json.loads(BRIDGE.with_name('actual-v8-bridge.json').read_bytes())['records'][0]
    record['instantiatedInput']['scenario']['facts'] = facts
    from cdr_terms.identity import digest
    record['output']['inputSha256'] = digest(record['instantiatedInput'])
    with pytest.raises(ValueError, match='eligibility differs'):
        validate_result(record['output'], record['template'], record['instantiatedInput'])


@pytest.mark.parametrize('explicit_null', [False, True])
def test_missing_customer_fact_cannot_authorize_complete_receipt(protocol, explicit_null):
    from tests.executable_benchmark_fixture import benchmark_control
    from tests.executable_protocol_fixture import reidentify
    from cdr_terms.identity import digest
    store, template, *_ = protocol
    definition = next(item for item in template['inputDefinitions'] if item['binding'] == 'deposit_principal')
    definition['binding'] = 'customer_fact'
    reidentify(template)
    run = benchmark_control(store, template)
    case = run['cases'][0]
    inputs = json.loads(store.read_blob(case['inputSha256']))
    if explicit_null:
        inputs['scenario']['facts'][definition['key']] = None
    result = json.loads(store.read_blob(case['actualSha256']))['result']
    result['inputSha256'] = digest(inputs)
    result['eligibility'] = {'status': 'meets', 'reasons': [], 'trace': {
        'id': template['eligibility']['id'], 'evidenceIds': template['eligibility']['evidenceIds'], 'status': 'meets'}}
    validate_instantiated_input(template, inputs)
    with pytest.raises(ValueError, match='eligibility differs'):
        validate_result(result, template, inputs)
