"""Inspect the historical proof archive without accessing a Pi or private backup."""
import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--operator', required=True)
    args = parser.parse_args()
    started = datetime.now(timezone.utc).isoformat()
    raw = args.archive.read_bytes()
    expected = '7445c2c8012a105ea40bf942fd7cdbb0b26564a11028abb2cfd7049367b29e48'
    if len(raw) != 25778 or sha(raw) != expected:
        raise ValueError('Historical archive identity mismatch')
    with zipfile.ZipFile(args.archive) as bundle:
        manifest_raw = bundle.read('artifact-manifest.json')
        if sha(manifest_raw) != '9f6e3708a38f8b28b43187350bfca54c1d9cce668e4adddfbd6ceb676b9a4bee':
            raise ValueError('Historical manifest identity mismatch')
        inventory = json.loads(manifest_raw)['inventory']
        if len(inventory) != 19:
            raise ValueError('Unexpected artifact population')
        if sorted(bundle.namelist()) != sorted([x['name'] for x in inventory] + ['artifact-manifest.json']):
            raise ValueError('Unlisted or duplicate archive member')
        for item in inventory:
            data = bundle.read(item['name'])
            if len(data) != item['bytes'] or sha(data) != item['sha256']:
                raise ValueError('Artifact identity mismatch: ' + item['name'])
        run = json.loads(bundle.read('scheduled-run.json'))
        token = json.loads(bundle.read('ordinary-token-execution.json'))
        if run['result'] != 'PASS' or run['detail']['after']['status'] != 'UP_TO_DATE':
            raise ValueError('Scheduled result mismatch')
        if token['result'] != 'PASS' or token['exit_code'] != 0 or token['elevated'] is not False:
            raise ValueError('Ordinary-token result mismatch')
        if token['operator_sid'] != run['operator'] or token['candidate_sha'] != run['candidate_code_sha']:
            raise ValueError('Execution identities differ')
        ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        definitions = []
        for name in ['task-installed.xml', 'task-readback.xml']:
            xml = bundle.read(name)
            original = bundle.read(name + '.original-bytes.txt').decode('utf-8-sig')
            if xml.decode('utf-16') != original:
                raise ValueError('XML derivative changes original text')
            definitions.append(ET.fromstring(xml))
        for section in ['Triggers', 'Principals', 'Settings', 'Actions']:
            parts = [element.find('t:' + section, ns) for element in definitions]
            if any(part is None for part in parts) or ET.tostring(parts[0]) != ET.tostring(parts[1]):
                raise ValueError('Task sections differ: ' + section)
        proof_hash = sha(bundle.read('proof-original-pr635.md'))
        if proof_hash != '18d24c433f2c2a4134769cf8664f58b1ab6218082a1668da5a7fec4a0143831a':
            raise ValueError('Original proof identity mismatch')
    report = {
        'result': 'PASS', 'scope': 'Local historical archive inspection only',
        'started_at_utc': started, 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
        'operator': args.operator,
        'exact_argv': [sys.executable, *sys.orig_argv[1:]], 'cwd': str(Path.cwd()),
        'verifier_sha256': sha(Path(__file__).read_bytes()),
        'archive_path': str(args.archive), 'archive_bytes': len(raw), 'archive_sha256': expected,
        'artifact_manifest_sha256': sha(manifest_raw), 'artifact_count': len(inventory),
        'original_proof_sha256': proof_hash, 'deviations': [],
        'runtime_access': False, 'backup_access': False, 'elevation_requested': False,
    }
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write('\n')
    print(json.dumps({'result': 'PASS', 'report_sha256': sha(args.output.read_bytes()),
                      'verifier_sha256': report['verifier_sha256']}))


if __name__ == '__main__':
    main()
