"""Technical expectation oracle only. No source approval, database, network or app imports.

Pure Fraction arithmetic; Decimal is used solely for independent rounding self-checks.
The caller supplies already-reviewed coverage for arithmetic tests; this module cannot
establish that coverage or authorize a banking calculation.
"""
from datetime import date, timedelta
from fractions import Fraction as F
import calendar


class Refusal(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise Refusal(code)


def rounded(value, scale, mode):
    require(mode in ('half_up', 'half_even', 'toward_zero'), 'rounding_mode')
    require(type(scale) is int and 0 <= scale <= 12, 'rounding_scale')
    factor = 10 ** scale
    magnitude = abs(value) * factor
    whole, remainder = divmod(magnitude.numerator, magnitude.denominator)
    comparison = 2 * remainder - magnitude.denominator
    up = mode == 'half_up' and comparison >= 0 or mode == 'half_even' and (comparison > 0 or comparison == 0 and whole % 2 == 1)
    return F((whole + int(up)) * (-1 if value < 0 else 1), factor)


def fixed(value, places):
    n = rounded(value, places, 'half_up') * 10 ** places
    n = int(n)
    digits = str(abs(n)).zfill(places + 1)
    return ('-' if n < 0 else '') + (digits[:-places] + '.' + digits[-places:] if places else digits)


def days(start, end):
    current, stop = date.fromisoformat(start), date.fromisoformat(end)
    while current < stop:
        yield current.isoformat()
        current += timedelta(days=1)


def posting_set(policy):
    inventory = policy['postingInventory']
    start, end, rule = inventory['from'], inventory['toExclusive'], inventory['rule']
    if rule['kind'] == 'calendar_month_end':
        expected = [d for d in days(start, end) if date.fromisoformat(d).day == calendar.monthrange(int(d[:4]), int(d[5:7]))[1]]
    else:
        require(rule['kind'] == 'explicit_dated_source_schedule', 'posting_rule')
        require(rule['sourceFrom'] <= start < end <= rule['sourceToExclusive'], 'posting_source_coverage')
        require(len(set(rule['sourceDueDates'])) == len(rule['sourceDueDates']), 'posting_duplicate')
        expected = sorted(d for d in rule['sourceDueDates'] if start <= d < end)
    require(inventory['dueDates'] == expected, 'posting_inventory_incomplete')
    listed = [d for interval in policy['intervals'] for d in interval['interest']['postingDates']]
    require(sorted(listed) == expected and len(set(listed)) == len(listed), 'posting_interval_inventory')
    for interval in policy['intervals']:
        require(all(interval['from'] <= d < interval['toExclusive'] for d in interval['interest']['postingDates']), 'posting_interval_date')
    return set(expected)


def validate(policy, private, completed_through_exclusive):
    start, end = private['startDate'], private['endDateExclusive']
    horizon = (date.fromisoformat(end) - date.fromisoformat(start)).days
    require(0 < horizon <= min(policy['maxHorizonDays'], 366), 'horizon')
    require(end <= completed_through_exclusive, 'completed_period')
    amount = F(private['openingBalance'])
    require(amount >= 0 and amount * 100 == int(amount * 100), 'opening_money')
    for flag in ('openingAccrualZero', 'noMovements', 'noWithholding'):
        require(private.get(flag) is True, 'confirmation:' + flag)
    require(policy['kind'] == 'aud_savings_base_period_v1' and policy['currency'] == 'AUD', 'policy_kind')
    require(policy['fees']['coverage'] == 'reviewed_complete_no_fees', 'fee_coverage')
    for field in ('bonus', 'intro', 'offset', 'linkedAccounts'):
        require(policy[field] == 'none_source_declared', 'unsupported:' + field)
    intervals = policy['intervals']
    require(0 < len(intervals) <= 128, 'interval_count')
    require(intervals[0]['from'] <= start < end <= intervals[-1]['toExclusive'], 'interval_coverage')
    require(policy['postingInventory']['from'] == intervals[0]['from'] and policy['postingInventory']['toExclusive'] == intervals[-1]['toExclusive'], 'posting_scope')
    prior, interest_settings = None, None
    for interval in intervals:
        require(interval['from'] < interval['toExclusive'] and (prior is None or prior == interval['from']), 'interval_gap_overlap')
        prior = interval['toExclusive']
        require(interval['kind'] == 'base' and interval['rateMeaning'] == 'additive', 'component')
        require(interval['allocation'] in ('marginal', 'whole_balance'), 'allocation')
        settings = {k:v for k,v in interval['interest'].items() if k not in ('postingDates', 'evidenceIds')}
        require(interest_settings is None or settings == interest_settings, 'global_interest_policy_changed')
        interest_settings = settings
        require(settings['dayCount'] == 'actual_365_fixed' and settings['postingResidue'] == 'discard_with_rounding_adjustment', 'daycount_residue')
        require(settings['balanceBasis'] == 'closing_balance_before_posted_interest' and settings['postingDestination'] == 'same_account', 'interest_basis')
        if settings['depositSettlementBasis'] == 'cleared_only' and interval['from'] < end and start < interval['toExclusive']:
            require(private.get('openingFundsCleared') is True, 'confirmation:openingFundsCleared')
        previous = F(0)
        for i,tier in enumerate(interval['tiers']):
            require(0 <= F(tier['annualRate']) <= 1, 'rate_fraction')
            upper = tier['upperInclusive']
            if upper is None:
                require(i == len(interval['tiers']) - 1, 'unlimited_tier')
            else:
                edge = F(upper)
                require(edge > previous and edge * 100 == int(edge * 100) and i != len(interval['tiers']) - 1, 'tier_edge')
                previous = edge
    rates = [t['annualRate'] for i in intervals for t in i['tiers']]
    require(private['confirmedAnnualRates'] == rates, 'rate_confirmation')
    return amount, posting_set(policy)


def interest_for_day(balance, interval):
    settings = interval['interest']
    tiers = interval['tiers']
    edges = [F(0)] + [F(t['upperInclusive']) for t in tiers[:-1]]
    if interval['allocation'] == 'whole_balance':
        chosen = next(i for i,t in enumerate(tiers) if t['upperInclusive'] is None or balance <= F(t['upperInclusive']))
        portions = [(tiers[chosen], balance)]
    else:
        portions = [(tier, max(F(0), min(balance, F(tier['upperInclusive']) if tier['upperInclusive'] is not None else balance) - lower)) for lower,tier in zip(edges, tiers)]
    accruals, contributions = [], []
    for tier, basis in portions:
        daily = F(tier['annualRate']) / 365
        rounding = settings['dailyRateRounding']
        if rounding is not None:
            units = 100 if rounding['unit'] == 'percent' else 1
            daily = rounded(daily * units, rounding['scale'], rounding['mode']) / units
        interest = basis * daily
        if settings['dailyAccrualRounding'] == 'per_tier' and settings['dailyAccrualScale'] is not None:
            interest = rounded(interest, settings['dailyAccrualScale'], settings['accrualRounding'])
        accruals.append(interest)
        if basis or not contributions and balance == 0:
            contributions.append({'tierId':tier['id'], 'basis':fixed(basis,2), 'annualRate':tier['annualRate'], 'accrual':fixed(interest,12)})
    total = sum(accruals, F(0))
    if settings['dailyAccrualRounding'] == 'aggregate' and settings['dailyAccrualScale'] is not None:
        total = rounded(total, settings['dailyAccrualScale'], settings['accrualRounding'])
    return total, contributions


def evaluate(policy, private, *, completed_through_exclusive):
    """Return technical expectation only; caller must verify source/approval separately."""
    try:
        balance, postings = validate(policy, private, completed_through_exclusive)
        opening = balance
        accrued = unposted = posted = F(0)
        ledger, daily = [], []
        for day in days(private['startDate'], private['endDateExclusive']):
            interval = next(i for i in policy['intervals'] if i['from'] <= day < i['toExclusive'])
            basis = balance
            earned, contributions = interest_for_day(balance, interval)
            accrued += earned
            unposted += earned
            ledger.append({'date':day, 'type':'interest_accrual', 'amount':fixed(earned,12), 'balance':fixed(balance,2)})
            if day in postings:
                payment = rounded(unposted, 2, interval['interest']['postingRounding'])
                balance += payment
                posted += payment
                unposted = F(0)
                ledger.append({'date':day, 'type':'interest_posting', 'amount':fixed(payment,2), 'balance':fixed(balance,2)})
            daily.append({'date':day,'intervalId':interval['id'],'basis':fixed(basis,2),'contributions':contributions,'accrual':fixed(earned,12),'accrued':fixed(accrued,12),'unposted':fixed(unposted,12),'posted':fixed(posted,2),'roundingAdjustment':fixed(posted+unposted-accrued,12),'closingPostedBalance':fixed(balance,2)})
        totals = {'openingBalance':fixed(opening,2), 'interestAccrued':fixed(accrued,12), 'interestPosted':fixed(posted,2), 'interestUnposted':fixed(unposted,12), 'closingBalance':fixed(balance,2), 'interestRoundingAdjustment':fixed(posted+unposted-accrued,12), 'feesCharged':'0.00', 'externalCashflowNet':'0.00'}
        return {'kind':'technical_calculation', 'totals':totals, 'ledger':ledger, 'daily':daily, 'exact':{'interestAccrued':str(accrued), 'interestUnposted':str(unposted), 'roundingAdjustment':str(posted+unposted-accrued)}}
    except Refusal as error:
        return {'kind':'technical_refusal', 'reason':str(error)}
