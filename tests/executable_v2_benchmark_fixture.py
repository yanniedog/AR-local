"""Actual committed technical adapter output with independently assembled expectations."""
import base64
import gzip
import json
from pathlib import Path

from cdr_terms.executable_v2_inputs import derive_facts
from cdr_terms.executable_eligibility import verify_eligibility
from cdr_terms.identity import canonical_json, digest


def retained_benchmark(store, revision="9c6090a"):
    path=Path(__file__).parent/f'fixtures/executable-templates/eligibility-v2-final-{revision}.json.gz'
    fixture=json.loads(gzip.decompress(path.read_bytes()))
    for sha,encoded in fixture['blobs'].items():
        assert store.put_blob(base64.b64decode(encoded))==sha
    bridge=json.loads(store.read_blob(fixture['bridgeSha256']))
    subject=bridge['selection']['subject']
    def put(value):
        return store.put_blob(canonical_json(value).encode('utf8'))
    context={key:bridge[key] for key in ('index','shard','selection')}
    context['manifest']=bridge['context']['manifest']
    context_sha=put(context)
    suite=dict(expectationAuthor='independent-python-verification-oracle',expectationKind='deterministic',
        adapterCodeSha256=fixture['codeManifests']['adapter'],evaluatorCodeSha256=fixture['codeManifests']['evaluator'],cases=[])
    run=dict(schemaVersion=2,subjectId=subject['id'],capability=subject['capability'],adapterVersion=subject['adapterVersion'],
        evaluatorVersion=subject['evaluatorVersion'],executionActor='actual-app-adapter-'+revision,contextSha256=context_sha,cases=[])
    for record in bridge['records']:
        raw=record['rawInput']; input_sha=put(raw)
        assert digest(raw)==record['rawInputSha256']
        actual_outcome={'result':record['result']} if 'result' in record else {'refusal':record['refusal'],'resultReturned':record['resultReturned']}
        expected_outcome=derive_outcome(subject,context,raw)
        shared=dict(subjectId=subject['id'],inputSha256=input_sha,contextSha256=context_sha,executionKind='actual_adapter')
        actual={**shared,'adapterCodeSha256':suite['adapterCodeSha256'],'evaluatorCodeSha256':suite['evaluatorCodeSha256'],'outcome':actual_outcome}
        expected={**shared,'derivationSha256':put({'oracle':'independent_python_eligibility_and_source_binding',
            'rawInputSha256':input_sha,'subjectId':subject['id'],'expectedOutcome':expected_outcome}), 'outcome':expected_outcome}
        run['cases'].append(dict(id=record['name'],inputSha256=input_sha,actualSha256=put(actual)))
        suite['cases'].append(dict(id=record['name'],inputSha256=input_sha,expectationSha256=put(expected),
            phase='holdout' if record['name']=='independent-holdout' else 'training'))
    run['suiteSha256']=put(suite)
    return put(run),subject,bridge


def derive_outcome(subject,context,raw):
    if raw['target']['productKey']!=subject['scope']['productKey']:
        return {'refusal':'Eligibility product publication is not verified','resultReturned':False}
    declared={'elig_'+digest([subject['id'],d['key']]) for d in subject['inputDefinitions'] if d['binding']=='customer_fact'}
    answers={k:v for k,v in raw['profile']['answers'].items() if k in declared}
    try:
        facts=derive_facts(subject,raw['scenario'],answers)
    except ValueError as error:
        return {'refusal':str(error),'resultReturned':False}
    manifest=context['manifest'];key=subject['scope']['productKey'];asset=context['shard']['products'][key]
    binding=dict(manifestSha256=digest(manifest),edition=manifest['payload_revision']['bundle_sha256'],
        indexSha256=manifest['executable_v2']['index']['sha256'],shardSha256=manifest['executable_v2']['shards'][context['index']['products'][key]]['sha256'],
        assetSha256=asset['identitySha256'],coreSha256=manifest['files']['core']['sha256'],detailsSha256=manifest['files']['details']['sha256'])
    inputs=dict(subject=subject,approval=context['selection']['approval'],binding=binding,target=raw['target'],scenario=raw['scenario'],customerAnswers=answers,facts=facts)
    return {'result':dict(schemaVersion=1,evaluationKind='eligibility_only',adapterVersion=subject['adapterVersion'],evaluatorVersion=subject['evaluatorVersion'],
        evaluationInputs=inputs,inputSha256=digest(inputs),eligibility=verify_eligibility(subject['eligibility'],facts))}
