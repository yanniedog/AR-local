"""Retained source URL defects and protocol boundaries; no fabricated rates."""
import pytest

from cdr_terms.discovery import discover_references, document_url
from cdr_terms.store import EvidenceStore


@pytest.mark.parametrize('field,url', [
    ('additionalInfoUri', 'https://australianmutual.bank/about-us/disclosures-and-reports/'),
    ('feesAndPricingUri', 'https://www.cwcu.com.au/disclosure-documents/fees-and-charges'),
    ('bundleUri', 'https://www.cwcu.com.au/lending/apply-for-a-loan'),
])
def test_retained_encoded_space_reference_preserves_original(field, url):
    raw = '%20' + url
    record = {'additionalInformation': {field: raw}}
    refs = discover_references(record)
    assert len(refs) == 1
    assert refs[0].url == url
    assert refs[0].sourceUrl == raw
    assert refs[0].sourcePath == '/additionalInformation/' + field
    assert refs[0].as_dict()['sourceNormalization'] == 'leading-encoded-space-v1'
    assert record['additionalInformation'][field] == raw
    assert document_url(raw) is None  # General URL admission is unchanged.


def test_normalized_uri_list_retains_distinct_anchor_scopes():
    refs = discover_references({'additionalInformation': {'additionalTermsUris': [
        '%20https://example.com/a%20b?q=%20#first',
        {'url': '%20%20https://example.com/a%20b?q=%20#second'}]}})
    assert len(refs) == 2
    assert {r.url for r in refs} == {'https://example.com/a%20b?q=%20'}
    assert len({r.sourcePath for r in refs}) == 2
    assert {r.sourceUrl.split('#')[-1] for r in refs} == {'first', 'second'}


@pytest.mark.parametrize('raw', ['%2520https://example.com/', '%09https://example.com/',
    '%20javascript:alert(1)', '%20//example.com/', '%20https://user:pass@example.com/',
    '%20https://example.com:bad/', '%20https://example.com/\x00bad'])
def test_no_broad_decode_or_unsafe_url_admission(raw):
    assert discover_references({'termsUri': raw}) == []


def test_normalization_context_is_persisted_and_idempotent(tmp_path):
    import json
    record = {'additionalInformation': {'feesAndPricingUri': '%20https://www.cwcu.com.au/disclosure-documents/fees-and-charges'}}
    with EvidenceStore(tmp_path) as store:
        args = dict(provider='Central West CUL', product_key='technical-url-protocol', record=record,
                    observed_at='2026-09-22T00:00:00Z', ingest_id='technical-url-protocol')
        first = store.observe(**args)
        assert store.observe(**args) == first
        rows = store.db.execute('SELECT context_json FROM applicability').fetchall()
        assert len(rows) == 1
        context = json.loads(rows[0][0])
        assert context['sourceUrl'] == record['additionalInformation']['feesAndPricingUri']
        assert context['sourceNormalization'] == 'leading-encoded-space-v1'
