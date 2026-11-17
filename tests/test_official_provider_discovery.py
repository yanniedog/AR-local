"""Retained official directory brand fields and original CDR product scopes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from cdr_terms.acquisition_processing import ProcessingQueue
from cdr_terms.acquisitions_queue import AcquisitionQueue
from cdr_terms.document_discovery_queue import discovery_inventory
from cdr_terms.identity import canonical_json, digest, utc_now
from cdr_terms.ingest import registry_context
from cdr_terms.provider_websites import DIRECTORY_URL, official_websites, process_directory
from cdr_terms.store import EvidenceStore

FIXTURES = Path(__file__).parent / 'fixtures'
BRANDS = json.loads((FIXTURES / 'provider-websites-20261118.json').read_bytes())
SOURCE = FIXTURES / 'cdr-canary-2026-09-07/Bank of Melbourne-null-detail.json'
OBSERVED = '2026-09-07T00:00:00Z'


def test_official_directory_exact_active_identity_only():
    sites = official_websites(canonical_json(BRANDS).encode())
    assert list(sites['bank of melbourne']) == ['https://www.bankofmelbourne.com.au/']
    assert list(sites['up']) == ['https://up.com.au/']
    changed = deepcopy(BRANDS)
    changed['value'][0]['brands'][0]['status'] = 'REVOKED'
    missing = changed['value'][0]['brands'][0]['brandName'].casefold()
    assert missing not in official_websites(canonical_json(changed).encode())
    ambiguous = deepcopy(BRANDS)
    brand = deepcopy(ambiguous['value'][0]['brands'][0])
    brand['website'] = 'https://directory-ambiguity.example/'
    ambiguous['value'][0]['brands'].append(brand)
    assert len(official_websites(canonical_json(ambiguous).encode())[brand['brandName'].casefold()]) == 2


def accepted_directory(store, body=None, final_url=DIRECTORY_URL):
    raw = SOURCE.read_bytes()
    product = json.loads(raw)
    observation = store.observe(provider=product['data']['brand'], product_key='Bank of Melbourne|BOMHLBasic',
        record=product, source_bytes=raw, observed_at=OBSERVED, ingest_id='retained')
    document = store.register_document(DIRECTORY_URL)
    context = canonical_json({'url': DIRECTORY_URL, 'sourcePath': '/discovery/official-provider-directory',
                              'relation': 'discovery_navigation', 'seedKind': 'official-provider-directory'})
    with store.db:
        store.db.execute('INSERT INTO applicability VALUES (?,?,?,?,?,?)',
            (digest([observation, document, context]), observation, document, '/discovery/official-provider-directory', 'discovery_navigation', context))
        store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,1)', ('retained', store.put_blob(b'capture protocol'), OBSERVED))
    queue = AcquisitionQueue(store)
    queue.enqueue(observation, ingest_id='retained', now=OBSERVED)
    while True:
        request = queue.claim()
        chosen = request['document_id'] == document
        check_id = digest([request['request_id'], request['lease_id']])
        if chosen:
            store.record_check(document_id=document, check_id=check_id, checked_at=utc_now(), status='fetched',
                body=body or canonical_json(BRANDS).encode(), media_type='application/json', metadata={'final_url': final_url})
        else:
            store.record_check(document_id=request['document_id'], check_id=check_id, checked_at=utc_now(),
                               status='failed', error_code='isolated_transport_fault')
        queue.finish(request, check_id, defer_processing=chosen, terminal=not chosen)
        if chosen:
            return observation, dict(store.db.execute('SELECT * FROM acquisition_requests WHERE request_id=?', (request['request_id'],)).fetchone()), dict(store.db.execute('SELECT * FROM acquisition_checks WHERE check_id=?', (check_id,)).fetchone())


def test_accepted_directory_queues_exact_website_without_network_or_model(tmp_path, monkeypatch):
    with EvidenceStore(tmp_path / 'derived') as store:
        observation, request, check = accepted_directory(store)
        def forbidden(*args, **kwargs):
            raise AssertionError('Offline identity processing must not fetch or interpret')
        monkeypatch.setattr('cdr_terms.acquisition.fetch_document', forbidden)
        monkeypatch.setattr('cdr_terms.acquisitions_queue.enqueue_interpretation', forbidden)
        queue = ProcessingQueue(store)
        outcome = queue.process_one(registry_context())
        assert outcome['status'] == 'complete'
        assert outcome['outcome']['provider_discovery']['bound'] == 1
        assert 'analysis_job_id' not in outcome['outcome']
        queue.validate_receipt(outcome)
        websites = [row[0] for row in store.db.execute("SELECT source_url FROM applicability a JOIN documents d USING(document_id) "
            "WHERE a.observation_id=? AND a.source_path='/discovery/official-provider-directory'", (observation,))]
        assert 'https://www.bankofmelbourne.com.au/sitemap.xml' in websites
        assert 'https://www.bankofmelbourne.com.au/' in websites
        inventory = discovery_inventory(store, 'Bank of Melbourne|BOMHLBasic')
        assert all(item['url'] != DIRECTORY_URL for item in inventory['documents'])
        website = next(item for item in inventory['documents'] if item['url'] == 'https://www.bankofmelbourne.com.au/')
        assert website['relevance'] == 'supplementary' and website['specificity'] == 'background'
        assert website['directorySource']['checkId'] == check['check_id']


def test_directory_redirect_or_tampered_source_cannot_grant_hosts(tmp_path):
    with EvidenceStore(tmp_path / 'derived') as store:
        observation, request, check = accepted_directory(store, final_url='https://unrelated.example/participants')
        outcome = ProcessingQueue(store).process_one(registry_context())
        assert outcome['status'] == 'retry_wait'
        assert store.db.execute("SELECT COUNT(*) FROM applicability WHERE context_json LIKE '%accepted-official-provider-website%'").fetchone()[0] == 0
        forged = {**check, 'metadata_json': canonical_json({'final_url': DIRECTORY_URL})}
        with pytest.raises(ValueError, match='identities differ'):
            process_directory(store, request, forged, [observation], guard=lambda: None)


def test_ambiguous_or_missing_exact_brand_retains_unknown_instead_of_guessing(tmp_path):
    changed = deepcopy(BRANDS)
    brand = next(item for item in changed['value'][0]['brands'] if item['brandName'] == 'Bank of Melbourne')
    brand['website'] = 'https://ambiguity.example/'
    changed['value'][0]['brands'].append(next(item for item in BRANDS['value'][0]['brands'] if item['brandName'] == 'Bank of Melbourne'))
    with EvidenceStore(tmp_path / 'derived') as store:
        accepted_directory(store, body=canonical_json(changed).encode())
        outcome = ProcessingQueue(store).process_one(registry_context())
        assert outcome['status'] == 'complete'
        assert outcome['outcome']['provider_discovery']['unresolved'] == 1
        assert outcome['outcome']['provider_discovery']['bound'] == 0
        ProcessingQueue(store).validate_receipt(outcome)
