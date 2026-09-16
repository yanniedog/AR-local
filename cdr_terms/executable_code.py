"""Bounded retained local source closure; package locks are metadata, not execution proof."""
import json
import posixpath
import re

from .identity import byte_digest, require_sha
from .executable_sources import _OPERATION
from .executable_imports import literal_imports

ENTRYPOINTS = {'adapter': 'mobile/src/data/executableContracts/instantiate.ts',
              'evaluator': 'mobile/src/lib/productTermsEngine/ledger.ts'}
ELIGIBILITY_ENTRYPOINTS = {'adapter': 'mobile/src/data/eligibilityContracts/adapter.ts',
                         'evaluator': 'mobile/src/lib/productTermsEngine/eligibility.ts'}
PATH = re.compile(r'[A-Za-z0-9_@. /-]+')
MAX_FILES = 256
MAX_SOURCE_BYTES = 8 * 1024 * 1024


def verify_code_artifact(store, identity, role, version, *, capability='fixed_td_calculation'):
    entrypoints = {'fixed_td_calculation': ENTRYPOINTS, 'eligibility_only': ELIGIBILITY_ENTRYPOINTS,
        'savings_calculation': {'adapter':'mobile/src/data/monetaryContracts/adapter.ts','evaluator':'mobile/src/lib/productTermsEngine/ledger.ts'},
        'savings_activity_calculation': {'adapter':'mobile/src/data/activityContracts/adapter.ts','evaluator':'mobile/src/lib/productTermsEngine/ledger.ts'},
        'mortgage_calculation': {'adapter':'mobile/src/data/mortgageContracts/adapter.ts','evaluator':'mobile/src/lib/productTermsEngine/ledger.ts'}}.get(capability)
    if entrypoints is None or role not in entrypoints:
        raise ValueError('Executable code capability/role unsupported')
    operation = _OPERATION.get()
    cache = operation.setdefault('code_artifacts', {}) if operation is not None and operation['store'] is store else {}
    key = (identity, role, version, capability)
    if key in cache:
        return cache[key]
    raw = store.read_blob(identity)
    if len(raw) > 128 * 1024:
        raise ValueError('Executable code manifest byte bound exceeded')
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or set(manifest) != {'schemaVersion', 'role', 'version', 'entrypoints', 'files', 'packageLock', 'externalPackages', 'scope'}
            or manifest['schemaVersion'] != 1 or manifest['role'] != role or manifest['version'] != version
            or manifest['entrypoints'] != [entrypoints[role]] or manifest['scope'] != 'local_literal_import_closure_with_locked_external_metadata'):
        raise ValueError('Executable code manifest role/version/scope mismatch')
    files = manifest['files']
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError('Executable code file bound exceeded')
    sources, total = {}, 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {'path', 'sha256', 'bytes'}:
            raise ValueError('Executable code file descriptor mismatch')
        path = item['path']
        if (not isinstance(path, str) or not PATH.fullmatch(path) or len(path) > 256 or path.startswith('/')
                or posixpath.normpath(path) != path or path.startswith('../') or path in sources):
            raise ValueError('Executable code path invalid or duplicate')
        require_sha(item['sha256'])
        body = store.read_blob(item['sha256'])
        total += len(body)
        if (type(item['bytes']) is not int or item['bytes'] != len(body) or not body
                or len(body) > 2 * 1024 * 1024 or total > MAX_SOURCE_BYTES or byte_digest(body) != item['sha256']):
            raise ValueError('Executable code source bytes/hash mismatch')
        sources[path] = body
    lock_path = manifest['packageLock']
    if lock_path != 'mobile/package-lock.json' or lock_path not in sources:
        raise ValueError('Executable retained dependency lock missing')
    lock = json.loads(sources[lock_path])
    if lock.get('lockfileVersion') not in (2, 3) or not isinstance(lock.get('packages'), dict):
        raise ValueError('Executable dependency lock format unsupported')
    externals, seen = set(), set()
    pending = list(manifest['entrypoints']) + [path for path in sources if path.endswith(('.ts', '.tsx', '.js', '.jsx'))]
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        if path not in sources:
            raise ValueError('Executable local import missing: ' + path)
        seen.add(path)
        text = sources[path].decode('utf-8-sig')
        for specifier in literal_imports(text):
            if not specifier.startswith('.'):
                externals.add('/'.join(specifier.split('/')[:2]) if specifier.startswith('@') else specifier.split('/')[0])
                continue
            base = posixpath.normpath(posixpath.join(posixpath.dirname(path), specifier))
            candidates = [base] if base in sources else [base + suffix for suffix in ('.ts', '.tsx', '.js', '.jsx', '.json', '/index.ts', '/index.tsx', '/index.js') if base + suffix in sources]
            if not candidates:
                raise ValueError('Executable unresolved local import: ' + specifier)
            pending.extend(candidates)
    declared = manifest['externalPackages']
    if not isinstance(declared, list) or len(declared) > 128:
        raise ValueError('Executable external package bound exceeded')
    expected = []
    for package in sorted(externals):
        metadata = lock['packages'].get('node_modules/' + package)
        if not isinstance(metadata, dict) or not isinstance(metadata.get('version'), str):
            raise ValueError('Executable external package absent from lock: ' + package)
        expected.append({'name': package, 'version': metadata['version']})
    if declared != expected:
        raise ValueError('Executable external package versions mismatch')
    if operation is not None and operation['store'] is store:
        operation['code_bytes'] = operation.get('code_bytes', 0) + total
        if len(cache) >= 8 or operation['code_bytes'] > 32 * 1024 * 1024:
            raise ValueError('Executable code operation byte bound exceeded')
    cache[key] = manifest
    return manifest
