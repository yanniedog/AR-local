"""Generation/hash binding and budget controls over retained public programme data."""
from __future__ import annotations

from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from app_payload_public_rates import (
    descriptor, load_candidate, package_catalogue, retag, validate_local_catalogue,
)
from app_payload_optional_assets import iter_payload_assets
from app_payload_revisions_state import bundle_sha256, validate_manifest
from cdr_domain.public_pricing import canonical_bytes, semantic_id
from cdr_public_rates_cdr import compile_record, inventory_from_compiled

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/public_rates'
GOLDEN = ROOT / 'contracts/public_rates/fixtures/resolver-golden-v1.json'
GENERATION = 'public-retained-fixture-generation-control'
DAY = '2026-10-14'
TAG = 'app-payload-2026-10-14-r000001'
BASE = 'https://github.com/yanniedog/AR-local/releases/download/' + TAG


@pytest.fixture(scope='module')
def candidate():
    cases = json.loads(GOLDEN.read_bytes())['cases']
    result = {'schemaVersion': 1, 'generationId': GENERATION, 'runDate': DAY,
              'products': [], 'programmes': [], 'referenceRates': [], 'evidence': [], 'coverage': [],
              'enabledProgrammeIds': []}
    for case in cases:
        source = case['publicSource']
        raw = (FIXTURES / source['fixture']).read_bytes()
        record = json.loads(raw)['data']
        section = case['programme']['section']
        provider = 'NAB' if section == 'Mortgage' else 'ANZ'
        compiled = compile_record(record, provider_name=provider, section=section,
                                  source_url=source['url'], source_sha256=source['sha256'],
                                  checked_at=case['programme']['freshness']['lastSuccessAt'],
                                  product_key=provider + '|' + record['productId'])
        programme = next(p for p in compiled['programmes'] if p['programmeId'] == case['programme']['programmeId'])
        product = {**compiled['product'], 'programmeIds': [programme['programmeId']]}
        result['products'].append(product)
        result['programmes'].append(programme)
        result['evidence'].extend(compiled['evidence'])
    result['coverage'] = inventory_from_compiled(result)
    return result


def asset(root, kind, value):
    blob = gzip.compress(canonical_bytes(value), mtime=0)
    sha = hashlib.sha256(blob).hexdigest()
    name = f'{kind}-{DAY}-{sha[:12]}.json.gz'
    (root / name).write_bytes(blob)
    return {'name': name, 'sha256': sha, 'bytes': len(blob), 'url': BASE + '/' + name}


def package(tmp_path, candidate, publication_receipt=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    files = {key: asset(tmp_path, key, {'schema_version': 1, 'run_date': DAY}) for key in ['core', 'details']}
    catalogue = package_catalogue(candidate, out_dir=tmp_path, release_base=BASE,
                                  core_sha256=files['core']['sha256'], details_sha256=files['details']['sha256'], publication_receipt=publication_receipt)
    manifest = {'schema_version': 1, 'run_date': DAY, 'repo': 'yanniedog/AR-local', 'tag': TAG,
                'files': files, 'source_observation': {'generation_id': GENERATION}, 'public_rate_catalogue': catalogue}
    return manifest


def test_disabled_catalogue_has_discovery_without_promoting_shadow_formulae(tmp_path, candidate):
    original = deepcopy(candidate)
    manifest = package(tmp_path, candidate)
    decoded = validate_local_catalogue(manifest, tmp_path)
    assert candidate == original
    assert decoded['index']['products'] == [] and len(decoded['products']) == 3
    assert all(product['programmeIds'] == [] and product['suppressedProgrammeCount'] == 1 for product in decoded['products'])
    assert all('pricing_programme_not_enabled' in product['reasonCodes'] for product in decoded['products'])
    assert all(product['sourceEvidence']['locator'] == '/data' and product['freshness']['lastSuccessAt'] for product in decoded['products'])
    programmes = [p for s in manifest['public_rate_catalogue']['shards']
                  for p in json.loads(gzip.decompress((tmp_path / s['name']).read_bytes()))['programmes']]
    assert programmes == []
    assert all(route['kind'] == 'discovery' for route in decoded['index']['routes'])
    assert all(shard['productIds'] == [] for shard in decoded['index']['shards'])
    assert 'public_rate_catalogue' not in manifest['files']
    assert all(asset['bytes'] <= 1048576 for _, asset in iter_payload_assets(manifest))


def test_approved_programmes_fees_and_public_evidence_are_bound(tmp_path, candidate, monkeypatch):
    enabled = deepcopy(candidate)
    import app_payload_public_rates as module
    # Operational approval source is controlled here; all pricing/expected data
    # still comes from the three retained public lender captures.
    monkeypatch.setattr(module, '_authorised_programmes', lambda data, receipt: {p['programmeId'] for p in data['programmes']})
    manifest = package(tmp_path, enabled, tmp_path / 'reviewed-receipt-control.json')
    validate_manifest(manifest, tmp_path)
    validate_local_catalogue(manifest, tmp_path)
    shards = [json.loads(gzip.decompress((tmp_path / asset['name']).read_bytes())) for asset in manifest['public_rate_catalogue']['shards']]
    programmes = [p for shard in shards for p in shard['programmes']]
    fee_sets = {f['feeSetId']: f for shard in shards for f in shard.get('feeSets', [])}
    assert all('formula' in p and 'fees' not in p and 'feeCoverage' not in p and p['feeSetId'] in fee_sets for p in programmes)
    assert all(fee_sets[p['feeSetId']]['productId'] == p['productId'] for p in programmes)
    assert any(fee['amount'] == '12' for f in fee_sets.values() for fee in f['fees'] if 'amount' in fee)


def test_reviewed_structure_suspension_keeps_discovery_and_other_verified_programmes(tmp_path, candidate, monkeypatch):
    from cdr_public_rates_publication import ProgrammeSelection
    import app_payload_public_rates as module
    savings = next(p for p in candidate['programmes'] if p['section'] == 'Savings')
    td = next(p for p in candidate['programmes'] if p['section'] == 'TD')
    reason = 'public_pricing_structure_changed_requires_review'
    selection = ProgrammeSelection({td['programmeId']}, suspensions={savings['programmeId']: {
        'programmeId': savings['programmeId'], 'productId': savings['productId'], 'section': 'Savings', 'reasonCodes': [reason]}})
    # Selection is an operational control here; the real gate is covered by
    # its full shadow-report/receipt tests and no public rate is modified.
    monkeypatch.setattr(module, '_authorised_programmes', lambda _data, _receipt: selection)
    manifest = package(tmp_path, candidate, tmp_path / 'reviewed-selection-control.json')
    decoded = validate_local_catalogue(manifest, tmp_path)
    products = {p['productId']: p for p in decoded['products']}
    assert products[savings['productId']]['programmeIds'] == []
    assert reason in products[savings['productId']]['reasonCodes']
    assert products[td['productId']]['programmeIds'] == [td['programmeId']]
    coverage = next(row for row in decoded['index']['coverage'] if row['section'] == 'Savings'
                    and row['providerId'] == products[savings['productId']]['providerId'])
    assert coverage['publicationStatus'] == 'published_with_suspensions'
    assert coverage['resolutionStatus'] == 'unresolved' and reason in coverage['reasonCodes']
    assert coverage['sourceStatus'] == 'observed'


@pytest.mark.parametrize('fault', ['generation', 'core', 'details', 'url'])
def test_mixed_generation_and_foreign_asset_routes_fail_closed(tmp_path, candidate, fault):
    manifest = package(tmp_path, candidate)
    if fault == 'generation':
        manifest['source_observation']['generation_id'] = 'unrelated-generation-control'
    elif fault in {'core', 'details'}:
        manifest['files'][fault]['sha256'] = '0' * 64
    else:
        manifest['public_rate_catalogue']['index']['url'] = 'https://untrusted.example/foreign.json.gz'
    with pytest.raises(ValueError):
        descriptor(manifest)


def test_torn_download_and_hash_mismatch_never_create_accepted_catalogue(tmp_path, candidate):
    manifest = package(tmp_path, candidate)
    index = manifest['public_rate_catalogue']['index']
    path = tmp_path / index['name']
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match='hash or size'):
        validate_local_catalogue(manifest, tmp_path)


def test_discovery_route_content_is_checked_after_immutable_hash_verification(tmp_path, candidate):
    manifest = package(tmp_path, candidate)
    original = manifest['public_rate_catalogue']['index']
    index = json.loads(gzip.decompress((tmp_path / original['name']).read_bytes()))
    index['routes'][0]['providerIds'] = []
    blob = gzip.compress(canonical_bytes(index), compresslevel=9, mtime=0)
    digest = hashlib.sha256(blob).hexdigest()
    name = f'public-rate-index-{DAY}-{digest[:12]}.json.gz'
    (tmp_path / name).write_bytes(blob)
    manifest['public_rate_catalogue']['index'] = {**original, 'name': name, 'url': BASE + '/' + name,
                                                 'sha256': digest, 'bytes': len(blob), 'decodedBytes': len(canonical_bytes(index))}
    with pytest.raises(ValueError, match='discovery shard routing'):
        validate_local_catalogue(manifest, tmp_path)


def test_retagging_changes_only_transport_urls_and_keeps_bundle_identity(tmp_path, candidate):
    manifest = package(tmp_path, candidate)
    original = bundle_sha256(manifest)
    revised = deepcopy(manifest)
    revised['tag'] = 'app-payload-2026-10-14-r000002'
    base = 'https://github.com/yanniedog/AR-local/releases/download/' + revised['tag']
    revised['files'] = {key: {**value, 'url': base + '/' + value['name']} for key, value in revised['files'].items()}
    retag(revised, url=lambda name: base + '/' + name)
    assert bundle_sha256(revised) == original
    revised['public_rate_catalogue']['index']['decodedBytes'] += 1
    assert bundle_sha256(revised) != original


def test_candidate_generation_and_immutable_filename_hash_are_verified(tmp_path, candidate):
    raw = canonical_bytes(candidate) + b'\n'
    digest = hashlib.sha256(raw).hexdigest()
    path = tmp_path / (digest + '.json')
    path.write_bytes(raw)
    assert load_candidate(path, source_observation={'generation_id': GENERATION}, run_date=DAY) == candidate
    with pytest.raises(ValueError, match='generation'):
        load_candidate(path, source_observation={'generation_id': 'other-control'}, run_date=DAY)
    path.write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='filename hash'):
        load_candidate(path, source_observation={'generation_id': GENERATION}, run_date=DAY)


def test_budget_and_unknown_enabled_identity_are_not_ignored(tmp_path, candidate, monkeypatch):
    import app_payload_public_rates as module
    monkeypatch.setattr(module, 'INDEX_DECODED', 128)
    with pytest.raises(ValueError, match='budget'):
        package(tmp_path, candidate)
    enabled = deepcopy(candidate)
    enabled['enabledProgrammeIds'] = ['nonexistent-programme-control']
    with pytest.raises(ValueError, match='cannot activate'):
        package(tmp_path / 'second', enabled)


def test_missing_formula_evidence_and_source_identity_cannot_be_enabled(tmp_path, candidate, monkeypatch):
    enabled = deepcopy(candidate)
    import app_payload_public_rates as module
    monkeypatch.setattr(module, '_authorised_programmes', lambda data, receipt: {p['programmeId'] for p in data['programmes']})
    enabled['evidence'] = []
    with pytest.raises(ValueError, match='evidence bindings'):
        package(tmp_path, enabled, tmp_path / 'reviewed-receipt-control.json')


def test_public_reference_families_remain_available_without_enabled_programmes(tmp_path, candidate):
    from cdr_public_rates_reference import extract_reference
    from cdr_public_rates_sources import reviewed_register
    profile = json.loads((ROOT / 'contracts/public_rates/reviewed-source-shapes-v1.json').read_bytes())['sources']['nab-indicator']
    source = next(item for item in reviewed_register()['sources'] if item['sourceId'] == 'nab-indicator')
    context = {**source, 'providerId': candidate['products'][0]['providerId'], 'sourceUrl': source['url'],
               'sourceSha256': profile['sha256'], 'checkedAt': '2026-10-14T11:50:00Z'}
    parsed = extract_reference((FIXTURES / profile['fixture']).read_bytes(), context)
    rate = next(row for row in parsed['referenceRates'] if row['name'] == 'Variable Rate for Home Loans (Standard Variable Rate)')
    fields = {'referenceId', 'providerId', 'name', 'value', 'unit', 'scopeId', 'conditions', 'evidenceIds', 'effectiveFrom', 'effectiveTo', 'freshness'}
    retained = deepcopy(candidate)
    retained['referenceRates'] = [{key: value for key, value in rate.items() if key in fields}]
    retained['evidence'].extend(parsed['evidence'])
    retained['products'][0]['referenceIds'] = [rate['referenceId']]
    manifest = package(tmp_path, retained)
    decoded = validate_local_catalogue(manifest, tmp_path)
    pricing_route = next(route for route in decoded['index']['routes'] if route['kind'] == 'pricing')
    assert retained['products'][0]['providerId'] in pricing_route['providerIds']
    shard = json.loads(gzip.decompress((tmp_path / pricing_route['name']).read_bytes()))
    assert shard['programmes'] == [] and shard['referenceRates'][0]['value'] == '9.02'
    assert shard['referenceRates'][0]['unit'] == 'percentage_points'
    assert any(product['referenceIds'] == [rate['referenceId']] for product in decoded['products'])


def test_discovery_routes_keep_retained_unresolved_products_discoverable(tmp_path, candidate):
    retained = deepcopy(candidate)
    retained['products'][0]['status'] = 'unknown'
    retained['products'][0]['aliases'] = [{'name': 'NAB Tailored Home Loan public historical name'}]
    retained['programmes'][0]['freshness']['state'] = 'stale'
    retained['products'][0]['freshness']['state'] = 'stale'
    manifest = package(tmp_path, retained)
    decoded = validate_local_catalogue(manifest, tmp_path)
    index = decoded['index']
    assert any(product['aliases'] for product in decoded['products'])
    product_id = retained['products'][0]['productId']
    assert any(product['productId'] == product_id and product['freshness']['state'] == 'stale' for product in decoded['products'])
    assert any(retained['products'][0]['providerId'] in route['providerIds'] for route in index['routes'] if route['kind'] == 'discovery')
    assert all(product_id not in shard['productIds'] for shard in index['shards'])


def test_chunked_candidates_load_only_approved_public_programmes(tmp_path, candidate, monkeypatch):
    from cdr_atomic import canonical_json_bytes
    from cdr_public_rates_candidate import write_chunks
    root = tmp_path / 'internal-archive'
    root.mkdir()
    chunked = deepcopy(candidate)
    chunked['programmeChunks'] = write_chunks(root, GENERATION, 'programme', chunked['programmes'])
    chunked['evidenceChunks'] = write_chunks(root, GENERATION, 'evidence', chunked['evidence'])
    chunked['programmes'], chunked['evidence'] = [], []
    raw = canonical_json_bytes(chunked)
    path = root / (hashlib.sha256(raw).hexdigest() + '.json')
    path.write_bytes(raw)
    captured = load_candidate(path, source_observation={'generation_id': GENERATION}, run_date=DAY)
    import cdr_public_rates_candidate as archive
    original_reader = archive._json
    read_paths = []
    def tracked_reader(path, maximum):
        read_paths.append(path)
        return original_reader(path, maximum)
    monkeypatch.setattr(archive, '_json', tracked_reader)
    disabled = package(tmp_path / 'disabled', captured)
    assert read_paths == []
    assert len(validate_local_catalogue(disabled, tmp_path / 'disabled')['products']) == 3
    import app_payload_public_rates as module
    approved = candidate['programmes'][1]['programmeId']
    monkeypatch.setattr(module, '_authorised_programmes', lambda data, receipt: {approved})
    enabled = package(tmp_path / 'enabled', captured, root / 'reviewed-receipt-control.json')
    validate_local_catalogue(enabled, tmp_path / 'enabled')
    assert {path.name for path in read_paths} == {row['name'] for row in [*chunked['programmeChunks'], *chunked['evidenceChunks']]}
    discovered = validate_local_catalogue(enabled, tmp_path / 'enabled')['products']
    assert sum(len(product['programmeIds']) for product in discovered) == 1


def test_full_public_inventory_discovery_fits_all_transport_budgets(tmp_path):
    import app_payload_public_rates as module
    path = FIXTURES / 'public-inventory-sizing-20261014.json.gz'
    metadata = json.loads(path.with_name(path.name + '.metadata.json').read_bytes())
    body = path.read_bytes()
    assert hashlib.sha256(body).hexdigest() == metadata['sha256']
    with gzip.open(path, 'rb') as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    assert len(raw) == metadata['decodedBytes'] <= 2 * 1024 * 1024
    observed = json.loads(raw)
    assert observed['pricingEvidence'] is False and observed['sourceInventoryProducts'] == 2934
    assert observed['legacyPublishedRows'] == 16396
    products, placeholder_ids = [], []
    # Only structural routing IDs are generated. Names, keys and row counts
    # are public captures; this fixture supplies no rate or eligibility data.
    for row in observed['products']:
        product = deepcopy(row['discovery'])
        ids = [semantic_id('programme', [product['productId'], 'transport-size-placeholder', number])
               for number in range(row['legacyPublishedRateRows'])]
        product['programmeIds'] = ids
        placeholder_ids.extend(ids)
        products.append(product)
    chunks = []
    for start in range(0, len(placeholder_ids), 10000):
        ids = placeholder_ids[start:start + 10000]
        identity = hashlib.sha256(canonical_bytes(ids)).hexdigest()
        chunks.append({'name': identity + '.json', 'sha256': identity, 'bytes': 1, 'programmeIds': ids})
    retained = {'schemaVersion': 1, 'generationId': GENERATION, 'runDate': DAY,
                'products': products, 'coverage': observed['coverage'], 'programmes': [],
                'referenceRates': [], 'evidence': [], 'enabledProgrammeIds': [], 'programmeChunks': chunks}
    old_flat = canonical_bytes({'products': products, 'coverage': retained['coverage']})
    assert len(old_flat) > module.INDEX_DECODED
    assert len(gzip.compress(old_flat, compresslevel=9, mtime=0)) > module.INDEX_COMPRESSED
    manifest = package(tmp_path, retained)
    result = validate_local_catalogue(manifest, tmp_path)
    catalogue = manifest['public_rate_catalogue']
    assert catalogue['index']['bytes'] <= module.INDEX_COMPRESSED
    assert catalogue['index']['decodedBytes'] <= module.INDEX_DECODED
    assert result['decodedBytes'] <= module.CATALOGUE_DECODED
    assert len(result['products']) == 2934 and result['index']['products'] == []
    assert sum(product['suppressedProgrammeCount'] for product in result['products']) == 16396
    assert all(product['programmeIds'] == [] for product in result['products'])
    assert {product['productId'] for product in result['products']} == {product['productId'] for product in products}
    assert all(route['kind'] == 'discovery' for route in result['index']['routes'])
    for asset in catalogue['shards']:
        assert asset['bytes'] <= module.SHARD_COMPRESSED and asset['decodedBytes'] <= module.SHARD_DECODED


def test_existing_legacy_filter_is_preserved_until_public_capability_activation():
    from app_payload_common import section_filter
    from cdr_quality_accounting import payload_accounting
    row = {'dataset': 'Mortgage', 'category': 'RESIDENTIAL_MORTGAGES', 'rate_family': 'lending',
           'rate_type': 'BUNDLE_DISCOUNT_VARIABLE', 'rate': '0.0649', 'public_rate_disposition': 'adjustment'}
    assert section_filter('Mortgage', row) is True
    assert section_filter('Mortgage', row, require_absolute=True) is False
    assert payload_accounting([], [row])['published_rates'] == 1
    strict = payload_accounting([], [row], public_rates_enabled=True)
    assert strict['published_rates'] == 0 and strict['exclusions'] == {'discount_not_absolute_rate': 1}
