import pytest
import copy
from tests.executable_v3_fixture import subject,reidentify
from cdr_terms.executable_v3_contract import validate_subject


def test_structured_technical_contract():
    validate_subject(subject())


def test_adjacent_ranges_union_distinct_required_evidence():
    value=subject();authority=value['authorityGraph']['authorities'][0]
    evidence=copy.deepcopy(value['evidence'][0]);evidence['id']='f'*64;evidence['clauseId']='f'*64
    value['evidence'].append(evidence)
    coverage=next(x for x in authority['fieldCoverage'] if x['field']=='rates')
    later=copy.deepcopy(coverage);later['from']='2026-01-05';later['evidenceIds']=[evidence['id']]
    coverage['toExclusive']='2026-01-05';authority['fieldCoverage'].append(later)
    value['policy']['intervals'][0]['fieldEvidenceIds']['rates'].append(evidence['id'])
    reidentify(value);validate_subject(value)


@pytest.mark.parametrize('change,match',[
 (lambda s:s['policy']['postingInventory'].update(dueDates=[]),'posting inventory'),
 (lambda s:s['policy']['intervals'][0].update(toExclusive='2026-01-09'),'posting dates'),
 (lambda s:s['policy']['intervals'][0]['tiers'][0].update(upperInclusive='0'),'tier edge'),
 (lambda s:s['authorityGraph']['authorities'][0]['fieldCoverage'].pop(),'field coverage'),
 (lambda s:s['authorityGraph']['members'][0].update(sha256='f'*64),'authority missing'),
 (lambda s:s['policy']['inputDefinitions'][0].update(binding='customer_fact'),'required local'),
])
def test_reidentified_semantic_counterexample(change,match):
    value=subject();change(value);reidentify(value)
    with pytest.raises(ValueError,match=match):validate_subject(value)
