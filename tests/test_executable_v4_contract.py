"""Technical protocol controls, without bank or original-source acceptance."""
import copy
import json
import pytest
from jsonschema import ValidationError
from cdr_terms.executable_v4_contract import ROOT, identity, validate_subject
from cdr_terms.executable_v4_graph import periods
from cdr_terms.executable_v4_material import field_value, validate_field_value, project_field


def sample():
    return json.loads((ROOT / 'drafts/positive-technical-example.json').read_bytes())['subject']


def reseal(subject):
    graph = subject['authorityGraph']; mapping = {}
    for authority in graph['authorities']:
        old = authority['id']; authority['id'] = identity(authority); mapping[old] = authority['id']
    for period in subject['policy']['intervals'] + [subject['policy']['bonus']['assessment']]:
        period['authorityId'] = mapping.get(period['authorityId'], period['authorityId'])
    for item in graph['supersessions']:
        for key in ('selectedAuthorityId', 'supersededAuthorityId'):
            item[key] = mapping.get(item[key], item[key])
    graph['identitySha256'] = identity(graph, 'identitySha256'); subject['id'] = identity(subject)


def test_complete_32_tier_technical_subject():
    subject = sample()
    assert len(subject['policy']['bonus']['tiers']) == 32
    validate_subject(subject)


def test_v8_not_admitted():
    subject = sample(); subject['evaluatorVersion'] = 'product-terms-engine-v8'; reseal(subject)
    with pytest.raises(ValueError, match='tuple differs'): validate_subject(subject)


def test_assessment_coverage_cannot_substitute_application():
    subject = sample(); authority = subject['authorityGraph']['authorities'][0]
    for coverage in authority['fieldCoverage']:
        if coverage['field'] == 'bonusApplication': coverage['toExclusive'] = subject['scope']['from']
    reseal(subject)
    with pytest.raises(ValueError, match='coverage incomplete'): validate_subject(subject)


def test_application_coverage_cannot_substitute_assessment():
    subject = sample(); authority = subject['authorityGraph']['authorities'][0]
    for coverage in authority['fieldCoverage']:
        if coverage['field'] == 'activityExclusions': coverage['from'] = subject['scope']['from']
    reseal(subject)
    with pytest.raises(ValueError, match='coverage incomplete'): validate_subject(subject)


def test_bonus_boundaries_must_be_ordered():
    subject = sample(); tiers = subject['policy']['bonus']['tiers']; tiers[1]['upperInclusive'] = tiers[0]['upperInclusive']
    reseal(subject)
    with pytest.raises(ValueError, match='ascending cents'): validate_subject(subject)


def test_supersession_cannot_extend_actual_overlap():
    subject = sample(); graph = subject['authorityGraph']; original = graph['authorities'][0]
    other = copy.deepcopy(original); other['from'] = '2026-01-01'
    for coverage in other['fieldCoverage']:
        coverage['from'] = max(coverage['from'], other['from'])
    other['fieldCoverage'] = [x for x in other['fieldCoverage'] if x['from'] < x['toExclusive']]
    other['id'] = identity(other); graph['authorities'].append(other)
    graph['supersessions'] = [{'selectedAuthorityId': original['id'], 'supersededAuthorityId': other['id'],
                              'from': '2025-12-01', 'toExclusive': '2026-01-11',
                              'evidenceIds': [subject['evidence'][0]['id']]}]
    reseal(subject)
    with pytest.raises(ValueError, match='actual authority overlap'): validate_subject(subject)


def test_all_26_material_projections_and_embedded_reference_refusal():
    subject = sample(); fields = set()
    for period in periods(subject):
        for field in period['requiredFields']:
            value = field_value(subject, period, field); fields.add(field)
            value['material']['authorityId'] = period['authorityId']
            with pytest.raises(ValidationError): validate_field_value(value)
    assert len(fields) == 26


def test_semantic_rate_change_is_visible_and_linkage_change_is_separate():
    subject = sample(); period = periods(subject)[0]
    expected = project_field(subject, period, 'bonusRates')
    changed = copy.deepcopy(subject)
    changed['policy']['bonus']['tiers'][0]['evidenceIds'] = ['0' * 64]
    assert project_field(changed, period, 'bonusRates') == expected
    changed['policy']['bonus']['tiers'][0]['annualRate'] = '0.25'
    assert project_field(changed, period, 'bonusRates') != expected
