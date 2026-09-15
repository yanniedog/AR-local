"""Association-aware extraction, staging and current source-review admission."""
import json

from . import structured_contract as contract
from .identity import byte_digest, canonical_json, digest, timestamp
from .store import validate_clause_locator
from .structured_store import present, write_transaction
from .structured_review import accepted

SEPARATOR = '\n\f\n'


def projection(value, job, proposal_id, review_id):
    texts, spans, offset = [], [], 0
    for page in value['pages']:
        if texts: offset += len(SEPARATOR)
        text = page['text']; texts.append(text)
        spans.append({'page': page['page'], 'start': offset, 'end': offset + len(text),
                      'text_sha256': byte_digest(text.encode('utf-8')), 'status': 'text_available' if text.strip() else 'textless_review_required'})
        offset += len(text)
    text = SEPARATOR.join(texts)
    coverage = {'policy_version': contract.EXTRACTOR, 'parent_extraction_id': job['source']['extraction_id'],
                'structure_proposal_id': proposal_id, 'structure_review_id': review_id,
                'page_spans': spans, 'selected_pages': job['pages'], 'unreadable_pages': [p['page'] for p in spans if p['status'] != 'text_available'],
                'ocr_status': 'tool_unavailable', 'coverage_status': 'partial_reviewed_regions_only'}
    return text, coverage


@contract.evidence_reads
def materialize(store, proposal_id, review_id, *, observed_at):
    _, value, job, regions = accepted(store, proposal_id, review_id)
    text, coverage = projection(value, job, proposal_id, review_id)
    text_sha = store.put_blob(text.encode('utf-8'))
    spans = coverage['page_spans']
    extraction = digest([job['source']['document_version_id'], contract.EXTRACTOR, text_sha, 'partial', coverage])
    offsets = {p['page']: p['start'] for p in spans}; clauses = {}
    for rid, region in regions.items():
        start, end = offsets[region['page']] + region['start'], offsets[region['page']] + region['end']
        locator = validate_clause_locator(text, coverage, start=start, end=end, page=region['page'], section=rid)
        cid = digest([extraction, locator, text[start:end]])
        clauses[rid] = {'clause_id': cid, 'locator': locator, 'text': text[start:end]}
    association = {'contract': contract.CONTRACT, 'extraction_id': extraction, 'proposal_id': proposal_id,
                   'review_id': review_id, 'clauses': clauses, 'regions': value['regions'], 'tables': value['tables'], 'links': value['links']}
    sha = store.put_blob(contract.bounded(association))
    with write_transaction(store):
        accepted(store, proposal_id, review_id)
        store.db.execute('INSERT OR IGNORE INTO extractions VALUES (?,?,?,?,?,?,?)',
                         (extraction, job['source']['document_version_id'], contract.EXTRACTOR, text_sha, timestamp(observed_at), 'partial', canonical_json(coverage)))
        store.db.execute('INSERT OR IGNORE INTO structured_extractions VALUES (?,?,?,?)', (extraction, proposal_id, review_id, sha))
        for rid, c in clauses.items():
            store.db.execute('INSERT OR IGNORE INTO clauses VALUES (?,?,?,?)', (c['clause_id'], extraction, canonical_json(c['locator']), c['text']))
            store.db.execute('INSERT OR IGNORE INTO structured_clauses VALUES (?,?,?)', (c['clause_id'], extraction, rid))
    return extraction, {'structure_review': {'contract': contract.CONTRACT, 'schema_sha256': contract.schema_sha(),
        'extraction_id': extraction, 'proposal_id': proposal_id, 'review_id': review_id, 'association_sha256': sha}}


def association(store, extraction_id, *, current=True):
    extraction = store.db.execute('SELECT * FROM extractions WHERE extraction_id=?', (extraction_id,)).fetchone()
    row = store.db.execute('SELECT * FROM structured_extractions WHERE extraction_id=?', (extraction_id,)).fetchone() if present(store) else None
    reserved = extraction and extraction['extractor_version'].startswith('reviewed-structure-')
    if not reserved and row is None: return None
    if not extraction or row is None or extraction['extractor_version'] != contract.EXTRACTOR:
        raise ValueError('Structured extraction binding missing or unsupported')
    _, value, job, regions = accepted(store, row['proposal_id'], row['review_id'], current=current)
    a = contract.load(store, row['association_sha256'])
    expected = {'contract': contract.CONTRACT, 'schema_sha256': contract.schema_sha(), 'extraction_id': extraction_id,
                'proposal_id': row['proposal_id'], 'review_id': row['review_id'], 'association_sha256': row['association_sha256']}
    contract.keys(a, 'contract extraction_id proposal_id review_id clauses regions tables links')
    if (a['contract'] != contract.CONTRACT or a['extraction_id'] != extraction_id or a['proposal_id'] != row['proposal_id']
            or a['review_id'] != row['review_id'] or a['regions'] != value['regions'] or a['tables'] != value['tables'] or a['links'] != value['links']
            or set(a['clauses']) != set(regions) or extraction['document_version_id'] != job['source']['document_version_id'] or extraction['status'] != 'partial'):
        raise ValueError('Structured association identity differs')
    text = contract.read(store, extraction['text_sha256']).decode('utf-8')
    coverage = json.loads(extraction['coverage_json']); contract.bounded(coverage)
    if (text, coverage) != projection(value, job, row['proposal_id'], row['review_id']):
        raise ValueError('Structured transcription projection differs')
    if digest([extraction['document_version_id'], extraction['extractor_version'], extraction['text_sha256'], extraction['status'], coverage]) != extraction_id:
        raise ValueError('Structured extraction identity differs')
    for rid, c in a['clauses'].items():
        contract.keys(c, 'clause_id locator text')
        locator = c['locator']; validate_clause_locator(text, coverage, **locator)
        region = regions[rid]
        span = next(p for p in coverage['page_spans'] if p['page'] == region['page'])
        if (locator != {'page': region['page'], 'start': span['start'] + region['start'], 'end': span['start'] + region['end'], 'section': rid}
                or c['text'] != text[locator['start']:locator['end']] or digest([extraction_id, locator, c['text']]) != c['clause_id']):
            raise ValueError('Structured clause association differs')
        stored = store.db.execute('SELECT c.*,s.region_id FROM clauses c JOIN structured_clauses s USING(clause_id) WHERE clause_id=?', (c['clause_id'],)).fetchone()
        if (not stored or stored['extraction_id'] != extraction_id or stored['region_id'] != rid
                or stored['text'] != c['text'] or json.loads(stored['locator_json']) != locator):
            raise ValueError('Structured clause binding missing')
    return expected, a


def validate_context(store, extraction_id, context):
    checked = association(store, extraction_id)
    supplied = context.get('structure_review')
    if checked is None:
        if supplied is not None or 'structure_review' in context: raise ValueError('Unbound structured context')
        return None
    contract.validate('context', supplied)
    if supplied != checked[0]: raise ValueError('Structured context association missing or stale')
    return checked[1]


def _dependencies(a, selected):
    required = set(selected)
    for table in a['tables']:
        for cell in table['cells']:
            if cell['region'] in selected: required.update(cell['headers'] + cell['units'])
    # Links on required headers/units also qualify the selected cell.
    for _ in range(len(a['links']) + 1):
        before = len(required)
        for link in a['links']:
            if required.intersection(link['targets']): required.update([link['marker'], link['note']])
        if before == len(required): break
    return required


def validate_output(store, extraction_id, context, output):
    a = validate_context(store, extraction_id, context)
    if a is None: return
    by_locator = {canonical_json(c['locator']): rid for rid, c in a['clauses'].items()}
    ids = []
    for c in output['clauses']:
        locator = {k: c[k] for k in ('start', 'end', 'page', 'section') if c[k] is not None}
        rid = by_locator.get(canonical_json(locator))
        if rid is None: raise ValueError('Staged clause omits reviewed structure association')
        ids.append(rid)
    for term in output['terms']:
        selected = {ids[i] for i in term['clause_indexes']}
        if not _dependencies(a, selected) <= selected:
            raise ValueError('Staged term omitted header, unit or footnote association')


def validate_term(store, term_revision_id, *, current=True):
    rows = store.db.execute('SELECT c.clause_id,c.extraction_id FROM term_sources s JOIN clauses c USING(clause_id) WHERE term_revision_id=?', (term_revision_id,)).fetchall()
    for extraction_id in {r['extraction_id'] for r in rows}:
        checked = association(store, extraction_id, current=current)
        if checked is None: continue
        a = checked[1]; ids = {r['clause_id'] for r in rows if r['extraction_id'] == extraction_id}
        selected = {rid for rid, c in a['clauses'].items() if c['clause_id'] in ids}
        if len(selected) != len(ids) or not _dependencies(a, selected) <= selected:
            raise ValueError('Term source structure associations incomplete')
