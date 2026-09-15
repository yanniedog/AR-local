import copy,json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator,ValidationError
from cdr_terms.monetary_material_fields import field_value,SCHEMA
from cdr_terms.executable_v3_graph import FIELDS
from tests.executable_v3_fixture import subject
from tests.executable_v3_fixture import monetary_protocol,technical_protocol,reidentify
from cdr_terms.executable_v3_sources import source_snapshot,_revisions
from cdr_terms.executable_v3_evidence import EvidenceOperation
from cdr_terms.monetary_material_fields import validate_material_coverage

@pytest.mark.parametrize('field',['rates','rounding','fees','eligibility'])
def test_reviewed_typed_values_reject_changed_policy(monetary_protocol,field):
    store,value,_=monetary_protocol
    source_snapshot(store,value)
    if field=='rates':value['policy']['intervals'][0]['tiers'][0]['annualRate']='0.04'
    elif field=='rounding':value['policy']['intervals'][0]['interest']['postingRounding']='half_even'
    elif field=='fees':value['policy']['fees']['inventory'][0]['categoryId']='changed-category'
    else:value['policy']['inputDefinitions'][0]['label']='Different role prompt'
    reidentify(value)
    with pytest.raises(ValueError,match='structured material'):source_snapshot(store,value)

def test_description_only_legacy_source_never_grandfathered(tmp_path):
    generator=technical_protocol(tmp_path,structured_material=False)
    store,value,_=next(generator)
    try:
        with pytest.raises(ValueError,match='structured material'):source_snapshot(store,value)
    finally:generator.close()

@pytest.mark.parametrize('fault',['key','unit','context','clause'])
def test_exact_value_requires_correct_revision_authority(monetary_protocol,fault):
    from cdr_terms.identity import canonical_json
    from cdr_terms.parameter_registry import registry_contract
    store,value,_=monetary_protocol
    revisions=_revisions(store,value,EvidenceOperation(store))
    for revision in revisions.values():
        row=revision['row']
        if fault=='key':row['parameter_key']='product.description'
        elif fault=='unit':row['unit']='AUD'
        elif fault=='clause':revision['clauses']={'f'*64}
        else:
            context=json.loads(store.read_blob(row['context_sha256']));context['parameter_registry']=registry_contract('terms-parameters-v2')
            row['context_sha256']=store.put_blob(canonical_json(context).encode())
    authority=value['authorityGraph']['authorities'][0]
    coverage=next(x for x in authority['fieldCoverage'] if x['field']=='rates')
    with pytest.raises(ValueError,match='structured material'):
        validate_material_coverage(store,value,authority,coverage,revisions,EvidenceOperation(store))

def test_old_registry_contract_hashes_are_preserved():
    from cdr_terms.parameter_registry import registry_contract
    assert registry_contract('terms-parameters-v1')['sha256']=='ada9acf47ff1436a7562af06df2107ca4aec28110c005f8d856a75312aec668e'
    old=registry_contract('terms-parameters-v2')
    assert old['sha256']=='a3297f2798acb65ce28343a9143d613efe436563abd344e0c2dd30c12f0c34de'
    assert all(not row['aliases'] for row in old['parameters'])


def test_material_context_obeys_private_member_budget(monetary_protocol):
    store,value,_=monetary_protocol
    revisions=_revisions(store,value,EvidenceOperation(store))
    oversized=store.put_blob(b' '*(2*1024*1024+1))
    for revision in revisions.values():revision['row']['context_sha256']=oversized
    authority=value['authorityGraph']['authorities'][0]
    with pytest.raises(ValueError,match='private byte budget'):
        validate_material_coverage(store,value,authority,authority['fieldCoverage'][0],revisions,EvidenceOperation(store))


def test_material_context_read_and_decode_charged_once(monetary_protocol,monkeypatch):
    store,value,_=monetary_protocol
    revisions=_revisions(store,value,EvidenceOperation(store));operation=EvidenceOperation(store)
    calls=[];original=operation.read_blob
    def tracked(identity):
        calls.append(identity);return original(identity)
    monkeypatch.setattr(operation,'read_blob',tracked)
    authority=value['authorityGraph']['authorities'][0]
    for coverage in authority['fieldCoverage']:
        validate_material_coverage(store,value,authority,coverage,revisions,operation)
    identities={r['row']['context_sha256'] for r in revisions.values()}
    assert set(calls)==identities and len(calls)==len(identities)
    assert operation.decoded_bytes==sum(len(operation.raw[x]) for x in identities)
    assert len(operation.material_values)==len(revisions)


def test_worker_receives_context_selected_closed_schema(monetary_protocol,tmp_path):
    from pi_terms_worker import prepare_job
    from cdr_terms.queue import staging_schema
    store,value,_=monetary_protocol
    job=dict(store.db.execute('SELECT j.*,x.text_sha256,x.document_version_id FROM analysis_jobs j JOIN extractions x USING(extraction_id) LIMIT 1').fetchone())
    job['lease_id']=store.db.execute('SELECT lease_id FROM job_events WHERE job_id=? AND lease_id IS NOT NULL ORDER BY sequence DESC LIMIT 1',(job['job_id'],)).fetchone()[0]
    root=(tmp_path/'worker-schema-proof').resolve()
    prepare_job(store,job,root)
    output=json.loads((root/'schema.json').read_bytes())
    context=json.loads((root/'input.json').read_bytes())['context']
    assert context['interpretation_contract']=='analysis-staging-material-v1'
    from cdr_terms.generation_schema import generation_schema
    assert output==generation_schema(context)
    def dialect(node):
        if isinstance(node,list):
            for child in node:dialect(child)
        elif isinstance(node,dict):
            assert not set(node)&{'allOf','if','then','else','not','oneOf','uniqueItems'}
            if node.get('type')=='object':
                assert node['additionalProperties'] is False
                assert set(node['required'])==set(node['properties'])
            for child in node.values():dialect(child)
    dialect(output)
    from cdr_terms.identity import byte_digest
    assert json.loads((root/'binding.json').read_bytes())['generation_schema_sha256']==byte_digest((root/'schema.json').read_bytes())
    term_schema={'$defs':output['$defs'],**output['properties']['terms']['items']}
    term=dict(parameter_key='monetary.savings_base_field_v1',value=field_value(value,value['policy']['intervals'][0],'rates'),
        unit=None,product_key=value['scope']['productKey'],tier=None,package=None,cohort=None,effective_from=None,effective_to=None,
        clause_indexes=[0],rule_pattern=None,conditions=[],exceptions=[])
    Draft202012Validator(term_schema).validate(term)
    for field in FIELDS:
        term['value']=field_value(value,value['policy']['intervals'][0],field)
        Draft202012Validator(term_schema).validate(term)
    from cdr_terms.parameter_registry import registry_contract
    old=staging_schema({'parameter_registry':registry_contract('terms-parameters-v2')})
    with pytest.raises(ValidationError):Draft202012Validator(old['properties']['terms']['items']).validate(term)
    term['parameter_key']='product.description'
    with pytest.raises(ValidationError):Draft202012Validator(term_schema).validate(term)
    broken=dict(context,interpretation_contract='analysis-staging-v1')
    with pytest.raises(ValueError,match='schema binding'):staging_schema(broken)


def test_generation_union_proof_respects_json_numeric_overlap():
    from cdr_terms.generation_schema import _disjoint,_types
    assert not _disjoint({'type':'integer'},{'type':'number'})
    assert not _disjoint({'const':1},{'type':'number'})
    with pytest.raises(ValueError,match='constant type'):_types({'const':1.5})

def test_all_closed_field_projections_have_no_provenance_cycles():
    value=subject();period=value['policy']['intervals'][0]
    for field in FIELDS:
        projected=field_value(value,period,field)
        assert projected['field']==field
        assert 'evidenceIds' not in json.dumps(projected)
        assert value['id'] not in json.dumps(projected)

@pytest.mark.parametrize('fault',['extra','wrongunit','text','unknownfield'])
def test_closed_material_value_refuses_untyped_claims(fault):
    value=subject();projected=field_value(value,value['policy']['intervals'][0],'rates')
    if fault=='extra':projected['material']['verified']=True
    elif fault=='wrongunit':projected['material']['rateUnit']='percent'
    elif fault=='text':projected['material']='quoted prose'
    else:projected['field']='arbitrary'
    with pytest.raises(ValidationError):Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(projected)
