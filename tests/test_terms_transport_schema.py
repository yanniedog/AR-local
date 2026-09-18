import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from cdr_terms.generation_schema import generation_schema
from cdr_terms.mortgage_material_fields import GROUPS, field_value
from cdr_terms.parameter_registry import interpretation_contract, registry_contract
from cdr_terms.transport_schema import transport_generation_schema


def context(version):
    name, sha = interpretation_contract(version)
    return dict(parameter_registry=registry_contract(version),
                interpretation_contract=name, interpretation_schema_sha256=sha)


@pytest.mark.parametrize('version', ['terms-parameters-v3', 'terms-parameters-v4'])
def test_provider_can_resolve_every_reference_without_nested_definitions(version):
    ctx = context(version)
    original = generation_schema(ctx)
    result = transport_generation_schema(ctx)
    Draft202012Validator.check_schema(result)
    pending = list(result.values())
    references = 0
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            assert '$defs' not in node
            if '$ref' in node:
                target = result
                for part in node['$ref'][2:].split('/'):
                    target = target[part.replace('~1', '/').replace('~0', '~')]
                assert isinstance(target, dict)
                references += 1
            pending.extend(node.values())
    assert references > 0
    assert generation_schema(ctx) == original


@pytest.mark.parametrize('version', ['terms-parameters-v3', 'terms-parameters-v4'])
def test_hoisting_discards_unreferenced_resource_containers(version):
    result = transport_generation_schema(context(version))
    assert result['type'] == 'object'
    assert 'mortgageCommon' not in result['$defs']
    assert 'mortgageDefinitions' not in result['$defs']
    assert all(any(key in schema for key in ('type', 'anyOf', '$ref'))
               for schema in result['$defs'].values())


def test_pruning_retains_transitive_constraints_and_drops_unused_only(monkeypatch):
    import cdr_terms.transport_schema as transport
    schema = {'type': 'object', 'properties': {'value': {'$ref': '#/$defs/outer'}},
              'required': ['value'], 'additionalProperties': False,
              '$defs': {'outer': {'type': 'array', 'items': {'$ref': '#/$defs/inner'}},
                        'inner': {'type': 'integer', 'minimum': 1},
                        'unused': {'$comment': 'Resource container after hoisting'}}}
    original = copy.deepcopy(schema)
    monkeypatch.setattr(transport, 'generation_schema', lambda _: copy.deepcopy(schema))
    result = transport.transport_generation_schema({})
    assert set(result['$defs']) == {'outer', 'inner'}
    assert schema == original
    for candidate in ({'value': [1]}, {'value': [0]}, {'value': ['1']},
                      {'value': [1], 'extra': True}, {}):
        assert Draft202012Validator(schema).is_valid(candidate) == Draft202012Validator(result).is_valid(candidate)


def test_hoisting_preserves_mortgage_values_and_rejections():
    subject = json.loads((Path(__file__).parent / 'fixtures/mortgage-v3/subject.json').read_bytes())
    ctx = context('terms-parameters-v4')
    schemas = [generation_schema(ctx), transport_generation_schema(ctx)]
    validators = [Draft202012Validator({'$defs': s['$defs'], **s['properties']['terms']['items']}) for s in schemas]
    for field in GROUPS:
        term = dict(parameter_key='monetary.mortgage_field_v1', value=field_value(subject, field),
                    unit=None, product_key=subject['scope']['productKey'], tier=None, package=None,
                    cohort=None, effective_from=None, effective_to=None, clause_indexes=[0],
                    rule_pattern=None, conditions=[], exceptions=[])
        for validator in validators:
            validator.validate(term)
            bad = copy.deepcopy(term)
            bad['value']['unexpected'] = True
            with pytest.raises(ValidationError):
                validator.validate(bad)
