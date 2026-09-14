"""Narrow evidence-only taxonomy rules for the retained 2026-05-13 observation.

These are classification rules, never eligibility or pricing rules. Missing or
unreviewed material dimensions produce no path. In particular there is no name,
date, twelve-month, unspecified-LVR, flat-balance or account-kind fallback.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

RULE_VERSION = 'may13-embedded-taxonomy-v2'
_DURATION = re.compile(r'P([1-9][0-9]*)(M|Y)')
_AMOUNT_NAME = re.compile(
    r'([1-9][0-9]*) (Month|Year) Term \$[0-9.]+ to less than \$[0-9.]+ '
    r'(Interest on Maturity|([1-9][0-9]*) Monthly Interest)')
_LVR_PATTERNS = (
    r'Under (?P<hi>[0-9.]+)% LVR inc LMI',
    r'LVR greater than (?P<lo>[0-9.]+)% and less than or equal to (?P<hi>[0-9.]+)% inc LMI',
    r'LVR up to (?P<hi>[0-9.]+)%',
    r'LVR (?P<lo>[0-9.]+)% up to (?P<hi>[0-9.]+)%',
    r'LVR (?P<hi>[0-9.]+)% or less',
)
_MORTGAGE_INFO = {
    '', 'New business rates, fees and charges apply',
    'Only available to AMP shareholders and AMP employees who apply directly through AMP Bank',
    'Up to 5 year interest only period. New business rates, fees and charges apply',
    'Greater than 5 years to up to 10 years interest only period. New business rates, fees and charges apply',
    'Construction is for up to 12 month period. Revert-to product is selected up front. '
    'New business rates, fees and charges apply',
}
_NEW_ACCOUNTS_CONTEXT = {'additionalInfo': 'New business rate',
                         'rateApplicabilityType': 'NEW_ACCOUNTS'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def months(value):
    match = _DURATION.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return None
    result = int(match[1]) * (12 if match[2] == 'Y' else 1)
    return result if result <= 1200 else None


def _proof(dimension, value, pointers, raw):
    evidence = []
    for pointer in pointers:
        selected = raw
        for key in pointer.strip('/').split('/'):
            selected = selected[int(key)] if isinstance(selected, list) else selected[key]
        evidence.append({'pointer': pointer, 'value': selected, 'value_sha256': digest(selected)})
    return {'dimension': dimension, 'value': value, 'evidence': evidence}


def _applicability(rate, prefix, raw):
    """Inspect both rate and tier clauses; unknown conditions block a path.

    The sole reviewed exemption names new accounts without modifying a
    taxonomy dimension. It is context, never proof of customer eligibility.
    Nested payment prose is not interpreted or overridden by top-level enums.
    """
    evidence, reasons = [], []
    locations = [(rate, prefix)] + [(tier, f'{prefix}/tiers/{index}')
                                  for index, tier in enumerate(rate.get('tiers', []))]
    for item, location in locations:
        if 'applicabilityConditions' not in item:
            continue
        conditions = item['applicabilityConditions']
        pointer = f'{location}/applicabilityConditions'
        if not isinstance(conditions, list):
            reasons.append('applicability_conditions_invalid_shape')
            evidence.append(_proof('unreviewed_applicability_context', 'UNKNOWN', [pointer], raw))
            continue
        for index, condition in enumerate(conditions):
            reviewed = digest(condition) == digest(_NEW_ACCOUNTS_CONTEXT)
            if not reviewed:
                reasons.append('rate_or_tier_applicability_requires_review')
            evidence.append(_proof('reviewed_applicability_context' if reviewed
                                   else 'unreviewed_applicability_context',
                                   'NEW_ACCOUNTS_CONTEXT_ONLY' if reviewed else 'UNKNOWN',
                                   [f'{pointer}/{index}'], raw))
    return evidence, reasons


def _lvr(rate, prefix, raw):
    tiers = rate.get('tiers', [])
    percent = [(i, tier) for i, tier in enumerate(tiers)
               if isinstance(tier, dict) and tier.get('unitOfMeasure') == 'PERCENT']
    if len(percent) != 1:
        return None, 'lvr_requires_one_reviewed_percent_tier'
    index, tier = percent[0]
    match = next((match for pattern in _LVR_PATTERNS
                  if (match := re.fullmatch(pattern, str(tier.get('name', ''))))), None)
    if match is None:
        return None, 'lvr_tier_text_unreviewed'
    lo, hi = decimal(tier.get('minimumValue')), decimal(tier.get('maximumValue'))
    text_hi = decimal(match['hi'])
    text_lo = decimal(match.groupdict().get('lo') or '0')
    if lo is None or hi is None or text_hi is None or text_lo is None:
        return None, 'lvr_invalid_bounds'
    # Corroborate both endpoints with explicit percent text. Never choose a
    # scale from numeric magnitude; sources contain both percent conventions.
    scales = [scale for scale in (Decimal(1), Decimal(100))
              if lo * scale == text_lo and hi * scale == text_hi]
    if len(scales) != 1 or not 0 <= text_lo < text_hi <= 95:
        return None, 'lvr_text_and_numeric_bounds_conflict'
    names = [(60, 'LVR_LE60'), (70, 'LVR_60_70'), (80, 'LVR_70_80'),
             (85, 'LVR_80_85'), (90, 'LVR_85_90'), (95, 'LVR_90_95')]
    token = next(token for upper, token in names if text_hi <= upper)
    # Consumer taxonomy uses the bucket of the upper LVR boundary, not an
    # exact applicability interval. Retain both actual bounds in its receipt.
    proof = _proof('lvr_upper_boundary_bucket', token, [f'{prefix}/tiers/{index}'], raw)
    proof.update({'minimum_percent': str(text_lo), 'maximum_percent': str(text_hi),
                  'numeric_scale_corroborated_by_text': str(scales[0])})
    return proof, None


def _term(rate, prefix, raw, *, mortgage=False):
    term = months(rate.get('additionalValue'))
    if term is None or (mortgage and term not in {12, 24, 36, 48, 60}):
        return None, 'term_requires_supported_explicit_month_duration'
    pointers = [f'{prefix}/additionalValue']
    for i, tier in enumerate(rate.get('tiers', [])):
        unit = tier.get('unitOfMeasure')
        if unit not in {'MONTH', 'DAY'}:
            continue
        if unit != 'MONTH' or decimal(tier.get('minimumValue')) != term or decimal(
                tier.get('maximumValue')) != term:
            return None, 'term_range_day_unit_or_conflicting_bounds'
        pointers.append(f'{prefix}/tiers/{i}')
    # A duration mentioned in additionalInfo may be a different condition or a
    # range. This narrow rule deliberately refuses it rather than extracting it.
    if re.search(r'\b\d+\s*[- ]?\s*(?:month|year|day|week)',
                 str(rate.get('additionalInfo', '')), re.I):
        return None, 'term_free_text_requires_review'
    return _proof('term_months', term, pointers, raw), None


def _mortgage(raw, rate, prefix):
    evidence, reasons = [], []
    if rate.get('additionalInfo', '') not in _MORTGAGE_INFO:
        reasons.append('mortgage_additional_info_requires_review')
    # This reviewed prose concerns cohort, IO period or construction, not a
    # substitute for one of the required enum/bound dimensions. Other prose
    # includes material LVR exceptions and is deliberately not auto-classified.
    elif 'additionalInfo' in rate:
        evidence.append(_proof('reviewed_rate_context', rate['additionalInfo'],
                               [f'{prefix}/additionalInfo'], raw))
    offset = len(evidence)
    maps = [('loan_purpose', 'loanPurpose', {'OWNER_OCCUPIED': 'OO', 'INVESTMENT': 'INV'}),
            ('repayment', 'repaymentType', {'PRINCIPAL_AND_INTEREST': 'PI', 'INTEREST_ONLY': 'IO'}),
            ('rate_structure', 'lendingRateType', {'VARIABLE': 'VARIABLE', 'FIXED': 'FIXED'})]
    for dimension, key, mapping in maps:
        value = mapping.get(rate.get(key))
        if value is None:
            reasons.append(f'{dimension}_unsupported_or_missing')
        else:
            evidence.append(_proof(dimension, value, [f'{prefix}/{key}'], raw))
    if rate.get('lendingRateType') == 'FIXED':
        term, reason = _term(rate, prefix, raw, mortgage=True)
        if reason:
            reasons.append(reason)
        else:
            evidence.append(term)
    lvr, reason = _lvr(rate, prefix, raw)
    if reason:
        reasons.append(reason)
    else:
        evidence.append(lvr)
    if reasons:
        return None, evidence, reasons
    parts = ['HOME_LOAN'] + [item['value'] for item in evidence[offset:offset + 3]]
    if rate['lendingRateType'] == 'FIXED':
        parts.append(f"{evidence[offset + 3]['value']}M")
    return '.'.join(parts + [lvr['value']]), evidence, []


def _td_tiers(rate, prefix, raw, term, payment):
    evidence, dollar_count = [], 0
    for i, tier in enumerate(rate.get('tiers', [])):
        if tier.get('unitOfMeasure') == 'MONTH':
            continue  # Already checked against exact duration by _term.
        if tier.get('unitOfMeasure') != 'DOLLAR':
            return None, 'balance_tier_unit_unreviewed'
        lo, hi = decimal(tier.get('minimumValue')), decimal(tier.get('maximumValue'))
        if lo is None or hi is None or not 0 <= lo < hi:
            return None, 'balance_requires_explicit_valid_bounds'
        if tier.get('rateApplicationMethod') not in {'WHOLE_BALANCE', 'PER_TIER'}:
            return None, 'balance_application_method_unreviewed'
        # Exact reviewed text grammar corroborates duration and payment rather
        # than treating a payment interval as the term (present in AMP source).
        name = str(tier.get('name', ''))
        match = _AMOUNT_NAME.fullmatch(name)
        if match:
            named_months = int(match[1]) * (12 if match[2] == 'Year' else 1)
            named_payment = 'AT_MATURITY' if match[3] == 'Interest on Maturity' else {
                '1': 'MONTHLY', '3': 'QUARTERLY', '12': 'ANNUALLY'}.get(match[4])
            if term != named_months or payment != named_payment:
                return None, 'term_or_payment_conflicts_with_tier_text'
        elif name.upper() not in {'AMOUNT', 'BALANCE'}:
            return None, 'balance_tier_text_unreviewed'
        evidence.append(f'{prefix}/tiers/{i}')
        dollar_count += 1
    if dollar_count != 1:
        return None, 'balance_requires_one_explicit_dollar_tier_no_flat_default'
    return _proof('balance_structure', 'TIERED', evidence, raw), None


def _td(raw, rate, prefix):
    evidence, reasons = [], []
    if rate.get('depositRateType') != 'FIXED':
        reasons.append('deposit_rate_structure_unreviewed')
    else:
        evidence.append(_proof('rate_structure', 'FIXED', [f'{prefix}/depositRateType'], raw))
    term, reason = _term(rate, prefix, raw)
    if reason:
        reasons.append(reason)
    else:
        evidence.append(term)
    payment = None
    pointers = [f'{prefix}/applicationType']
    if rate.get('applicationType') == 'MATURITY':
        payment = 'AT_MATURITY'
    elif rate.get('applicationType') == 'PERIODIC':
        payment = {'P1M': 'MONTHLY', 'P3M': 'QUARTERLY', 'P1Y': 'ANNUALLY',
                   'P12M': 'ANNUALLY'}.get(rate.get('applicationFrequency'))
        pointers.append(f'{prefix}/applicationFrequency')
    if payment is None:
        reasons.append('payment_type_or_frequency_unsupported_or_missing')
    else:
        evidence.append(_proof('interest_payment', payment, pointers, raw))
    # Additional payment prose can describe exceptions to the enum (including
    # annual payments on a MATURITY row). No such prose is auto-authorized.
    if rate.get('additionalInfo') not in (None, ''):
        reasons.append('deposit_additional_info_requires_review')
    balance, reason = _td_tiers(rate, prefix, raw, term['value'] if term else None, payment)
    if reason:
        reasons.append(reason)
    else:
        evidence.append(balance)
    if reasons:
        return None, evidence, reasons
    return f"TERM_DEPOSIT.{term['value']}M.{payment}.TIERED", evidence, []


def classify(raw, family, index):
    """Return supported dimensions and reasons even when no complete path exists.

    Pointers address the decoded embedded details_json data object, not original
    HTTP wire bytes. index is zero-based and is bound by the candidate builder.
    """
    array = {'lending': 'lendingRates', 'deposit': 'depositRates'}.get(family)
    if array is None or type(index) is not int or index < 0:
        raise ValueError('invalid raw rate identity')
    rate, prefix = raw[array][index], f'/{array}/{index}'
    category = raw.get('productCategory')
    evidence = [_proof('product_category', category, ['/productCategory'], raw)]
    if category == 'RESIDENTIAL_MORTGAGES' and family == 'lending':
        path, dimensions, reasons = _mortgage(raw, rate, prefix)
    elif category == 'TERM_DEPOSITS' and family == 'deposit':
        path, dimensions, reasons = _td(raw, rate, prefix)
    elif category == 'TRANS_AND_SAVINGS_ACCOUNTS':
        path, dimensions, reasons = None, [], ['savings_account_kind_and_component_semantics_unreviewed']
    else:
        path, dimensions, reasons = None, [], ['category_or_rate_family_unreviewed']
    applicability, applicability_reasons = _applicability(rate, prefix, raw)
    return {'taxonomy_path': None if applicability_reasons else path,
            'dimensions': evidence + dimensions + applicability,
            'unresolved_reasons': sorted(set(reasons + applicability_reasons)), 'rule_version': RULE_VERSION}
