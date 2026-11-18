"""Whole-catalogue criteria from retained CDR products, with integrity faults."""
from contextlib import closing
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sqlite3

import pytest

from app_payload_product_criteria import prepare_criteria, verify_criteria
from app_payload_criteria_wire import decode_products
from app_payload_product_evidence_contract import canonical, digest
from cdr_clean_export import bank_product_key, detail_json
from cdr_outputs import ensure_db, insert_rows
from tests.test_app_payload_product_evidence import make_contract

DAY = '2026-05-19'


def source(root):
    database = root / 'exports/local-cdr.sqlite'
    database.parent.mkdir()
    captured = json.loads((Path(__file__).parent / 'fixtures/product_facts_real_2026-05-19.json').read_bytes())['products']
    rows = []
    for item in captured:
        record = item['record']
        row = dict(run_date=DAY, dataset=item['dataset'], provider=item['provider'],
                   product_id=record['productId'], product_name=record['name'],
                   category=record.get('productCategory', ''), description=record.get('description', ''),
                   details_json=detail_json(record))
        row['product_key'] = bank_product_key(row)
        rows.append(row)
    with closing(sqlite3.connect(database)) as db:
        ensure_db(db)
        insert_rows(db, 'bank_products', rows)
        db.commit()
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    return database, make_contract(database, root), rows


def build(tmp_path):
    database, contract, rows = source(tmp_path)
    original = (database.read_bytes(), contract.read_bytes())
    output = tmp_path / 'criteria'
    prepared = prepare_criteria(database, contract, output, run_date=DAY)
    manifest = dict(run_date=DAY, source_observation=prepared['source'], files=prepared['files'])
    return database, contract, rows, original, output, prepared, manifest


def test_retained_whole_product_inventory_and_readback_preserve_originals(tmp_path):
    database, contract, rows, original, output, prepared, manifest = build(tmp_path)
    proof = verify_criteria(output, manifest)
    assert proof['coverage'] == {'productsExpected': 3, 'productsObserved': 3, 'complete': True}
    index = json.loads(gzip.decompress((output / prepared['files']['product_criteria_index']['name']).read_bytes()))
    assert set(index['products']) == {row['product_key'] for row in rows}
    shard_key = next(iter(index['products'].values()))
    shard = json.loads(gzip.decompress((output / prepared['files'][shard_key]['name']).read_bytes()))
    facts = [fact for product in decode_products(shard).values() for fact in product['facts']]
    assert {'feature', 'fee', 'eligibility', 'constraint'} <= {fact['kind'] for fact in facts}
    assert index['scope'] == 'product-filter-facets-v1'
    assert not {'rate', 'tier'} & {fact['kind'] for fact in facts}
    assert prepared['publication_authorized'] is False
    assert (database.read_bytes(), contract.read_bytes()) == original


def test_criteria_rejects_another_generation_and_undeclared_or_missing_shards(tmp_path):
    *_, output, prepared, manifest = build(tmp_path)
    wrong = deepcopy(manifest)
    wrong['source_observation']['generation_id'] = 'obs-another'
    with pytest.raises(ValueError, match='source differs'):
        verify_criteria(output, wrong)
    missing = deepcopy(manifest)
    del missing['files'][next(key for key in missing['files'] if '_shard_' in key)]
    with pytest.raises(ValueError, match='inventory differs'):
        verify_criteria(output, missing)


def test_criteria_does_not_accept_tampered_assets_or_an_appended_gzip_member(tmp_path):
    *_, output, prepared, manifest = build(tmp_path)
    entry = prepared['files']['product_criteria_index']
    path = output / entry['name']
    path.write_bytes(path.read_bytes() + gzip.compress(b'{}'))
    with pytest.raises(ValueError, match='bytes differ'):
        verify_criteria(output, manifest)


def test_current_source_hash_mismatch_cannot_seal_optional_package(tmp_path):
    database, contract, _ = source(tmp_path)
    with closing(sqlite3.connect(database)) as db:
        db.execute("UPDATE bank_products SET product_name='source changed'")
        db.commit()
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    output = tmp_path / 'refused'
    with pytest.raises(ValueError, match='database differs'):
        prepare_criteria(database, contract, output, run_date=DAY)
    assert not output.exists()


def test_legacy_financial_detail_assets_stay_identical_without_opt_in():
    from app_payload_details import build_details
    fixture = json.loads((Path(__file__).parent / 'fixtures/greater_bank_fee_details_2026-05-19.json').read_bytes())
    products = [{'product_key': 'greater', 'details_json': json.dumps(fixture['record'])}]
    legacy = build_details(products)['greater']
    richer = build_details(products, include_criteria=True)['greater']
    assert 'facts' not in legacy
    assert richer['facts']
    assert legacy == {key: value for key, value in richer.items() if key != 'facts'}


def test_shared_document_metadata_factors_without_losing_scoped_citations():
    from app_payload_product_criteria import compact_documents
    from cdr_terms.product_documents import describe_product_sources
    captured = json.loads((Path(__file__).parent / 'fixtures/product_facts_real_2026-05-19.json').read_bytes())['products'][0]
    reference = next(item for item in describe_product_sources(captured['record'], 'Up|up-home', 'Up')
                     if item['url'].endswith('.pdf'))
    # Source paths/roles are protocol controls over one retained official link;
    # they assert no lender fee, eligibility or legal applicability.
    first = {**reference, 'sourcePath': '/fees/0/additionalInfoUri', 'relation': 'fees',
             'label': 'Fee reference', 'sourceUrl': reference['url'], 'citations': []}
    second = {**reference, 'sourcePath': '/eligibility/0/additionalInfoUri', 'relation': 'eligibility',
              'label': 'Eligibility reference', 'sourceUrl': reference['url'] + '#page=3', 'citations': []}
    rows = compact_documents([first, second, deepcopy(first)], 'Up|up-home')
    assert len(rows) == 1
    assert 'productKey' not in rows[0] and 'checkedAt' not in rows[0]
    citations = {item['sourcePath']: item for item in rows[0]['citations']}
    assert set(citations) == {first['sourcePath'], second['sourcePath']}
    assert citations[first['sourcePath']]['relation'] == 'fees'
    assert 'sourceUrl' not in citations[first['sourcePath']]  # Exact document URL is implicit.
    assert citations[second['sourcePath']]['sourceUrl'].endswith('#page=3')
    assert {item['label'] for item in citations.values()} == {'Fee reference', 'Eligibility reference'}
    changed = {**second, 'contentSha256': 'f' * 64}
    assert len(compact_documents([first, changed], 'Up|up-home')) == 2


def test_writer_targets_small_shards_and_reports_larger_indivisible_products(tmp_path, monkeypatch):
    import app_payload_product_criteria as criteria
    # A smaller write target exercises splitting using unchanged real products.
    monkeypatch.setattr(criteria, 'WRITE_SHARD_RAW', 1)
    *_, output, prepared, manifest = build(tmp_path)
    assert len(prepared['files']) == 4  # Three whole products plus the index.
    assert prepared['layout']['products_exceeding_target'] == 3
    assert 1 < prepared['layout']['max_shard_decoded_bytes'] <= criteria.SHARD_RAW
    assert prepared['layout']['largest_product_key']
    assert prepared['layout']['index_decoded_bytes'] > 0
    assert verify_criteria(output, manifest)['coverage']['complete']


def test_optional_feature_locator_preserves_legacy_semantics_and_refuses_ambiguity():
    from app_payload_product_criteria import scoped_feature_facts
    from app_payload_feature_facts import feature_facts
    retained = json.loads((Path(__file__).parent / 'fixtures/product_facts_real_2026-05-19.json').read_bytes())['products'][0]
    record = json.loads(detail_json(retained['record']))
    legacy = feature_facts(record, 'Up|retained', record.get('description'))
    located = scoped_feature_facts(record, 'Up|retained')
    assert located and all(item.get('sourcePathBasis') == 'raw-cdr' for item in located)
    assert [{key: value for key, value in item.items() if key not in {'sourcePath', 'sourcePathBasis'}} for item in located] == legacy
    assert {item['sourcePath'] for item in located} == {'/features/0', '/features/1', '/features/2'}
    duplicate = deepcopy(record)
    duplicate['features'].append(deepcopy(duplicate['features'][0]))
    assert all('sourcePath' not in item for item in scoped_feature_facts(duplicate, 'Up|retained')
               if item.get('sourceType') == duplicate['features'][0]['featureType'])
    record.pop('_sourcePaths')
    assert scoped_feature_facts(record, 'Up|retained') == legacy


def test_v1_retained_wire_still_verifies_without_dictionary_tables(tmp_path):
    import hashlib
    *_, output, prepared, manifest = build(tmp_path)
    for key, entry in list(manifest['files'].items()):
        value = json.loads(gzip.decompress((output / entry['name']).read_bytes()))
        if key != 'product_criteria_index':
            value['products'] = decode_products(value)
            value.pop('keyTable'); value.pop('stringTable')
        value['schema_version'] = 1
        blob = gzip.compress(canonical(value), mtime=0)
        sha = hashlib.sha256(blob).hexdigest()
        name = f'product-criteria-legacy-{sha}.json.gz'
        (output / name).write_bytes(blob)
        manifest['files'][key] = {'name': name, 'sha256': sha, 'bytes': len(blob)}
    assert verify_criteria(output, manifest)['coverage']['complete']
