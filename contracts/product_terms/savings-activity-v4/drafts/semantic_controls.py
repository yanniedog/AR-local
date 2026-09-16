"""Draft-only cross-input controls; not original-source or bank validation."""
from datetime import date
from fractions import Fraction


def validate(subject, inputs):
    policy, scope = subject['policy'], subject['scope']
    bonus = policy['bonus']; assessment = bonus['assessment']
    def require(ok, reason):
        if not ok: raise ValueError(reason)
    require(assessment['from'] < assessment['toExclusive'] <= scope['from'] < scope['toExclusive'], 'preceding_window')
    require((date.fromisoformat(scope['toExclusive'])-date.fromisoformat(assessment['from'])).days <= 366, 'combined_horizon')
    require((assessment['appliesFrom'],assessment['appliesToExclusive']) == (scope['from'],scope['toExclusive']), 'application_window')
    require(scope['toExclusive'] <= subject['authorityGraph']['completedPeriod']['completedThroughExclusive'], 'source_completion')
    require((inputs['startDate'],inputs['endDateExclusive']) == (scope['from'],scope['toExclusive']), 'private_application')
    evidence={e['id'] for e in subject['evidence']}
    def refs(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='evidenceIds': require(set(item)<=evidence,'evidence_reference')
                elif key=='fieldEvidenceIds':
                    for ids in item.values(): require(set(ids)<=evidence,'evidence_reference')
                refs(item)
        elif isinstance(value,list):
            for item in value:refs(item)
    refs(policy)
    metrics=assessment['metrics'];fields=[m['field'] for m in metrics]
    require(len(set(fields))==len(fields) and len({m['id'] for m in metrics})==len(metrics),'duplicate_metric')
    for metric in metrics:
        require(not set(metric['includedClassifications']) & set(metric['excludedClassifications']),'classification_overlap')
    rule=assessment['rule'];leaves=rule['rules'] if rule['op'] in ('and','or') else [rule]
    require(sorted(x['field'] for x in leaves)==sorted(fields),'metric_rule_inventory')
    def rates(actual, expected, fields, reason):
        require(len(actual)==len(expected),'missing_'+reason)
        keys=[tuple(row[k] for k in fields) for row in actual]
        require(len(keys)==len(set(keys)),'duplicate_'+reason)
        expected={tuple(row[k] for k in fields):Fraction(row['annualRate']) for row in expected}
        require(set(keys)==set(expected),'inventory_'+reason)
        require(all(Fraction(row['annualRate'])==expected[tuple(row[k] for k in fields)] for row in actual),'value_'+reason)
    rates(inputs['confirmedAnnualRates'],[dict(intervalId=i['id'],tierId=t['id'],annualRate=t['annualRate']) for i in policy['intervals'] for t in i['tiers']],['intervalId','tierId'],'base_rates')
    rates(inputs['confirmedBonusAnnualRates'],[dict(componentId=bonus['componentId'],tierId=t['id'],annualRate=t['annualRate']) for t in bonus['tiers']],['componentId','tierId'],'bonus_rates')
    events=inputs['activity']['events'];require(len({e['id'] for e in events})==len(events),'duplicate_event')
    for event in events:
        require(event['accountId']==inputs['accountId'],'event_account')
        require(assessment['from']<=event['date']<assessment['toExclusive'],'event_window')
        require(event['dateBasis']==assessment['dateBasis'],'event_basis')
        require((Fraction(event['amount'])*100).denominator==1,'event_cents')
    coverage=inputs['activity']['coverage'][0]
    require(coverage['accountId']==inputs['accountId'] and (coverage['from'],coverage['toExclusive'])==(assessment['from'],assessment['toExclusive']),'coverage_binding')
