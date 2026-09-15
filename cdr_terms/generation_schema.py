"""Disposable strict-output projection; canonical staging remains the authority.

Generation omits uniqueItems and negative assertions unsupported by the provider.
Those constraints remain mandatory in queue staging validation.
"""
import copy
from .queue import staging_schema
from .parameter_registry import VERSION


def _values(node):
    if 'const' in node:return {repr(node['const'])}
    if 'enum' in node:return {repr(x) for x in node['enum']}
    return None


def _types(node):
    if 'type' in node:
        value=node['type'];types=set(value if isinstance(value,list) else [value])
        if 'integer' in types:types.add('number')
        return types
    if 'const' in node:
        value=node['const']
        if value is None:return {'null'}
        if type(value) is bool:return {'boolean'}
        if type(value) is int:return {'integer','number'}
        if type(value) is str:return {'string'}
        raise ValueError('Unsupported generation constant type')
    return set()


def _disjoint(left,right):
    a,b=_types(left),_types(right)
    if a and b and a.isdisjoint(b):return True
    for key in set(left.get('properties',{})) & set(right.get('properties',{})):
        if key not in left.get('required',[]) or key not in right.get('required',[]):continue
        a,b=_values(left['properties'][key]),_values(right['properties'][key])
        if a is not None and b is not None and a.isdisjoint(b):return True
    return False


def _project(node):
    if isinstance(node,list):return [_project(x) for x in node]
    if not isinstance(node,dict):return node
    node=copy.deepcopy(node)
    if 'oneOf' in node:
        branches=node.pop('oneOf')
        if any(not _disjoint(a,b) for i,a in enumerate(branches) for b in branches[i+1:]):
            raise ValueError('Generation union is not provably disjoint')
        node['anyOf']=branches
    for key in ('not','uniqueItems','$schema','$id'):node.pop(key,None)
    if any(key in node for key in ('allOf','if','then','else')):raise ValueError('Unsupported generation conditional')
    if 'const' in node:
        types=_types(node)
        node.setdefault('type','integer' if 'integer' in types else next(iter(types)));node['enum']=[node.pop('const')]
    if 'enum' in node and 'type' not in node:
        node['type']='string'
    if node.get('type')=='object':
        if node.get('additionalProperties') is not False or set(node.get('required',[]))!=set(node.get('properties',{})):
            raise ValueError('Generation objects must be closed and fully required')
    return {key:_project(value) for key,value in node.items()}


def generation_schema(context):
    schema=staging_schema(context)
    if context.get('parameter_registry',{}).get('version')!=VERSION:return schema
    for key in set(schema['properties'])-set(schema['required']):
        target={'historical_scope':'historical_target','incorporated_scope':'incorporated_target'}.get(key)
        if target is None:raise ValueError('Unknown optional generation scope')
        if target in context:schema['required'].append(key)
        else:del schema['properties'][key]
    material=schema['$defs']['materialValue']
    conditions=material.pop('allOf');branches=[]
    definitions=material.pop('$defs')
    for condition in conditions:
        branch=copy.deepcopy(material)
        branch['properties'].update(condition['if']['properties'])
        branch['properties'].update(condition['then']['properties'])
        branches.append(branch)
    schema['$defs']['materialValue']={'anyOf':branches,'$defs':definitions}
    term=schema['properties']['terms']['items'];conditional=term.pop('allOf')[0]
    scalar=copy.deepcopy(term);structured=copy.deepcopy(term)
    scalar['properties'].update(conditional['else']['properties'])
    scalar['properties']['parameter_key']={'type':'string','enum':[x['key'] for x in context['parameter_registry']['parameters'] if x['key']!='monetary.savings_base_field_v1']}
    structured['properties'].update(conditional['then']['properties'])
    structured['properties'].update(conditional['if']['properties'])
    schema['properties']['terms']['items']={'anyOf':[scalar,structured]}
    return _project(schema)
