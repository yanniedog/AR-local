"""Actual app technical capture plus independently recomputed expectations. No bank approval."""
import json
from pathlib import Path
import pytest
from cdr_terms.store import EvidenceStore
from cdr_terms.identity import canonical_json,digest
from cdr_terms.executable_v3_financial import financial_expectation

ROOT=Path(__file__).parent/'fixtures/monetary-v3'


@pytest.fixture
def actual_savings_bridge(tmp_path):
    bridge=json.loads((ROOT/'actual-bridge.json').read_bytes());codes=json.loads((ROOT/'code-identities.json').read_bytes())
    with EvidenceStore(tmp_path/'actual-savings-technical') as store:
        for path in (ROOT/'blobs').iterdir():assert store.put_blob(path.read_bytes())==path.name
        subject,run,put=retain_benchmark(store,bridge,codes)
        yield store,subject,run,put,bridge


def retain_benchmark(store,bridge,codes):
    def put(value):return store.put_blob(canonical_json(value).encode('utf8'))
    subject=bridge['selection']['subject']
    context=put(dict(manifest=bridge['context']['manifest'],index=bridge['index'],shard=bridge['shard'],selection=bridge['selection']))
    cases=[];expectations=[]
    for record in bridge['records']:
        raw=record['rawInput'];raw_sha=put(raw)
        assert digest(raw)==record['rawInputSha256']
        outcome={'result':record['result']} if 'result' in record else {k:record[k] for k in ('refusal','resultReturned')}
        expected=financial_expectation(subject,raw['inputs']) if 'result' in record else dict(kind='technical_refusal',reason=record['refusal'])
        common=dict(subjectId=subject['id'],inputSha256=raw_sha,contextSha256=context,executionKind='actual_adapter')
        actual=put(dict(common,adapterCodeSha256=codes['adapter'],evaluatorCodeSha256=codes['evaluator'],outcome=outcome))
        derivation=put(dict(schemaVersion=1,method='independent_fraction_oracle_v1',policySha256=digest(subject['policy']),inputSha256=raw_sha,expected=expected))
        expectation=put(dict(common,derivationSha256=derivation,expected=expected))
        cases.append(dict(id=record['name'],inputSha256=raw_sha,actualSha256=actual))
        expectations.append(dict(id=record['name'],inputSha256=raw_sha,expectationSha256=expectation,phase='holdout' if record['name']=='holdout' else 'training'))
    suite=put(dict(expectationAuthor='independent Fraction oracle reviewer',expectationKind='deterministic',adapterCodeSha256=codes['adapter'],evaluatorCodeSha256=codes['evaluator'],cases=expectations))
    run=dict(schemaVersion=3,subjectId=subject['id'],capability=subject['capability'],adapterVersion=subject['adapterVersion'],evaluatorVersion=subject['evaluatorVersion'],executionActor='retained actual app adapter execution',suiteSha256=suite,contextSha256=context,cases=cases)
    return subject,run,put
