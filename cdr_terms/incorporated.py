"""Source-pinned interpretation of candidate incorporated documents, never applicability."""
from __future__ import annotations

import json
from typing import Any, Mapping

from .graph import DocumentGraph
from .identity import byte_digest, canonical_json, digest, exact_value
from .store import EvidenceStore

MAX_TARGET_BYTES = 64 * 1024


def _ancestry(store: EvidenceStore, node: Mapping[str, Any]) -> list[dict]:
    from .acquisition_processing import ProcessingQueue
    graph, path, seen = DocumentGraph(store), [], set()
    while node:
        if node['node_id'] in seen or len(path) >= 9:
            raise ValueError('Incorporated ancestry exceeds the reviewed graph bound')
        seen.add(node['node_id'])
        check = graph._check(node)
        expansion = store.db.execute('SELECT * FROM document_graph_expansions WHERE node_id=?', (node['node_id'],)).fetchone()
        if not check or not expansion or expansion['check_id'] != check['check_id']:
            raise ValueError('Incorporated ancestry lacks an exact accepted expansion')
        ProcessingQueue(store)._receipt_capture({'request_id': node['request_id'], 'check_id': check['check_id'], 'status': 'complete'})
        edges = [dict(row) for row in store.db.execute(
            'SELECT * FROM document_graph_edges WHERE parent_node_id=? AND child_node_id=? ORDER BY edge_id',
            (node['parent_node_id'], node['node_id']))]
        if node['parent_node_id'] and not edges:
            raise ValueError('Incorporated child has no retained parent anchor')
        path.append({'node_id': node['node_id'], 'node_sha256': digest(dict(node)),
            'check_id': check['check_id'], 'document_version_id': check['document_version_id'],
            'final_url': json.loads(check['metadata_json']).get('final_url'),
            'expansion_sha256': digest(dict(expansion)),
            'parent_edges': [{'edge_id': row['edge_id'], 'sha256': digest(row)} for row in edges]})
        node = store.db.execute('SELECT * FROM document_graph_nodes WHERE node_id=?', (node['parent_node_id'],)).fetchone() if node['parent_node_id'] else None
    return path


def build_target(store: EvidenceStore, node_id: str, *, require_current: bool = True, check_blobs: bool = True) -> dict:
    node = store.db.execute('SELECT * FROM document_graph_nodes WHERE node_id=?', (node_id,)).fetchone()
    if not node or not 1 <= node['depth'] <= 8:
        raise ValueError('Incorporated interpretation requires a retained child node')
    if require_current and DocumentGraph(store)._source_reason(node):
        raise ValueError('Incorporated source ancestry was superseded')
    root = store.db.execute('SELECT * FROM document_graph_roots WHERE root_id=?', (node['root_id'],)).fetchone()
    expansion = store.db.execute('SELECT * FROM document_graph_expansions WHERE node_id=?', (node_id,)).fetchone()
    source = store.db.execute('SELECT x.*,v.content_sha256 FROM extractions x JOIN document_versions v USING(document_version_id) '
        'WHERE extraction_id=?', (expansion['extraction_id'] if expansion else None,)).fetchone()
    check = DocumentGraph(store)._check(node)
    if (not source or not check or source['document_version_id'] != check['document_version_id']
            or source['status'] not in {'partial', 'complete'} or source['text_sha256'] == byte_digest(b'')):
        raise ValueError('Incorporated document requires usable retained text')
    scopes = [dict(row) for row in store.db.execute(
        'SELECT a.*,o.product_key,o.source_sha256,o.observed_at,o.ingest_id FROM document_graph_scopes s '
        'JOIN applicability a USING(applicability_id) JOIN observations o USING(observation_id) '
        'WHERE s.root_id=? ORDER BY a.applicability_id LIMIT 1001', (node['root_id'],))]
    if not scopes or len(scopes) > 1000:
        raise ValueError('Incorporated product scope is missing or exceeds its bound')
    target = {'schema_version': 1, 'scope': 'incorporated_candidate_only', 'applicability_status': 'unreviewed',
        'node_id': node_id, 'root_id': node['root_id'], 'root_sha256': digest(dict(root)),
        'extraction_id': source['extraction_id'], 'extraction_text_sha256': source['text_sha256'],
        'document_version_id': source['document_version_id'], 'document_content_sha256': source['content_sha256'],
        'ancestry': _ancestry(store, node), 'source_scopes': scopes}
    target['target_sha256'] = digest(target)
    if len(canonical_json(target).encode('utf-8')) > MAX_TARGET_BYTES:
        raise ValueError('Incorporated target exceeds its public-context bound')
    if check_blobs:
        for identity in {source['content_sha256'], source['text_sha256'], *(scope['source_sha256'] for scope in scopes)}:
            store.read_blob(identity)
    return target


def product_sources(target: Mapping[str, Any]) -> dict[str, str]:
    products: dict[str, str] = {}
    for scope in target['source_scopes']:
        key, source = scope['product_key'], scope['source_sha256']
        if key in products and products[key] != source:
            raise ValueError('Incorporated target mixes product source observations')
        products[key] = source
    return products


def validate_target(store: EvidenceStore, extraction_id: str, context: Mapping[str, Any], *, require_current=True, check_blobs=True) -> dict:
    target = context.get('incorporated_target')
    if not isinstance(target, dict) or not isinstance(target.get('node_id'), str) or 'historical_target' in context:
        raise ValueError('Incorporated target is malformed or mixes historical scope')
    exact_value(target)
    expected = build_target(store, target['node_id'], require_current=require_current, check_blobs=check_blobs)
    if (digest(target) != digest(expected) or extraction_id != expected['extraction_id']
            or context.get('product_keys') != sorted(product_sources(expected))
            or context.get('source_product_sha256') != product_sources(expected)):
        raise ValueError('Incorporated target differs from its exact retained source scope')
    return expected


def output_scope(target: Mapping[str, Any]) -> dict:
    return {key: target[key] for key in ('scope', 'applicability_status', 'target_sha256', 'document_version_id', 'extraction_id')}


def enqueue_expansion(store, expansion, registry_context, *, priority, guard):
    """Caller owns the expansion transaction and processing lease throughout."""
    from .queue import TermsQueue
    source = store.db.execute('SELECT status,text_sha256 FROM extractions WHERE extraction_id=?', (expansion['extraction_id'],)).fetchone()
    node = store.db.execute('SELECT depth FROM document_graph_nodes WHERE node_id=?', (expansion['node_id'],)).fetchone()
    if not node or node['depth'] == 0 or not source or source['status'] == 'failed' or not store.read_blob(source['text_sha256']):
        return None  # Durable graph receipt already retains unavailable extraction.
    target = build_target(store, expansion['node_id'])
    products = product_sources(target)
    context = {**registry_context, 'product_keys': sorted(products), 'source_product_sha256': products, 'incorporated_target': target}
    return TermsQueue(store).enqueue_in_transaction(target['extraction_id'], context, priority=priority, completion_guard=guard)
