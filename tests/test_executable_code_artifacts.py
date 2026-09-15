"""Closed retained implementation provenance, distinct from execution attestation."""
import json
import base64
import gzip
from cdr_terms.identity import byte_digest

import pytest

from cdr_terms.executable_code import verify_code_artifact
from cdr_terms.identity import canonical_json
from cdr_terms.store import EvidenceStore
from tests.executable_code_fixture import retained_code_artifacts
from tests.test_executable_actual_bridge import BRIDGE


@pytest.mark.parametrize('change', ['blob', 'role', 'version', 'entrypoint', 'duplicate', 'path', 'missing_import', 'bytes', 'dynamic', 'concatenation', 'external'])
def test_unverified_code_artifacts_are_refused(tmp_path, change):
    with EvidenceStore(tmp_path) as store:
        template = {'adapterVersion': 'fixed-aud-td-v1', 'evaluatorVersion': 'product-terms-engine-v8'}
        identity = retained_code_artifacts(store, template)['adapterCodeSha256']
        manifest = json.loads(store.read_blob(identity))
        if change == 'blob':
            manifest = {'approved': True}
        elif change == 'role':
            manifest['role'] = 'evaluator'
        elif change == 'version':
            manifest['version'] = 'self-asserted-other'
        elif change == 'entrypoint':
            manifest['entrypoints'] = ['mobile/unrelated.ts']
        elif change == 'duplicate':
            manifest['files'].append(manifest['files'][0])
        elif change == 'path':
            manifest['files'][0]['path'] = '../outside.ts'
        elif change == 'missing_import':
            manifest['files'] = [item for item in manifest['files'] if not item['path'].endswith('/decimal.ts')]
        elif change == 'bytes':
            manifest['files'][0]['bytes'] += 1
        elif change in {'dynamic', 'concatenation'}:
            item = next(item for item in manifest['files'] if item['path'].endswith('/instantiate.ts'))
            call = b'import(variablePath);' if change == 'dynamic' else b"require('./transport' + suffix);"
            body = store.read_blob(item['sha256']) + b'\n' + call + b'\n'
            item.update(sha256=store.put_blob(body), bytes=len(body))
        else:
            manifest['externalPackages'] = []
        bad = store.put_blob(canonical_json(manifest).encode())
        with pytest.raises(ValueError):
            verify_code_artifact(store, bad, 'adapter', template['adapterVersion'])


def test_all_original_bridge_source_hashes_are_preserved(tmp_path):
    bridge = json.loads(BRIDGE.with_name('actual-v8-bridge.json').read_bytes())
    with EvidenceStore(tmp_path) as store:
        template = bridge['records'][0]['template']
        identity = retained_code_artifacts(store, template)['adapterCodeSha256']
        manifest = verify_code_artifact(store, identity, 'adapter', template['adapterVersion'])
        hashes = {item['path']: item['sha256'] for item in manifest['files']}
        bundle = json.loads(gzip.decompress(BRIDGE.with_name('actual-v8-code-closure.json.gz').read_bytes()))
        assert all(byte_digest(base64.b64decode(bundle['recordedBridgeFiles'][item['file']])) == item['sha256'] for item in bridge['code'])
        assert all(hashes['mobile/' + item['file']] == item['sha256'] for item in bridge['code'] if 'mobile/' + item['file'] in hashes)
