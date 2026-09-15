"""Verify the neutral adapter's material contract, independently of receipt claims."""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
import re


def material_contract(template, principal, funded, maturity):
    """Exact source-derived contract fields; customer values remain private."""
    t, refs = template, template['fieldClauseIds']
    all_refs = list(dict.fromkeys(value for values in refs.values() for value in values))
    end = (date.fromisoformat(maturity) + timedelta(days=1)).isoformat()
    account = 'td_' + t['id']
    return dict(schemaVersion=1, evaluatorVersion=t['evaluatorVersion'], id=t['id'], productId=t['productKey'],
        direction='asset', currency='AUD', applicability={'cohortKey': t['cohortKey'], 'from': funded, 'toExclusive': end},
        evidence=t['evidence'], unsupportedTerms=[], eligibility=t['eligibility'],
        initialAnnualRate=t['annualRate'], initialRateEvidenceIds=refs['annualRate'],
        interest={**t['interest'], 'balanceBasis': 'closing_balance_before_posted_interest',
            'eventOrder': 'ordered_events_then_accrual_then_posting', 'postingDates': [], 'offset': 'none', 'evidenceIds': all_refs},
        feeSchedule=dict(schemaVersion=1, accountId=account, **{'from': funded}, toExclusive=end,
            inventoryCoverage='reviewed_complete', deferredObligations='none_confirmed', evidenceIds=refs['feeDisposition'],
            ordering='before_scenario_events', inventory=[dict(categoryId='all_fees', state='none_applicable', feeIds=[], evidenceIds=refs['feeDisposition'])], fees=[]),
        tdLifecycle=dict(schemaVersion=1, mode='fixed_maturity', cohortKey=t['cohortKey'], evidenceIds=all_refs,
            confirmationEvidenceIds=[], investmentAmount=principal, fundedDate=funded, accrualStartDate=funded,
            term=t['term'], nominalMaturityDate=maturity, calendar=None, roundingReviewed=True, taxTreatment='none_confirmed',
            payments=dict(cadence='maturity', destination='linked_account', firstPeriodEnd=None,
                monthConvention=t['term']['monthConvention'], periodEnds=[], evidenceIds=refs['postingPolicy']),
            closure=dict(kind='maturity', confirmedDate=maturity, acceptedNoticeDate=None, feeDecision='waived',
                principalRecovery='unknown', evidenceIds=refs['postingPolicy'])))


def validate_instantiated_input(template, inputs, *, complete=True):
    contract, scenario = inputs.get('contract'), inputs.get('scenario')
    if not isinstance(contract, dict) or not isinstance(scenario, dict):
        raise ValueError('Executable instantiated contract/scenario required')
    lifecycle = contract.get('tdLifecycle') or {}
    try:
        principal = lifecycle['investmentAmount']
        amount = Decimal(principal)
        start = date.fromisoformat(lifecycle['fundedDate'])
        end = date.fromisoformat(lifecycle['nominalMaturityDate'])
        term = template['term']
        if term['unit'] == 'days':
            expected_end = start + timedelta(days=term['count'])
        else:
            month = start.year * 12 + start.month - 1 + term['count']
            year, month = divmod(month, 12)
            last = monthrange(year, month + 1)[1]
            day = last if term['monthConvention'] == 'preserve_month_end' and start.day == monthrange(start.year, start.month)[1] else min(start.day, last)
            expected_end = date(year, month + 1, day)
        if (not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal('.01'))
                or end != expected_end or not 0 < (end - start).days <= 3660
                or not template['effectiveFrom'] <= start.isoformat() < template['effectiveToExclusive']
                or template['effectiveScope'] == 'whole_accrual_horizon' and end.isoformat() > template['effectiveToExclusive']):
            raise ValueError('Executable instantiated term/amount/applicability mismatch')
        for kind, bound in template['principalBounds'].items():
            if 'value' in bound:
                value = Decimal(bound['value'])
                if (amount < value if kind == 'minimum' else amount > value) or amount == value and not bound['inclusive']:
                    raise ValueError('Executable instantiated amount outside source tier')
        expected = material_contract(template, principal, start.isoformat(), end.isoformat())
    except (KeyError, TypeError, ArithmeticError) as error:
        raise ValueError('Executable instantiated material fields missing') from error
    if set(contract) != set(expected) | {'review', 'dependencyIds'}:
        raise ValueError('Executable instantiated contract shape mismatch')
    for key, value in expected.items():
        actual = contract[key]
        if key == 'initialAnnualRate':
            if Decimal(actual) == Decimal(value):
                continue
        if actual != value:
            raise ValueError('Executable instantiated material field mismatch: ' + key)
    review = contract['review']
    if (not isinstance(review, dict) or set(review) != {'applicability', 'materialTerms', 'feeCoverage', 'rateSchedule', 'benchmarkSha256'}
            or any(review[key] != 'verified' for key in ('applicability', 'materialTerms', 'feeCoverage', 'rateSchedule'))):
        raise ValueError('Executable instantiated review fields mismatch')
    dependencies = contract['dependencyIds']
    required = {template['id'], template['sourceObservationId'], template['sourceSha256'],
                *template['documentVersionIds'], *template['termRevisionIds']}
    if not isinstance(dependencies, list) or not required <= set(dependencies):
        raise ValueError('Executable instantiated source dependencies missing')
    validate_scenario(template, contract, scenario, complete=complete)


def validate_scenario(template, contract, scenario, *, complete):
    lifecycle = contract['tdLifecycle']
    fixed = {'accountId': 'td_' + template['id'], 'productId': template['productKey'],
             'cohortKey': template['cohortKey'], 'startDate': lifecycle['fundedDate'],
             'endDateExclusive': contract['applicability']['toExclusive'], 'initialOffset': '0',
             'events': [], 'assumptions': []}
    if set(scenario) != set(fixed) | {'openingBalance', 'facts', 'tdConfirmation'} or any(scenario[k] != value for k, value in fixed.items()):
        raise ValueError('Executable scenario fixed adapter structure mismatch')
    facts = scenario['facts']
    definitions = {item['key']: item for item in template['inputDefinitions']}
    if not isinstance(facts, dict) or not set(facts) <= set(definitions):
        raise ValueError('Executable scenario facts are not reviewed inputs')
    for key, definition in definitions.items():
        fact = facts.get(key)
        if fact is None and definition['binding'] == 'customer_fact':
            continue
        kind = definition['type']
        if (not isinstance(fact, dict) or set(fact) != ({'type', 'value', 'unit'} if kind == 'decimal' else {'type', 'value'})
                or fact['type'] != kind or kind == 'decimal' and fact['unit'] != definition['unit']):
            raise ValueError('Executable scenario fact type/unit mismatch')
        value = fact['value']
        if kind == 'decimal' and (not isinstance(value, str) or not re.fullmatch(r'-?[0-9]{1,32}(?:\.[0-9]{1,12})?', value)):
            raise ValueError('Executable scenario decimal fact malformed')
        if kind == 'boolean' and type(value) is not bool or kind in {'text', 'date'} and not isinstance(value, str):
            raise ValueError('Executable scenario typed fact malformed')
        if kind == 'date':
            date.fromisoformat(value)
        expected = {'deposit_principal': scenario['openingBalance'], 'funded_date': lifecycle['fundedDate'],
                    'maturity_date': lifecycle['nominalMaturityDate']}.get(definition['binding'])
        if complete and expected is not None and (Decimal(value) != Decimal(expected) if kind == 'decimal' else value != expected):
            raise ValueError('Executable scenario-owned fact binding mismatch')
    if complete:
        confirmation = scenario['tdConfirmation']
        if (not isinstance(confirmation, dict) or Decimal(scenario['openingBalance']) != Decimal(lifecycle['investmentAmount'])
                or Decimal(confirmation.get('principal', 'NaN')) != Decimal(lifecycle['investmentAmount'])
                or confirmation.get('fundedDate') != lifecycle['fundedDate']
                or confirmation.get('maturityDate') != lifecycle['nominalMaturityDate']):
            raise ValueError('Executable complete scenario confirmation differs from contract')
