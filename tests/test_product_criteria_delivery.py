"""Real retained source criteria are optional assets, never financial content."""
from copy import deepcopy

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
