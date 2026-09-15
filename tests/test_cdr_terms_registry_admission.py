"""Late review regressions: vocabulary scope, new admission and worker failures."""
import copy
import json

import pytest

from cdr_terms.acquisitions_queue import enqueue_interpretation
from cdr_terms.ingest import registry_context
from cdr_terms.parameter_registry import canonical_parameter, registry_contract
from cdr_terms.queue import TermsQueue
from cdr_terms.store import EvidenceStore
from tests.test_cdr_terms_evidence import evidence, _clause, NOW  # noqa: F401
from tests.test_pi_terms_worker import setup, simulate, invoke, latest  # noqa: F401


@pytest.mark.parametrize('alias', [
    'name', 'description', 'brandName', 'productCategory', 'depositRateType',
    'lendingRateType', 'repaymentType', 'loanPurpose', 'feeType', 'feeMethodUType',
    'rateApplicationMethod', 'isTailored', 'rate', 'comparisonRate',
])
def test_bare_source_leaves_do_not_identify_canonical_parameters(alias):
    assert canonical_parameter(alias) is None
    assert all(alias not in row['aliases'] for row in registry_contract()['parameters'])


@pytest.mark.parametrize('entry', ['direct', 'transaction', 'interpretation', 'historical'])
def test_new_jobs_cannot_use_absent_registry(evidence, entry):
    store, observation, key, _, version, _, _ = evidence
    extraction, _ = _clause(evidence)
    queue = TermsQueue(store)
    context = {'product_keys': [key]}
    with pytest.raises(ValueError, match='registry'):
        if entry == 'direct':
            queue.enqueue(extraction, context)
        elif entry == 'transaction':
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                queue.enqueue_in_transaction(extraction, context, priority=1, completion_guard=lambda: None)
        elif entry == 'interpretation':
            enqueue_interpretation(store, version, [observation], priority=1, registry_context={})
        else:
            queue.enqueue_historical(extraction, [observation], registry_context={})
    assert store.db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0] == 0


@pytest.mark.parametrize('change', [
    {'parameter_key': 'product.invented'}, {'unit': 'AUD'}, {'value': False},
    {'rule_pattern': 'unreviewed-calculation'},
])
def test_registry_staging_failure_blocks_once_without_account_cooldown(setup, monkeypatch, change):
    import pi_terms_worker as worker
    with EvidenceStore(setup[0]) as store:
        queue = TermsQueue(store)
        old = queue.claim()
        queue.event(old['job_id'], 'blocked', lease_id=old['lease_id'], error_code='test_setup')
        context = {**registry_context(), 'product_keys': ['protocol-only']}
        job_id = queue.enqueue(old['extraction_id'], context)
        job = store.db.execute('SELECT * FROM analysis_jobs WHERE job_id=?', (job_id,)).fetchone()
        output = copy.deepcopy(setup[4])
        output['context_sha256'] = job['context_sha256']
        output['clauses'] = [{'start': 0, 'end': 1, 'page': None, 'section': None,
                              'disposition': 'parameter', 'reason': 'Fault injection only'}]
        term = {key: None for key in ('unit', 'tier', 'package', 'cohort', 'effective_from', 'effective_to', 'rule_pattern')}
        term.update(parameter_key='product.name', value='Protocol', product_key='protocol-only',
                    clause_indexes=[0], conditions=[], exceptions=[])
        term.update(change)
        output['terms'] = [term]
    active = (*setup[:3], job_id, output, setup[5])
    calls = simulate(monkeypatch, active)
    result = invoke(active)
    assert result['result'] == 'BLOCKED'
    assert result['reason'] == 'invalid_staging_schema'
    assert latest(active)['status'] == 'blocked'
    assert 'retry_after' not in worker.read_state(active[0])
    assert invoke(active)['result'] == 'NO_WORK'
    assert len(calls) == 1
    # Another valid job is not delayed by this deterministic output defect.
    with EvidenceStore(active[0]) as store:
        queue = TermsQueue(store)
        next_id = queue.enqueue(output['extraction_id'], {**registry_context(), 'product_keys': ['another-protocol-scope']})
        next_job = store.db.execute('SELECT * FROM analysis_jobs WHERE job_id=?', (next_id,)).fetchone()
        next_output = {**output, 'context_sha256': next_job['context_sha256'], 'clauses': [], 'terms': []}
    following = (*active[:3], next_id, next_output, active[5])
    next_calls = simulate(monkeypatch, following)
    assert invoke(following)['result'] == 'STAGED'
    assert len(next_calls) == 1

@pytest.mark.parametrize('legacy_version', [None, 'terms-parameters-v1'])
def test_retained_legacy_rows_keep_exact_context_and_original_staging(evidence, legacy_version):
    from cdr_terms.identity import canonical_json, digest

    store, _, key, _, _, _, _ = evidence
    extraction, _ = _clause(evidence)
    context = {'product_keys': [key]}
    if legacy_version:
        context['parameter_registry'] = registry_contract(legacy_version)
        assert context['parameter_registry']['sha256'] == 'ada9acf47ff1436a7562af06df2107ca4aec28110c005f8d856a75312aec668e'
    raw = canonical_json(context).encode('utf-8')
    context_sha = digest(context)
    job_id = digest([extraction, context_sha])
    blob_sha = store.put_blob(raw)
    # Materialize a retained pre-upgrade row directly; public enqueue deliberately
    # cannot manufacture this historical contract after the upgrade.
    with store.db:
        store.db.execute('INSERT INTO analysis_jobs VALUES (?,?,?,?,?,?)',
                         (job_id, extraction, context_sha, blob_sha, 1, NOW))
    before = tuple(store.db.execute('SELECT * FROM analysis_jobs WHERE job_id=?', (job_id,)).fetchone())
    queue = TermsQueue(store)
    assert queue.validate_input(job_id) == context
    output = {'schema_version': 1, 'extraction_id': extraction, 'context_sha256': context_sha,
              'clauses': [], 'terms': [], 'unresolved': ['Retained incomplete interpretation']}
    queue.validate_staging(job_id, output)
    assert tuple(store.db.execute('SELECT * FROM analysis_jobs WHERE job_id=?', (job_id,)).fetchone()) == before
    assert store.read_blob(blob_sha) == raw
    with pytest.raises(ValueError, match='registry'):
        queue.enqueue(extraction, context)


@pytest.mark.parametrize('entry', ['direct', 'transaction', 'interpretation', 'historical'])
def test_new_jobs_cannot_opt_into_retired_registry_v1(evidence, entry):
    store, observation, key, _, version, _, _ = evidence
    extraction, _ = _clause(evidence)
    context = {'product_keys': [key], 'parameter_registry': registry_contract('terms-parameters-v1')}
    queue = TermsQueue(store)
    with pytest.raises(ValueError, match='registry'):
        if entry == 'direct':
            queue.enqueue(extraction, context)
        elif entry == 'transaction':
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                queue.enqueue_in_transaction(extraction, context, priority=1, completion_guard=lambda: None)
        elif entry == 'interpretation':
            enqueue_interpretation(store, version, [observation], priority=1, registry_context=context)
        else:
            queue.enqueue_historical(extraction, [observation], registry_context=context)
    assert store.db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0] == 0
