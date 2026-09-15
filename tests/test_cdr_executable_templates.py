"""Approval protocol controls only; no source-approved banking template is created."""
import copy
import json
import sqlite3

import pytest

from app_payload_executable import load_published_executable, package_executable
from cdr_terms.executable_contract import validate_asset, validate_template
from cdr_terms.executable_publication import build_executable_asset, publish_executable_asset
from cdr_terms.executable_reviews import review_template, stage_template
from cdr_terms.identity import canonical_json, digest
from tests.executable_protocol_fixture import NOW, VECTOR, protocol, reidentify, stage_and_proof  # noqa: F401


def approve(store, template, *, proof=None, reviewer='protocol-independent-review', reviewer_kind='human'):
    proof = proof or stage_and_proof(store, template)
    return review_template(store, template['id'], decision='approved', reviewer=reviewer, reviewer_kind=reviewer_kind,
        reviewed_at=NOW, evidence_sha256=store.put_blob(canonical_json(proof).encode()), reason='Protocol transition only')


def build(store, template):
    return build_executable_asset(store, template['productKey'], core_asset_sha256=template['selectedRate']['coreAssetSha256'], run_date=template['runDate'])


def publish(store, template, payload, previous=None):
    return publish_executable_asset(store, payload, expected_previous_identity=previous,
        expected_observation_id=template['sourceObservationId'], published_at=NOW)


def load(store, template, source):
    return load_published_executable(store.root, source_observation=source, run_date=template['runDate'],
        core_asset_sha256=template['selectedRate']['coreAssetSha256'], product_keys=[template['productKey']])


def test_cross_language_vector_preserves_unicode_and_decimal_text():
    vector = json.loads(VECTOR.read_bytes())
    template = vector['template']
    validate_template(template)
    assert template['id'] == vector['expectedId']
    assert canonical_json({k: v for k, v in template.items() if k != 'id'}) == vector['canonicalWithoutId']
    assert template['annualRate'] == '0.0500' and '😀' in vector['canonicalWithoutId']


def test_positive_protocol_publication_and_revocation_invalidate_read(protocol):
    store, template, _, source = protocol
    stage_template(store, template, interpreter='protocol-author', staged_at=NOW)
    assert build(store, template)['templates'] == []
    review = approve(store, template)
    asset = build(store, template)
    validate_asset(asset)
    assert asset['templates'][0]['approval']['reviewId'] == review
    publication = publish(store, template, asset)
    assert publish(store, template, asset, asset['identitySha256']) == publication
    assert load(store, template, source) == {template['productKey']: asset}
    negative = store.put_blob(canonical_json({'templateId': template['id'], 'decision': 'revoked'}).encode())
    review_template(store, template['id'], decision='revoked', reviewer='protocol-reviewer', reviewer_kind='human',
        reviewed_at=NOW, evidence_sha256=negative, reason='Protocol revocation')
    with pytest.raises(ValueError, match='changed'):
        load(store, template, source)
    replacement = build(store, template)
    assert replacement['templates'] == [] and replacement['identitySha256'] != asset['identitySha256']
    publish(store, template, replacement, asset['identitySha256'])
    assert load(store, template, source) == {template['productKey']: replacement}


@pytest.mark.parametrize('kind,reviewer', [('model', 'second-pass'), ('human', 'protocol-author')])
def test_model_or_same_interpreter_cannot_approve(protocol, kind, reviewer):
    store, template, *_ = protocol
    proof = stage_and_proof(store, template)
    with pytest.raises(ValueError):
        approve(store, template, proof=proof, reviewer_kind=kind, reviewer=reviewer)


@pytest.mark.parametrize('fault', ['tierKey', 'packageKey', 'effectiveFrom', 'annualRate', 'rowSha', 'self_verified'])
def test_wrong_scope_rate_variant_or_staged_assertion_rejected(protocol, fault):
    store, template, *_ = protocol
    changed = copy.deepcopy(template)
    if fault in ('tierKey', 'packageKey'): changed[fault] = 'another-scope'
    if fault == 'effectiveFrom': changed[fault] = '2026-01-02'
    if fault == 'annualRate': changed[fault] = '0.06'
    if fault == 'rowSha': changed['selectedRate']['rowSha256'] = '0' * 64
    if fault == 'self_verified': changed['review'] = {'materialTerms': 'verified'}
    reidentify(changed)
    with pytest.raises(Exception):
        stage_template(store, changed, interpreter='protocol-author', staged_at=NOW)


def test_deep_input_refused_before_recursive_schema_work():
    value = {}
    for _ in range(2000): value = {'nested': value}
    with pytest.raises(ValueError, match='depth/node'):
        validate_template(value)


def test_publication_cas_and_independent_approval_binding(protocol):
    store, template, *_ = protocol
    approve(store, template)
    asset = build(store, template)
    with pytest.raises(ValueError, match='CAS'):
        publish(store, template, asset, '0' * 64)
    asset['templates'][0]['approval']['templateId'] = '0' * 64
    asset['identitySha256'] = digest({k: v for k, v in asset.items() if k != 'identitySha256'})
    with pytest.raises(ValueError, match='approval template'):
        validate_asset(asset)


def test_equal_unrelated_benchmark_blobs_do_not_approve(protocol):
    store, template, *_ = protocol
    proof = stage_and_proof(store, template)
    proof['benchmarkResultSha256'] = store.put_blob(b'{}')
    with pytest.raises(ValueError, match='benchmark'):
        approve(store, template, proof=proof)


def test_new_tables_are_append_only_and_old_evidence_survives_reopen(protocol):
    from cdr_terms.store import EvidenceStore
    store, template, *_ = protocol
    approve(store, template)
    before = store.db.execute('SELECT COUNT(*) FROM term_revisions').fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match='append-only'):
        store.db.execute("UPDATE executable_reviews SET decision='revoked'")
    store.db.rollback()
    with EvidenceStore(store.root) as reopened:
        assert reopened.db.execute('SELECT COUNT(*) FROM term_revisions').fetchone()[0] == before
        assert reopened.db.execute('SELECT COUNT(*) FROM executable_reviews').fetchone()[0] == 1


def test_additive_schema_preserves_exact_existing_rows_and_blobs(protocol):
    from cdr_terms.store import EvidenceStore
    store, *_ = protocol
    # Reconstruct the prior database shape, before any executable rows exist.
    for table in ('executable_publications', 'executable_reviews', 'executable_template_documents',
                  'executable_template_terms', 'executable_templates'):
        store.db.execute('DROP TABLE ' + table)
    store.db.commit()
    before = list(store.db.iterdump())
    blobs = {path.relative_to(store.root): path.read_bytes() for path in store.root.rglob('*')
             if path.is_file() and 'evidence.sqlite3' not in path.name}
    with EvidenceStore(store.root) as reopened:
        after = list(reopened.db.iterdump())
        assert [line for line in before if line.startswith('INSERT INTO')] == [
            line for line in after if line.startswith('INSERT INTO')]
        assert reopened.db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert reopened.db.execute('PRAGMA user_version').fetchone()[0] == 1
    assert all((store.root / path).read_bytes() == raw for path, raw in blobs.items())


def test_manifest_addressed_packaging_binds_destination_core(protocol):
    store, template, core, source = protocol
    approve(store, template)
    publish(store, template, build(store, template))
    snapshot = load(store, template, source)
    written = {}
    def write(key, value):
        written[key] = value
        return {'sha256': digest(value), 'bytes': len(canonical_json(value).encode()), 'name': key + '.gz'}
    files = package_executable(snapshot, core=core, core_asset_sha256=template['selectedRate']['coreAssetSha256'],
                               run_date=template['runDate'], write_asset=write)
    assert written['executable-index']['products'][template['productKey']] == 'executable_shard_000'
    assert set(files) == {'executable_index', 'executable_shard_000'}
    with pytest.raises(ValueError, match='destination core'):
        package_executable(snapshot, core=core, core_asset_sha256='0'*64, run_date=template['runDate'], write_asset=write)


def test_explicit_public_build_api_and_same_core_revocation_edition(protocol, tmp_path, monkeypatch):
    import app_payload_build as builder
    from app_payload_revisions_state import bundle_sha256
    store, template, core, source = protocol
    approve(store, template)
    first = build(store, template)
    publish(store, template, first)
    data = {'core': core, 'details': {'products': {template['productKey']: {}}}, 'run_date': template['runDate'],
            'counts': {}, 'search_index': None, 'history_banks': None, 'bank_history': None}
    monkeypatch.setattr(builder, '_compute_payload', lambda *args, **kwargs: copy.deepcopy(data))
    monkeypatch.setattr(builder.payload_crypto, 'resolve_key_from_env', lambda: None)
    default = builder.build_payload(tmp_path, tmp_path/'default')
    assert 'executable_index' not in default['files']
    before = builder.build_payload(tmp_path, tmp_path/'before', source_observation=source, executable_root=store.root)
    assert 'executable_index' in before['files']
    negative = store.put_blob(canonical_json({'templateId': template['id'], 'decision': 'revoked'}).encode())
    review_template(store, template['id'], decision='revoked', reviewer='protocol-reviewer', reviewer_kind='human',
        reviewed_at=NOW, evidence_sha256=negative, reason='Protocol revocation')
    with pytest.raises(ValueError, match='changed'):
        builder.build_payload(tmp_path, tmp_path/'stale', source_observation=source, executable_root=store.root)
    assert not (tmp_path/'stale/manifest.json').exists()
    publish(store, template, build(store, template), first['identitySha256'])
    after = builder.build_payload(tmp_path, tmp_path/'after', source_observation=source, executable_root=store.root)
    assert before['files']['core']['sha256'] == after['files']['core']['sha256']
    assert bundle_sha256(before) != bundle_sha256(after)
    monkeypatch.setattr(builder.payload_crypto, 'resolve_key_from_env', lambda: b'x'*32)
    with pytest.raises(ValueError, match='unencrypted'):
        builder.build_payload(tmp_path, tmp_path/'encrypted', source_observation=source, executable_root=store.root)


def test_deep_schema_wrong_ids_and_principal_bounds_refuse():
    template = json.loads(VECTOR.read_bytes())['template']
    for bad in ('constructor', 'prototype', 'not a safe id', '1starts_wrong'):
        changed = copy.deepcopy(template)
        changed['eligibility']['id'] = bad
        with pytest.raises(Exception):
            validate_template(reidentify(changed))
    template['principalBounds']['maximum'] = {'value': '0.00', 'inclusive': False}
    with pytest.raises(ValueError, match='principal bounds'):
        validate_template(reidentify(template))


def test_operation_core_cache_does_not_escape_to_next_operation(protocol, monkeypatch):
    from cdr_terms.executable_sources import selected_row, source_operation
    store, template, *_ = protocol
    original = store.read_blob
    reads = []
    def read(identity):
        reads.append(identity)
        return original(identity)
    monkeypatch.setattr(store, 'read_blob', read)
    with source_operation(store):
        selected_row(store, template)
        selected_row(store, template)
    assert reads.count(template['selectedRate']['coreAssetSha256']) == 1
    with source_operation(store):
        selected_row(store, template)
    assert reads.count(template['selectedRate']['coreAssetSha256']) == 2


def test_unrelated_equal_typed_benchmark_outputs_are_rejected(protocol):
    store, template, *_ = protocol
    proof = stage_and_proof(store, template)
    benchmark = json.loads(store.read_blob(proof['benchmarkResultSha256']))
    actual = json.loads(store.read_blob(benchmark['cases'][0]['actualSha256']))
    actual['result'] = {}
    benchmark['cases'][0]['actualSha256'] = store.put_blob(canonical_json(actual).encode())
    proof['benchmarkResultSha256'] = store.put_blob(canonical_json(benchmark).encode())
    with pytest.raises(ValueError, match='receipt.*shape'):
        approve(store, template, proof=proof)
