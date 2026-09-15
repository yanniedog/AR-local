"""Closed report inventory contract. A content seal never grants bank authority."""
from jsonschema import Draft202012Validator


def obj(properties, optional=()):
    return {'type': 'object', 'properties': properties, 'additionalProperties': False,
            'required': [key for key in properties if key not in optional]}


def array(items):
    return {'type': 'array', 'items': items, 'maxItems': 4096}


def nullable(value):
    return {'anyOf': [value, {'type': 'null'}]}


TEXT = {'type': 'string', 'maxLength': 4096}
HASH = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
NUMBER = {'type': 'integer', 'minimum': 0, 'maximum': 1000000000}
NULL = {'type': 'null'}
FALSE = {'const': False}


def fields(names):
    return {key: TEXT for key in names.split()}


def inventory_stages(row):
    def stage(observed, expected, basis):
        return {'observed': observed, 'expected': expected, 'basis': basis,
                'status': 'unknown_denominator' if expected is None else 'inventory_reported'}
    docs, terms = row['documents'], row['interpretations']
    subjects = row['executables']['subjects']
    return {
        'extraction': stage(sum(bool(d['extractions']) for d in docs),
                            sum(d['retained_version'] is not None for d in docs), 'retained_documents_with_extraction_records'),
        'graph': stage(len(row['graph']['nodes']), None, 'recorded_nodes_not_complete_document_inventory'),
        'interpretation': stage(len(terms), None, 'recorded_terms_not_complete_material_field_inventory'),
        'review': stage(sum(t['review'] is not None for t in terms), len(terms), 'recorded_latest_reviews_not_bank_approval'),
        'executable_review': stage(sum(s['recorded_review'] is not None for s in subjects), len(subjects), 'recorded_latest_scope_reviews_not_revalidated'),
        'executable_delivery': stage(sum(len(d['subject_ids']) for d in row['delivered']), None, 'selected_edition_scopes_not_all_required_scopes'),
    }


def schema():
    review = obj({**fields('review_id decision reviewed_at'), 'evidence_sha256': HASH})
    subject = obj({**fields('subject_id capability'), 'scope_id': nullable(TEXT), 'wire_version': NUMBER,
                   'recorded_review': nullable(review), 'current_approval_revalidated': FALSE,
                   'unavailable_reason': {'const': 'unsupported registry wire version'}}, ('unavailable_reason',))
    publication = obj({**fields('publication_id observation_id published_at capability'),
                       'identity_sha256': HASH, 'state': {'enum': ['active', 'removed']}})
    executable = obj({'status': {'enum': ['reported', 'not_reported']},
                      'subjects': array(subject), 'publications': array(publication)})
    version = obj({**fields('document_version_id observed_at'), 'content_sha256': HASH, 'byte_size': NUMBER})
    extraction = obj(fields('extraction_id extractor_version status text_sha256 coverage_sha256'))
    document = obj({'document_id': TEXT, 'latest_status': {'enum': ['pending', 'fetched', 'unchanged', 'failed', 'unsupported', 'blocked', 'deferred']},
                    'latest_check_id': nullable(TEXT), 'retained_version': nullable(version), 'extractions': array(extraction)})
    interpretation = obj({**fields('term_revision_id parameter_key applicability_sha256'), 'unit': nullable(TEXT), 'rule_set_id': nullable(TEXT),
                          'review': nullable(obj({**fields('review_id status reviewer_kind'), 'evidence_sha256': HASH})),
                          'changes': array(obj({**fields('term_change_id kind'), 'after_revision_id': nullable(TEXT)}))})
    node = obj({**fields('node_id root_id document_id'), 'parent_node_id': nullable(TEXT),
                'depth': NUMBER, 'reason': nullable(TEXT)})
    graph = obj({'status': {'enum': ['reported', 'not_reported']}, 'completeness': {'const': 'unknown'},
                 'nodes': array(node), 'edges': array(obj({**fields('edge_id parent_node_id reason'), 'child_node_id': nullable(TEXT)}))})
    stage = lambda basis, observed, expected: obj({'basis': {'const': basis}, 'observed': observed, 'expected': expected})
    stages = obj({'capture': stage('known_referenced_documents', NUMBER, NUMBER),
                  'complete_document_inventory': stage('legal_completeness_unverified', NUMBER, NULL),
                  'bank_approved_products': stage('bank_acceptance_provenance_unavailable', NULL, NULL)})
    for key, basis in [('extraction', 'retained_documents_with_extraction_records'),
                       ('graph', 'recorded_nodes_not_complete_document_inventory'),
                       ('interpretation', 'recorded_terms_not_complete_material_field_inventory'),
                       ('review', 'recorded_latest_reviews_not_bank_approval'),
                       ('executable_review', 'recorded_latest_scope_reviews_not_revalidated'),
                       ('executable_delivery', 'selected_edition_scopes_not_all_required_scopes')]:
        stages['properties'][key] = obj({'observed': NUMBER, 'expected': nullable(NUMBER),
                                        'basis': {'const': basis}, 'status': {'enum': ['unknown_denominator', 'inventory_reported']}})
        stages['required'].append(key)
    delivered = obj({'capability': {'enum': ['fixed_td_calculation', 'eligibility_only', 'savings_calculation', 'mortgage_calculation']},
                     'asset_sha256': HASH, 'subject_ids': array(TEXT),
                     'status': {'const': 'delivered_as_of_selected_edition'}, 'bank_acceptance': {'const': 'unclassified'}})
    common = {'evidence_class': {'enum': ['unclassified', 'technical_fixture']}, 'bank_approved': NULL, 'delivered': array(delivered)}
    reported = obj({**common, 'status': {'const': 'reported'}, **fields('observation_id observed_at'),
                    'source_sha256': HASH, 'matches_current_observation': nullable({'type': 'boolean'}),
                    'document_references': array(obj(fields('applicability_id document_id relation'))),
                    'documents': array(document), 'graph': graph, 'interpretations': array(interpretation),
                    'executables': executable, 'stages': stages})
    unavailable = obj({**common, 'status': {'const': 'unavailable'},
                       'reason': {'enum': ['selected finalized capture unavailable', 'selected observation unavailable']}})
    return {'oneOf': [reported, unavailable]}


def validate_rows(products):
    validator = Draft202012Validator(schema())
    for row in products.values():
        if next(validator.iter_errors(row), None) is not None:
            raise ValueError('Report evidence closed inventory contract invalid; bank acceptance cannot be promoted')
        if row['status'] == 'reported':
            if any(row['stages'][key] != value for key, value in inventory_stages(row).items()):
                raise ValueError('Report stage inventory differs')

            for subject in row['executables']['subjects']:
                if subject['scope_id'] is None and subject['wire_version'] != 1:
                    raise ValueError('Only legacy wire 1 has a null scope')
            documents = row['documents']
            ids = [item['document_id'] for item in documents]
            if len(set(ids)) != len(ids) or set(ids) != {r['document_id'] for r in row['document_references']}:
                raise ValueError('Report document inventory differs')
            capture = row['stages']['capture']
            if (capture['expected'] != len(ids) or capture['observed'] != sum(
                    d['latest_status'] in ('fetched', 'unchanged') for d in documents)
                    or row['stages']['complete_document_inventory']['observed'] != len(ids)):
                raise ValueError('Report stage inventory differs')


def validate_header(value):
    snapshot = obj({'row_count': NUMBER, 'row_inventory_sha256': HASH, 'blob_sha256s': array(HASH),
                    **{key: NUMBER for key in ('processed_io_bytes', 'row_bytes', 'row_byte_limit', 'processed_io_limit',
                        'per_blob_limit', 'read_chunk_limit', 'max_read_request', 'max_materialized_blob')},
                    'raw_blob_cache_bytes': {'const': 0},
                    'sqlite_application_id': {'type': 'integer', 'minimum': 0, 'maximum': 2147483647}, 'sqlite_user_version': NUMBER})
    code = obj({name: HASH for name in ('cdr_report_terms.py', 'cdr_report_terms_store.py', 'cdr_report_terms_contract.py')})
    for item, contract in [(value['snapshot'], snapshot), (value['exporter_code_sha256s'], code)]:
        if next(Draft202012Validator(contract).iter_errors(item), None) is not None:
            raise ValueError('Report evidence header contract invalid')
    if value['bank_acceptance_policy'] != 'unclassified_unless_independently_verified; no upgrade supported in v1':
        raise ValueError('Report evidence bank acceptance policy invalid')
