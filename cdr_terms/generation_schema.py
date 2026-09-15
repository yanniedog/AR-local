"""Disposable strict-output projection; canonical staging remains the authority.

Generation omits uniqueItems and negative assertions unsupported by the provider.
Those constraints remain mandatory in queue staging validation.
"""
import copy
from .queue import staging_schema
from .parameter_registry import VERSION,SAVINGS_VERSION


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


def _resolved(node,root):
    seen=set()
    while '$ref' in node:
        ref=node['$ref']
        if ref in seen or len(seen)>=32 or not ref.startswith('#/'):raise ValueError('Unsupported generation reference')
        seen.add(ref);value=root
        for part in ref[2:].split('/'):value=value[part.replace('~1','/').replace('~0','~')]
        node={**value,**{k:v for k,v in node.items() if k!='$ref'}}
    return node


def _project(node,root=None):
    if root is None:root=node
    if isinstance(node,list):return [_project(x,root) for x in node]
    if not isinstance(node,dict):return node
    node=copy.deepcopy(node)
    if 'oneOf' in node:
        branches=node.pop('oneOf')
        if any(not _disjoint(_resolved(a,root),_resolved(b,root)) for i,a in enumerate(branches) for b in branches[i+1:]):
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
    return {key:_project(value,root) for key,value in node.items()}


def _reachable_definitions(schema):
    """Remove only unreachable resource definitions, retaining all applied constraints."""
    pending=[schema];references=set()
    while pending:
        node=pending.pop()
        if isinstance(node,list):pending.extend(node)
        elif isinstance(node,dict):
            if '$ref' in node:
                ref=node['$ref']
                if not ref.startswith('#/'):raise ValueError('Nonlocal generation reference')
                if ref not in references:
                    if len(references)>=512:raise ValueError('Generation reference bound exceeded')
                    references.add(ref);target=schema
                    for part in ref[2:].split('/'):target=target[part.replace('~1','/').replace('~0','~')]
                    pending.append(target)
            pending.extend(value for key,value in node.items() if key!='$defs')
    def prune(node,path='#'):
        if isinstance(node,list):return [prune(v,path+'/'+str(i)) for i,v in enumerate(node)]
        if not isinstance(node,dict):return node
        result={k:prune(v,path+'/'+k) for k,v in node.items() if k!='$defs'}
        if '$defs' in node:
            result['$defs']={k:prune(v,path+'/$defs/'+k) for k,v in node['$defs'].items()
                             if any(r==path+'/$defs/'+k or r.startswith(path+'/$defs/'+k+'/') for r in references)}
        return result
    return prune(schema)


def generation_schema(context):
    schema=staging_schema(context)
    if context.get('parameter_registry',{}).get('version') not in (VERSION,SAVINGS_VERSION):return schema
    for key in set(schema['properties'])-set(schema['required']):
        target={'historical_scope':'historical_target','incorporated_scope':'incorporated_target'}.get(key)
        if target is None:raise ValueError('Unknown optional generation scope')
        if target in context:schema['required'].append(key)
        else:del schema['properties'][key]
    for name in ('materialValue','mortgageValue'):
        if name not in schema['$defs']:continue
        material=schema['$defs'][name]
        if 'allOf' not in material:continue  # Already a closed discriminated union.
        conditions=material.pop('allOf');branches=[]
        definitions=material.pop('$defs',{})
        for condition in conditions:
            branch=copy.deepcopy(material)
            branch['properties'].update(condition['if']['properties'])
            branch['properties'].update(condition['then']['properties'])
            branches.append(branch)
        schema['$defs'][name]={'anyOf':branches,'$defs':definitions}
    term=schema['properties']['terms']['items'];conditional=term.pop('allOf')[0]
    structured=[];keys=[]
    while 'if' in conditional:
        branch=copy.deepcopy(term);branch['properties'].update(conditional['then']['properties'])
        branch['properties'].update(conditional['if']['properties']);structured.append(branch)
        keys.append(branch['properties']['parameter_key']['const']);conditional=conditional['else']
    scalar=copy.deepcopy(term);scalar['properties'].update(conditional['properties'])
    scalar['properties']['parameter_key']={'type':'string','enum':[x['key'] for x in context['parameter_registry']['parameters'] if x['key'] not in keys]}
    schema['properties']['terms']['items']={'anyOf':[scalar,*structured]}
    if context['parameter_registry']['version']==VERSION:schema=_reachable_definitions(schema)
    return _project(schema)
