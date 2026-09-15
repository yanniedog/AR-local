"""Verify actual mortgage adapter propagation before independent arithmetic."""
from .identity import digest
from .executable_v2_inputs import exact_object
from .executable_eligibility import verify_eligibility
from .mortgage_inputs import facts,require_offer_facts
from .mortgage_projection import projection


def validate_result(result,subject,raw):
    exact_object(raw,('target','inputs','profile'),'mortgage raw call')
    exact_object(result,('schemaVersion','evaluationKind','adapterVersion','evaluatorVersion','verificationScope','basis','adapterInputs','inputSha256','calculationInputs','receipt'),'mortgage result')
    if type(result['schemaVersion']) is not int or result['schemaVersion']!=1 or result['evaluationKind']!=subject['capability'] or any(result[k]!=subject[k] for k in ('adapterVersion','evaluatorVersion')):raise ValueError('Mortgage result version differs')
    if (result['verificationScope']!='Current publication and approved structured source policy verified on-device; original source bytes and typed material revisions verified by producer.'
        or result['basis']!='User-reported historical loan period. Obligations are separate from cleared payments; external fees are separate from loan cashflows. No credit approval or full portfolio comparison.'):
        raise ValueError('Mortgage result verification scope or basis differs')
    value=result['adapterInputs'];exact_object(value,('subject','approval','binding','target','inputs','customerAnswers','facts'),'mortgage adapter input')
    derived,answers=facts(subject,raw['inputs'],raw['profile']);require_offer_facts(subject,derived)
    if any(digest(value[k])!=digest(v) for k,v in (('subject',subject),('target',raw['target']),('inputs',raw['inputs']),('facts',derived),('customerAnswers',answers))) or result['inputSha256']!=digest(value):raise ValueError('Mortgage raw adapter input propagation differs')
    expected=projection(subject,raw['inputs'],value['binding'],value['approval'],derived)
    if digest(result['calculationInputs'])!=digest(expected):raise ValueError('Mortgage actual contract/scenario projection differs')
    receipt=result['receipt']
    if receipt['inputSha256']!=digest(dict(evaluatorVersion=subject['evaluatorVersion'],**expected)) or receipt['contractId']!=subject['id'] or receipt['dependencies']!=expected['contract']['dependencyIds'] or receipt['eligibility']!=verify_eligibility(subject['policy']['eligibility'],derived):raise ValueError('Mortgage evaluator input/eligibility differs')
