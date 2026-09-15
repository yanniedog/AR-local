"""Exact current product/details/variant authority for scoped eligibility."""
import json
import re
from datetime import date, timedelta

from .executable_sources import _core, finalized_capture, source_checked
from .identity import canonical_json, digest
from .observation_checks import current_observation
from .reporting import build_product_asset
from .executable_v2_contract import validate_subject
from .revisions import APPLICABILITY_FIELDS

FAMILIES = {'Mortgage': 'Mortgage', 'Savings': 'Savings', 'TD': 'TD'}


def validate_destination(subject, core, details, *, core_sha, details_sha):
    scope, source = subject['scope'], subject['source']
    if source['coreAssetSha256'] != core_sha or source['detailsAssetSha256'] != details_sha:
        raise ValueError('Executable v2 adopted assets differ')
    if core['run_date'] != source['runDate'] or details['run_date'] != source['runDate']:
        raise ValueError('Executable v2 adopted dates differ')
    product = details.get('products', {}).get(scope['productKey'])
    if not isinstance(product, dict) or digest(product) != source['productRecordSha256']:
        raise ValueError('Executable v2 exact details product differs')
    rows = core.get('sections', {}).get(FAMILIES[scope['family']], {}).get('rates', [])
    if not isinstance(rows, list) or len(rows) > 200000:
        raise ValueError('Executable v2 source rows exceed bound')
    for binding in source['rateRows']:
        index = binding['coreRowIndex']
        if index >= len(rows):
            raise ValueError('Executable v2 selected rate missing')
        row = rows[index]
        if not isinstance(row, dict) or row.get('product_key') != scope['productKey'] or row.get('rate_index') != binding['rateIndex'] or digest(row) != binding['rowSha256']:
            raise ValueError('Executable v2 selected rate differs')


def selected_assets(store, subject):
    source, scope = subject['source'], subject['scope']
    receipt = finalized_capture(store, source['generationId'], source['runDate'])
    if ((source['observationId'], scope['productKey'], source['sourceSha256']) not in receipt['_verified_members']
            or receipt['export_contract_digest'] != source['exportContractSha256']):
        raise ValueError('Executable v2 finalized member differs')
    manifest = json.loads(store.read_blob(source['provenanceManifestSha256']))
    expected = {'generation_id': source['generationId'], 'contract_digest': source['exportContractSha256']}
    if manifest.get('enc') or manifest.get('run_date') != source['runDate'] or any(manifest.get('source_observation', {}).get(k) != v for k, v in expected.items()):
        raise ValueError('Executable v2 provenance manifest differs')
    assets = {}
    for name, field in (('core', 'coreAssetSha256'), ('details', 'detailsAssetSha256')):
        asset, size = _core(store, source[field])  # Same operation-local count/decoded byte budget.
        descriptor = manifest['files'][name]
        if descriptor['sha256'] != source[field] or descriptor['bytes'] != size or descriptor.get('enc'):
            raise ValueError('Executable v2 source descriptor differs')
        assets[name] = asset
    validate_destination(subject, assets['core'], assets['details'], core_sha=source['coreAssetSha256'], details_sha=source['detailsAssetSha256'])


def _coverage(applicability, subject):
    scope, source = subject['scope'], subject['source']
    if set(applicability) != APPLICABILITY_FIELDS or any(applicability.get(k) != scope[s] for k, s in (
            ('product_key', 'productKey'), ('cohort', 'cohortKey'), ('tier', 'tierKey'), ('package', 'packageKey'))):
        raise ValueError('Executable v2 source applicability differs')
    lower, upper = applicability.get('effective_from'), applicability.get('effective_to')
    for endpoint in (lower, upper):
        if endpoint is not None:
            if not isinstance(endpoint, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', endpoint):
                raise ValueError('Executable v2 source interval precision unknown')
            date.fromisoformat(endpoint)
    if ((lower is not None and lower > scope['effectiveFrom'])
            or (upper is not None and upper < scope['effectiveToExclusive'])):
        raise ValueError('Executable v2 coverage exceeds source interval')
    if lower is None or upper is None:
        observed = date.fromisoformat(source['runDate'])
        if scope['effectiveFrom'] != observed.isoformat() or scope['effectiveToExclusive'] != (observed + timedelta(days=1)).isoformat():
            raise ValueError('Executable v2 unstated source dates support observed day only')


@source_checked
def source_snapshot(store, subject):
    validate_subject(subject)
    source, scope = subject['source'], subject['scope']
    observation = current_observation(store, scope['productKey'])
    if any(observation[k] != source[v] for k, v in (('observation_id', 'observationId'), ('source_sha256', 'sourceSha256'), ('ingest_id', 'generationId'))):
        raise ValueError('Executable v2 current observation differs')
    raw = json.loads(store.read_blob(source['sourceSha256']))
    if scope['coverage'] == 'product':
        product = raw.get('data', raw) if isinstance(raw, dict) else None
        category = product.get('productCategory') if isinstance(product, dict) else None
        expected = {'Mortgage': 'RESIDENTIAL_MORTGAGES', 'Savings': 'TRANS_AND_SAVINGS_ACCOUNTS', 'TD': 'TERM_DEPOSITS'}
        if category != expected[scope['family']]:
            raise ValueError('Executable v2 product-wide family lacks source category')
    selected_assets(store, subject)
    projection = build_product_asset(store, scope['productKey'])
    revisions = {r['term_revision_id']: r for r in projection['revisions']}
    clauses, reviews = set(), []
    for identity in source['termRevisionIds']:
        revision = revisions.get(identity)
        if revision is None:
            raise ValueError('Executable v2 revision is not currently validated')
        _coverage(revision['applicability'], subject)
        clauses.update(revision['clause_ids'])
        row = store.db.execute('SELECT review_id FROM reviews WHERE term_revision_id=? ORDER BY sequence DESC LIMIT 1', (identity,)).fetchone()
        reviews.append(row[0])
    if not set(source['documentVersionIds']) <= {d['document_version_id'] for d in projection['documents']}:
        raise ValueError('Executable v2 document is not current')
    for evidence in subject['evidence']:
        row = store.db.execute('SELECT c.*,x.document_version_id,v.content_sha256,d.source_url '
            'FROM clauses c JOIN extractions x USING(extraction_id) JOIN document_versions v USING(document_version_id) '
            'JOIN documents d USING(document_id) WHERE clause_id=?', (evidence['clauseId'],)).fetchone()
        if row is None or evidence['clauseId'] not in clauses:
            raise ValueError('Executable v2 clause lacks validated source')
        expected = {'documentVersionId': row['document_version_id'], 'documentSha256': row['content_sha256'],
            'sourceUrl': row['source_url'], 'locator': canonical_json(json.loads(row['locator_json'])), 'quote': row['text']}
        if any(evidence[k] != v for k, v in expected.items()):
            raise ValueError('Executable v2 clause bytes differ')
    return digest([subject['id'], reviews, projection['identity_sha256'], source['coreAssetSha256'], source['detailsAssetSha256']])
