"""Retained local adapter inputs remain private and bind opened-rate propagation."""
import re
from datetime import date, datetime
from decimal import Decimal


def validate_adapter_input(local, inputs, template, result, execution_kind):
    if (execution_kind not in {'adapter_and_evaluator', 'evaluator_fault_injection'}
            or result['status'] == 'complete' and execution_kind != 'adapter_and_evaluator'):
        raise ValueError('Executable adapter execution kind mismatch')
    fields = {'principal', 'confirmedAnnualRate', 'fundedDate', 'maturityDate',
              'confirmed', 'confirmedAt', 'noWithholdingConfirmed'}
    if not isinstance(local, dict) or set(local) != fields:
        raise ValueError('Executable raw adapter input shape mismatch')
    if (local['confirmed'] is not True or local['noWithholdingConfirmed'] is not True
            or not isinstance(local['principal'], str)
            or not re.fullmatch(r'(?:0|[1-9][0-9]{0,31})(?:\.[0-9]{1,2})?', local['principal'])
            or Decimal(local['principal']) <= 0):
        raise ValueError('Executable raw adapter confirmation/amount invalid')
    rate = local['confirmedAnnualRate']
    if not isinstance(rate, str) or not re.fullmatch(r'(?:0(?:\.[0-9]{1,12})?|1(?:\.0{1,12})?)', rate):
        raise ValueError('Executable raw adapter opened rate malformed')
    for key in ('fundedDate', 'maturityDate'):
        if not isinstance(local[key], str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', local[key]):
            raise ValueError('Executable raw adapter date malformed')
        date.fromisoformat(local[key])
    if (not isinstance(local['confirmedAt'], str)
            or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,3})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])', local['confirmedAt'])
            or datetime.fromisoformat(local['confirmedAt'].replace('Z', '+00:00')).tzinfo is None):
        raise ValueError('Executable raw adapter confirmation time invalid')
    scenario = inputs['scenario']
    confirmation = scenario.get('tdConfirmation')
    required = {'source', 'recordedAt', 'principal', 'fundedDate', 'maturityDate', 'noWithholding', 'annualRate'}
    if not isinstance(confirmation, dict) or set(confirmation) != required:
        raise ValueError('Executable propagated adapter confirmation shape mismatch')
    if any(not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,32}(?:\.[0-9]{1,2})?', value)
           for value in (confirmation['principal'], scenario['openingBalance'])):
        raise ValueError('Executable propagated adapter principal malformed')
    if (confirmation['source'] != 'user_supplied_bank_confirmation'
            or confirmation['noWithholding'] is not True
            or confirmation['recordedAt'] != local['confirmedAt']
            or confirmation['fundedDate'] != local['fundedDate']
            or confirmation['maturityDate'] != local['maturityDate']
            or scenario['startDate'] != local['fundedDate']
            or Decimal(confirmation['principal']) != Decimal(local['principal'])
            or Decimal(scenario['openingBalance']) != Decimal(local['principal'])
            or not isinstance(confirmation['annualRate'], str)
            or not re.fullmatch(r'(?:0(?:\.[0-9]{1,12})?|1(?:\.0{1,12})?)', confirmation['annualRate'])
            or Decimal(confirmation['annualRate']) != Decimal(rate)):
        raise ValueError('Executable raw adapter input propagation mismatch')
    contract = inputs['contract']
    whole, _, fraction = local['principal'].partition('.')
    canonical_principal = whole + '.' + fraction.ljust(2, '0')
    if any(value != canonical_principal for value in (
            confirmation['principal'], scenario['openingBalance'], contract['tdLifecycle']['investmentAmount'])):
        raise ValueError('Executable raw adapter principal differs from lifecycle')
    raw_facts = {'deposit_principal': local['principal'], 'funded_date': local['fundedDate'],
                 'maturity_date': local['maturityDate']}
    for definition in template['inputDefinitions']:
        if definition['binding'] in raw_facts:
            fact = scenario['facts'].get(definition['key'])
            if not isinstance(fact, dict) or fact.get('value') != raw_facts[definition['binding']]:
                raise ValueError('Executable raw scenario-owned fact propagation mismatch')
    if confirmation['maturityDate'] != contract['tdLifecycle']['nominalMaturityDate']:
        raise ValueError('Executable raw adapter maturity propagation mismatch')
    return (result['status'] == 'unsupported' and execution_kind == 'evaluator_fault_injection'
            and result['issues'] == ['td_confirmed_rate_mismatch']
            and Decimal(rate) != Decimal(template['annualRate'])
            and Decimal(contract['initialAnnualRate']) == Decimal(template['annualRate']))
