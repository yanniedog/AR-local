"""Retained product scopes, a verbatim official link, and protocol controls."""
import json
import sqlite3
from pathlib import Path

import pytest

from cdr_terms.acquisitions_queue import AcquisitionQueue
from cdr_terms.document_discovery_queue import register_discovery, discovery_inventory, reconcile_capture_discovery
from cdr_terms.extraction import extract_document
from cdr_terms.identity import digest
from cdr_terms.ingest import capture_finalized
from cdr_terms.product_documents import describe_reference, describe_references, discovery_plan
from cdr_terms.store import EvidenceStore
from tests.cdr_terms_source_fixture import source_generation

FIXTURES = Path(__file__).parent / 'fixtures'
OBSERVED = '2026-09-07T00:00:00Z'


def up_record():
    return json.loads((FIXTURES / 'product_facts_real_2026-05-19.json').read_bytes())['products'][0]['record']


def test_every_ingest_has_an_immutable_discovery_obligation_without_network(tmp_path, monkeypatch):
    run, _, finalized = source_generation(tmp_path, '2026-09-07', OBSERVED)
    def forbidden(*args, **kwargs):
        raise AssertionError('Finalization discovery cannot fetch documents')
    monkeypatch.setattr('cdr_terms.acquisition.fetch_document', forbidden)
    receipt = capture_finalized(run, finalized, tmp_path / 'derived', forbidden_roots=[run.parent], observed_at=OBSERVED)
    with EvidenceStore(tmp_path / 'derived') as store:
        rows = store.db.execute('SELECT * FROM product_document_discovery').fetchall()
        assert len(rows) == receipt['products'] == 1
        plan = json.loads(rows[0]['plan_json'])
        assert plan['networkCalled'] is False
        assert plan['status'] == 'declared-references'
        with pytest.raises(sqlite3.IntegrityError, match='append-only'):
            store.db.execute('DELETE FROM product_document_discovery')


def test_no_reference_product_uses_reviewed_official_adapter_and_existing_queue(tmp_path):
    record = up_record()
    assert describe_references(record, product_key='Up|up-home') == []
    plan = discovery_plan(record, provider='Up')
    assert plan['status'] == 'queued' and len(plan['seeds']) == 2
    with EvidenceStore(tmp_path / 'derived') as store:
        observation = store.observe(provider='Up', product_key='Up|up-home', record=record,
                                    observed_at=OBSERVED, ingest_id='one')
        proof = register_discovery(store, observation, record, now=OBSERVED)
        assert register_discovery(store, observation, record, now=OBSERVED) == proof
        queued = AcquisitionQueue(store).enqueue(observation, ingest_id='one', now=OBSERVED)
        assert len(queued) == 2
        assert store.db.execute('SELECT COUNT(*) FROM product_document_discovery').fetchone()[0] == 1
        # A new ingest gets new checks, even when its raw details did not change.
        second = store.observe(provider='Up', product_key='Up|up-home', record=record,
                               observed_at='2026-09-08T00:00:00Z', ingest_id='two')
        register_discovery(store, second, record, now='2026-09-08T00:00:00Z')
        assert set(queued).isdisjoint(AcquisitionQueue(store).enqueue(second, ingest_id='two', now='2026-09-08T00:00:00Z'))


def test_unknown_official_host_is_disclosed_not_invented():
    # This retained sparse product has no source URL; no domain is inferred.
    record = json.loads((FIXTURES / 'product_facts_real_2026-05-19.json').read_bytes())['products'][1]['record']
    plan = discovery_plan(record, provider='Unknown host protocol boundary')
    assert plan['status'] == 'missing-official-source' and plan['seeds'] == []


def test_preupgrade_reconciliation_uses_current_time_without_rewriting_old_capture(tmp_path, monkeypatch):
    record = up_record()
    current = '2026-11-18T00:00:00Z'
    monkeypatch.setattr('cdr_terms.document_discovery_queue.utc_now', lambda: current)
    with EvidenceStore(tmp_path / 'derived') as store:
        observation = store.observe(provider='Up', product_key='Up|up-home', record=record,
                                    observed_at=OBSERVED, ingest_id='old')
        source = store.db.execute('SELECT source_sha256 FROM observations WHERE observation_id=?', (observation,)).fetchone()[0]
        receipt = {'generation_id': 'old', 'captured_at': OBSERVED,
                   'sources': [{'observation_id': observation, 'sha256': source}]}
        original = json.dumps(receipt, sort_keys=True)
        assert reconcile_capture_discovery(store, receipt) == 1
        assert reconcile_capture_discovery(store, receipt) == 0
        assert store.db.execute('SELECT created_at FROM product_document_discovery').fetchone()[0] == '2026-11-18T00:00:00.000000Z'
        assert store.db.execute('SELECT MIN(created_at) FROM acquisition_requests').fetchone()[0] == '2026-11-18T00:00:00.000000Z'
        assert json.dumps(receipt, sort_keys=True) == original


def test_generic_references_create_only_same_origin_discovery_navigation():
    record = up_record()
    # Transport/URL boundary fault, retaining real product identity and facts.
    record['additionalInformation'] = {'overviewUri': 'https://up.com.au/'}
    plan = discovery_plan(record, provider='No adapter for this control')
    assert [seed['url'] for seed in plan['seeds']] == ['https://up.com.au/sitemap.xml']
    descriptor = describe_references(record, product_key='Up|up-home')[0]
    assert descriptor['specificity'] == 'background'
    assert descriptor['documentType'] == 'navigation'
    assert descriptor['relevance'] == 'supplementary'
    assert descriptor['checkedAt'] is None


def test_actual_official_anchor_resolves_direct_pdf_and_keeps_candidate_scope():
    retained = json.loads((FIXTURES / 'product-document-links-20261118.json').read_bytes())
    _, state, coverage = extract_document(retained['html'].encode(), 'text/html', retained['sourceUrl'])
    assert state == 'partial'
    link = coverage['candidate_links'][0]
    assert link['url'] == retained['documentUrl']
    descriptor = describe_reference({**link, 'sourcePath': '/discovery/anchor/1', 'relation': 'terms'},
                                    up_record(), product_key='Up|up-home')
    assert descriptor['specificity'] == 'exact-product'
    assert descriptor['documentType'] == 'terms-and-conditions'
    assert descriptor['relevance'] == 'candidate'  # Matching a name is not legal review.
    assert descriptor['citations'] == [{'sourcePath': '/discovery/anchor/1'}]


def test_sitemap_parser_provides_bounded_graph_candidates_not_verified_terms():
    retained = json.loads((FIXTURES / 'product-document-links-20261118.json').read_bytes())
    # XML syntax wrapper is a protocol control; target is captured official URL.
    raw = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>'
           + retained['documentUrl'] + '</loc></url></urlset>').encode()
    _, state, coverage = extract_document(raw, 'application/xml', 'https://up.com.au/sitemap.xml')
    assert state == 'partial' and coverage['candidate_links_total'] == 1
    assert coverage['candidate_links'][0]['url'] == retained['documentUrl']
    assert coverage['legal_completeness'] == 'unknown'
    evil = b'<!DOCTYPE urlset [<!ENTITY x SYSTEM "file:///etc/passwd">]><urlset/>'
    assert extract_document(evil, 'application/xml', 'https://up.com.au/sitemap.xml')[2]['reason'] == 'sitemap_entities_forbidden'
    assert extract_document(evil.decode().encode('utf-16'), 'application/xml', 'https://up.com.au/sitemap.xml')[2]['reason'] == 'unsupported_sitemap_encoding'
    assert extract_document(b'<anything/>', 'application/xml', 'https://up.com.au/sitemap.xml')[1] == 'failed'


def test_sitemap_overflow_is_explicit():
    raw = ('<urlset>' + ''.join(f'<url><loc>https://up.com.au/docs/{i}.pdf</loc></url>' for i in range(300)) + '</urlset>').encode()
    _, state, coverage = extract_document(raw, 'text/xml', 'https://up.com.au/sitemap.xml')
    assert state == 'partial' and len(coverage['candidate_links']) == 256
    assert coverage['candidate_links_total'] == 300 and coverage['candidate_links_omitted'] == 44


def test_inventory_never_promotes_retrieval_to_verified_product_applicability(tmp_path):
    record = up_record()
    with EvidenceStore(tmp_path / 'derived') as store:
        observation = store.observe(provider='Up', product_key='Up|up-home', record=record,
                                    observed_at=OBSERVED, ingest_id='one')
        register_discovery(store, observation, record, now=OBSERVED)
        queue = AcquisitionQueue(store)
        queue.enqueue(observation, ingest_id='one', now=OBSERVED)
        with store.db:
            store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,1)', ('one', store.put_blob(b'capture protocol'), OBSERVED))
        inventory = discovery_inventory(store, 'Up|up-home')
        assert len(inventory['documents']) == 2
        assert all(doc['verification'] == 'pending' and doc['relevance'] == 'candidate' for doc in inventory['documents'])
        request = queue.claim(now='2026-11-18T00:00:00Z')
        check_id = digest([request['request_id'], request['lease_id']])
        store.record_check(document_id=request['document_id'], check_id=check_id, checked_at='2026-11-18T00:00:00Z',
                           status='fetched', body=b'Protocol body; not legal completeness', media_type='text/plain')
        queue.finish(request, check_id, defer_processing=True, now='2026-11-18T00:00:01Z')
        inventory = discovery_inventory(store, 'Up|up-home')
        captured = [doc for doc in inventory['documents'] if doc['verification'] == 'captured']
        assert len(captured) == 1 and captured[0]['relevance'] == 'candidate'
        assert captured[0]['checkedAt'] == '2026-11-18T00:00:00.000000Z'
