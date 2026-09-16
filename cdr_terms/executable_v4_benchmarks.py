"""Actual adapter receipts, private retained inputs and independent arithmetic gates."""
import hashlib
import json
from pathlib import Path
from .identity import digest,require_sha
from .executable_contract import _bounded
from .executable_code import verify_code_artifact
from .executable_v2_inputs import exact_object
from .executable_v3_evidence import evidence_operation
from .executable_v4_context import context_binding,target_binding
from .executable_v4_inputs import check_inputs,validate_result
from .executable_v4_financial import verify_financial


def verify_benchmark(store,identity,subject):
    input_check,result_check,financial_check=check_inputs,validate_result,verify_financial
    allowed=('Activity product publication is not verified','Account period is outside source-reviewed historical coverage','Confirmed account rates differ from the reviewed historical schedule','Confirmed bonus rates differ from source','Activity account or assessment window differs')
    cache={};charged=0
    def artifact(sha):
        nonlocal charged
        require_sha(sha)
        if sha in cache:return cache[sha]
        path=Path(store.root)/'blobs'/sha[:2]/sha
        if path.is_symlink() or path.resolve()!=path or not path.is_file():raise ValueError('Unsafe savings benchmark artifact')
        size=path.stat().st_size
        if size>4*1024*1024 or charged+size>32*1024*1024 or len(cache)>=256:raise ValueError('Savings benchmark artifact budget exceeded')
        if hasattr(store,'used'):
            if store.used+size>512*1024*1024:raise ValueError('Terms projection work budget exceeded')
            store.used+=size
        with path.open('rb') as stream:raw=stream.read(size+1)
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Savings benchmark artifact bytes differ')
        value=json.loads(raw);_bounded(value,4*1024*1024,ascii_keys=False)
        charged+=size;cache[sha]=value;return value
    run=artifact(identity)
    exact_object(run,('schemaVersion','subjectId','capability','adapterVersion','evaluatorVersion','executionActor','suiteSha256','contextSha256','cases'),'savings benchmark run')
    if run['schemaVersion']!=4 or run['subjectId']!=subject['id'] or any(run[k]!=subject[k] for k in ('capability','adapterVersion','evaluatorVersion')):raise ValueError('Savings benchmark subject differs')
    suite=artifact(run['suiteSha256']);context=artifact(run['contextSha256'])
    exact_object(suite,('expectationAuthor','expectationKind','adapterCodeSha256','evaluatorCodeSha256','cases'),'savings suite')
    if not isinstance(run['executionActor'],str) or not run['executionActor'].strip() or not isinstance(suite['expectationAuthor'],str) or not suite['expectationAuthor'].strip() or suite['expectationAuthor'].strip()==run['executionActor'].strip() or suite['expectationKind'] not in ('human','deterministic'):raise ValueError('Savings independent expectation author required')
    for role in ('adapter','evaluator'):verify_code_artifact(store,suite[role+'CodeSha256'],role,subject[role+'Version'],capability=subject['capability'])
    cases=run['cases']
    if not isinstance(cases,list) or not 6<=len(cases)<=64 or not isinstance(suite['cases'],list) or len(suite['cases'])!=len(cases):raise ValueError('Savings benchmark case inventory differs')
    seen=set();inputs=set();refusals=set();qualifications=set();complete=holdouts=0
    with evidence_operation(store) as operation:
        binding,core=context_binding(context,subject,operation)
        for case,expected_case in zip(cases,suite['cases']):
            exact_object(case,('id','inputSha256','actualSha256'),'savings actual case')
            exact_object(expected_case,('id','inputSha256','expectationSha256','phase'),'savings expected case')
            if not isinstance(case['id'],str) or not case['id'] or case['id'] in seen or expected_case['phase'] not in ('training','holdout') or any(case[k]!=expected_case[k] for k in ('id','inputSha256')):raise ValueError('Savings case association differs')
            seen.add(case['id']);raw=artifact(case['inputSha256']);actual=artifact(case['actualSha256']);expected=artifact(expected_case['expectationSha256'])
            if digest(raw) in inputs:raise ValueError('Savings duplicate semantic input')
            inputs.add(digest(raw));exact_object(raw,('target','inputs','profile'),'savings raw input')
            shared=('subjectId','inputSha256','contextSha256','executionKind')
            exact_object(actual,(*shared,'adapterCodeSha256','evaluatorCodeSha256','outcome'),'savings execution')
            exact_object(expected,(*shared,'derivationSha256','expected'),'savings expectation')
            if (actual['executionKind']!='actual_adapter' or any(actual[k]!=expected[k] for k in shared) or actual['subjectId']!=subject['id'] or actual['inputSha256']!=case['inputSha256'] or actual['contextSha256']!=run['contextSha256'] or any(actual[k]!=suite[k] for k in ('adapterCodeSha256','evaluatorCodeSha256'))):raise ValueError('Savings actual execution binding differs')
            derivation=artifact(expected['derivationSha256'])
            required=dict(schemaVersion=1,method='independent_fraction_oracle_v1',policySha256=digest(subject['policy']),inputSha256=case['inputSha256'],expected=expected['expected'])
            if derivation!=required:raise ValueError('Savings independent derivation association differs')
            outcome=actual['outcome']
            if isinstance(outcome,dict) and set(outcome)=={'result'}:
                result=outcome['result'];target_binding(raw['target'],subject,core);result_check(result,subject,raw)
                if result['adapterInputs']['binding']!=binding or result['adapterInputs']['approval']!=context['selection']['approval']:raise ValueError('Savings retained publication binding differs')
                normalized=financial_check(result,subject,raw['inputs'])
                if expected['expected']!=normalized:raise ValueError('Savings retained independent expectation differs')
                qualifications.add(normalized['qualified'])
                if result['receipt']['claimAvailable'] is True:
                    complete+=1;holdouts+=expected_case['phase']=='holdout'
            else:
                exact_object(outcome,('refusal','resultReturned'),'savings refusal')
                if outcome['resultReturned'] is not False:raise ValueError('Savings refusal returned a calculation')
                try:
                    target_binding(raw['target'],subject,core);input_check(subject,raw['inputs'])
                except ValueError as error:
                    reason=str(error)
                    if reason not in allowed or outcome['refusal']!=reason or expected['expected']!={'kind':'technical_refusal','reason':reason}:raise ValueError('Savings refusal control differs') from error
                    refusals.add(reason)
                else:raise ValueError('Savings claimed refusal is not independently reproducible')
    if complete<2 or not holdouts or refusals!=set(allowed) or qualifications!={True,False,None}:
        raise ValueError('Activity benchmark requires complete holdout, bonus/base/unknown and five actual refusal controls')
