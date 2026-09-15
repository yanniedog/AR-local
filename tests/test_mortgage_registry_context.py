"""Technical schema controls, not source or bank policy acceptance."""
import copy,json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator,ValidationError
from cdr_terms.parameter_registry import registry_contract,interpretation_contract,validate_parameter_terms
from cdr_terms.queue import staging_schema
from cdr_terms.generation_schema import generation_schema
from cdr_terms.identity import digest
from cdr_terms.mortgage_material_fields import GROUPS,field_value,validate_field_value


def context(version):
    name,sha=interpretation_contract(version)
    return dict(parameter_registry=registry_contract(version),interpretation_contract=name,interpretation_schema_sha256=sha)


def test_immutable_v3_registry_and_generation():
    old=context('terms-parameters-v3')
    assert old['parameter_registry']['sha256']=='8b05e31f30f323f0ac37e25c2a42692a935bafe5e7e56f3944aa423c50d81126'
    assert all(not row['aliases'] for row in old['parameter_registry']['parameters'])
    assert digest(generation_schema(old))=='574f70c21ddc48b048ab62c78bb165f9462eb425320a8f3929172af1fb86d926'
    assert old['interpretation_schema_sha256']=='cefd91e370e8d1b6275fee0bf6af1c302d31b01674babd978811440ced28a02c'


def test_all_mortgage_fields_in_canonical_and_generation():
    subject=json.loads((Path(__file__).parent/'fixtures/mortgage-v3/subject.json').read_bytes())
    current=context('terms-parameters-v4');canonical=staging_schema(current);generated=generation_schema(current)
    for field in GROUPS:
        value=field_value(subject,field);validate_field_value(value)
        term=dict(parameter_key='monetary.mortgage_field_v1',value=value,unit=None,product_key=subject['scope']['productKey'],
                  tier=None,package=None,cohort=None,effective_from=None,effective_to=None,clause_indexes=[0],rule_pattern=None,conditions=[],exceptions=[])
        validate_parameter_terms(current,[term])
        for schema in (canonical,generated):
            Draft202012Validator({'$defs':schema['$defs'],**schema['properties']['terms']['items']}).validate(term)
        with pytest.raises(ValueError,match='Unknown canonical'):validate_parameter_terms(context('terms-parameters-v3'),[term])
        bad=copy.deepcopy(term);bad['parameter_key']='product.description'
        with pytest.raises((ValueError,ValidationError)):validate_parameter_terms(current,[bad])
        bad=copy.deepcopy(term);bad['unit']='AUD'
        with pytest.raises(ValueError,match='unit'):validate_parameter_terms(current,[bad])


def test_v4_generation_root_closed_and_no_unsupported_combinators():
    schema=generation_schema(context('terms-parameters-v4'));pending=[schema]
    while pending:
        node=pending.pop()
        if isinstance(node,list):pending.extend(node)
        elif isinstance(node,dict):
            assert not set(node)&{'oneOf','allOf','if','then','else','not','uniqueItems'}
            if node.get('type')=='object':assert node['additionalProperties'] is False and set(node['required'])==set(node['properties'])
            pending.extend(node.values())
