"""Fabricated protocol controls only; no banking acceptance or product approval."""
import copy
import gzip
import json
from pathlib import Path

import pytest

from cdr_terms.executable_contract import REVIEW_CHECKS
from cdr_terms.executable_reviews import source_snapshot, stage_template
from cdr_terms.identity import byte_digest, canonical_json, digest
from cdr_terms.revisions import REVIEW_CHECKS as TERM_CHECKS, review_term, stage_term
from cdr_terms.store import EvidenceStore
from tests.test_cdr_terms_evidence import _staged_term
from tests.cdr_terms_source_fixture import source_generation

NOW = '2026-01-01T01:00:00Z'
VECTOR = Path(__file__).parent / 'fixtures/executable-templates/canonical-identity-v1.json'


def reidentify(value):
    value['id'] = digest({k: v for k, v in value.items() if k != 'id'})
    return value


@pytest.fixture
def protocol(tmp_path):
    template = copy.deepcopy(json.loads(VECTOR.read_bytes())['template'])
    quote = 'Protocol contract control'
    raw = canonical_json({'data': {'name': quote, 'brand': 'Protocol only', 'productId': 'protocol'},
                          'links': {'self': 'https://example.invalid/protocol'}}).encode()
    record = json.loads(raw)
    _, state, finalized = source_generation(tmp_path, template['runDate'], NOW, raw)
    contract_body = (state / finalized['export_contract_path']).read_bytes()
    template['sourceGenerationId'] = finalized['generation_id']
    with EvidenceStore(tmp_path / 'protocol-only-store') as store:
        key = template['productKey']
        observation = store.observe(provider='Protocol only', product_key=key, record=record,
                                    source_bytes=raw, observed_at=NOW, ingest_id=template['sourceGenerationId'])
        version = store.db.execute('SELECT document_version_id FROM document_versions').fetchone()[0]
        doc = store.db.execute('SELECT document_id FROM document_versions').fetchone()[0]
        fixture = (store, observation, key, doc, version, raw, record['data'])
        def scope(output):
            output['terms'][0].update(cohort=template['cohortKey'], tier=template['tierKey'],
                package=template['packageKey'], effective_from=template['effectiveFrom'], effective_to=template['effectiveToExclusive'])
        _, _, _, args = _staged_term(fixture, output_change=scope)
        args['applicability'].update(cohort=template['cohortKey'], tier=template['tierKey'],
            package=template['packageKey'], effective_from=template['effectiveFrom'], effective_to=template['effectiveToExclusive'])
        term = stage_term(store, **args)
        proof = store.put_blob(canonical_json({'term_revision_id': term, 'passed': True, 'checks': sorted(TERM_CHECKS)}).encode())
        review_term(store, term, status='validated', reviewer='protocol-independent', reviewer_kind='human',
                    reviewed_at=NOW, evidence_sha256=proof, reason='Protocol state transition, not business approval')
        clause = store.db.execute('SELECT * FROM clauses').fetchone()
        clause_id = clause['clause_id']
        template.update(sourceObservationId=observation, sourceSha256=byte_digest(raw),
                        documentVersionIds=[version], termRevisionIds=[term])
        template['evidence'] = [{'id': clause_id, 'clauseId': clause_id, 'documentVersionId': version,
            'documentSha256': byte_digest(raw), 'sourceUrl': 'https://example.invalid/protocol',
            'locator': canonical_json(json.loads(clause['locator_json'])), 'quote': clause['text'],
            'quoteSha256': byte_digest(clause['text'].encode())}]
        for field in template['fieldClauseIds']:
            template['fieldClauseIds'][field] = [clause_id]
        for definition in template['inputDefinitions']:
            definition['clauseIds'] = [clause_id]
        template['eligibility']['evidenceIds'] = [clause_id]
        row = {'product_key': key, 'rate_index': 1, 'rate': '0.05', 'rate_type': 'FIXED', 'term': 'P100D'}
        core = {'run_date': template['runDate'], 'sections': {'TD': {'rates': [row]}}}
        from app_payload_build import _gzip_bytes
        core_sha = store.put_blob(_gzip_bytes(core))
        source = {'generation_id': template['sourceGenerationId'], 'contract_digest': finalized['export_contract_digest']}
        capture = {'schema_version': 1, 'status': 'CAPTURED_AND_QUEUED', 'products': 1,
            'generation_id': template['sourceGenerationId'], 'source_run_date': template['runDate'],
            'export_contract_digest': finalized['export_contract_digest'],
            'source_provenance': {'basis': 'finalized_source_generation', 'contract_sha256': store.put_blob(contract_body),
                                  'contract_digest': finalized['export_contract_digest']},
            'sources': [{'observation_id': observation, 'product_key': key, 'sha256': byte_digest(raw)}]}
        capture_sha = store.put_blob(canonical_json(capture).encode())
        with store.db:
            store.db.execute('INSERT INTO ingest_captures VALUES (?,?,?,?)', (source['generation_id'], capture_sha, NOW, 1))
        manifest = {'run_date': template['runDate'], 'source_observation': source,
                    'files': {'core': {'sha256': core_sha, 'bytes': len(store.read_blob(core_sha))}}}
        template['selectedRate'].update(coreAssetSha256=core_sha, sourceManifestSha256=store.put_blob(canonical_json(manifest).encode()), rowSha256=digest(row))
        reidentify(template)
        yield store, template, core, source


def stage_and_proof(store, template):
    stage_template(store, template, interpreter='protocol-author', staged_at=NOW)
    from tests.executable_benchmark_fixture import benchmark_control
    benchmark = benchmark_control(store, template)
    proof = {'schemaVersion': 1, 'templateId': template['id'], 'adapterVersion': template['adapterVersion'],
        'evaluatorVersion': template['evaluatorVersion'], 'sourceSnapshotSha256': source_snapshot(store, template),
        'benchmarkResultSha256': store.put_blob(canonical_json(benchmark).encode()), 'checks': sorted(REVIEW_CHECKS), 'passed': True}
    return proof
