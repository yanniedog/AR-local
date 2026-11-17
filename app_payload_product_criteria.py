"""Optional compact whole-catalogue criteria, built only after financial release.

Source verification reuses the full-fact snapshot contract. Failure leaves no
completion marker and can never change a financial asset or its pending state.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import re
import zlib

from app_payload_criteria import criteria_facts
from app_payload_feature_facts import feature_facts, source_documents
from cdr_terms.product_documents import describe_reference, describe_product_sources
from app_payload_product_evidence import Budget, file_digest, no_journals, regular, signature, source_binding
from app_payload_product_evidence_contract import Limits, canonical, decode, require
from cdr_atomic import atomic_write_json, _fsync_directory

INDEX_RAW = 8 * 1024**2
SHARD_RAW = 4 * 1024**2
WRITE_SHARD_RAW = 512 * 1024
FILE_COMPRESSED = 1024**2
TOTAL_RAW = 32 * 1024**2
TOTAL_COMPRESSED = 16 * 1024**2
MAX_PRODUCTS = 20000
MAX_SHARDS = 256
SCOPE = 'product-filter-facets-v1'
CRITERIA_FILE = re.compile(r'^product_criteria_(?:index|shard_[0-9]{3})$')


def _descriptor(output, kind, raw):
    blob = gzip.compress(raw, mtime=0)
    require(len(blob) <= FILE_COMPRESSED, 'criteria compressed file budget exceeded')
    sha = hashlib.sha256(blob).hexdigest()
    name = f'product-criteria-{kind}-{sha}.json.gz'
    with (output / name).open('xb') as stream:
        stream.write(blob)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(name=name, sha256=sha, bytes=len(blob))


_CITATION_FIELDS = ('sourcePath', 'relation', 'sourceUrl', 'originalSourceUrl',
                    'sourceNormalization', 'label')


def compact_documents(documents, product_key):
    """Factor shared document metadata without losing scoped source references.

    Product identity is the containing route. Equal URLs with conflicting check,
    applicability or version metadata remain separate. A citation's absent
    sourceUrl means the document URL itself, rather than a guessed new address.
    """
    groups, seen = {}, {}
    for document in documents:
        require(document.get('productKey', product_key) == product_key,
                'document inventory belongs to another product')
        common = {key: value for key, value in document.items()
                  if key not in (*_CITATION_FIELDS, 'citations', 'productKey') and value is not None}
        identity = canonical(common)
        group = groups.setdefault(identity, {**common, 'sourcePath': document['sourcePath'],
                                            'relation': document['relation'], 'citations': []})
        top = {key: document[key] for key in _CITATION_FIELDS if document.get(key) is not None}
        citations = document.get('citations') or [{'sourcePath': document['sourcePath']}]
        for supplied in citations:
            citation = {**(top if supplied.get('sourcePath') == document['sourcePath'] else {}), **supplied}
            citation = {key: value for key, value in citation.items() if value is not None}
            if citation.get('sourceUrl') == common['url']:
                citation.pop('sourceUrl')
            token = canonical(citation)
            if token not in seen.setdefault(identity, set()):
                seen[identity].add(token)
                group['citations'].append(citation)
    return [{**groups[key], 'citations': sorted(groups[key]['citations'], key=canonical)}
            for key in sorted(groups)]


def scoped_feature_facts(record, product_key):
    """Add only proven raw locators; preserve legacy feature semantics and IDs."""
    facts = feature_facts(record, product_key, record.get('description'))
    source, paths = record.get('features'), record.get('_sourcePaths')
    if not isinstance(source, list) or not isinstance(paths, dict):
        return facts
    by_type = {}
    for index, item in enumerate(source):
        if isinstance(item, dict) and isinstance(item.get('featureType'), str):
            by_type.setdefault(item['featureType'], []).append(index)
    for fact in facts:
        indices = by_type.get(fact.get('sourceType'), [])
        if len(indices) != 1:
            continue
        pointer = paths.get(f'/features/{indices[0]}')
        if isinstance(pointer, str) and re.fullmatch(r'/features/[0-9]+', pointer):
            fact.update(sourcePath=pointer, sourcePathBasis='raw-cdr')
    return facts


def prepare_criteria(database, contract_path, output, *, run_date, evidence_documents=None):
    """Return ordinary manifest file descriptors, without URLs or authority.

evidence_documents may be a caller-verified immutable product->documents map.
It must already bind the selected observation; acquisition is never performed
here. Without it, original CDR reference descriptors remain candidates only.
"""
    database, contract_path = regular(database), regular(contract_path)
    output = Path(output).absolute()
    require(not output.exists() and not any(p.is_symlink() for p in (output, *output.parents)),
            'criteria destination must be new and non-symlink')
    require(database.parent != output and database.parent not in output.parents,
            'criteria output overlaps retained source')
    budget = Budget(Limits())
    no_journals(database)
    before = signature(database)
    binding = source_binding(database, contract_path, budget)
    require(binding['observation_date'] == run_date, 'criteria date differs from selected source')
    source = dict(generation_id=binding['generation_id'], contract_digest=binding['contract_digest'])
    header = dict(schema_version=1, run_date=run_date, source=source, scope=SCOPE)
    output.mkdir(parents=True, exist_ok=False)
    files, routes, pending = {}, {}, {}
    raw_total = compressed_total = count = 0
    max_shard_raw = largest_product_bytes = oversized_products = 0
    largest_product_key = None

    def flush(values):
        nonlocal raw_total, compressed_total, max_shard_raw
        if not values:
            return
        require(len(files) < MAX_SHARDS, 'criteria shard count exceeded')
        raw = canonical({**header, 'products': values})
        require(len(raw) <= SHARD_RAW, 'criteria shard decoded budget exceeded')
        blob = gzip.compress(raw, mtime=0)
        if len(blob) > FILE_COMPRESSED and len(values) > 1:
            items = list(values.items())
            middle = len(items) // 2
            flush(dict(items[:middle])); flush(dict(items[middle:]))
            return
        key = f'product_criteria_shard_{len(files):03d}'
        descriptor = _descriptor(output, f'shard-{len(files):03d}', raw)
        files[key] = descriptor
        max_shard_raw = max(max_shard_raw, len(raw))
        raw_total += len(raw); compressed_total += descriptor['bytes']
        require(raw_total <= TOTAL_RAW and compressed_total <= TOTAL_COMPRESSED,
                'criteria aggregate budget exceeded')
        routes.update({product: key for product in values})

    db = sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=1)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA cache_size=-2048')
        db.execute('PRAGMA mmap_size=0')
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, SHARD_RAW)
        db.set_progress_handler(lambda: int(time.monotonic() >= budget.deadline), 10000)
        rows = db.execute('SELECT product_key,details_json,provider FROM bank_products '
                          'WHERE run_date=? ORDER BY product_key', (run_date,))
        pending_size = 0
        for key, details, provider in rows:
            budget.check()
            require(isinstance(key, str) and key and key not in routes and key not in pending,
                    'duplicate or missing criteria product identity')
            record = decode((details or '{}').encode('utf-8'))
            require(isinstance(record, dict), 'criteria product detail is not an object')
            # Current rate/tier facets already live in exact core rows; all
            # original rate/tier evidence remains in the full lazy fact lane.
            # Global filters never need a second copy of those scoped prices.
            facts = scoped_feature_facts(record, key) + [
                fact for fact in criteria_facts(record, key) if fact['kind'] not in {'rate', 'tier'}]
            # The legacy cleaner already removed nested URI fields. Classify
            # preserved raw references first, then add official adapter seeds;
            # rediscovery from cleaned fields alone would lose those citations.
            documents = {(item['url'], item['sourcePath'], item.get('sourceUrl')):
                         describe_reference(item, record, product_key=key)
                         for item in source_documents(record) or []}
            for item in describe_product_sources(record, key, provider):
                documents.setdefault((item['url'], item['sourcePath'], item.get('sourceUrl')), item)
            for item in (evidence_documents or {}).get(key, []):
                require(item.get('productKey') == key, 'document inventory belongs to another product')
                matching = [identity for identity in documents if identity[:2] == (item['url'], item['sourcePath'])]
                if matching:
                    for identity in matching:
                        documents[identity] = {**documents[identity], **item}
                else:
                    documents[(item['url'], item['sourcePath'], item.get('sourceUrl'))] = item
            documents = compact_documents(documents.values(), key)
            value = dict(facts=facts, sourceDocuments=documents)
            size = len(canonical({key: value}))
            require(size + len(canonical({**header, 'products': {}})) <= SHARD_RAW,
                    'single criteria product exceeds shard budget')
            if size > largest_product_bytes:
                largest_product_bytes, largest_product_key = size, key
            if size > WRITE_SHARD_RAW:
                oversized_products += 1
            if pending and pending_size + size + len(canonical({**header, 'products': {}})) > WRITE_SHARD_RAW:
                flush(pending); pending = {}; pending_size = 0
            pending[key] = value; pending_size += size; count += 1
            require(count <= MAX_PRODUCTS, 'criteria product count exceeded')
        flush(pending)
        expected = db.execute('SELECT COUNT(*) FROM bank_products WHERE run_date=?', (run_date,)).fetchone()[0]
        require(count == expected and count > 0 and len(routes) == count, 'criteria product inventory differs')
    finally:
        db.close()
    coverage = dict(productsExpected=expected, productsObserved=count, complete=True)
    raw = canonical({**header, 'products': routes, 'coverage': coverage})
    require(len(raw) <= INDEX_RAW, 'criteria index decoded budget exceeded')
    files['product_criteria_index'] = _descriptor(output, 'index', raw)
    raw_total += len(raw); compressed_total += files['product_criteria_index']['bytes']
    require(raw_total <= TOTAL_RAW and compressed_total <= TOTAL_COMPRESSED,
            'criteria aggregate budget exceeded')
    budget.check(); no_journals(database)
    require(signature(database) == before and file_digest(database, budget) == binding['database']['sha256'],
            'criteria source database changed')
    require(source_binding(database, contract_path, budget) == binding, 'criteria source contract changed')
    verify_criteria(output, dict(run_date=run_date, source_observation=source, files=files))
    result = dict(schema='ar-product-criteria-prepared-v1', source=source, run_date=run_date,
                  files=files, coverage=coverage, decoded_bytes=raw_total, compressed_bytes=compressed_total,
                  layout=dict(target_shard_decoded_bytes=WRITE_SHARD_RAW, index_decoded_bytes=len(raw),
                              max_shard_decoded_bytes=max_shard_raw, largest_product_key=largest_product_key,
                              largest_product_decoded_bytes=largest_product_bytes,
                              products_exceeding_target=oversized_products),
                  publication_authorized=False)
    _fsync_directory(output)
    atomic_write_json(output / 'prepared.json', result, create_once=True)
    return result


def criteria_files(manifest):
    files = manifest.get('files', {})
    require(isinstance(files, dict), 'criteria manifest files missing')
    keys = [key for key in files if str(key).startswith('product_criteria_')]
    require(all(CRITERIA_FILE.fullmatch(key) for key in keys), 'unknown criteria file key')
    require(not keys or 'product_criteria_index' in keys, 'criteria index missing')
    require(len(keys) <= MAX_SHARDS + 1, 'criteria shard count exceeded')
    return {key: files[key] for key in sorted(keys)}


def _read_asset(root, entry, maximum):
    require(isinstance(entry, dict), 'criteria asset descriptor missing')
    name, sha, size = entry.get('name'), entry.get('sha256'), entry.get('bytes')
    require(isinstance(name, str) and re.fullmatch(r'product-criteria-[A-Za-z0-9-]+\.json\.gz', name),
            'invalid criteria asset name')
    require(isinstance(sha, str) and re.fullmatch('[0-9a-f]{64}', sha), 'invalid criteria asset digest')
    require(name.endswith(f'-{sha}.json.gz'), 'criteria asset name differs from digest')
    require(type(size) is int and 0 < size <= FILE_COMPRESSED, 'criteria compressed file budget exceeded')
    path = regular(Path(root) / name)
    with path.open('rb') as stream:
        blob = stream.read(size + 1)
    require(len(blob) == size and hashlib.sha256(blob).hexdigest() == sha, 'criteria file bytes differ')
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = inflater.decompress(blob, maximum + 1)
    require(len(raw) <= maximum and inflater.eof and not inflater.unused_data
            and not inflater.unconsumed_tail, 'criteria gzip boundary or decoded budget differs')
    return decode(raw), len(raw)


def _product(value, product_key):
    require(isinstance(value, dict) and set(value) == {'facts', 'sourceDocuments'}, 'invalid criteria product')
    require(isinstance(value['facts'], list) and isinstance(value['sourceDocuments'], list),
            'invalid criteria product collections')
    ids = set()
    for fact in value['facts']:
        require(isinstance(fact, dict) and isinstance(fact.get('id'), str)
                and re.fullmatch('[0-9a-f]{20}', fact['id']) and fact['id'] not in ids,
                'invalid or duplicate criteria fact identity')
        ids.add(fact['id'])
        require(fact.get('kind') in {'fee', 'rate', 'tier', 'bundle', 'attribute', 'feature',
                                   'eligibility', 'constraint', 'condition'}
                and isinstance(fact.get('canonicalKey'), str), 'invalid criteria fact kind/key')
        if fact.get('criteriaVersion') == 1:
            require(fact.get('evidenceState') in {'observed', 'conditional', 'unknown', 'conflicting'}
                    and fact.get('sourcePathBasis') in {'raw-cdr', 'cleaned-cdr'}
                    and isinstance(fact.get('sourcePath'), str), 'invalid criteria provenance')
            if fact.get('valueType') == 'decimal':
                for field in ('value', 'minValue', 'maxValue'):
                    require(field not in fact or isinstance(fact[field], str)
                            and decimal_value(fact[field]), 'invalid exact decimal criterion')
    for reference in value['sourceDocuments']:
        require(isinstance(reference, dict) and reference.get('productKey', product_key) == product_key
                and all(isinstance(reference.get(field), str)
                        for field in ('url', 'sourcePath', 'relation')), 'invalid criteria source reference')


def decimal_value(value):
    from app_payload_criteria import decimal_text
    return re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value) is not None and decimal_text(value) is not None


def verify_criteria(root, manifest):
    """Verify the entire optional inventory and generation, not just one route."""
    files = criteria_files(manifest)
    if not files:
        return None
    observed = manifest.get('source_observation')
    require(isinstance(observed, dict), 'criteria requires selected source observation')
    source = {key: observed.get(key) for key in ('generation_id', 'contract_digest')}
    require(all(isinstance(value, str) and value for value in source.values()), 'criteria source missing')
    index, raw_total = _read_asset(root, files['product_criteria_index'], INDEX_RAW)
    header = dict(schema_version=1, run_date=manifest.get('run_date'), source=source, scope=SCOPE)
    require(isinstance(index, dict) and set(index) == {*header, 'products', 'coverage'}
            and all(index.get(key) == value for key, value in header.items()), 'criteria index source differs')
    products, coverage = index['products'], index['coverage']
    require(isinstance(products, dict) and 0 < len(products) <= MAX_PRODUCTS
            and all(isinstance(key, str) and key and isinstance(route, str) for key, route in products.items()),
            'invalid criteria product routing')
    require(coverage == dict(productsExpected=len(products), productsObserved=len(products), complete=True),
            'criteria coverage differs')
    shards = set(files) - {'product_criteria_index'}
    require(set(products.values()) == shards, 'criteria index/shard inventory differs')
    seen = set()
    for key in sorted(shards):
        shard, size = _read_asset(root, files[key], SHARD_RAW)
        raw_total += size
        require(isinstance(shard, dict) and set(shard) == {*header, 'products'}
                and all(shard.get(field) == value for field, value in header.items()), 'criteria shard source differs')
        values = shard['products']
        require(isinstance(values, dict) and values, 'criteria shard empty or malformed')
        for product, value in values.items():
            require(product not in seen and products.get(product) == key, 'criteria product route differs')
            seen.add(product)
            _product(value, product)
    require(seen == set(products) and raw_total <= TOTAL_RAW
            and sum(entry['bytes'] for entry in files.values()) <= TOTAL_COMPRESSED,
            'criteria aggregate inventory or budget differs')
    return dict(source=source, coverage=coverage, files=len(files), decoded_bytes=raw_total)
