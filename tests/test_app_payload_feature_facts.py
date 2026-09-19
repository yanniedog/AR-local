import copy
import json

import pytest

from app_payload_details import build_details
from app_payload_feature_facts import feature_facts


def supports(facts, code):
    selected = [f for f in facts if f['canonicalKey'] == 'feature.' + code.lower()]
    return bool(selected) and all(f.get('value') is True and f['unit'] == 'boolean' for f in selected)


def test_unqualified_structured_feature_reaches_details_without_changing_source():
    record = {'features': [{'featureType': 'OFFSET'}, {'featureType': 'REDRAW'}]}
    saved = copy.deepcopy(record)
    detail = build_details([{'product_key': 'p', 'details_json': record}])['p']
    assert supports(detail['facts'], 'OFFSET') and supports(detail['facts'], 'REDRAW')
    assert detail['features'] == [{'label': 'OFFSET'}, {'label': 'REDRAW'}]
    assert record == saved
    assert detail['facts'] == feature_facts(record, 'p')
    assert feature_facts(record, 'different-product') != detail['facts']


@pytest.mark.parametrize('record', [
    {}, {'features': None}, {'features': {}}, {'features': [None, 'OFFSET', {}]},
    {'features': [{'featureType': 'offset'}]},
    {'description': 'An offset account is available.'},
    {'features': [{'featureType': 'OFFSET', 'additionalInfo': 'Variable loans only'}]},
    {'features': [{'featureType': 'OFFSET', 'additionalValue': '100%'}]},
    {'features': [{'featureType': 'OFFSET', 'futureScopeField': ['fixed']}]},
    {'features': [{'featureType': 'OFFSET'}], 'effectiveFrom': '2099-01-01'},
    {'features': [{'featureType': 'OFFSET'}], 'effectiveTo': '2000-01-01'},
    {'features': [{'featureType': 'OFFSET'}], 'description': 'No offset account is available.'},
    {'features': [{'featureType': 'OFFSET'}, {'featureType': 'OFFSET', 'additionalInfo': 'Fixed only'}]},
    {'features': [{'featureType': 'OFFSET'}], 'lendingRates': [{'additionalInfo': 'No offset facility'}]},
    {'features': [{'featureType': 'OFFSET'}], 'description': 'Offset is available for variable loans only.'},
    {'features': [{'featureType': 'OFFSET'}], 'sourceDocuments': [{'sourcePath': '/features/0/additionalInfoUri', 'url': 'https://example.com/terms'}]},
    {'features': [{'featureType': 'OFFSET'}], 'description': 'Offsets apply to variable loans only.'},
], ids=['missing', 'null', 'object', 'malformed-items', 'bad-code', 'text-only',
        'conditional', 'parameterized', 'unknown-scope', 'future', 'expired',
        'contradiction', 'mixed-scope', 'nested-contradiction', 'narrative-scope', 'linked-scope', 'plural-scope'])
def test_unknown_negative_or_conditional_evidence_cannot_grant_match(record):
    assert not supports(feature_facts(record, 'p'), 'OFFSET')


def test_unknown_stays_unknown_and_other_features_keep_their_scope():
    record = {'features': [{'featureType': 'OFFSET', 'additionalInfo': 'Variable only'},
                           {'featureType': 'REDRAW'}]}
    facts = feature_facts(record, 'p')
    offset = next(f for f in facts if f['sourceType'] == 'OFFSET')
    assert 'value' not in offset and offset['condition'] == 'Variable only'
    assert supports(facts, 'REDRAW')
    detail = build_details([{'product_key': 'p', 'details_json': json.dumps(record)}])['p']
    assert detail['features'][0]['info'] == 'Variable only'


def test_feature_projection_does_not_add_numeric_or_executable_terms():
    record = {'features': [{'featureType': 'OFFSET'}],
              'lendingRates': [{'lendingRateType': 'VARIABLE', 'rate': '0.0599'}],
              'fees': [{'feeType': 'PERIODIC', 'amount': '10.00'}]}
    assert {f['kind'] for f in feature_facts(record, 'p')} == {'feature'}
