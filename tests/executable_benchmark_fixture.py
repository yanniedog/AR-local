"""Typed fixture controls for approval storage, not an executed product benchmark."""
from cdr_terms.executable_benchmarks import TOTALS
from cdr_terms.identity import byte_digest, canonical_json


def benchmark_control(store, template):
    put = lambda value: store.put_blob(canonical_json(value).encode())
    codes = {'adapterCodeSha256': store.put_blob(b'protocol adapter identity only'),
             'evaluatorCodeSha256': store.put_blob(b'protocol evaluator identity only')}
    cases, suite_cases = [], []
    for status in ('complete', 'unsupported'):
        inputs = {'evaluatorVersion': template['evaluatorVersion'],
            'contract': {'id': template['id'], 'productId': template['productKey'], 'dependencyIds': [template['id']]},
            'scenario': {'protocolControl': status}}
        input_sha = put(inputs)
        complete = status == 'complete'
        receipt = {'schemaVersion': 1, 'evaluatorVersion': template['evaluatorVersion'], 'inputSha256': input_sha,
            'contractId': template['id'], 'dependencies': [template['id']], 'status': status,
            'completeness': 'factual_complete' if complete else 'unsupported', 'issueDetails': [],
            'claimAvailable': complete, 'issues': [] if complete else ['protocol-refusal'], 'assumptions': [],
            'eligibility': {'status': 'meets', 'reasons': [], 'trace': {'id': 'protocol', 'status': 'meets', 'evidenceIds': []}} if complete else None,
            'totals': {key: None if key == 'principalRepaid' else '0.00' for key in TOTALS} if complete else None,
            'ledger': [{'date': '2026-01-01', 'id': 'protocol', 'type': 'interest_posting', 'amount': '0.00', 'balance': '0.00', 'evidenceIds': []}] if complete else []}
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
