"""Independent receipt verification oracle for the retained eligibility.ts contract.

This verifies eligibility traces; it is not a producer financial execution engine.
"""
import re
from datetime import date
from decimal import Decimal


def _decimal(value):
    if (not isinstance(value, str) or len(value) > 72
            or not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,24})?', value)):
        raise ValueError('invalid_decimal')
    return Decimal(value)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError('invalid_calendar_date')
    parsed = date.fromisoformat(value)
    if not 1900 <= parsed.year <= 2200:
        raise ValueError('calendar_year_unsupported')
    return parsed


def _compare(actual, expected):
    if not isinstance(actual, dict) or not isinstance(expected, dict) or actual.get('type') != expected.get('type'):
        raise ValueError('fact_type_mismatch')
    kind = actual.get('type')
    if kind == 'decimal':
        if not actual.get('unit') or actual.get('unit') != expected.get('unit'):
            raise ValueError('fact_unit_mismatch')
        left, right = _decimal(actual.get('value')), _decimal(expected.get('value'))
    elif kind == 'date':
        left, right = _date(actual.get('value')), _date(expected.get('value'))
    elif kind in {'boolean', 'text'}:
        wanted = bool if kind == 'boolean' else str
        left, right = actual.get('value'), expected.get('value')
        if type(left) is not wanted or type(right) is not wanted:
            raise ValueError('invalid_fact')
    else:
        raise ValueError('fact_type_unsupported')
    return 0 if left == right else -1 if left < right else 1


def verify_eligibility(rule, facts):
    """Match the app's three-valued result, including ordered reasons and full trace."""
    nodes, reasons, seen = 0, [], set()
    def visit(item, depth):
        nonlocal nodes
        item = item if isinstance(item, dict) else {}
        identity = item.get('id') if isinstance(item.get('id'), str) else 'invalid_rule'
        evidence = item.get('evidenceIds') if isinstance(item.get('evidenceIds'), list) else []
        base = {'id': identity, 'evidenceIds': evidence}
        def unknown(reason):
            reasons.append(reason)
            return {**base, 'status': 'needs_information', 'reason': reason}
        nodes += 1
        if nodes > 512 or depth > 16:
            return unknown('rule_limit_exceeded')
        if not item.get('id') or identity in seen:
            return unknown('rule_identity_invalid')
        seen.add(identity)
        op = item.get('op')
        if op == 'unknown':
            return unknown(item.get('reason') or 'unsupported_rule')
        if op in {'and', 'or'}:
            rules = item.get('rules')
            if not isinstance(rules, list) or not 1 <= len(rules) <= 128:
                return unknown('empty_or_oversized_rule_group')
            children = [visit(child, depth + 1) for child in rules]
            states = [child['status'] for child in children]
            decisive = 'does_not_meet' if op == 'and' else 'meets'
            status = decisive if decisive in states else 'needs_information' if 'needs_information' in states else 'meets' if op == 'and' else 'does_not_meet'
            return {**base, 'status': status, 'children': children}
        if op == 'not':
            child = visit(item.get('rule'), depth + 1)
            status = child['status'] if child['status'] == 'needs_information' else 'does_not_meet' if child['status'] == 'meets' else 'meets'
            return {**base, 'status': status, 'children': [child]}
        if op != 'compare':
            return unknown('operator_unsupported')
        field = item.get('field')
        if field not in facts:
            return unknown('missing:' + str(field))
        comparison = item.get('comparison')
        try:
            if comparison not in {'eq', 'ne', 'gt', 'gte', 'lt', 'lte'}:
                return unknown('comparison_unsupported')
            if comparison in {'gt', 'gte', 'lt', 'lte'} and item['expected']['type'] not in {'decimal', 'date'}:
                return unknown('ordered_type_unsupported')
            value = _compare(facts[field], item.get('expected'))
            passed = {'eq': value == 0, 'ne': value != 0, 'gt': value > 0, 'gte': value >= 0, 'lt': value < 0, 'lte': value <= 0}[comparison]
            return {**base, 'status': 'meets' if passed else 'does_not_meet'}
        except (ValueError, TypeError, KeyError):
            return unknown('invalid:' + str(field))
    trace = visit(rule, 0)
    return {'status': trace['status'], 'trace': trace, 'reasons': list(dict.fromkeys(reasons))}
