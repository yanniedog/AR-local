"""Recheck exact selected public row and current source/revision scope, read-only."""
from __future__ import annotations

import gzip
import io
import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from decimal import Decimal, InvalidOperation

from .identity import canonical_json, digest
from .observation_checks import current_observation
from .reporting import build_product_asset
from cdr_export_contract import validate_contract, contract_digest, source_generation_digest

MAX_CORE_RAW = 32 * 1024 * 1024
MAX_CAPTURES = 4
MAX_CAPTURE_BYTES = 32 * 1024 * 1024
_OPERATION = ContextVar('executable_source_operation', default=None)


def source_checked(function):
    @wraps(function)
    def checked(store, *args, **kwargs):
        with source_operation(store):
            return function(store, *args, **kwargs)
    return checked


@contextmanager
def source_operation(store):
    current = _OPERATION.get()
    if current is not None and current['store'] is store:
        yield
        return
    token = _OPERATION.set({'store': store, 'cores': {}, 'captures': {}, 'decoded_bytes': 0})
    try:
        yield
    finally:
        _OPERATION.reset(token)


def _core(store, identity):
    operation = _OPERATION.get()
    cache = operation['cores'] if operation is not None and operation['store'] is store else {}
    if identity in cache:
        return cache[identity]
    compressed = store.read_blob(identity)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(MAX_CORE_RAW + 1)
    if len(raw) > MAX_CORE_RAW:
        raise ValueError('Executable source core byte bound exceeded')
    if operation is not None:
        operation['decoded_bytes'] += len(raw)
        if operation['decoded_bytes'] > 64 * 1024 * 1024 or len(cache) >= 4:
            raise ValueError('Executable decoded core operation bound exceeded')
    core = json.loads(raw)
    if len(core.get('sections', {}).get('TD', {}).get('rates', [])) > 200000:
        raise ValueError('Executable core row bound exceeded')
    result = (core, len(compressed))
    cache[identity] = result
    return result


def finalized_capture(store, generation, run_date):
    capture = store.db.execute('SELECT * FROM ingest_captures WHERE ingest_id=?', (generation,)).fetchone()
    if capture is None:
        raise ValueError('Executable template requires finalized source capture')
    operation = _OPERATION.get()
    cache = operation['captures'] if operation is not None and operation['store'] is store else {}
    key = (generation, run_date, capture['receipt_sha256'], capture['products'])
    if key in cache:
        return cache[key]
    receipt_raw = store.read_blob(capture['receipt_sha256'])
    used = operation.get('capture_bytes', 0) if operation is not None else 0
    if len(cache) >= MAX_CAPTURES or len(receipt_raw) + used > MAX_CAPTURE_BYTES:
        raise ValueError('Executable capture operation bound exceeded')
    receipt = json.loads(receipt_raw)
    provenance = receipt.get('source_provenance') or {}
    if (receipt.get('schema_version') != 1 or receipt.get('status') != 'CAPTURED_AND_QUEUED'
            or receipt.get('generation_id') != generation or receipt.get('source_run_date') != run_date
            or receipt.get('products') != capture['products'] or receipt.get('products') != len(receipt.get('sources', []))
            or provenance.get('basis') != 'finalized_source_generation'):
        raise ValueError('Executable completed capture receipt mismatch')
    contract_raw = store.read_blob(provenance['contract_sha256'])
    size = len(receipt_raw) + len(contract_raw)
    if size + used > MAX_CAPTURE_BYTES:
        raise ValueError('Executable capture operation bound exceeded')
    contract = json.loads(contract_raw)
    validate_contract(contract)
    if (source_generation_digest(contract) != contract['source_generation_digest']
            or contract_digest(contract) != contract['contract_digest']):
        raise ValueError('Executable retained export contract digest mismatch')
    if (contract['generation_id'] != generation or contract['observation_date'] != run_date
            or contract['contract_digest'] != receipt['export_contract_digest']
            or provenance.get('contract_digest') != contract['contract_digest']):
        raise ValueError('Executable retained finalized export contract mismatch')
    members = {}
    if not isinstance(receipt['sources'], list) or len(receipt['sources']) > 20000:
        raise ValueError('Executable capture member bound exceeded')
    for source in receipt['sources']:
        member = (source.get('observation_id'), source.get('product_key'), source.get('sha256'))
        if member in members:
            raise ValueError('Executable duplicate finalized capture member')
        members[member] = True
    receipt['_verified_members'] = members
    cache[key] = receipt
    if operation is not None and operation['store'] is store:
        operation['capture_bytes'] = used + size
    return receipt


def selected_row(store, template):
    binding = template['selectedRate']
    manifest = json.loads(store.read_blob(binding['sourceManifestSha256']))
    descriptor = manifest['files']['core']
    core, compressed_size = _core(store, binding['coreAssetSha256'])
    if descriptor['sha256'] != binding['coreAssetSha256'] or descriptor['bytes'] != compressed_size or manifest.get('enc'):
        raise ValueError('Executable source core descriptor mismatch')
    receipt = finalized_capture(store, template['sourceGenerationId'], template['runDate'])
    if (template['sourceObservationId'], template['productKey'], template['sourceSha256']) not in receipt['_verified_members']:
        raise ValueError('Executable product missing from finalized capture')
    expected = {'generation_id': template['sourceGenerationId'], 'contract_digest': receipt['export_contract_digest']}
    source = manifest.get('source_observation') or {}
    if any(source.get(k) != v for k, v in expected.items()) or any(
            value != template['runDate'] for value in (core['run_date'], manifest['run_date'], receipt['source_run_date'])):
        raise ValueError('Executable selected row source generation mismatch')
    rows = core['sections']['TD']['rates']
    index = binding['coreRowIndex']
    if index >= len(rows):
        raise ValueError('Executable selected row missing')
    row = rows[index]
    if (row.get('product_key') != template['productKey'] or row.get('rate_index') != binding['rateIndex']
            or digest(row) != binding['rowSha256']):
        raise ValueError('Executable selected row identity mismatch')
    validate_row_semantics(template, row)
    return row


def validate_row_semantics(template, row):
    try:
        if Decimal(str(row['rate'])) != Decimal(template['annualRate']):
            raise ValueError('Executable annual rate differs from selected variant')
        for key in ('balance_min', 'balance_max'):
            value = row.get(key)
            if value is not None and (not Decimal(str(value)).is_finite() or Decimal(str(value)) < 0):
                raise ValueError('Executable selected balance bound is unsupported')
            bound = template['principalBounds']['minimum' if key == 'balance_min' else 'maximum']
            if value is not None and ('value' not in bound or Decimal(bound['value']) != Decimal(str(value))):
                raise ValueError('Executable principal bound differs from selected variant')
    except (InvalidOperation, KeyError) as error:
        raise ValueError('Executable selected row has nonnumeric rate/bounds') from error
    term = template['term']
    suffix = 'D' if term['unit'] == 'days' else 'M'
    if row.get('term') != f"P{term['count']}{suffix}":
        raise ValueError('Executable term differs from exact selected variant')
    if row.get('rate_type') != 'FIXED':
        raise ValueError('Executable selected variant is not fixed')
    if row.get('interest_payment') not in (None, 'at_maturity', 'maturity'):
        raise ValueError('Executable selected variant does not pay at maturity')


def validate_current_sources(store, template):
    observation = current_observation(store, template['productKey'])
    if any(observation[k] != template[t] for k, t in (
            ('observation_id', 'sourceObservationId'), ('source_sha256', 'sourceSha256'),
            ('ingest_id', 'sourceGenerationId'))):
        raise ValueError('Executable template source observation changed')
    store.read_blob(template['sourceSha256'])
    selected_row(store, template)
    asset = build_product_asset(store, template['productKey'])
    revisions = {r['term_revision_id']: r for r in asset['revisions']}
    clauses = set()
    for identity in template['termRevisionIds']:
        revision = revisions.get(identity)
        scope = {'product_key': template['productKey'], 'tier': template['tierKey'], 'package': template['packageKey'],
                 'cohort': template['cohortKey'], 'effective_from': template['effectiveFrom'],
                 'effective_to': template['effectiveToExclusive']}
        if revision is None or revision['applicability'] != scope:
            raise ValueError('Executable source revision missing, stale, rejected or wrong cohort')
        clauses.update(revision['clause_ids'])
    selected = {d['document_version_id'] for d in asset['documents']}
    if not set(template['documentVersionIds']) <= selected:
        raise ValueError('Executable source document changed')
    for item in template['evidence']:
        row = store.db.execute('SELECT c.*,x.document_version_id,v.content_sha256,d.source_url '
                               'FROM clauses c JOIN extractions x USING(extraction_id) '
                               'JOIN document_versions v USING(document_version_id) JOIN documents d USING(document_id) '
                               'WHERE clause_id=?', (item['clauseId'],)).fetchone()
        if row is None or item['clauseId'] not in clauses:
            raise ValueError('Executable clause lacks current validated revision')
        expected = {'documentVersionId': row['document_version_id'], 'documentSha256': row['content_sha256'],
                    'sourceUrl': row['source_url'], 'locator': canonical_json(json.loads(row['locator_json'])), 'quote': row['text']}
        if any(item[k] != v for k, v in expected.items()):
            raise ValueError('Executable clause evidence changed')
    return observation
