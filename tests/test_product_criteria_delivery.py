"""Real retained source criteria are optional assets, never financial content."""
from copy import deepcopy
import gzip
import json

import pytest

from app_payload_financial_projection import criteria_files, financial_manifest
from app_payload_product_evidence_contract import canonical, digest
from app_payload_product_evidence_daily import FinancialEvidence
from app_payload_publication_assets import complete_assets, verify_stage
from app_payload_product_criteria import verify_criteria
from pi_product_evidence_retry import OptionalRetry
from tests.test_product_evidence_optional_retry import optional, source


def worker(optional):
    (fixture, pointer, contract), _, _, _, sha = optional
    owner = OptionalRetry(fixture['state'], sha)
    return fixture, owner, FinancialEvidence(fixture['state'].parent, fixture['state'],
                                              pointer, contract, pin_store=owner)


def test_criteria_frozen_after_financial_release_are_in_complete_inventory(optional, monkeypatch):
    fixture, owner, value = worker(optional)
    original = (fixture['root'] / 'manifest.json').read_bytes()
    root, manifest = value.resume()
    files = criteria_files(manifest)
    assert 'product_criteria_index' in files and len(files) >= 2
    assert verify_criteria(root, manifest)['coverage']['complete'] is True
    assert canonical(financial_manifest(manifest)) == original
    assert (fixture['root'] / 'manifest.json').read_bytes() == original
    inventory = dict(complete_assets(manifest, root=root))
    assert all(inventory[key] == descriptor for key, descriptor in files.items())
    index = json.loads(gzip.decompress((root / files['product_criteria_index']['name']).read_bytes()))
    products = {}
    for shard in set(index['products'].values()):
        products.update(json.loads(gzip.decompress((root / files[shard]['name']).read_bytes()))['products'])
    references = [reference for product in products.values() for reference in product['sourceDocuments']]
    assert any(reference['url'].endswith('Up-Home-Loan-Booklet.pdf')
               and reference['verification'] == 'discovery-candidate' for reference in references)
    assert all(reference.get('productKey', key) == key for key, product in products.items()
               for reference in product['sourceDocuments'])
    verify_stage(root, expected_manifest_sha256=digest((root / 'manifest.json').read_bytes()))
    import app_payload_product_criteria
    monkeypatch.setattr(app_payload_product_criteria, 'prepare_criteria',
                        lambda *a, **k: pytest.fail('frozen retry recomputed criteria'))
    again, observed = worker(optional)[2].resume()
    assert again == root and observed == manifest


def test_criteria_failure_leaves_financial_source_and_pending_unchanged(optional, monkeypatch):
    fixture, owner, value = worker(optional)
    pending = fixture['state'] / 'app-payload-publication-pending.json'
    before = pending.read_bytes()
    original = (fixture['root'] / 'manifest.json').read_bytes()
    import app_payload_product_criteria
    def failed(*a, **k):
        raise TimeoutError('optional criteria preparation')
    monkeypatch.setattr(app_payload_product_criteria, 'prepare_criteria', failed)
    with pytest.raises(TimeoutError):
        value.resume()
    assert owner.progress().get('candidate_pin') is None
    assert pending.read_bytes() == before
    assert (fixture['root'] / 'manifest.json').read_bytes() == original


def test_changed_criteria_bytes_fail_frozen_readback(optional):
    _, _, value = worker(optional)
    root, manifest = value.resume()
    item = criteria_files(manifest)['product_criteria_index']
    target = root / item['name']
    target.write_bytes(target.read_bytes() + b'changed')
    with pytest.raises(ValueError):
        worker(optional)[2].resume()


def test_financial_projection_removes_only_reserved_exact_file_keys():
    manifest = {'files': {'core': {'sha256': 'financial'},
                         'product_criteria_index': {'sha256': 'optional'},
                         'product_criteria_shard_000': {'sha256': 'optional'},
                         'product_criteria_shard_000_extra': {'sha256': 'unknown'}},
                'product_evidence_v1': {'source': 'optional'}}
    original = deepcopy(manifest)
    assert financial_manifest(manifest) == {'files': {'core': {'sha256': 'financial'},
        'product_criteria_shard_000_extra': {'sha256': 'unknown'}}}
    assert manifest == original


def test_readonly_document_inventory_uses_exact_ready_generation_and_contract(optional, monkeypatch, tmp_path):
    fixture, _, value = worker(optional)
    import cdr_terms.document_discovery_queue
    calls = []
    def documents(root, generation, keys, *, expected_contract_digest):
        calls.append((root, generation, keys, expected_contract_digest))
        return {key: [] for key in keys}
    monkeypatch.setenv('AR_LOCAL_TERMS_ROOT', str(tmp_path / 'optional-terms'))
    monkeypatch.setattr(cdr_terms.document_discovery_queue, 'publication_document_inventory', documents)
    value.resume()
    assert len(calls) == 1
    assert calls[0][1] == value.source['generation_id']
    assert calls[0][3] == value.source['contract_digest']
    assert calls[0][2] and len(set(calls[0][2])) == len(calls[0][2])
