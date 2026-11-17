"""Track raw object pointers while the display cleaner compacts arrays.

Only paths are retained. This adds no source assertions or legal interpretation.
The legacy cleaner remains authoritative for which values survive.
"""
from cdr_clean_export import NOISE_KEYS, URL_KEY_RE, clean_value


def _part(value):
    return str(value).replace('~', '~0').replace('/', '~1')


def source_paths(record):
    paths = {}

    def visit(value, cleaned_path, original_path):
        if isinstance(value, dict):
            if cleaned_path:
                paths[cleaned_path] = original_path
            for key, child in value.items():
                if str(key).lower() in NOISE_KEYS or URL_KEY_RE.search(str(key)):
                    continue
                if clean_value(child) not in ('', None, [], {}):
                    suffix = '/' + _part(key)
                    visit(child, cleaned_path + suffix, original_path + suffix)
        elif isinstance(value, list):
            out_index = 0
            for index, child in enumerate(value):
                if clean_value(child) not in ('', None, [], {}):
                    visit(child, f'{cleaned_path}/{out_index}', f'{original_path}/{index}')
                    out_index += 1
    visit(record, '', '')
    return paths
