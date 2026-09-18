"""Hoist definitions for the subscription provider without changing validation."""
import copy

from .generation_schema import generation_schema


def transport_generation_schema(context):
    """Keep canonical/versioned generation contracts intact; adapt transport only."""
    schema = generation_schema(context)
    definitions, names = {}, {}

    def pointer(value):
        return value.replace('~', '~0').replace('/', '~1')

    def collect(node, path='#'):
        if isinstance(node, list):
            for i, value in enumerate(node):
                collect(value, path + '/' + str(i))
        elif isinstance(node, dict):
            for name, value in node.get('$defs', {}).items():
                location = path + '/$defs/' + pointer(name)
                # Preserve top-level names and allocate nested names independently.
                alias = name if path == '#' else 'transport_definition_' + str(len(names))
                if alias in names:
                    raise ValueError('Transport definition name collision')
                names[alias] = value
                definitions[location] = '#/$defs/' + pointer(alias)
            for key, value in node.items():
                collect(value, path + '/' + pointer(key))

    collect(schema)
    locations = sorted(definitions, key=len, reverse=True)

    def rewrite(node):
        if isinstance(node, list):
            return [rewrite(value) for value in node]
        if not isinstance(node, dict):
            return copy.deepcopy(node)
        result = {key: rewrite(value) for key, value in node.items() if key != '$defs'}
        if '$ref' in result:
            reference = result['$ref']
            if not reference.startswith('#/'):
                raise ValueError('Nonlocal transport reference')
            for location in locations:
                if reference == location or reference.startswith(location + '/'):
                    result['$ref'] = definitions[location] + reference[len(location):]
                    break
        return result

    result = rewrite(schema)
    result['$defs'] = {name: rewrite(value) for name, value in names.items()}
    return result
