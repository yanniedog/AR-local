"""Captured product facts/bodies; base gzip bytes are explicit technical controls."""
from copy import deepcopy
import gzip
from pathlib import Path
import shutil

import pytest

from app_payload_product_evidence_contract import canonical, digest
from app_payload_product_evidence_transport import pack_snapshot, compressed
from app_payload_product_response_transport import pack_responses
import app_payload_product_evidence_reference as reference
import app_payload_product_evidence_inventory as inventory
from tests.test_app_payload_product_response_sources import real_source, reader


@pytest.fixture
def prepared(tmp_path):
    values = real_source(tmp_path); snapshot, _, _, binding, _ = values
    root = tmp_path / 'payload'; root.mkdir(); files = {}
    for key in ('core', 'details'):
        blob = compressed(canonical({'technical_control': key})); checksum = digest(blob)
        name = f'{key}-2026-05-19-{checksum[:12]}.json.gz'; (root / name).write_bytes(blob)
        files[key] = dict(name=name, sha256=checksum, bytes=len(blob), url='https://example.invalid/' + name)
        binding[key + '_sha256'] = checksum
    manifest = dict(schema_version=1, run_date='2026-05-19', files=files,
                    source_observation={k: binding['source'][k] for k in reference.SOURCE_FIELDS})
    fact_root = tmp_path / 'fact-delivery'; raw_root = tmp_path / 'raw-delivery'
    facts = pack_snapshot(snapshot, fact_root, expected_source=binding['source'],
                          core_sha256=binding['core_sha256'], details_sha256=binding['details_sha256'])
    raw = pack_responses(reader(values), raw_root)
    capabilities = {'product_evidence_v1': facts['capability'], 'product_response_evidence_v1': raw['capability']}
    for namespace, source in (('product_evidence_v1', fact_root), ('product_response_evidence_v1', raw_root)):
        capability = capabilities[namespace]
        for entry in [capability['index'], *capability['shards']]:
            shutil.copyfile(source / entry['name'], root / entry['name'])
        install(root, manifest, namespace, capability)
    save(root, manifest)
    return root, manifest, capabilities


def save(root, manifest):
    (root / 'manifest.json').write_bytes(canonical(manifest))


def install(root, manifest, namespace, capability):
    if namespace in manifest:
        (root / manifest[namespace]['capability']['name']).unlink()
    value, blob = reference.encode_reference(namespace, capability, manifest)
    manifest[namespace] = value; (root / value['capability']['name']).write_bytes(blob)


def test_complete_transitive_inventory_is_read_only_and_has_no_authority(prepared, monkeypatch):
    root, manifest, capabilities = prepared
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    def forbidden(*args, **kwargs): raise AssertionError('read-only adapter wrote a file')
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    result = inventory.verify_local_inventory(root)
    expected = {'manifest.json', *(x['name'] for x in result['inventory'].values())}
    assert expected == set(before)
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    assert result['selection_verified'] is False and result['publication_authorized'] is False
    assert result['namespaces']['product_evidence_v1']['facts'] == capabilities['product_evidence_v1']['facts']
    assert result['namespaces']['product_response_evidence_v1']['bodies'] == capabilities['product_response_evidence_v1']['bodies']
    assert result['total_compressed_bytes'] > result['base_network_budget']['journeys']['all_declared_assets']['bytes']
    assert manifest['source_observation']['generation_id'].startswith('obs-')


def test_old_manifest_without_optional_namespaces_preserves_bundle(prepared):
    from app_payload_revisions_state import bundle_sha256
    root, manifest, _ = prepared
    keep = {'manifest.json', *(x['name'] for x in manifest['files'].values())}
    for path in root.iterdir():
        if path.name not in keep: path.unlink()
    for namespace in reference.LANES: manifest.pop(namespace)
    manifest.pop('source_observation'); save(root, manifest)
    expected = bundle_sha256(manifest)
    result = inventory.verify_local_inventory(root)
    assert result['bundle_sha256'] == expected and result['namespaces'] == {}


@pytest.mark.parametrize('field', ['generation_id', 'observation_date', 'observation_state', 'contract_digest'])
def test_manifest_source_is_independent_binding_not_capability_echo(prepared, field):
    root, manifest, _ = prepared
    manifest['source_observation'][field] = 'wrong'
    save(root, manifest)
    with pytest.raises(ValueError, match='detached from manifest source'): inventory.verify_local_inventory(root)


@pytest.mark.parametrize('field', ['core', 'details'])
def test_actual_base_bytes_must_match_bound_hash(prepared, field):
    root, manifest, _ = prepared; path = root / manifest['files'][field]['name']
    blob = path.read_bytes(); path.write_bytes(bytes([blob[0] ^ 1]) + blob[1:])
    with pytest.raises(ValueError, match='digest or size'): inventory.verify_local_inventory(root)


@pytest.mark.parametrize('size', [65536, 65537])
@pytest.mark.parametrize('field', ['bytes', 'decoded_bytes'])
def test_literal_capability_64k_boundary_precedes_inflate(prepared, field, size, monkeypatch):
    _, manifest, _ = prepared; namespace = 'product_evidence_v1'; value = deepcopy(manifest[namespace])
    value['capability'][field] = size
    if size == 65536:
        reference.validate_reference(namespace, value, manifest)
    else:
        monkeypatch.setattr(reference.zlib, 'decompressobj', lambda *a: pytest.fail('inflation before declared bound'))
        with pytest.raises(ValueError, match='64 KiB'): reference.decode_capability(namespace, value, b'', manifest)


@pytest.mark.parametrize('size', [65536, 65537])
def test_actual_root_manifest_64k_boundary(prepared, size):
    root, manifest, _ = prepared; raw = canonical(manifest)
    (root / 'manifest.json').write_bytes(raw + b' ' * (size - len(raw)))
    if size == 65536: inventory.verify_local_inventory(root)
    else:
        with pytest.raises(ValueError, match='unsafe delivery evidence'): inventory.verify_local_inventory(root)


@pytest.mark.parametrize('fault', ['missing-cap', 'missing-index', 'missing-shard', 'corrupt', 'extra', 'future', 'eager'])
def test_no_silent_transitive_omission(prepared, fault):
    root, manifest, capabilities = prepared; namespace = 'product_evidence_v1'
    cap = capabilities[namespace]
    if fault.startswith('missing'):
        entry = {'missing-cap': manifest[namespace]['capability'], 'missing-index': cap['index'], 'missing-shard': cap['shards'][0]}[fault]
        (root / entry['name']).unlink()
    elif fault == 'corrupt': (root / cap['shards'][0]['name']).write_bytes(b'corrupt')
    elif fault == 'extra': (root / 'unbound.json.gz').write_bytes(b'unbound')
    elif fault == 'future': manifest['product_evidence_v2'] = manifest.pop(namespace); save(root, manifest)
    else: manifest['files']['hidden'] = dict(cap['shards'][0]); save(root, manifest)
    with pytest.raises((OSError, ValueError)): inventory.verify_local_inventory(root)


def test_cross_lane_snapshot_binding_mismatch_rejected(prepared):
    root, manifest, capabilities = prepared; namespace = 'product_response_evidence_v1'
    cap = deepcopy(capabilities[namespace]); cap['binding']['facts']['snapshot_sha256'] = 'f' * 64
    install(root, manifest, namespace, cap); save(root, manifest)
    with pytest.raises(ValueError, match='source bindings differ'): inventory.verify_local_inventory(root)


@pytest.mark.parametrize('fault', ['trailing', 'second-member', 'depth', 'duplicate'])
def test_capability_gzip_and_json_boundaries(prepared, fault):
    _, manifest, _ = prepared; namespace = 'product_evidence_v1'; value = deepcopy(manifest[namespace])
    if fault == 'depth': raw = b'[' * 10000 + b']' * 10000
    elif fault == 'duplicate': raw = b'{"schema":1,"schema":2}'
    else: raw = b'{}'
    blob = compressed(raw)
    if fault == 'trailing': blob += b'ignored'
    if fault == 'second-member': blob += compressed(b'{}')
    checksum = digest(blob)
    value['capability'] = dict(name=f'product-evidence-capability-{checksum}.json.gz', sha256=checksum,
                               bytes=len(blob), decoded_bytes=len(raw))
    with pytest.raises(ValueError): reference.decode_capability(namespace, value, blob, manifest)


@pytest.mark.parametrize('mutation', ['late-file', 'verified-shard'])
def test_inventory_membership_and_identity_rechecked_after_full_readback(prepared, monkeypatch, mutation):
    root, _, capabilities = prepared; original = inventory.verify_facts
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if mutation == 'late-file': (root / 'late.json').write_bytes(b'{}')
        else:
            path = root / capabilities['product_evidence_v1']['shards'][0]['name']
            path.write_bytes(path.read_bytes() + b'late')
        return result
    monkeypatch.setattr(inventory, 'verify_facts', changed)
    with pytest.raises(ValueError, match='changed payload inventory'): inventory.verify_local_inventory(root)


def test_lazy_inventory_does_not_raise_current_16mib_budget(prepared, monkeypatch):
    import app_payload_network_budget as budget
    root, manifest, _ = prepared
    assert budget.ROLLING_TOTAL_MAX_BYTES == 16 * 1024**2
    base_bytes = sum(x['bytes'] for x in manifest['files'].values())
    monkeypatch.setattr(budget, 'ROLLING_TOTAL_MAX_BYTES', base_bytes)
    result = inventory.verify_local_inventory(root)
    assert result['total_compressed_bytes'] > base_bytes
    monkeypatch.setattr(budget, 'ROLLING_TOTAL_MAX_BYTES', base_bytes - 1)
    with pytest.raises(ValueError, match='payload total bytes'): inventory.verify_local_inventory(root)


def test_reference_roundtrip_deterministic_and_wrong_product_lane_rejected(prepared):
    _, manifest, caps = prepared
    for namespace, cap in caps.items():
        first, blob = reference.encode_reference(namespace, cap, manifest)
        assert reference.encode_reference(namespace, cap, manifest) == (first, blob)
        assert reference.decode_capability(namespace, first, blob, manifest) == cap
        other = next(key for key in reference.LANES if key != namespace)
        with pytest.raises(ValueError): reference.decode_capability(other, first, blob, manifest)


@pytest.mark.parametrize('fault', [None, 'latest', 'wrong-repo', 'wrong-generation', 'outside', 'different-capability'])
def test_readback_url_resolves_only_exact_immutable_adopted_asset(prepared, fault):
    from app_payload_common import DEFAULT_REPO
    from app_payload_revisions_state import bundle_sha256
    root, manifest, caps = prepared; namespace = 'product_evidence_v1'; cap = deepcopy(caps[namespace])
    manifest['repo'] = DEFAULT_REPO; manifest['tag'] = 'app-payload-2026-05-19-r000001'
    checksum = bundle_sha256(manifest)
    manifest['payload_revision'] = dict(schema_version=1, revision=1, bundle_sha256=checksum,
                                        generation_id='sha256-' + checksum, parent_revision=None)
    entry = dict(cap['index'])
    blob = (root / manifest[namespace]['capability']['name']).read_bytes()
    if fault == 'latest': manifest['tag'] = 'app-payload-latest'
    elif fault == 'wrong-repo': manifest['repo'] = 'other/repository'
    elif fault == 'wrong-generation': manifest['payload_revision']['generation_id'] = 'sha256-' + 'f' * 64
    elif fault == 'outside': entry['name'] = 'unbound.json.gz'
    elif fault == 'different-capability':
        cap['facts'] += 1; blob = compressed(canonical(cap))
    if fault:
        with pytest.raises(ValueError): reference.immutable_asset_url(manifest, namespace, entry, capability_blob=blob)
    else:
        prefix = f"https://github.com/{DEFAULT_REPO}/releases/download/{manifest['tag']}/"
        assert reference.immutable_asset_url(manifest, namespace, entry, capability_blob=blob) == prefix + entry['name']
        direct = manifest[namespace]['capability']
        assert reference.immutable_asset_url(manifest, namespace, direct) == prefix + direct['name']


def test_historical_compressor_encoding_does_not_change_adopted_asset_resolution(prepared, monkeypatch):
    from app_payload_common import DEFAULT_REPO
    from app_payload_revisions_state import bundle_sha256
    _, manifest, caps = prepared; namespace = 'product_evidence_v1'; cap = caps[namespace]
    blob = gzip.compress(canonical(cap), compresslevel=1, mtime=123)
    checksum = digest(blob); descriptor = manifest[namespace]['capability']
    descriptor.update(name=f'product-evidence-capability-{checksum}.json.gz', sha256=checksum, bytes=len(blob))
    manifest.update(repo=DEFAULT_REPO, tag='app-payload-2026-05-19-r000001')
    bundle = bundle_sha256(manifest)
    manifest['payload_revision'] = dict(schema_version=1, revision=1, bundle_sha256=bundle, generation_id='sha256-' + bundle)
    monkeypatch.setattr(reference, 'compressed', lambda _: pytest.fail('historical capability was recompressed'))
    url = reference.immutable_asset_url(manifest, namespace, cap['index'], capability_blob=blob)
    assert url.endswith('/' + cap['index']['name'])
