"""Exact captured source and separately reviewed scope protocol controls."""
import json

import pytest

from app_payload_build import _gzip_bytes
from cdr_terms.executable_v2_sources import source_snapshot, _coverage
from cdr_terms.identity import canonical_json, digest
from tests.executable_protocol_fixture import protocol
from tests.executable_v2_fixture import subject_from_template, reidentify


@pytest.fixture
def v2_protocol(protocol):
    store, template, core, source = protocol
    subject = subject_from_template(template)
    product = {'features': [], 'name': 'Technical protocol record'}
    details = {'run_date': template['runDate'], 'products': {template['productKey']: product}}
    details_sha = store.put_blob(_gzip_bytes(details))
    manifest = json.loads(store.read_blob(template['selectedRate']['sourceManifestSha256']))
    manifest['files']['details'] = {'sha256': details_sha, 'bytes': len(store.read_blob(details_sha))}
    subject['source'].update(detailsAssetSha256=details_sha, productRecordSha256=digest(product),
        provenanceManifestSha256=store.put_blob(canonical_json(manifest).encode()),
        exportContractSha256=source['contract_digest'])
    yield store, reidentify(subject), core, details


def test_exact_source_scope_and_assets(v2_protocol):
    store, subject, _, _ = v2_protocol
    assert len(source_snapshot(store, subject)) == 64


def test_unknown_applicability_key_cannot_invent_scope(v2_protocol):
    subject = v2_protocol[1]
    scope = subject['scope']
    applicability = dict(product_key=scope['productKey'],cohort=scope['cohortKey'],tier=scope['tierKey'],
        package=scope['packageKey'],effective_from=scope['effectiveFrom'],effective_to=scope['effectiveToExclusive'],
        effective_scope='anything')
    with pytest.raises(ValueError, match='applicability differs'):
        _coverage(applicability, subject)


def test_product_wide_requires_actual_source_category(v2_protocol):
    store, subject, _, _ = v2_protocol
    subject['scope'].update(coverage='product',rateIndexes=[])
    subject['source']['rateRows'] = []
    with pytest.raises(ValueError, match='family lacks source category'):
        source_snapshot(store, reidentify(subject))


def test_details_record_hash_cannot_be_substituted(v2_protocol):
    store, subject, _, _ = v2_protocol
    subject['source']['productRecordSha256'] = '0'*64
    with pytest.raises(ValueError, match='details product differs'):
        source_snapshot(store, reidentify(subject))
