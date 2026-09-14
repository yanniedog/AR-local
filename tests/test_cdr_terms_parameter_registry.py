"""Real source admission plus injected type/unit/trust boundary faults."""
import copy
import json

import pytest

from cdr_terms.identity import byte_digest, digest
from cdr_terms.ingest import registry_context
from cdr_terms.parameter_registry import (canonical_parameter, registry_contract,
                                         validate_parameter_terms, validate_registry_context)
from cdr_terms.revisions import stage_term
from tests.test_cdr_terms_evidence import _staged_term, evidence  # noqa: F401


def test_real_retained_name_survives_new_registry_staging_and_revision(evidence):
    queue, job, output, args = _staged_term(evidence, context_change=registry_context())
    revision = stage_term(evidence[0], **args)
    saved = evidence[0].db.execute('SELECT value_json FROM term_revisions WHERE term_revision_id=?', (revision,)).fetchone()
    assert json.loads(saved[0]) == evidence[-1]['name'] == output['terms'][0]['value']
    assert queue.validate_input(job)['parameter_registry'] == registry_contract()
    assert registry_context()['executable_rules'] == 'unapproved'


@pytest.mark.parametrize('change,match', [
    ({'parameter_key': 'product.invented'}, 'Unknown canonical'),
    ({'parameter_key': 'name'}, 'Unknown canonical'),
    ({'unit': 'AUD'}, 'unit mismatch'),
    ({'value': False}, 'value type'),
    ({'rule_pattern': 'execute_something'}, 'Unreviewed rule'),
])
def test_new_job_rejects_unreviewed_interpretation_without_losing_source(evidence, change, match):
    queue, job, output, _ = _staged_term(evidence, context_change=registry_context(), save=False)
    output['terms'][0].update(change)
    with pytest.raises(ValueError, match=match):
        queue.validate_staging(job, output)
    assert evidence[0].db.execute('SELECT COUNT(*) FROM term_revisions').fetchone()[0] == 0
    assert evidence[0].read_blob(queue.validate_input(job)['source_product_sha256'][evidence[2]]) == evidence[-2]


def test_unmatched_fine_print_can_remain_explicit_unresolved_staging(evidence):
    queue, job, output, _ = _staged_term(evidence, context_change=registry_context(), save=False)
    output['terms'] = []
    output['clauses'][0].update(disposition='unresolved', reason='No reviewed canonical interpretation')
    queue.validate_staging(job, output)
    assert output['clauses'][0]['start'] < output['clauses'][0]['end']


@pytest.mark.parametrize('value,unit,valid', [
    ('0', 'fraction_per_year', True), ('-0.001', 'fraction_per_year', True),
    ('0.0455', 'fraction_per_year', True), ('4.55', 'fraction_per_year', False),
    ('0.0455', 'percent', False), (0, 'fraction_per_year', False),
    (False, 'fraction_per_year', False), ('NaN', 'fraction_per_year', False),
    ('1e-2', 'fraction_per_year', False), (None, 'fraction_per_year', False),
])
def test_fraction_unit_is_explicit_and_zero_is_not_missing(value, unit, valid):
    term = {'parameter_key': 'rate.advertised', 'value': value, 'unit': unit, 'rule_pattern': None}
    if valid:
        validate_parameter_terms(registry_context(), [term])
    else:
        with pytest.raises(ValueError):
            validate_parameter_terms(registry_context(), [term])


def test_boolean_false_is_not_integer_zero_or_unknown():
    term = {'parameter_key': 'product.tailored', 'value': False, 'unit': None, 'rule_pattern': None}
    validate_parameter_terms(registry_context(), [term])
    for value in (0, None, 'false'):
        with pytest.raises(ValueError, match='type'):
            validate_parameter_terms(registry_context(), [{**term, 'value': value}])


def test_context_hash_binds_definitions_and_rejects_rehashed_injected_fields():
    original = registry_context()
    changed = copy.deepcopy(original)
    changed['parameter_registry']['parameters'][0]['unit'] = 'invented'
    assert digest(changed) != digest(original)
    changed['parameter_registry']['sha256'] = digest({key: value for key, value in changed['parameter_registry'].items() if key != 'sha256'})
    with pytest.raises(ValueError, match='registry context'):
        validate_registry_context(changed)
    changed = copy.deepcopy(original)
    changed['parameter_registry']['customer_profile'] = {'private': True}
    with pytest.raises(ValueError, match='registry context'):
        validate_registry_context(changed)
    assert registry_context() == original


def test_exact_cdr_aliases_do_not_guess_narrative_or_ambiguous_amounts():
    assert canonical_parameter('comparisonRate') == 'rate.comparison'
    assert canonical_parameter('rate.comparison') == 'rate.comparison'
    assert canonical_parameter('cheap interest') is None
    assert canonical_parameter('amount') is None
    registry = registry_contract()
    registry['parameters'].clear()
    assert registry_contract()['parameters']


def test_immutable_legacy_context_retains_its_existing_contract(evidence):
    queue, job, output, args = _staged_term(evidence)
    queue.validate_staging(job, output)
    assert stage_term(evidence[0], **args)

@pytest.mark.parametrize('inject_profile', [False, True])
def test_worker_envelope_admits_exact_registry_and_refuses_nested_profile(evidence, tmp_path, inject_profile):
    from cdr_terms.queue import TermsQueue
    from pi_terms_worker import prepare_job
    from tests.test_cdr_terms_evidence import _clause, NOW

    store, _, key, _, _, body, _ = evidence
    extraction, _ = _clause(evidence)
    context = {**registry_context(), 'product_keys': [key],
               'source_product_sha256': {key: byte_digest(body)}}
    if inject_profile:
        context['parameter_registry']['customer_profile'] = {'private': 'must not reach transport'}
    queue = TermsQueue(store)
    job_id = queue.enqueue(extraction, context, now=NOW)
    # Exercise the actual transport preparation boundary, including its queue
    # input validation, without a model call or test-only context whitelist.
    job = dict(store.db.execute('SELECT j.*, x.text_sha256, x.document_version_id '
                               'FROM analysis_jobs j JOIN extractions x USING(extraction_id) '
                               'WHERE job_id=?', (job_id,)).fetchone())
    job['lease_id'] = 'transport-contract-test-only'
    operation = (tmp_path / 'worker-operation').resolve()
    if inject_profile:
        with pytest.raises(ValueError, match='registry context'):
            prepare_job(store, job, operation)
        assert not operation.exists()
    else:
        prepare_job(store, job, operation)
        payload = json.loads((operation / 'input.json').read_bytes())
        assert payload['context'] == context
        assert payload['context']['parameter_registry'] == registry_contract()
        assert payload['source_text'] == store.read_blob(job['text_sha256']).decode('utf-8')
