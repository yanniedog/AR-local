"""Activity material projections; public source semantics exclude private facts."""
from .executable_v4_contract import schema_validate
from .executable_v4_graph import BASE_FIELDS
from .executable_v3_contract import _range
from .monetary_material_fields import project_field as base_project, _semantic


def project_field(subject, period, field):
    if field in BASE_FIELDS:
        return base_project(subject, period, field)
    bonus = subject['policy']['bonus']; assessment = bonus['assessment']
    def pick(source, *keys): return {key: source[key] for key in keys}
    values = {
        'assessmentWindow': pick(assessment, 'from', 'toExclusive'),
        'activityAccountRole': pick(assessment, 'accountRole'),
        'activityDateBasis': pick(assessment, 'dateBasis'),
        'settlementPolicy': pick(assessment, 'settlement'),
        'classificationInventory': pick(assessment, 'metrics'),
        'metricThresholds': pick(assessment, 'rule'),
        'bonusApplication': pick(assessment, 'assessmentKey', 'from', 'toExclusive', 'appliesFrom', 'appliesToExclusive'),
        'bonusRates': pick(bonus, 'componentId', 'allocation', 'tiers'),
        'rateComponents': {'base': 'additive', 'bonus': bonus['kind']},
        'activityExclusions': {'intro': subject['policy']['intro'], 'otherBonusComponents': 'none_source_declared'},
    }
    return _semantic(values[field])


def validate_field_value(value):
    schema_validate(value, 'material-field')
    _range(value['from'], value['toExclusive'])


def field_value(subject, period, field):
    scope = {k: subject['scope'][k] for k in ('productKey', 'cohortKey', 'tierKey', 'packageKey')}
    value = dict(schemaVersion=1, field=field, scope=scope, material=project_field(subject, period, field),
                 **{'from': period['from'], 'toExclusive': period['toExclusive']})
    validate_field_value(value)
    return value
