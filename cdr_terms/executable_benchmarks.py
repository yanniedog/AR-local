"""Typed retained adapter/evaluator results and independently derived expectations."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .executable_contract import _bounded, MAX_TEMPLATE_BYTES
from .identity import byte_digest, canonical_json
from .executable_inputs import validate_instantiated_input
from .executable_code import verify_code_artifact
from .executable_adapter_input import validate_adapter_input

TOTALS = frozenset(('openingBalance', 'externalCashflowNet', 'principalRepaid', 'externalInflows',
                   'externalOutflows', 'interestAccrued', 'interestPosted', 'interestUnposted',
                   'interestRoundingAdjustment', 'feesCharged', 'closingBalance'))
RECEIPT_FIELDS = frozenset(('schemaVersion', 'evaluatorVersion', 'inputSha256', 'contractId',
    'dependencies', 'status', 'completeness', 'issueDetails', 'claimAvailable', 'issues',
    'assumptions', 'eligibility', 'totals', 'ledger'))


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError('Executable benchmark ' + label + ' shape mismatch')


def _json(store, identity):
    body = store.read_blob(identity)
    if len(body) > MAX_TEMPLATE_BYTES:
        raise ValueError('Executable benchmark artifact byte bound exceeded')
    value = json.loads(body)
    _bounded(value, MAX_TEMPLATE_BYTES)
    return value


def _strings(value):
    return isinstance(value, list) and len(value) <= 4096 and all(type(x) is str and len(x) <= 4000 for x in value)


def _amount(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ValueError('Executable benchmark decimal required')
    try:
        if not Decimal(value).is_finite():
            raise ValueError('Executable benchmark nonfinite decimal')
    except InvalidOperation as error:
        raise ValueError('Executable benchmark invalid decimal') from error


def _trace(value, depth=0):
    if (not isinstance(value, dict) or not {'id', 'status', 'evidenceIds'} <= set(value)
            or set(value) - {'id', 'status', 'evidenceIds', 'reason', 'children'}
            or depth > 16 or not isinstance(value['id'], str)
            or value['status'] not in {'meets', 'does_not_meet', 'needs_information'}
            or not _strings(value['evidenceIds'])):
        raise ValueError('Executable benchmark eligibility trace invalid')
    children = value.get('children', [])
    if not isinstance(children, list) or len(children) > 128:
        raise ValueError('Executable benchmark eligibility trace bound exceeded')
    for child in children:
        _trace(child, depth + 1)


def validate_result(result, template, inputs):
    if not isinstance(result, dict) or not RECEIPT_FIELDS <= set(result) or set(result) - RECEIPT_FIELDS - {'localTdConfirmation'}:
        raise ValueError('Executable benchmark evaluator receipt shape mismatch')
    if (result['schemaVersion'] != 1 or result['evaluatorVersion'] != template['evaluatorVersion']
            or result['inputSha256'] != byte_digest(canonical_json(inputs).encode())
            or result['contractId'] != inputs['contract']['id']):
        raise ValueError('Executable benchmark evaluator input identity mismatch')
    if (not all(_strings(result[k]) for k in ('dependencies', 'issues', 'assumptions'))
            or result['issueDetails'] != []):
        raise ValueError('Executable benchmark dependency/issue contract mismatch')
    if result['status'] not in {'complete', 'unsupported'}:
        raise ValueError('Executable benchmark requires complete or refusal control')
    complete = result['status'] == 'complete'
    if complete and template['id'] not in result['dependencies']:
        raise ValueError('Executable benchmark complete receipt lacks template dependency')
    if (result['claimAvailable'] is not complete or result['completeness'] != ('factual_complete' if complete else 'unsupported')
            or (complete and (result['issues'] or result['assumptions']))):
        raise ValueError('Executable benchmark claim status mismatch')
    if not complete:
        if result['totals'] is not None or result['ledger'] != [] or not result['issues']:
            raise ValueError('Executable refusal control has executable totals')
        return
    if not isinstance(result['totals'], dict) or not TOTALS <= set(result['totals']) or set(result['totals']) - TOTALS - {'feesDebitedBalance', 'feesPaidExternal'}:
        raise ValueError('Executable benchmark totals shape mismatch')
    for key, amount in result['totals'].items():
        if key == 'principalRepaid' and amount is None:
            continue
        _amount(amount)
    v8 = template['evaluatorVersion'] == 'product-terms-engine-v8'
    if v8 and 'localTdConfirmation' not in result:
        raise ValueError('Executable v8 benchmark requires confirmed annual rate')
    if 'localTdConfirmation' in result:
        confirmation = result['localTdConfirmation']
        fields = ('source', 'recordedAt', 'principal', 'fundedDate', 'maturityDate', 'noWithholding')
        _object(confirmation, (*fields, 'annualRate') if v8 else fields, 'local confirmation')
        if (confirmation != inputs['scenario'].get('tdConfirmation') or confirmation['source'] != 'user_supplied_bank_confirmation'
                or confirmation['noWithholding'] is not True or confirmation['principal'] != inputs['scenario'].get('openingBalance')):
            raise ValueError('Executable benchmark local confirmation binding mismatch')
        if v8:
            rates = (confirmation['annualRate'], template['annualRate'], inputs['contract'].get('initialAnnualRate'))
            if (any(not isinstance(rate, str) or not re.fullmatch(r'(?:0(?:\.[0-9]{1,12})?|1(?:\.0{1,12})?)', rate) for rate in rates)
                    or len({Decimal(rate) for rate in rates}) != 1):
                raise ValueError('Executable benchmark confirmed annual rate mismatch')
        _amount(confirmation['principal'])
        date.fromisoformat(confirmation['fundedDate'])
        date.fromisoformat(confirmation['maturityDate'])
        if datetime.fromisoformat(confirmation['recordedAt'].replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('Executable benchmark local confirmation timestamp lacks zone')
    eligibility = result['eligibility']
    _object(eligibility, ('status', 'trace', 'reasons'), 'eligibility')
    if eligibility['status'] != 'meets' or eligibility['reasons'] != []:
        raise ValueError('Executable benchmark eligibility not met')
    _trace(eligibility['trace'])
    if not isinstance(result['ledger'], list) or not 1 <= len(result['ledger']) <= 10000:
        raise ValueError('Executable benchmark ledger bound exceeded')
    for entry in result['ledger']:
        required = {'date', 'id', 'type', 'amount', 'balance', 'evidenceIds'}
        if not isinstance(entry, dict) or not required <= set(entry) or set(entry) - required - {'note', 'settlementStatus'}:
            raise ValueError('Executable benchmark ledger entry shape mismatch')
        if entry['type'] not in {'cashflow', 'interest_accrual', 'interest_posting'} or not _strings(entry['evidenceIds']):
            raise ValueError('Executable benchmark TD ledger entry unsupported')
        _amount(entry['amount'])
        _amount(entry['balance'])


def verify_benchmark(store, identity, template, *, legacy_descriptor_replay=False):
    result = _json(store, identity)
    _object(result, ('schemaVersion', 'templateId', 'adapterVersion', 'evaluatorVersion', 'executionActor', 'suiteSha256', 'cases'), 'run')
    if result['schemaVersion'] != 1 or any(result[k] != template[t] for k, t in (
            ('templateId', 'id'), ('adapterVersion', 'adapterVersion'), ('evaluatorVersion', 'evaluatorVersion'))):
        raise ValueError('Executable benchmark binds another template/adapter/evaluator')
    suite = _json(store, result['suiteSha256'])
    _object(suite, ('expectationAuthor', 'expectationKind', 'adapterCodeSha256', 'evaluatorCodeSha256', 'cases'), 'suite')
    if (not result['executionActor'] or not suite['expectationAuthor'] or suite['expectationAuthor'] == result['executionActor']
            or suite['expectationKind'] not in {'human', 'deterministic'}):
        raise ValueError('Executable benchmark expectations require independent derivation')
    for key, role, version in (('adapterCodeSha256', 'adapter', template['adapterVersion']),
                               ('evaluatorCodeSha256', 'evaluator', template['evaluatorVersion'])):
        if legacy_descriptor_replay:
            if not store.read_blob(suite[key]):
                raise ValueError('Executable benchmark code identity is empty')
        else:
            verify_code_artifact(store, suite[key], role, version)
    cases = result['cases']
    if not isinstance(cases, list) or not 2 <= len(cases) <= 256 or len(suite['cases']) != len(cases):
        raise ValueError('Executable benchmark case inventory mismatch')
    seen, statuses = set(), set()
    v8 = template['evaluatorVersion'] == 'product-terms-engine-v8'
    extra = ('adapterInputSha256', 'executionKind') if v8 else ()
    rate_refusal = False
    for case, expected_case in zip(cases, suite['cases']):
        _object(case, ('id', 'inputSha256', 'actualSha256') + extra, 'case')
        _object(expected_case, ('id', 'inputSha256', 'expectationSha256') + extra, 'expected case')
        if not case['id'] or case['id'] in seen or any(case[k] != expected_case[k] for k in ('id', 'inputSha256') + extra):
            raise ValueError('Executable benchmark case identity mismatch')
        seen.add(case['id'])
        inputs = _json(store, case['inputSha256'])
        _object(inputs, ('evaluatorVersion', 'contract', 'scenario'), 'instantiated input')
        if (inputs['evaluatorVersion'] != template['evaluatorVersion'] or inputs['contract'].get('productId') != template['productKey']
                or template['id'] not in inputs['contract'].get('dependencyIds', [])):
            raise ValueError('Executable benchmark instantiated input template mismatch')
        actual = _json(store, case['actualSha256'])
        _object(actual, ('templateId', 'inputSha256', 'adapterVersion', 'evaluatorVersion', 'adapterCodeSha256', 'evaluatorCodeSha256', 'result') + extra, 'actual receipt')
        if (actual['templateId'] != template['id'] or actual['inputSha256'] != case['inputSha256']
                or any(actual[k] != template[k] for k in ('adapterVersion', 'evaluatorVersion'))
                or any(actual[k] != suite[k] for k in ('adapterCodeSha256', 'evaluatorCodeSha256'))
                or any(actual[k] != case[k] for k in extra)):
            raise ValueError('Executable benchmark execution/code binding mismatch')
        expected = _json(store, expected_case['expectationSha256'])
        _object(expected, ('templateId', 'inputSha256', 'derivationSha256', 'result') + extra, 'independent expectation')
        if any(expected[k] != case[k] for k in extra):
            raise ValueError('Executable expected raw adapter input identity mismatch')
        if expected['templateId'] != template['id'] or expected['inputSha256'] != case['inputSha256'] or not store.read_blob(expected['derivationSha256']):
            raise ValueError('Executable benchmark independent derivation missing')
        validate_instantiated_input(template, inputs, complete=actual['result'].get('status') == 'complete')
        validate_result(actual['result'], template, inputs)
        validate_result(expected['result'], template, inputs)
        if actual['result'] != expected['result']:
            raise ValueError('Executable benchmark output differs from independent expectation')
        if v8:
            rate_refusal |= validate_adapter_input(_json(store, case['adapterInputSha256']), inputs, template, actual['result'], case['executionKind'])
        statuses.add(actual['result']['status'])
    if statuses != {'complete', 'unsupported'}:
        raise ValueError('Executable benchmark needs a positive case and refusal control')
    if v8 and not rate_refusal:
        raise ValueError('Executable v8 benchmark requires an opened-rate mismatch refusal control')
