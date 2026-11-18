"""Exact-generation optional evidence reads never initialize or modify storage."""
import json

import pytest

from cdr_terms.document_discovery_queue import publication_document_inventory
from cdr_terms.ingest import capture_finalized
from cdr_terms.product_documents import describe_product_sources
from cdr_terms.store import EvidenceStore
from tests.cdr_terms_source_fixture import source_generation
from tests.test_product_document_discovery import up_record

NOW = '2026-09-07T00:00:00Z'


def captured(tmp_path):
    run, _, finalized = source_generation(tmp_path, '2026-09-07', NOW)
    root = tmp_path / 'derived'
    receipt = capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at=NOW)
    return run, root, finalized, receipt


def test_product_sources_preserve_adapter_provenance_without_claiming_retrieval():
    sources = describe_product_sources(up_record(), 'Up|up-home', 'Up')
    assert len(sources) == 2
    assert all(item['origin'] == 'reviewed-provider-adapter' for item in sources)
    assert all(item['verification'] == 'discovery-candidate' and item['relevance'] == 'candidate' for item in sources)
    assert all(item['checkedAt'] is None and item['sourcePath'] == '/discovery/provider-adapter' for item in sources)


def test_missing_archive_and_missing_generation_return_only_unavailable(tmp_path):
    assert publication_document_inventory(tmp_path / 'absent', 'one', ['product']) == {'product': []}
    assert not (tmp_path / 'absent').exists()
    _, root, _, receipt = captured(tmp_path)
    key = receipt['sources'][0]['product_key']
    assert publication_document_inventory(root, 'not-captured', [key]) == {key: []}


def test_exact_generation_reader_does_not_open_writable_store(tmp_path, monkeypatch):
    _, root, finalized, receipt = captured(tmp_path)
    key = receipt['sources'][0]['product_key']
    before = (root / 'evidence.sqlite3').read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('Optional publication must not initialize schema or create a store')
    monkeypatch.setattr(EvidenceStore, '__init__', forbidden)
    inventory = publication_document_inventory(root, receipt['generation_id'], [key],
                                               expected_contract_digest=finalized['export_contract_digest'])
    assert len({item['url'] for item in inventory[key]}) == 3
    assert all(item['verification'] == 'pending' for item in inventory[key])
    assert (root / 'evidence.sqlite3').read_bytes() == before


def test_wrong_contract_and_corrupt_retained_product_fail_optional_inventory(tmp_path):
    _, root, _, receipt = captured(tmp_path)
    key = receipt['sources'][0]['product_key']
    with pytest.raises(ValueError, match='export contract'):
        publication_document_inventory(root, receipt['generation_id'], [key], expected_contract_digest='0' * 64)
    sha = receipt['sources'][0]['sha256']
    (root / 'blobs' / sha[:2] / sha).write_bytes(b'corrupted retained evidence')
    with pytest.raises(ValueError, match='bytes changed'):
        publication_document_inventory(root, receipt['generation_id'], [key])


def test_old_generation_cannot_borrow_documents_from_newer_current_product(tmp_path):
    _, root, _, first = captured(tmp_path)
    run, _, finalized = source_generation(tmp_path, '2026-09-08', '2026-09-08T00:00:00Z')
    capture_finalized(run, finalized, root, forbidden_roots=[run.parent], observed_at='2026-09-08T00:00:00Z')
    key = first['sources'][0]['product_key']
    assert publication_document_inventory(root, first['generation_id'], [key]) == {key: []}


@pytest.mark.parametrize('keys', [['same', 'same'], [''], [{}]])
def test_ambiguous_or_invalid_product_requests_are_refused(tmp_path, keys):
    with pytest.raises(ValueError, match='identities'):
        publication_document_inventory(tmp_path / 'absent', 'one', keys)
