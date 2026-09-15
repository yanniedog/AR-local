"""Closed wire, offline references and exact association protocol controls."""
import copy
import json
from pathlib import Path

import pytest

from cdr_terms.executable_v2_contract import CHECKS, validate_asset, validate_subject
from cdr_terms.identity import digest
from tests.executable_v2_fixture import reidentify


@pytest.fixture
def subject():
    return json.loads((Path(__file__).parent / 'fixtures/executable-templates/canonical-identity-v2.json').read_bytes())['subject']


def asset(subject):
    source = subject['source']
    value = dict(schemaVersion=2, productKey=subject['scope']['productKey'],
        sourceObservationId=source['observationId'], sourceGenerationId=source['generationId'],
        runDate=source['runDate'], coreAssetSha256=source['coreAssetSha256'], detailsAssetSha256=source['detailsAssetSha256'],
        approvalPolicy='as_of_adopted_edition', subjects=[{'subject':subject, 'approval':{
            'subjectId':subject['id'], 'capability':subject['capability'], 'reviewId':'d'*64,
            'reviewEvidenceSha256':'e'*64, 'benchmarkResultSha256':'f'*64, 'sourceSnapshotSha256':'a'*64,
            'reviewedAt':'2026-01-01T01:00:00Z', 'checks':{key:'verified' for key in CHECKS}}}])
    return identify_asset(value)


def identify_asset(value):
    value['identitySha256'] = digest({k:v for k,v in value.items() if k != 'identitySha256'})
    return value


def test_actual_relative_schema_reference_and_unicode_identity(subject):
    validate_subject(subject)
    validate_asset(asset(subject), product_key=subject['scope']['productKey'])


def test_frozen_index_allows_unicode_product_keys(subject):
    from cdr_terms.executable_v2_contract import schema_validate
    schema_validate(dict(schema_version=2,run_date=subject['source']['runDate'],
        core_asset_sha256=subject['source']['coreAssetSha256'],details_asset_sha256=subject['source']['detailsAssetSha256'],
        products={subject['scope']['productKey']:'executable_v2_shard_000'}),'executable-index-v2.schema.json')


@pytest.mark.parametrize('url', ['https://', 'https://user@example.invalid/', 'https://example.invalid:99999/', 'https://example.invalid/ x'])
def test_invalid_source_url_refused(subject, url):
    subject['evidence'][0]['sourceUrl'] = url
    with pytest.raises(ValueError):
        validate_subject(reidentify(subject))


def test_blank_label_refused(subject):
    subject['inputDefinitions'][0]['label'] = ' \t '
    with pytest.raises(ValueError, match='blank'):
        validate_subject(reidentify(subject))


def test_approval_must_name_exact_subject(subject):
    value = asset(subject)
    value['subjects'][0]['approval']['subjectId'] = '0'*64
    with pytest.raises(ValueError, match='approval subject'):
        validate_asset(identify_asset(value))


def test_different_subject_same_scope_refused(subject):
    value = asset(subject)
    other = copy.deepcopy(value['subjects'][0])
    other['subject']['inputDefinitions'][0]['label'] = 'Changed reviewed label'
    reidentify(other['subject'])
    other['approval']['subjectId'] = other['subject']['id']
    value['subjects'].append(other)
    with pytest.raises(ValueError, match='duplicate subject/scope'):
        validate_asset(identify_asset(value))
