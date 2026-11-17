"""Pure financial-content projection; optional assets remain in whole bundle hashes."""
import re

CRITERIA_KEY = re.compile(r'product_criteria_(?:index|shard_[0-9]{3})\Z')
OPTIONAL_ROOTS = frozenset({'product_evidence_v1', 'product_response_evidence_v1',
                            'optional_product_evidence_status'})


def criteria_files(manifest):
    """Only the reserved exact names belong to the criteria sidecar."""
    files = manifest.get('files', {})
    if not isinstance(files, dict):
        raise ValueError('manifest files must be an object')
    return {key: value for key, value in files.items()
            if isinstance(key, str) and CRITERIA_KEY.fullmatch(key)}


def financial_manifest(manifest):
    """Exclude known optional delivery only, never a similarly named unknown asset."""
    value = {key: item for key, item in manifest.items() if key not in OPTIONAL_ROOTS}
    if criteria_files(manifest):
        value['files'] = {key: item for key, item in manifest['files'].items()
                          if not isinstance(key, str) or not CRITERIA_KEY.fullmatch(key)}
    return value
