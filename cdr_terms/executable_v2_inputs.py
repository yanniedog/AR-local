"""Independent verification of the retained eligibility adapter's private inputs."""
from .executable_contract import _bounded
from .executable_eligibility import _compare, _date, verify_eligibility
from .executable_v2_contract import validate_subject, validate_asset
from .identity import digest, require_sha


def exact_object(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError('Eligibility benchmark ' + label + ' shape mismatch')


def valid_fact(value):
    if not isinstance(value, dict):
        return False
    try:
        _compare(value, value)
        kind = value['type']
        return (kind != 'text' or len(value['value']) <= 2000) and (kind != 'decimal' or len(value['unit']) <= 80)
    except (ValueError, TypeError, KeyError):
        return False


def derive_facts(subject, scenario, answers):
    exact_object(scenario, ('assessmentDate','values'), 'scenario')
    _date(scenario['assessmentDate'])
    scope = subject['scope']
    if not scope['effectiveFrom'] <= scenario['assessmentDate'] < scope['effectiveToExclusive']:
        raise ValueError('Assessment date is outside the reviewed coverage interval')
    values = scenario['values']
    allowed = {d['binding'] for d in subject['inputDefinitions']} - {'customer_fact','assessment_date'}
    if not isinstance(values, dict) or not set(values) <= allowed:
        raise ValueError('Scenario role is not declared')
    ids = {'elig_' + digest([subject['id'], d['key']]) for d in subject['inputDefinitions'] if d['binding'] == 'customer_fact'}
    if not isinstance(answers, dict) or not set(answers) <= ids:
        raise ValueError('Eligibility benchmark customer scope differs')
    facts = {}
    for definition in subject['inputDefinitions']:
        binding, key = definition['binding'], definition['key']
        if binding == 'assessment_date':
            fact = {'type':'date','value':scenario['assessmentDate']}
        elif binding != 'customer_fact':
            if binding not in values:
                continue
            fact = values[binding]
        else:
            answer = answers.get('elig_' + digest([subject['id'], key]))
            if not answer or answer.get('state') != 'known':
                continue
            provenance = answer.get('provenance', {})
            if (provenance.get('productKey') != scope['productKey']
                    or provenance.get('effectiveFrom') and scenario['assessmentDate'] < provenance['effectiveFrom']
                    or provenance.get('effectiveToExclusive') and scenario['assessmentDate'] >= provenance['effectiveToExclusive']):
                continue
            fact = answer.get('fact')
        if not valid_fact(fact) or fact['type'] != definition['type'] or fact['type'] == 'decimal' and fact['unit'] != definition['unit']:
            if binding != 'customer_fact':
                raise ValueError('Scenario fact does not match its reviewed type or unit')
            continue
        facts[key] = fact
    return facts


def validate_evaluation(result, subject, raw_input):
    _bounded(result, 1024 * 1024, ascii_keys=False)
    _bounded(raw_input, 512 * 1024, ascii_keys=False)
    validate_subject(subject)
    exact_object(result, ('schemaVersion','evaluationKind','adapterVersion','evaluatorVersion','evaluationInputs','inputSha256','eligibility'), 'result')
    if result['schemaVersion'] != 1 or result['evaluationKind'] != 'eligibility_only' or any(result[k] != subject[k] for k in ('adapterVersion','evaluatorVersion')):
        raise ValueError('Eligibility benchmark capability/version differs')
    inputs = result['evaluationInputs']
    exact_object(inputs, ('subject','approval','binding','target','scenario','customerAnswers','facts'), 'evaluation input')
    if inputs['subject'] != subject or result['inputSha256'] != digest(inputs):
        raise ValueError('Eligibility benchmark subject/input identity differs')
    source = subject['source']
    association = dict(schemaVersion=2,productKey=subject['scope']['productKey'],sourceObservationId=source['observationId'],
        sourceGenerationId=source['generationId'],runDate=source['runDate'],coreAssetSha256=source['coreAssetSha256'],
        detailsAssetSha256=source['detailsAssetSha256'],approvalPolicy='as_of_adopted_edition',
        subjects=[{'subject':subject,'approval':inputs['approval']}])
    association['identitySha256'] = digest(association)
    validate_asset(association)  # Shape/association only; this is not approval authority.
    exact_object(raw_input, ('scenario','profile','target') if 'target' in raw_input else ('scenario','profile'), 'raw input')
    if inputs['scenario'] != raw_input['scenario']:
        raise ValueError('Eligibility benchmark raw scenario differs')
    profile = raw_input['profile']
    if not isinstance(profile, dict) or not isinstance(profile.get('answers'), dict):
        raise ValueError('Eligibility benchmark raw profile invalid')
    declared = {'elig_' + digest([subject['id'], d['key']]) for d in subject['inputDefinitions'] if d['binding'] == 'customer_fact'}
    if inputs['customerAnswers'] != {k:v for k,v in profile['answers'].items() if k in declared}:
        raise ValueError('Eligibility benchmark raw customer answers differ')
    binding = inputs['binding']
    exact_object(binding, ('manifestSha256','edition','indexSha256','shardSha256','assetSha256','coreSha256','detailsSha256'), 'binding')
    for value in binding.values():
        require_sha(value)
    if binding['coreSha256'] != subject['source']['coreAssetSha256'] or binding['detailsSha256'] != subject['source']['detailsAssetSha256']:
        raise ValueError('Eligibility benchmark source assets differ')
    target = inputs['target']
    if 'target' in raw_input and raw_input['target'] != target:
        raise ValueError('Eligibility benchmark requested target differs')
    if not isinstance(target, dict):
        raise ValueError('Eligibility benchmark target invalid')
    fields = ('kind','productKey','productRecordSha256')
    exact_object(target, fields if target.get('kind') == 'product' else (*fields,'section','coreRowIndex','rateIndex','rowSha256'), 'target')
    if target['productKey'] != subject['scope']['productKey'] or target['productRecordSha256'] != subject['source']['productRecordSha256']:
        raise ValueError('Eligibility benchmark target product differs')
    if target['kind'] == 'product':
        if subject['scope']['coverage'] != 'product':
            raise ValueError('Eligibility benchmark rate scope cannot target whole product')
    elif (target['kind'] != 'rate_variant' or target['section'] != subject['scope']['family']
          or subject['scope']['coverage'] == 'rate_variants' and {k:target[k] for k in ('coreRowIndex','rateIndex','rowSha256')} not in subject['source']['rateRows']):
        raise ValueError('Eligibility benchmark target variant differs')
    facts = derive_facts(subject, inputs['scenario'], inputs['customerAnswers'])
    if facts != inputs['facts'] or verify_eligibility(subject['eligibility'], facts) != result['eligibility']:
        raise ValueError('Eligibility benchmark actual facts/result differs from verification oracle')
