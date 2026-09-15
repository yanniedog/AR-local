"""Technical report controls using retained source bytes, never bank acceptance."""
import gzip
import json

import pytest

from cdr_product_report import generate, read_bundle
from cdr_report_terms import export_evidence, admit_evidence, bundle_binding, encoded, sha
from cdr_terms.identity import canonical_json, digest
from cdr_terms.observation_checks import bind_manual_check
from tests.test_cdr_terms_evidence import NOW, LATER, FIXTURE, OBSERVED


@pytest.fixture
def evidence(tmp_path):
    from cdr_terms.store import EvidenceStore
    from tests.cdr_terms_source_fixture import source_generation
    body = FIXTURE.read_bytes()
    source = json.loads(body)
    record = source['data']
    _, state, finalized = source_generation(tmp_path, '2026-09-07', OBSERVED, body)
    with EvidenceStore(tmp_path / 'evidence') as store:
        store.report_contract = (state / finalized['export_contract_path']).read_bytes()
        key = 'Bank of Melbourne|' + record['productId']
        observation = store.observe(provider=record['brand'], product_key=key, record=source,
                                    source_bytes=body, observed_at=OBSERVED, ingest_id=finalized['generation_id'])
        document = store.db.execute('SELECT document_id FROM documents WHERE source_url=?', (source['links']['self'],)).fetchone()[0]
        yield store, observation, key, document, store.last_success(document)['document_version_id'], body, record


def bundle(tmp_path, evidence):
    store, observation, key, _, _, body, _ = evidence
    contract = json.loads(store.report_contract)
    receipt = {'schema_version': 1, 'status': 'CAPTURED_AND_QUEUED', 'products': 1,
               'generation_id': contract['generation_id'], 'source_run_date': '2026-09-07',
               'source_provenance': {'basis': 'finalized_source_generation', 'contract_sha256': store.put_blob(store.report_contract), 'contract_digest': contract['contract_digest']},
               'export_contract_digest': contract['contract_digest'], 'sources': [
                   {'product_key': key, 'observation_id': observation, 'sha256': sha(body)}]}
    blob = store.put_blob(canonical_json(receipt).encode())
    with store.db:
        store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,?)',
                         (receipt['generation_id'], blob, NOW, 1))
    root = tmp_path / 'bundle'
    root.mkdir()
    manifest = {'run_date': '2026-09-07', 'counts': {}, 'source_observation': {
        'generation_id': receipt['generation_id'], 'contract_digest': contract['contract_digest']}, 'files': {}}
    for kind, payload in {'core': {'run_date': '2026-09-07', 'sections': {}},
                          'details': {'run_date': '2026-09-07', 'products': {key: {'fees': []}}}}.items():
        raw = gzip.compress(encoded(payload))
        name = kind + '.json.gz'
        (root / name).write_bytes(raw)
        manifest['files'][kind] = {'name': name, 'bytes': len(raw), 'sha256': sha(raw), 'url': 'https://example.test/' + name}
    (root / 'manifest.json').write_bytes(encoded(manifest))
    return root


def reseal(root, mutate):
    value = json.loads((root / 'evidence.json').read_bytes())
    mutate(value)
    raw = encoded(value)
    (root / 'evidence.json').write_bytes(raw)
    seal = json.loads((root / 'seal.json').read_bytes())
    seal.update(bytes=len(raw), sha256=sha(raw))
    (root / 'seal.json').write_bytes(encoded(seal))


def test_absent_attachment_preserves_original_report(tmp_path, evidence, monkeypatch):
    from datetime import datetime, timezone
    import cdr_product_report as report
    class Clock:
        @staticmethod
        def now(_):
            return datetime(2026, 9, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(report, 'datetime', Clock)
    source = bundle(tmp_path, evidence)
    before, after = tmp_path / 'before', tmp_path / 'after'
    report._generate(source, before)
    generate(source, after, terms_evidence=None)
    assert {p.name: p.read_bytes() for p in before.iterdir()} == {p.name: p.read_bytes() for p in after.iterdir()}
    assert json.loads((after / 'audit-evidence.json').read_bytes())['products'][0]['document_capture'] == 'not_reported'


def test_selected_inventory_consistent_json_csv_html_without_source_writes(tmp_path, evidence):
    store, _, key, *_ = evidence
    source = bundle(tmp_path, evidence)
    output = tmp_path / 'sealed'
    before = (store.root / 'evidence.sqlite3').read_bytes()
    export_evidence(source, store.root, output)
    assert (store.root / 'evidence.sqlite3').read_bytes() == before
    report = generate(source, tmp_path / 'report', terms_evidence=output)
    data = json.loads((tmp_path / 'report' / 'product-data.json').read_bytes())
    proof = data[0]['terms_evidence']
    assert proof['observation_id'] == evidence[1]
    assert proof['evidence_class'] == 'unclassified' and proof['bank_approved'] is None
    assert proof['stages']['complete_document_inventory']['expected'] is None
    assert report['export_row_counts']['terms-evidence.csv'] == 1
    import csv
    with (tmp_path / 'report' / 'terms-evidence.csv').open(encoding='utf-8-sig', newline='') as stream:
        row = next(csv.DictReader(stream))
    assert row['product_key'] == key and json.loads(row['evidence_json']) == proof
    html = (tmp_path / 'report' / 'report.html').read_text(encoding='utf8')
    embedded = json.loads(html.split('id="data">')[1].split('</script>')[0])
    assert embedded['products'][0]['terms_evidence'] == proof


def test_exact_historical_observation_is_not_replaced_by_new_current(tmp_path, evidence):
    store, observation, key, _, _, body, record = evidence
    source = bundle(tmp_path, evidence)
    newer = store.observe(provider=record['brand'], product_key=key, record=json.loads(body),
                          source_bytes=body, observed_at=NOW, ingest_id='newer')
    with store.db:
        store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,?)', ('newer', sha(body), NOW, 1))
    export_evidence(source, store.root, tmp_path / 'sealed')
    row = json.loads((tmp_path / 'sealed' / 'evidence.json').read_bytes())['products'][key]
    assert row['observation_id'] == observation != newer
    assert row['matches_current_observation'] is False


def test_failed_latest_capture_keeps_prior_success_separate(tmp_path, evidence):
    store, observation, key, document, *_ = evidence
    source = bundle(tmp_path, evidence)
    check = digest(['failure'])
    store.record_check(document_id=document, check_id=check, checked_at=LATER, status='failed',
                       error_code='technical_failure')
    bind_manual_check(store, observation, check)
    export_evidence(source, store.root, tmp_path / 'sealed')
    row = json.loads((tmp_path / 'sealed' / 'evidence.json').read_bytes())['products'][key]
    doc = next(d for d in row['documents'] if d['document_id'] == document)
    assert doc['latest_status'] == 'failed' and doc['retained_version'] is not None
    assert row['graph']['completeness'] == 'unknown'


@pytest.mark.parametrize('field', ['manifest_sha256', 'core_sha256', 'details_sha256', 'source_generation_id'])
def test_mismatched_attachment_never_creates_report(tmp_path, evidence, field):
    source = bundle(tmp_path, evidence)
    sealed = tmp_path / 'sealed'
    export_evidence(source, evidence[0].root, sealed)
    reseal(sealed, lambda v: v['binding'].update({field: 'wrong'}))
    with pytest.raises(ValueError, match='identity'):
        generate(source, tmp_path / 'report', terms_evidence=sealed)
    assert not (tmp_path / 'report').exists()


def test_technical_can_only_downgrade_and_bank_promotion_refuses(tmp_path, evidence):
    source = bundle(tmp_path, evidence)
    sealed = tmp_path / 'sealed'
    export_evidence(source, evidence[0].root, sealed, technical=True)
    row = json.loads((sealed / 'evidence.json').read_bytes())['products'][evidence[2]]
    assert row['evidence_class'] == 'technical_fixture' and row['bank_approved'] is None
    reseal(sealed, lambda v: v['products'][evidence[2]].update(evidence_class='bank_source_verified'))
    with pytest.raises(ValueError, match='bank acceptance'):
        generate(source, tmp_path / 'report', terms_evidence=sealed)


def test_corrupt_or_oversized_late_attachment_leaves_no_partial_report(tmp_path, evidence, monkeypatch):
    import cdr_report_terms as terms
    source = bundle(tmp_path, evidence)
    sealed = tmp_path / 'sealed'
    export_evidence(source, evidence[0].root, sealed)
    monkeypatch.setattr(terms, 'MAX_BYTES', 20)
    with pytest.raises(ValueError):
        generate(source, tmp_path / 'report', terms_evidence=sealed)
    assert not (tmp_path / 'report').exists()

    monkeypatch.setattr(terms, 'MAX_BYTES', 24 * 1024 * 1024)
    (sealed / 'evidence.json').write_bytes(b'{}')
    with pytest.raises(ValueError):
        generate(source, tmp_path / 'report', terms_evidence=sealed)
    assert not (tmp_path / 'report').exists()


@pytest.mark.parametrize('mutation', ['nested_bank', 'stage_denominator', 'extra_private_field'])
def test_resealed_nested_contract_tampering_refuses(tmp_path, evidence, mutation):
    source = bundle(tmp_path, evidence)
    sealed = tmp_path / 'sealed'
    export_evidence(source, evidence[0].root, sealed)
    def mutate(value):
        row = value['products'][evidence[2]]
        if mutation == 'nested_bank':
            row['delivered'] = [dict(capability='savings_calculation', asset_sha256='a'*64,
                subject_ids=['x'], status='delivered_as_of_selected_edition', bank_acceptance='verified')]
        elif mutation == 'stage_denominator':
            row['stages']['complete_document_inventory']['expected'] = 0
        else:
            row['document_references'][0]['source_path'] = 'C:/private/source.json'
    reseal(sealed, mutate)
    with pytest.raises(ValueError, match='contract'):
        generate(source, tmp_path / 'report', terms_evidence=sealed)
    assert not (tmp_path / 'report').exists()


def test_store_shared_budget_and_corrupt_retained_blob_fail_atomically(tmp_path, evidence, monkeypatch):
    import cdr_report_terms_store as module
    source = bundle(tmp_path, evidence)
    monkeypatch.setattr(module, 'MAX_ROW_BYTES', 5)
    with pytest.raises(ValueError, match='budget'):
        export_evidence(source, evidence[0].root, tmp_path / 'tiny')
    assert not (tmp_path / 'tiny').exists()
    monkeypatch.setattr(module, 'MAX_ROW_BYTES', 24 * 1024 * 1024)
    identity = sha(evidence[5])
    (evidence[0].root / 'blobs' / identity[:2] / identity).write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='identity'):
        export_evidence(source, evidence[0].root, tmp_path / 'corrupt')
    assert not (tmp_path / 'corrupt').exists()
