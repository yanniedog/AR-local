"""Typed fixture controls for approval storage, not an executed product benchmark."""
from cdr_terms.executable_benchmarks import TOTALS
from cdr_terms.identity import byte_digest, canonical_json
from cdr_terms.executable_inputs import material_contract
from tests.executable_code_fixture import retained_code_artifacts
from datetime import date, timedelta


def benchmark_control(store, template):
    put = lambda value: store.put_blob(canonical_json(value).encode())
    codes = retained_code_artifacts(store, template)
    cases, suite_cases = [], []
    for status in ('complete', 'unsupported'):
        funded = template['effectiveFrom']
        maturity = (date.fromisoformat(funded) + timedelta(days=template['term']['count'])).isoformat()
        contract = material_contract(template, '1000.00', funded, maturity)
        contract['dependencyIds'] = [template['id'], template['sourceObservationId'], template['sourceSha256'],
                                     *template['documentVersionIds'], *template['termRevisionIds']]
        contract['review'] = {**{key: 'verified' for key in ('applicability', 'materialTerms', 'feeCoverage', 'rateSchedule')},
                              'benchmarkSha256': 'b' * 64}
        inputs = {'evaluatorVersion': template['evaluatorVersion'],
            'contract': contract,
            'scenario': {'accountId': 'td_' + template['id'], 'productId': template['productKey'],
                'cohortKey': template['cohortKey'], 'startDate': funded, 'endDateExclusive': contract['applicability']['toExclusive'],
                'initialOffset': '0', 'events': [], 'assumptions': [], 'facts': {}}}
        for definition in template['inputDefinitions']:
            binding = definition['binding']
            if binding == 'deposit_principal':
                inputs['scenario']['facts'][definition['key']] = {'type': 'decimal', 'value': '1000.00', 'unit': 'AUD'}
            elif binding in {'funded_date', 'maturity_date'}:
                inputs['scenario']['facts'][definition['key']] = {'type': 'date', 'value': funded if binding == 'funded_date' else maturity}
        if template['evaluatorVersion'] == 'product-terms-engine-v8':
            inputs['contract']['initialAnnualRate'] = template['annualRate']
            inputs['scenario'].update(openingBalance='1000.00', tdConfirmation={
                'source': 'user_supplied_bank_confirmation', 'recordedAt': '2026-01-01T00:00:00Z',
                'principal': '1000.00', 'fundedDate': funded, 'maturityDate': maturity,
                'noWithholding': True, 'annualRate': template['annualRate']})
        input_sha = put(inputs)
        complete = status == 'complete'
        receipt = {'schemaVersion': 1, 'evaluatorVersion': template['evaluatorVersion'], 'inputSha256': input_sha,
            'contractId': template['id'], 'dependencies': [template['id']], 'status': status,
            'completeness': 'factual_complete' if complete else 'unsupported', 'issueDetails': [],
            'claimAvailable': complete, 'issues': [] if complete else ['protocol-refusal'], 'assumptions': [],
            'eligibility': {'status': 'meets', 'reasons': [], 'trace': {'id': 'protocol', 'status': 'meets', 'evidenceIds': []}} if complete else None,
            'totals': {key: None if key == 'principalRepaid' else '0.00' for key in TOTALS} if complete else None,
            'ledger': [{'date': '2026-01-01', 'id': 'protocol', 'type': 'interest_posting', 'amount': '0.00', 'balance': '0.00', 'evidenceIds': []}] if complete else []}
        if complete and template['evaluatorVersion'] == 'product-terms-engine-v8':
            receipt['localTdConfirmation'] = inputs['scenario']['tdConfirmation']
        actual = {'templateId': template['id'], 'inputSha256': input_sha, 'adapterVersion': template['adapterVersion'],
                  'evaluatorVersion': template['evaluatorVersion'], **codes, 'result': receipt}
        expected = {'templateId': template['id'], 'inputSha256': input_sha,
                    'derivationSha256': store.put_blob(b'Protocol fixture expected state, not banking acceptance'), 'result': receipt}
        cases.append({'id': status, 'inputSha256': input_sha, 'actualSha256': put(actual)})
        suite_cases.append({'id': status, 'inputSha256': input_sha, 'expectationSha256': put(expected)})
    suite = {'expectationAuthor': 'protocol-expectation-author', 'expectationKind': 'human', **codes, 'cases': suite_cases}
    return {'schemaVersion': 1, 'templateId': template['id'], 'adapterVersion': template['adapterVersion'],
        'evaluatorVersion': template['evaluatorVersion'], 'executionActor': 'protocol-execution-capture',
        'suiteSha256': put(suite), 'cases': cases}
