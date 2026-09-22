"""Discovery-to-publication protocol controls; no fabricated acceptance data."""
import copy

import pytest

from app_payload_details import build_details
from cdr_clean_export import detail_json


@pytest.mark.parametrize('raw', [
    '%20https://www.cwcu.com.au/disclosure-documents/fees-and-charges',
    ' %20%20HTTPS://example.com/a%20b?q=%20#fees ',
])
def test_recovered_reference_survives_cleaning_and_payload_packaging(raw):
    cleaned = detail_json({'additionalInformation': {'feesAndPricingUri': raw}})
    result = build_details([{'product_key': 'protocol-product', 'details_json': cleaned}])
    reference = result['protocol-product']['sourceDocuments'][0]
    assert reference['sourceUrl'] == raw
    assert reference['sourceNormalization'] == 'leading-encoded-space-v1'
    assert reference['sourcePath'] == '/additionalInformation/feesAndPricingUri'
    assert reference['url'].startswith('https://')
    if 'example.com' in raw:
        assert reference['url'] == 'https://example.com/a%20b?q=%20'


@pytest.mark.parametrize('patch', [
    {'sourceNormalization': 'unknown'}, {'sourceNormalization': None},
    {'sourceNormalization': {}}, {'sourceUrl': 'https://example.com/fees'},
    {'sourceUrl': '%2520https://example.com/fees'},
    {'sourceUrl': '%20javascript:alert(1)'},
    {'sourceUrl': '%20https://user:pass@example.com/fees'},
    {'url': 'https://other.example/fees'}, {'sourceUrl': None},
])
def test_normalization_marker_cannot_waive_exact_safe_source_binding(patch):
    reference = {'url': 'https://example.com/fees', 'sourceUrl': '%20https://example.com/fees',
                 'sourcePath': '/fees/0/additionalInfoUri', 'relation': 'fees',
                 'sourceNormalization': 'leading-encoded-space-v1'}
    reference.update(patch)
    with pytest.raises(ValueError, match='invalid_source_document_reference'):
        build_details([{'product_key': 'protocol-product', 'details_json': {'sourceDocuments': [reference]}}])


def test_marker_without_original_source_is_refused():
    reference = {'url': 'https://example.com/fees', 'sourcePath': '/fees',
                 'relation': 'fees', 'sourceNormalization': 'leading-encoded-space-v1'}
    with pytest.raises(ValueError, match='invalid_source_document_reference'):
        build_details([{'product_key': 'protocol-product', 'details_json': {'sourceDocuments': [reference]}}])


def test_ordinary_reference_is_preserved_without_a_marker():
    record = {'sourceDocuments': [{'url': 'https://example.com/fees',
        'sourceUrl': 'https://example.com/fees#clause', 'sourcePath': '/fees', 'relation': 'fees'}]}
    original = copy.deepcopy(record)
    result = build_details([{'product_key': 'protocol-product', 'details_json': record}])
    assert result['protocol-product']['sourceDocuments'] == original['sourceDocuments']
    assert record == original
