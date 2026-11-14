"""Real captured product bodies plus deliberately invalid provenance controls."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

import pytest

from app_payload_product_evidence import prepare_snapshot
from app_payload_product_evidence_contract import canonical, digest
from app_payload_product_response_sources import ResponseSources, exported_projection, version
from cdr_attempt_evidence_promotion import promote_attempt_evidence
from cdr_clean_export import bank_product_key
from cdr_export_contract import build_contract
from cdr_outputs import ensure_db, insert_rows
from cdr_product_facts import clean_fact_rows
from cdr_raw_attempt_journal import RawAttemptJournal

DAY = '2026-05-19'


def real_source(tmp_path, *, mode='normal'):
    captured = json.loads((Path(__file__).parent / 'fixtures/product_facts_real_2026-05-19.json').read_bytes())
    retained = json.loads((Path(__file__).parent / 'fixtures/publication-accounting-2026-09-22.json').read_bytes())
    providers = {row['provider_dir']: row for row in retained['provider_states']}
    exports = tmp_path / 'exports'; exports.mkdir()
    database = exports / 'local-cdr.sqlite'; run = tmp_path / 'run'
    journal = RawAttemptJournal(run / '_raw-attempt-journals-v1', 'response-test')
    original_bodies = {}; sequence = 0

    def record(body, provider, pid, phase):
        nonlocal sequence
        sequence += 1
        endpoint = providers[provider]['endpoint_url'].rstrip('/')
        url = endpoint if phase == 'products_index' else endpoint + '/' + quote(pid, safe='')
        journal.record(str(sequence), request_url=url, request_headers={'x-v': '1000'},
                       started_at=DAY + 'T00:00:00Z', completed_at=DAY + 'T00:00:01Z',
                       status=200, outcome='success', body=body, response_headers={'x-v': '1000'},
                       context=dict(provider=provider, product_id=pid, phase=phase,
                                    cdr_version=None if mode == 'header-version-only' else 1000))

    with closing(sqlite3.connect(database)) as connection:
        ensure_db(connection)
        for number, product in enumerate(captured['products']):
            raw = deepcopy(product['record']); pid = raw['productId']; provider = product['provider']
            if number == 0 and mode in {'true-one', 'false-zero', 'two-true-one', 'two-false-zero'}:
                raw['futureControl'] = {'nested': 1 if mode.endswith('one') else 0}
            base = dict(dataset=product['dataset'], provider=provider, product_id=pid,
                        product_name=raw.get('name') or 'Captured product', category=raw.get('productCategory', ''))
            base['product_key'] = bank_product_key(base)
            insert_rows(connection, 'bank_product_facts', [dict(run_date=DAY, **row) for row in clean_fact_rows(raw, base)])
            insert_rows(connection, 'bank_products', [dict(run_date=DAY, **base, source_file='retained-real-fixture',
                        last_updated='', details_json=json.dumps(exported_projection({'data': raw}), ensure_ascii=False))])
            record(canonical({'data': {'products': [raw]}}), provider, pid, 'products_index')
            body = b'{ "data" : ' + json.dumps(raw, ensure_ascii=False).encode('utf-8') + b' }\n'
            original_bodies[base['product_key']] = body
            if number == 0 and mode == 'index_only': continue
            if number == 0 and mode == 'wrong_id':
                wrong = deepcopy(raw); wrong['productId'] = 'deliberately-wrong-identity'
                body = canonical({'data': wrong})
            if number == 0 and mode in {'true-one', 'false-zero'}:
                wrong = deepcopy(raw); wrong['futureControl']['nested'] = mode == 'true-one'
                body = canonical({'data': wrong})
            record(body, provider, pid, 'product_detail')
            if number == 0 and mode == 'ambiguous':
                # A null ignored by the legacy export distinguishes original bytes.
                alternate = deepcopy(raw); alternate['futureNull'] = None
                record(canonical({'data': alternate}), provider, pid, 'product_detail')
            if number == 0 and mode == 'retry': record(body, provider, pid, 'product_detail')
            if number == 0 and mode in {'two-true-one', 'two-false-zero'}:
                other = deepcopy(raw); other['futureControl']['nested'] = mode == 'two-true-one'
                record(canonical({'data': other}), provider, pid, 'product_detail')
        connection.commit(); connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    status = {'raw_attempt_journal': dict(journal.summary(), path='_raw-attempt-journals-v1/response-test',
                                         path_resolution='relative_to_ingest_run_root')}
    (run / 'banks').mkdir(); (run / 'banks/ingest-status.json').write_bytes(canonical(status))
    promote_attempt_evidence(run, exports)
    artifacts = [dict(path=p.relative_to(exports).as_posix(), bytes=p.stat().st_size, sha256=digest(p.read_bytes()))
                 for p in exports.rglob('*') if p.is_file()]
    contract = build_contract(exports, observation_date=DAY, observed_at=DAY + 'T01:00:00+11:00',
        observation_state='partial', source_path=f'runs/{DAY}/_exports', completion_marker_path=f'{DAY}.done.json',
        coverage=retained['coverage'], provider_states=retained['provider_states'], register_hashes=retained['register_hashes'],
        normalization_version='future-projection-v2' if mode == 'unknown-projection' else 'legacy-v1', artifacts=artifacts)
    contract_path = tmp_path / 'state/contract.json'; contract_path.parent.mkdir(); contract_path.write_bytes(canonical(contract))
    snapshot_root = tmp_path / 'snapshot'; snapshot = prepare_snapshot(database, contract_path, snapshot_root)
    binding = dict(source=snapshot['source'], snapshot_sha256=digest((snapshot_root / 'snapshot.json').read_bytes()),
                   core_sha256='a'*64, details_sha256='b'*64, scope=snapshot['scope'])
    return snapshot_root, exports, contract_path, binding, original_bodies


def reader(values, **kwargs):
    snapshot, exports, contract, binding, _ = values
    return ResponseSources(snapshot, exports, contract, expected_binding=binding, **kwargs)


def test_exact_original_body_reconciles_all_real_products_without_lock_or_source_writes(tmp_path, monkeypatch):
    values = real_source(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    from cdr_file_lock import FileLock
    def forbidden(_): raise AssertionError('read-only source must never acquire writable FileLock')
    monkeypatch.setattr(FileLock, '__enter__', forbidden)
    source = reader(values); products = list(source.products())
    assert len(products) == 3
    for product in products:
        if product['identity']['provider'] == 'Bank Australia':
            # This retained technical fixture has no classifying source category.
            assert product['state'] == 'projection_unverified' and product['reasons'] == ['dataset_unverified']
        else: assert product['state'] == 'matched'
        assert source.body(product['details'][0]['sha256']) == values[-1][product['identity']['product_key']]
        assert product['details'][0]['events'][0]['request_version'] == 1000
        assert 'headers' not in json.dumps(product) and 'request_url' not in json.dumps(product)
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize('mode,state', [('index_only', 'index_only'), ('wrong_id', 'index_only'), ('ambiguous', 'ambiguous')])
def test_never_confuses_index_invalid_or_ambiguous_body_with_current_detail(tmp_path, mode, state):
    products = list(reader(real_source(tmp_path, mode=mode)).products())
    changed = next(p for p in products if p['identity']['provider'] == 'Up')
    assert changed['state'] == state and changed['current_body_sha256'] is None
    if mode == 'ambiguous': assert len(changed['details']) == 2
    if mode == 'wrong_id': assert changed['reasons'] == ['response_invalid']


def test_identical_retries_preserve_events_without_ambiguous_body(tmp_path):
    products = list(reader(real_source(tmp_path, mode='retry')).products())
    product = next(p for p in products if p['identity']['provider'] == 'Up')
    assert product['state'] == 'matched' and len(product['details']) == 1
    assert len(product['details'][0]['events']) == 2


@pytest.mark.parametrize('mode', ['true-one', 'false-zero', 'two-true-one', 'two-false-zero'])
def test_projection_matching_never_conflates_json_boolean_and_number(tmp_path, mode):
    products = list(reader(real_source(tmp_path, mode=mode)).products())
    product = next(p for p in products if p['identity']['provider'] == 'Up')
    if mode.startswith('two-'):
        assert product['state'] == 'matched' and len(product['details']) == 2
        assert sum(v['matches_export'] for v in product['details']) == 1
    else:
        assert product['state'] == 'projection_unverified' and product['current_body_sha256'] is None
        assert not product['details'][0]['matches_export']


def test_explicit_withhold_retains_source_without_redacting_original(tmp_path):
    values = real_source(tmp_path); key = next(iter(values[-1])); raw = values[-1][key]
    products = list(reader(values, withheld=[digest(raw)]).products())
    product = next(p for p in products if p['identity']['product_key'] == key)
    assert product['state'] == 'index_only' and product['reasons'] == ['body_withheld_unresolved']
    assert any(p.read_bytes() == raw for p in values[1].rglob('*.body'))


def test_unknown_projection_retains_bodies_without_current_match_claim(tmp_path):
    products = list(reader(real_source(tmp_path, mode='unknown-projection')).products())
    assert all(p['state'] == 'projection_unverified' and p['projection'] == 'unsupported'
               and p['current_body_sha256'] is None and p['details'] for p in products)


def test_missing_context_version_can_use_verified_request_version(tmp_path):
    products = list(reader(real_source(tmp_path, mode='header-version-only')).products())
    assert all(p['details'] and p['details'][0]['events'][0]['request_version'] == 1000 for p in products)


def test_unbound_journal_append_after_initial_proof_is_not_ignored(tmp_path):
    source = reader(real_source(tmp_path))
    (source.proof.exports/source.proof.base/'late-unbound.body').write_bytes(b'new uncommitted response')
    with pytest.raises(ValueError, match='inventory changed'): source.recheck()


@pytest.mark.parametrize('fault', ['body', 'event', 'key', 'head', 'manifest', 'extra', 'missing'])
def test_whole_journal_is_required_even_for_one_body(tmp_path, fault):
    values = real_source(tmp_path); exports = values[1]
    journal = next((exports / 'attempt-evidence/raw-attempt-journals-v1').iterdir())
    targets = {'body': next((journal/'bodies').glob('*.body')), 'event': next((journal/'events').glob('*.json')),
               'key': next((journal/'keys').glob('*.json')), 'head': journal/'current.json',
               'manifest': journal/'promotion-manifest.json'}
    if fault == 'extra': (journal/'unbound').write_bytes(b'unbound')
    elif fault == 'missing': next((journal/'keys').glob('*.json')).unlink()
    else: targets[fault].write_bytes(b'corrupt')
    with pytest.raises((ValueError, OSError)): reader(values)


@pytest.mark.parametrize('raw,expected', [(1000,1000), ('2147483647',2147483647), (2147483648,None),
                                         (True,None), ('0',None), ('1e3',None), (None,None)])
def test_positive_safe_version_metadata_is_not_frozen_to_known_cdr_versions(raw, expected):
    assert version(raw) == expected
