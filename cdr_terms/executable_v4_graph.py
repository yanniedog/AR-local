"""Explicit authority ownership across preceding assessment and application."""
from .executable_v3_graph import FIELDS, POSTING_FIELDS, _covers, validate_inventory
from .executable_v3_contract import _range

BASE_FIELDS = FIELDS - {'noBonusIntro'}
APPLICATION_FIELDS = BASE_FIELDS | {'bonusRates', 'rateComponents', 'bonusApplication', 'activityExclusions'}
ASSESSMENT_FIELDS = {'assessmentWindow', 'activityAccountRole', 'activityDateBasis',
                     'settlementPolicy', 'classificationInventory', 'metricThresholds',
                     'bonusApplication', 'activityExclusions'}


def periods(subject):
    policy = subject['policy']; bonus = policy['bonus']; assessment = bonus['assessment']
    result = []
    for interval in policy['intervals']:
        refs = dict(interval['fieldEvidenceIds'])
        refs.update(bonus['fieldEvidenceIds'])
        refs['bonusApplication'] = assessment['fieldEvidenceIds']['bonusApplication']
        result.append({**interval, 'fieldEvidenceIds': refs, 'requiredFields': APPLICATION_FIELDS})
    refs = dict(assessment['fieldEvidenceIds'])
    refs['activityExclusions'] = bonus['fieldEvidenceIds']['activityExclusions']
    result.append({**assessment, 'id': assessment['assessmentKey'], 'fieldEvidenceIds': refs,
                   'requiredFields': ASSESSMENT_FIELDS, 'interest': {'postingDates': []}})
    return result


def _coverage(subject, selected, period):
    for field in period['requiredFields']:
        required = set(period['fieldEvidenceIds'].get(field, []))
        if field == 'eligibility':
            pending = [subject['policy']['eligibility']]
            while pending:
                node = pending.pop(); required.update(node.get('evidenceIds', []))
                pending.extend(node.get('rules', []))
                if 'rule' in node: pending.append(node['rule'])
        entries = [x for x in selected['fieldCoverage'] if x['field'] == field
                   and x['from'] < period['toExclusive'] and period['from'] < x['toExclusive']
                   and set(x['evidenceIds']) <= required and set(x['evidenceIds'])]
        if not required or not required <= {ref for x in entries for ref in x['evidenceIds']}:
            raise ValueError('Activity field evidence coverage incomplete')
        if not _covers([(x['from'], x['toExclusive']) for x in entries], period['from'], period['toExclusive']):
            raise ValueError('Activity field temporal coverage incomplete')
        if field in POSTING_FIELDS and not set(period['interest']['postingDates']) <= {d for x in entries for d in x['postingEventDates']}:
            raise ValueError('Activity posting event coverage incomplete')


def validate_graph(subject):
    authorities = validate_inventory(subject)
    graph = subject['authorityGraph']; used = set()
    for relation in graph['supersessions']:
        _range(relation['from'], relation['toExclusive'])
        selected = authorities.get(relation['selectedAuthorityId'])
        previous = authorities.get(relation['supersededAuthorityId'])
        if (selected is None or previous is None or selected['id'] == previous['id']
            or not max(selected['from'], previous['from']) <= relation['from']
            < relation['toExclusive'] <= min(selected['toExclusive'], previous['toExclusive'])):
            raise ValueError('Activity supersession exceeds actual authority overlap')
    for period in periods(subject):
        selected = authorities.get(period['authorityId'])
        if selected is None or not selected['from'] <= period['from'] < period['toExclusive'] <= selected['toExclusive']:
            raise ValueError('Activity period authority missing')
        used.add(selected['id']); _coverage(subject, selected, period)
        for candidate in authorities.values():
            lower = max(candidate['from'], period['from']); upper = min(candidate['toExclusive'], period['toExclusive'])
            if candidate['id'] == selected['id'] or lower >= upper: continue
            relations = [r for r in graph['supersessions'] if r['selectedAuthorityId'] == selected['id']
                         and r['supersededAuthorityId'] == candidate['id']]
            if not _covers([(r['from'], r['toExclusive']) for r in relations], lower, upper):
                raise ValueError('Activity conflicting authority lacks supersession')
            used.add(candidate['id'])
    if used != set(authorities):
        raise ValueError('Activity unused authority')
