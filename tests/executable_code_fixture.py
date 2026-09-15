"""Exact historical e181 local source bytes; external runtime packages are excluded."""
import base64
import gzip
import json
from pathlib import Path

from cdr_terms.executable_code import ENTRYPOINTS
from cdr_terms.identity import canonical_json


def retained_code_artifacts(store, template):
    path = Path(__file__).parent / 'fixtures/executable-templates/actual-v8-code-closure.json.gz'
    bundle = json.loads(gzip.decompress(path.read_bytes()))
    files = []
    for name, encoded in bundle['files'].items():
        body = base64.b64decode(encoded)
        files.append({'path': name, 'sha256': store.put_blob(body), 'bytes': len(body)})
    lock = json.loads(base64.b64decode(bundle['files']['mobile/package-lock.json']))
    # Independent source capture enumerated all static external imports, including type imports.
    names = sorted(set('/'.join(name.split('/')[:2]) if name.startswith('@') else name.split('/')[0]
                       for name in bundle['provenance']['externalSpecifiers']))
    packages = [{'name': name, 'version': lock['packages']['node_modules/' + name]['version']} for name in names]
    result = {}
    for role, key, version in [('adapter', 'adapterCodeSha256', template['adapterVersion']),
                               ('evaluator', 'evaluatorCodeSha256', template['evaluatorVersion'])]:
        manifest = dict(schemaVersion=1, role=role, version=version, entrypoints=[ENTRYPOINTS[role]],
            files=files, packageLock='mobile/package-lock.json', externalPackages=packages,
            scope='local_literal_import_closure_with_locked_external_metadata')
        result[key] = store.put_blob(canonical_json(manifest).encode())
    return result
