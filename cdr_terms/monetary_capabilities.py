"""Closed wire-3 capability dispatch; no body-selected arbitrary adapters."""
TUPLES={
    'savings_calculation':('aud_savings_base_period_v1','aud-savings-base-v1','product-terms-engine-v8'),
    'mortgage_calculation':('aud_mortgage_confirmed_obligations_v1','aud-mortgage-confirmed-obligations-v1','product-terms-engine-v8'),
}


def require_capability(value):
    if value not in TUPLES:raise ValueError('Unsupported monetary capability')
    return value


def validate_tuple(subject):
    capability=require_capability(subject.get('capability'))
    if subject.get('schemaVersion')!=3 or tuple(subject.get(k) for k in ('kind','adapterVersion','evaluatorVersion'))!=TUPLES[capability]:
        raise ValueError('Monetary capability tuple differs')
    return capability


def periods(subject):
    if subject.get('schemaVersion') == 4:
        from .executable_v4_contract import validate_tuple as activity_tuple
        from .executable_v4_graph import periods as activity_periods
        activity_tuple(subject)
        return activity_periods(subject)
    if validate_tuple(subject)=='mortgage_calculation':
        from .mortgage_contract import periods as mortgage_periods
        return mortgage_periods(subject)
    return subject['policy']['intervals']
