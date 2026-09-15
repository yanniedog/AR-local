"""Retained actual adapter cases plus independent eligibility verification, not approval."""
import json
import zlib

from .executable_contract import _bounded
from .executable_code import verify_code_artifact
from .executable_v2_contract import validate_asset, schema_validate
from .executable_v2_inputs import exact_object, validate_evaluation, derive_facts
from .identity import digest


def _context(context, subject, result, store, read_blob):
    exact_object(context, ('manifest','index','shard','selection'), 'context')
    manifest, index, shard = (context[k] for k in ('manifest','index','shard'))
    from app_payload_optional_assets import executable_asset_url
    from app_payload_network_budget import validate_payload_network_budget
    from .identity import canonical_json
    validate_payload_network_budget(manifest,manifest_bytes=len(canonical_json(manifest).encode('utf8')))
    executable_asset_url(manifest, manifest['executable_v2']['index'], repo=manifest['repo'])
    if (manifest.get('source_observation',{}).get('generation_id') != subject['source']['generationId']
            or manifest.get('source_observation',{}).get('contract_digest') != subject['source']['exportContractSha256']):
        raise ValueError('Eligibility benchmark context observation differs')
    key = subject['scope']['productKey']
    shard_key = index['products'][key]
    for name,descriptor,document in (('index',manifest['executable_v2']['index'],index),
            ('shard',manifest['executable_v2']['shards'][shard_key],shard)):
        raw=read_blob(descriptor['sha256'])
        if len(raw)!=descriptor['bytes']:
            raise ValueError('Eligibility benchmark compressed asset bytes differ')
        decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
        body=decoder.decompress(raw,512*1024+1)
        if len(body)>512*1024 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('Eligibility benchmark compressed asset bound/format invalid')
        decoded=json.loads(body)
        schema_validate(decoded,f'executable-{name}-v2.schema.json',512*1024)
        if decoded!=document:
            raise ValueError('Eligibility benchmark decoded asset differs')
    from .executable_sources import _core
    from .executable_v2_sources import validate_destination
    core,core_size=_core(store,subject['source']['coreAssetSha256'])
    details,details_size=_core(store,subject['source']['detailsAssetSha256'])
    if core_size!=manifest['files']['core']['bytes'] or details_size!=manifest['files']['details']['bytes']:
        raise ValueError('Eligibility benchmark adopted asset bytes differ')
    validate_destination(subject,core,details,core_sha=manifest['files']['core']['sha256'],details_sha=manifest['files']['details']['sha256'])
    if (not set(index['products']) <= set(details.get('products',{}))
            or set(index['products'].values()) != set(manifest['executable_v2']['shards'])):
        raise ValueError('Eligibility benchmark shard inventory differs')
    for product,member in shard['products'].items():
        validate_asset(member,product_key=product)
        if (product not in details.get('products',{}) or index['products'].get(product)!=shard_key or member['runDate']!=manifest['run_date']
                or member['sourceGenerationId']!=subject['source']['generationId']
                or member['coreAssetSha256']!=manifest['files']['core']['sha256']
                or member['detailsAssetSha256']!=manifest['files']['details']['sha256']):
            raise ValueError('Eligibility benchmark shard product association differs')
        for item in member['subjects']:
            validate_destination(item['subject'],core,details,core_sha=manifest['files']['core']['sha256'],details_sha=manifest['files']['details']['sha256'])
    asset = shard['products'][key]
    validate_asset(asset, product_key=key)
    if context['selection']['subject'] != subject or {'subject':subject,'approval':context['selection']['approval']} not in asset['subjects']:
        raise ValueError('Eligibility benchmark selection association differs')
    for document in (index, shard):
        if (document['schema_version'] != 2 or document['run_date'] != subject['source']['runDate']
                or document['core_asset_sha256'] != subject['source']['coreAssetSha256']
                or document['details_asset_sha256'] != subject['source']['detailsAssetSha256']):
            raise ValueError('Eligibility benchmark context source differs')
    expected = dict(manifestSha256=digest(manifest),edition=manifest['payload_revision']['bundle_sha256'],
        indexSha256=manifest['executable_v2']['index']['sha256'],
        shardSha256=manifest['executable_v2']['shards'][shard_key]['sha256'],assetSha256=asset['identitySha256'],
        coreSha256=manifest['files']['core']['sha256'],detailsSha256=manifest['files']['details']['sha256'])
    if context['selection']['edition'] != expected['edition']:
        raise ValueError('Eligibility benchmark selection edition differs')
    if result is not None and (result['evaluationInputs']['binding'] != expected or result['evaluationInputs']['approval'] != context['selection']['approval']):
        raise ValueError('Eligibility benchmark retained context binding differs')
    if result is not None:
        _target(result['evaluationInputs']['target'],subject,core)


def _target(target,subject,core):
    if target.get('productKey')!=subject['scope']['productKey'] or target.get('productRecordSha256')!=subject['source']['productRecordSha256']:
        raise ValueError('Eligibility target product/source binding differs')
    if target.get('kind')=='rate_variant':
        rows=core.get('sections',{}).get(target.get('section'),{}).get('rates',[])
        index=target.get('coreRowIndex')
        if type(index) is not int or not 0<=index<len(rows):
            raise ValueError('Eligibility target rate binding differs')
        row=rows[index]
        if row.get('product_key')!=target['productKey'] or row.get('rate_index')!=target.get('rateIndex') or digest(row)!=target.get('rowSha256'):
            raise ValueError('Eligibility target rate binding differs')


def verify_benchmark(store, identity, subject):
    charged, read = 0, set()
    def read_blob(sha):
        nonlocal charged
        body = store.read_blob(sha)
        if sha not in read:
            charged += len(body); read.add(sha)
        if len(body) > 2 * 1024 * 1024 or charged > 32 * 1024 * 1024:
            raise ValueError('Eligibility benchmark artifact budget exceeded')
        return body
    def artifact(sha):
        body=read_blob(sha)
        value = json.loads(body)
        _bounded(value, 2 * 1024 * 1024, ascii_keys=False)
        return value
    run = artifact(identity)
    exact_object(run, ('schemaVersion','subjectId','capability','adapterVersion','evaluatorVersion','executionActor','suiteSha256','contextSha256','cases'), 'run')
    if run['schemaVersion'] != 2 or run['subjectId'] != subject['id'] or any(run[k] != subject[k] for k in ('capability','adapterVersion','evaluatorVersion')):
        raise ValueError('Eligibility benchmark subject/version differs')
    suite, context = artifact(run['suiteSha256']), artifact(run['contextSha256'])
    exact_object(suite, ('expectationAuthor','expectationKind','adapterCodeSha256','evaluatorCodeSha256','cases'), 'suite')
    if (not isinstance(run['executionActor'], str) or not run['executionActor'].strip()
            or not isinstance(suite['expectationAuthor'],str) or not suite['expectationAuthor'].strip()
            or run['executionActor'] == suite['expectationAuthor'] or suite['expectationKind'] not in ('human','deterministic')):
        raise ValueError('Eligibility benchmark requires independent expectations')
    for role in ('adapter','evaluator'):
        verify_code_artifact(store,suite[role+'CodeSha256'],role,subject[role+'Version'],capability='eligibility_only')
    cases = run['cases']
    if not isinstance(cases,list) or not 7 <= len(cases) <= 64 or not isinstance(suite['cases'],list) or len(cases) != len(suite['cases']):
        raise ValueError('Eligibility benchmark case inventory differs')
    seen, inputs, canonical_inputs, states, refusals, holdouts = set(), set(), set(), set(), set(), 0
    for actual_case, expected_case in zip(cases,suite['cases']):
        exact_object(actual_case,('id','inputSha256','actualSha256'), 'actual case')
        exact_object(expected_case,('id','inputSha256','expectationSha256','phase'), 'expected case')
        if (not isinstance(actual_case['id'],str) or not actual_case['id'] or actual_case['id'] in seen
                or actual_case['inputSha256'] in inputs or expected_case['phase'] not in ('training','holdout')
                or any(actual_case[k] != expected_case[k] for k in ('id','inputSha256'))):
            raise ValueError('Eligibility benchmark case identity/phase differs')
        seen.add(actual_case['id']); inputs.add(actual_case['inputSha256'])
        raw, actual, expected = (artifact(actual_case['inputSha256']), artifact(actual_case['actualSha256']),artifact(expected_case['expectationSha256']))
        exact_object(raw,('scenario','profile','target'),'requested adapter input')
        if digest(raw) in canonical_inputs:
            raise ValueError('Eligibility benchmark duplicate semantic input')
        canonical_inputs.add(digest(raw))
        shared = ('subjectId','inputSha256','contextSha256','executionKind','outcome')
        exact_object(actual,(*shared,'adapterCodeSha256','evaluatorCodeSha256'), 'actual execution')
        exact_object(expected,(*shared,'derivationSha256'), 'independent expected execution')
        if (actual['executionKind'] != 'actual_adapter' or any(actual[k] != expected[k] for k in shared)
                or actual['subjectId'] != subject['id'] or actual['inputSha256'] != actual_case['inputSha256']
                or actual['contextSha256'] != run['contextSha256']
                or any(actual[k] != suite[k] for k in ('adapterCodeSha256','evaluatorCodeSha256'))):
            raise ValueError('Eligibility benchmark execution binding differs')
        derivation = artifact(expected['derivationSha256'])
        if not isinstance(derivation,dict) or not derivation:
            raise ValueError('Eligibility independent derivation missing')
        outcome = actual['outcome']
        if isinstance(outcome,dict) and set(outcome) == {'result'}:
            result = outcome['result']
            validate_evaluation(result,subject,raw)
            _context(context,subject,result,store,read_blob)
            states.add(result['eligibility']['status'])
            holdouts += expected_case['phase'] == 'holdout'
        else:
            exact_object(outcome,('refusal','resultReturned'), 'adapter refusal')
            _context(context,subject,None,store,read_blob)
            if outcome['resultReturned'] is not False:
                raise ValueError('Eligibility adapter refusal returned a result')
            from .executable_sources import _core
            core,_=_core(store,subject['source']['coreAssetSha256'])
            try:
                _target(raw['target'],subject,core)
            except ValueError:
                if outcome['refusal']!='Eligibility product publication is not verified':
                    raise ValueError('Eligibility target refusal message differs')
                refusals.add('target_binding')
                continue
            try:
                derive_facts(subject,raw['scenario'],{})
            except ValueError as error:
                reason = str(error)
                if reason != outcome['refusal'] or reason not in ('Assessment date is outside the reviewed coverage interval','Scenario fact does not match its reviewed type or unit'):
                    raise ValueError('Eligibility refusal is not the retained supported control') from error
                refusals.add(reason)
            else:
                raise ValueError('Eligibility claimed adapter refusal is not reproducible')
    if states != {'meets','does_not_meet','needs_information'} or len(refusals) != 3 or not holdouts:
        raise ValueError('Eligibility benchmark needs all three outcomes, a holdout and scope/target/input refusal controls')
