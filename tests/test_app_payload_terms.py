"""Retained CDR projections; fabricated capture envelopes are protocol controls."""
import copy
import gzip
import json

import pytest

import app_payload_terms as terms
from app_payload_terms import load_published_terms
from app_payload_build import _package, _attach_terms
from app_payload_revisions_state import bundle_sha256
from cdr_terms.identity import canonical_json
from cdr_terms.reporting import build_product_asset, publish_product_asset
from tests.test_cdr_terms_evidence import evidence, NOW  # noqa: F401


def publish(evidence):
    store, observation, key, *_ = evidence
    receipt = {'generation_id': 'retained-september7', 'source_run_date': '2026-09-07',
               'export_contract_digest': 'a' * 64}
    blob = store.put_blob(canonical_json(receipt).encode())
    with store.db:
        store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,?)',
                         (receipt['generation_id'], blob, NOW, 1))
    payload = build_product_asset(store, key)
    publish_product_asset(store, payload, expected_previous_identity=None,
                          expected_observation_id=observation, published_at=NOW)
    return payload, {'generation_id': receipt['generation_id'], 'contract_digest': 'a' * 64}


def test_loads_current_published_projection_read_only_and_keeps_unknowns(evidence):
    payload, source = publish(evidence)
    store, _, key, *_ = evidence
    changes = store.db.total_changes
    result = terms.load_published_terms(store.root, source_observation=source,
                                        run_date='2026-09-07', product_keys=[key, 'unpublished'])
    assert result == {key: payload}
    assert result[key]['coverage']['calculation']['status'] == 'unknown'
    assert store.db.total_changes == changes


@pytest.mark.parametrize('fault', ['date', 'generation', 'contract', 'source'])
def test_refuses_wrong_generation_or_stale_projection(evidence, fault):
    _, source = publish(evidence)
    store, _, key, _, _, body, record = evidence
    day = '2026-09-07'
    if fault == 'date':
        day = '2026-09-08'
    elif fault == 'generation':
        source['generation_id'] = 'unknown'
    elif fault == 'contract':
        source['contract_digest'] = 'b' * 64
    else:
        store.observe(provider=record['brand'], product_key=key, record=json.loads(body),
                      source_bytes=body, observed_at=NOW, ingest_id='newer')
    with pytest.raises(ValueError):
        terms.load_published_terms(store.root, source_observation=source, run_date=day, product_keys=[key])


def test_missing_root_does_not_create_a_database(tmp_path):
    root = tmp_path / 'absent'
    with pytest.raises(FileNotFoundError):
        terms.load_published_terms(root, source_observation={'generation_id': 'x', 'contract_digest': 'a'*64},
                                   run_date='2026-09-07', product_keys=[])
    assert not root.exists()


def test_all_shards_are_manifest_assets_and_retagging_preserves_bundle(evidence, tmp_path):
    payload, _ = publish(evidence)
    key = payload['product_key']
    manifest = _package({'sections': {}}, {'products': {}}, '2026-09-07', tmp_path,
                        repo='owner/repository', tag='app-payload-latest', counts={}, terms={key: payload})
    index = json.loads(gzip.decompress((tmp_path / manifest['files']['terms_index']['name']).read_bytes()))
    assert index == {'schema_version': 2, 'run_date': '2026-09-07', 'products': {key: 'terms_shard_000'}}
    shard = manifest['files'][index['products'][key]]
    assert json.loads(gzip.decompress((tmp_path / shard['name']).read_bytes()))['products'][key] == payload
    changed = copy.deepcopy(manifest)
    changed['tag'] = 'app-payload-2026-09-07-r000002'
    for asset in changed['files'].values():
        asset['url'] = asset['url'].replace('app-payload-latest', changed['tag'])
    assert bundle_sha256(changed) == bundle_sha256(manifest)
    assert b'releases/download' not in gzip.decompress((tmp_path / manifest['files']['terms_index']['name']).read_bytes())


def test_opt_in_hook_and_unchanged_default(evidence):
    payload, source = publish(evidence)
    data = {'run_date': '2026-09-07', 'source_observation': source,
            'details': {'products': {payload['product_key']: {}}}}
    _attach_terms(data, None)
    assert 'terms' not in data
    _attach_terms(data, evidence[0].root)
    assert data['terms'] == {payload['product_key']: payload}


def test_snapshot_budget_and_missing_blob_fail_closed(evidence, monkeypatch):
    _, source = publish(evidence)
    monkeypatch.setattr(terms, 'MAX_BLOB_WORK', 1)
    with pytest.raises(ValueError, match='byte budget'):
        terms.load_published_terms(evidence[0].root, source_observation=source,
                                   run_date='2026-09-07', product_keys=[evidence[2]])


def test_shard_overflow_refuses_without_dropping_terms(evidence, monkeypatch):
    payload, _ = publish(evidence)
    monkeypatch.setattr(terms, 'MAX_SHARD_RAW', 1)
    writes = []
    with pytest.raises(ValueError, match='byte bound'):
        terms.package_terms({payload['product_key']: payload}, run_date='2026-09-07',
                            write_asset=lambda *args: writes.append(args))
    assert not writes


@pytest.mark.parametrize('budget_delta', [0, -1])
def test_snapshot_budget_counts_product_input_without_shard_envelope(evidence, monkeypatch, budget_delta):
    payload, _ = publish(evidence)
    key = payload['product_key']
    input_bytes = len(canonical_json(payload).encode('utf-8'))
    monkeypatch.setattr(terms, 'MAX_SNAPSHOT_RAW', input_bytes + budget_delta)
    writes = {}

    def write_asset(name, body):
        writes[name] = body
        return {'name': name}

    if budget_delta < 0:
        with pytest.raises(ValueError, match='byte bound'):
            terms.package_terms({key: payload}, run_date='2026-09-07', write_asset=write_asset)
        assert not writes
    else:
        terms.package_terms({key: payload}, run_date='2026-09-07', write_asset=write_asset)
        assert writes['terms_shard_000']['products'] == {key: payload}
        assert len(terms._json(writes['terms_shard_000'])) > input_bytes

def test_unchanged_daily_capture_can_rebind_published_projection(evidence):
    original, source = publish(evidence)
    store, old_observation, key, _, _, body, record = evidence
    assert load_published_terms(store.root, source_observation=source,
        run_date='2026-09-07', product_keys=[key]) == {key: original}
    new_generation = 'retained-september8'
    new_observation = store.observe(provider=record['brand'], product_key=key,
        record=json.loads(body), source_bytes=body, observed_at='2026-09-08T00:00:00Z',
        ingest_id=new_generation)
    receipt = {'generation_id': new_generation, 'source_run_date': '2026-09-08',
        'export_contract_digest': 'b' * 64}
    blob = store.put_blob(canonical_json(receipt).encode())
    with store.db:
        store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,?)',
            (new_generation, blob, '2026-09-08T01:00:00Z', 1))
    current = build_product_asset(store, key)
    assert current == original, 'Unchanged evidence should retain its public identity'
    publication = publish_product_asset(store, current, expected_previous_identity=original['identity_sha256'],
        expected_observation_id=new_observation, published_at='2026-09-08T01:00:00Z')
    assert publish_product_asset(store, current, expected_previous_identity=original['identity_sha256'],
        expected_observation_id=new_observation, published_at='2026-09-08T02:00:00Z') == publication
    assert store.db.execute('SELECT COUNT(*) FROM publications').fetchone()[0] == 2
    assert new_observation != old_observation
    assert load_published_terms(store.root, source_observation={
        'generation_id': new_generation, 'contract_digest': 'b' * 64},
        run_date='2026-09-08', product_keys=[key]) == {key: current}
