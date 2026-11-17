"""Typed descriptive criteria; original evidence remains in the lazy fact archive.

This projection does not certify eligibility or execute pricing rules. Decimal
strings preserve source precision, and scoped/conditional facts stay explicit.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re

from cdr_product_facts import compact_facts
from cdr_rate_normalize import rate_divisor

VERSION = 1
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_DURATION = re.compile(r"^P(?:[0-9.]+[YMWD])+(?:T(?:[0-9.]+[HMS])+)?$", re.I)
_MONEY = {"MIN_BALANCE", "MAX_BALANCE", "OPENING_BALANCE", "MIN_LIMIT", "MAX_LIMIT", "MIN_AMOUNT", "MAX_AMOUNT",
          "MINIMUM_BALANCE", "MAXIMUM_BALANCE", "MINIMUM_AMOUNT", "MAXIMUM_AMOUNT"}
_AGES = {"MIN_AGE", "MAX_AGE"}


def decimal_text(raw, divisor=1):
    """Bounded exact conversion; no binary-float round trip or locale guessing."""
    if isinstance(raw, bool) or raw is None or len(str(raw)) > 96:
        return None
    try:
        value = Decimal(str(raw).strip())
        if not value.is_finite() or abs(value.adjusted()) > 96:
            return None
        with localcontext() as context:
            context.prec = 200
            value /= Decimal(str(divisor))
            return format(value, 'f')
    except (InvalidOperation, ValueError):
        return None


def _items(record, name):
    values = record.get(name)
    return enumerate(values) if isinstance(values, list) else ()


def _identity(key, value):
    body = json.dumps([key, value], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(body.encode('utf-8')).hexdigest()[:20]


def _pointer(record, path):
    paths = record.get('_sourcePaths')
    raw = paths.get(path) if isinstance(paths, dict) else None
    if isinstance(raw, str) and re.fullmatch(r'(?:/[A-Za-z0-9_~.-]+)+', raw):
        return raw, 'raw-cdr'
    return path, 'cleaned-cdr'


def _typed(raw, code, *, currency='AUD'):
    if isinstance(raw, bool):
        return raw, 'boolean', 'boolean'
    if raw is None or raw == '':
        return None, 'text', 'text'
    unit = ('year' if code in _AGES else currency if code in _MONEY else
            'fraction' if 'LVR' in code else 'count')
    if isinstance(raw, str) and _DURATION.fullmatch(raw):
        return raw.upper(), 'duration', 'duration'
    value = decimal_text(raw)
    if value is not None:
        return value, unit, 'decimal'
    return str(raw), 'text', 'text'


def _base(record, key, path, kind, canonical, code, *, parent=None, condition=None):
    source, basis = _pointer(record, path)
    value = dict(kind=kind, canonicalKey=canonical, sourceType=code,
                 sourcePath=source, sourcePathBasis=basis, criteriaVersion=VERSION)
    if parent:
        value['parentId'] = parent
    if condition:
        value['condition'] = str(condition)
    value['evidenceState'] = 'conditional' if condition or _qualified(record, path, source, basis) else 'observed'
    for field in ('effectiveFrom', 'effectiveTo'):
        if isinstance(record.get(field), str) and record[field].strip():
            value[field] = record[field]
    # Entity groups intentionally exclude indexes; duplicate occurrences get
    # distinct fact IDs below without collapsing their source paths.
    value['groupId'] = _identity(key, [kind, canonical, parent, condition])[:16]
    return value


def _qualified(record, path, source, basis):
    """A scoped document or unassessed effective date may qualify a scalar."""
    if any(record.get(field) not in (None, '') for field in ('effectiveFrom', 'effectiveTo')):
        return True
    current = record
    try:
        for part in path.strip('/').split('/'):
            current = current[int(part)] if isinstance(current, list) else current[part]
    except (KeyError, IndexError, TypeError, ValueError):
        return True
    if isinstance(current, dict) and any(current.get(field) for field in ('discounts', 'applicabilityConditions')):
        return True
    references = record.get('sourceDocuments')
    for reference in references if isinstance(references, list) else []:
        pointer = reference.get('sourcePath') if isinstance(reference, dict) else None
        if not isinstance(pointer, str):
            continue
        if basis == 'raw-cdr' and (pointer == source or pointer.startswith(source + '/')):
            return True
        if basis != 'raw-cdr' and pointer.startswith('/' + path.strip('/').split('/')[0] + '/'):
            return True  # Legacy compaction cannot identify which entity it qualifies.
    return False


def _value(fact, raw, unit, value_type):
    fact.update(unit=unit, valueType=value_type)
    if raw is not None:
        fact['value'] = raw
    else:
        fact['evidenceState'] = 'unknown'
    return fact


def _boundaries(record, key):
    for group, kind, field in (('eligibility', 'eligibility', 'eligibilityType'),
                               ('constraints', 'constraint', 'constraintType')):
        for index, item in _items(record, group):
            if not isinstance(item, dict):
                continue
            code = item.get(field)
            if not isinstance(code, str) or not _CODE.fullmatch(code):
                continue
            fact = _base(record, key, f'/{group}/{index}', kind,
                         f'{kind}.{code.lower()}', code, condition=item.get('additionalInfo'))
            yield _value(fact, *_typed(item.get('additionalValue'), code,
                                      currency=item.get('currency') or 'AUD'))


def _fee_facts(record, key):
    for index, fee in _items(record, 'fees'):
        if not isinstance(fee, dict):
            continue
        code = str(fee.get('feeType') or 'OTHER')
        if not _CODE.fullmatch(code):
            continue
        # Keep the established fee projection's caps/discount relationships,
        # then replace binary floats with exact source decimal strings.
        projections = compact_facts({'fees': [fee]}, key)
        root = next((fact for fact in projections if fact['kind'] == 'fee' and not fact.get('parentId')), None)
        if root is None:
            continue
        fact = {**root, **_base(record, key, f'/fees/{index}', 'fee',
                               f'fee.{code.lower()}', code, condition=fee.get('additionalInfo'))}
        # Same fee type with a different name/cadence is a distinct occurrence;
        # consumers cannot assume one selected fee represents the whole product.
        fact['groupId'] = _identity(key, ['fee', code, fee.get('name'), fee.get('additionalValue')])[:16]
        method = str(fee.get('feeMethodUType') or '').lower()
        fixed = fee.get('fixedAmount') if isinstance(fee.get('fixedAmount'), dict) else {}
        raw = fee.get('amount') if fee.get('amount') not in (None, '') else fixed.get('amount')
        if method == 'fixedamount' or raw not in (None, ''):
            amount = decimal_text(raw)
            if method == 'variable' or code == 'VARIABLE':
                amount = None  # A placeholder zero is never a free fee.
            _value(fact, amount, str(fee.get('currency') or fixed.get('currency') or 'AUD'), 'decimal')
            if amount is None:
                fact.pop('value', None)
        else:
            # Rate-based/variable unions need their exact source method. The
            # full projection remains available but cannot act as a scalar fee.
            fact.pop('value', None)
            fact['evidenceState'] = 'unknown'
        for field in ('minValue', 'maxValue', 'comparisonValue'):
            fact.pop(field, None)  # Legacy float-derived bounds are not exact.
        yield fact
        for field in ('balanceRate', 'transactionRate', 'accruedRate'):
            if fee.get(field) not in (None, ''):
                child = _base(record, key, f'/fees/{index}', 'fee',
                              f'fee.{code.lower()}.{field}', code,
                              parent=fact['groupId'], condition=fee.get('additionalInfo'))
                yield _value(child, decimal_text(fee[field]), 'fraction', 'decimal')
        rated = fee.get('rateBased')
        if isinstance(rated, dict) and rated.get('rate') not in (None, ''):
            child = _base(record, key, f'/fees/{index}/rateBased', 'fee',
                          f'fee.{code.lower()}.rate', code, parent=fact['groupId'],
                          condition=fee.get('additionalInfo'))
            yield _value(child, decimal_text(rated['rate']), 'fraction', 'decimal')
        for field, canonical, unit in (('feeCap', 'cap', fee.get('currency') or 'AUD'),
                                       ('accrualFrequency', 'accrual_frequency', 'duration'),
                                       ('feeCapPeriod', 'cap_period', 'duration')):
            if fee.get(field) not in (None, ''):
                child = _base(record, key, f'/fees/{index}', 'fee',
                              f'fee.{code.lower()}.{canonical}', code,
                              parent=fact['groupId'], condition=fee.get('additionalInfo'))
                raw = decimal_text(fee[field]) if canonical == 'cap' else str(fee[field])
                yield _value(child, raw, unit, 'decimal' if canonical == 'cap' else 'duration')


def _rates(record, key):
    for name, family, code_field in (('lendingRates', 'lending', 'lendingRateType'),
                                     ('depositRates', 'deposit', 'depositRateType')):
        rates = [item for _, item in _items(record, name) if isinstance(item, dict)]
        divisor = rate_divisor(rates, family)
        for index, rate in _items(record, name):
            if not isinstance(rate, dict):
                continue
            code = str(rate.get(code_field) or 'OTHER')
            if not _CODE.fullmatch(code):
                continue
            fact = _base(record, key, f'/{name}/{index}', 'rate', f'rate.{family}.{code.lower()}',
                         code, condition=rate.get('additionalInfo'))
            fact['groupId'] = _identity(key, ['rate', family, rate])[:16]
            fact['appliesTo'] = [str(rate[field]) for field in ('loanPurpose', 'repaymentType') if rate.get(field)]
            fact['evidenceState'] = 'conditional'  # Never promote one tier to product-wide pricing.
            if rate.get('applicationFrequency'):
                fact['cadence'] = str(rate['applicationFrequency'])
            value = decimal_text(rate.get('rate'), divisor)
            if value is not None and family == 'lending' and Decimal('0') < Decimal(value) < Decimal('.02'):
                value = decimal_text(value, '.1')  # Match the existing export convention.
            yield _value(fact, value, 'fraction', 'decimal')
            for field, suffix, unit in (('comparisonRate', 'comparison', 'fraction'),
                                         ('additionalValue', 'term', 'duration'),
                                         ('calculationFrequency', 'calculation_frequency', 'duration')):
                if rate.get(field) not in (None, ''):
                    child = _base(record, key, f'/{name}/{index}', 'rate',
                                  f'rate.{family}.{code.lower()}.{suffix}', code,
                                  parent=fact['groupId'], condition=rate.get('additionalInfo'))
                    child['evidenceState'] = 'conditional'
                    raw = decimal_text(rate[field], divisor) if unit == 'fraction' else str(rate[field])
                    yield _value(child, raw, unit, 'decimal' if unit == 'fraction' else 'duration')
            yield from _nested(record, key, rate, f'/{name}/{index}', fact['groupId'])


def _nested(record, key, parent, path, parent_id):
    for index, tier in _items(parent, 'tiers'):
        if not isinstance(tier, dict):
            continue
        unit = {'DOLLAR': 'AUD', 'PERCENT': 'fraction'}.get(tier.get('unitOfMeasure'), 'count')
        fact = _base(record, key, f'{path}/tiers/{index}', 'tier', 'tier.range',
                     str(tier.get('rateApplicationMethod') or 'OTHER'), parent=parent_id,
                     condition=tier.get('additionalInfo'))
        fact.update(unit=unit, valueType='decimal', evidenceState='conditional')
        fact['groupId'] = _identity(key, ['tier', parent_id, tier])[:16]
        for field, dest in (('minimumValue', 'minValue'), ('maximumValue', 'maxValue')):
            if (value := decimal_text(tier.get(field))) is not None:
                fact[dest] = value
        yield fact
        yield from _conditions(record, key, tier, f'{path}/tiers/{index}', fact['groupId'])
    yield from _conditions(record, key, parent, path, parent_id)


def _conditions(record, key, parent, path, parent_id):
    conditions = parent.get('applicabilityConditions')
    if isinstance(conditions, dict):
        conditions = [conditions]
    for index, item in enumerate(conditions if isinstance(conditions, list) else []):
        if not isinstance(item, dict):
            continue
        code = str(item.get('rateApplicabilityType') or 'OTHER')
        if not _CODE.fullmatch(code):
            continue
        fact = _base(record, key, f'{path}/applicabilityConditions/{index}', 'condition',
                     f'condition.{code.lower()}', code, parent=parent_id, condition=item.get('additionalInfo'))
        fact['evidenceState'] = 'conditional'
        yield _value(fact, *_typed(item.get('additionalValue'), code))


def criteria_facts(record, product_key):
    """Add comparable descriptions without weakening conservative feature facts."""
    facts = [*_boundaries(record, product_key), *_fee_facts(record, product_key), *_rates(record, product_key)]
    for index, bundle in _items(record, 'bundles'):
        if isinstance(bundle, dict):
            fact = _base(record, product_key, f'/bundles/{index}', 'bundle', 'bundle.linked', 'BUNDLE',
                         condition=bundle.get('additionalInfo') or bundle.get('description'))
            fact['evidenceState'] = 'conditional'
            facts.append(_value(fact, bundle.get('name'), 'text', 'text'))
    occurrences = Counter()
    for fact in facts:
        semantic = {k: v for k, v in fact.items() if k not in {'sourcePath', 'sourcePathBasis'}}
        fingerprint = _identity(product_key, semantic)
        occurrence = occurrences[fingerprint]
        occurrences[fingerprint] += 1
        fact['id'] = _identity(product_key, [fingerprint, occurrence])
    return facts
