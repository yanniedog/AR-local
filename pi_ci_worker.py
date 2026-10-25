"""Fixed NNP, read-only deployment verification phases; never acquires a lease.

Root owns host admission, source replacement and fixed service transitions.
Candidate imports happen only after privilege and read-only mount checks.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import stat


def boundary(data, candidate):
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if (os.geteuid() == 0 or status.get('NoNewPrivs', '').strip() != '1'
            or any(int(status.get(key, '-1').strip(), 16) != 0 for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))):
        raise ValueError('read-only verifier requires non-root, NNP and zero capabilities')
    context = Path('/namespace.json'); info = context.lstat()
    if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o222 or info.st_size > 4096:
        raise ValueError('fixed root namespace attestation required')
    value = json.loads(context.read_bytes())
    namespaces = {name: Path('/proc/self/ns/' + name).stat().st_ino for name in ('user', 'pid', 'mnt')}
    if (value.get('schema') != 'ar-local-ci-namespace-v1' or os.getuid() != value['uid']
            or os.getgid() != value['gid'] or os.getgroups()
            or namespaces['user'] != value['namespaces']['user']
            or any(namespaces[name] == value['namespaces'][name] for name in ('pid', 'mnt'))
            or Path('/proc/self/cgroup').read_text().strip() != '0::' + value['cgroup']):
        raise ValueError('private PID/mount namespace or faithful host UID mapping is unavailable')
    for root in (Path(data), Path(candidate), Path('/srv/ar-local/AR-local')):
        if not os.statvfs(root).f_flag & os.ST_RDONLY:
            raise ValueError('verifier source and authoritative data must be read-only')


def verify(phase, manifest, manifest_sha256, previous, work):
    # This import path is fixed by the root launcher, never by CI request text.
    boundary('/srv/ar-local/data', '/candidate')
    sys.path.insert(0, '/candidate')
    from pi_cdr_quality_activate_evidence import read, sha, validate_manifest
    from pi_cdr_quality_activate import protected_files, source_files, git, smoke
    from pi_cdr_quality_runtime_state import require_controls, require_predecessor
    if sha(manifest) != manifest_sha256:
        raise ValueError('root-sealed intent digest differs')
    # A consumed intent remains valid for its own guarded rollback after expiry.
    value = read(manifest) if phase.startswith('rollback') else validate_manifest(manifest, manifest_sha256)
    predecessor = read(previous)
    production = Path('/srv/ar-local/AR-local')
    data = Path('/srv/ar-local/data')
    require_controls(data, value['publication_controls'], value['rollback_contract'])
    if phase == 'rollback-check':
        return {'result': 'PASS', 'phase': phase, 'controls': 'UNCHANGED'}
    if protected_files(data) != value['protected_files']:
        raise ValueError('protected observation changed since sealed canary')
    expected_commit = value['target_commit'] if phase == 'post' else value['previous_commit']
    expected_files = value['source_files'] if phase == 'post' else predecessor['source_files']
    if (git(production, 'rev-parse', 'HEAD') != expected_commit
            or git(production, 'status', '--porcelain', '--untracked-files=no')
            or source_files(production) != expected_files):
        raise ValueError('live tracked source differs from approved predecessor/candidate')
    if phase == 'pre':
        require_predecessor(production, value['rollback_contract'])
    # Every path uses the exact sealed candidate verifier, including rollback.
    smoke(Path(value['source_root']), operation=work, phase=phase,
          commit=value['target_commit'], files=value['source_files'])
    require_controls(data, value['publication_controls'], value['rollback_contract'])
    if protected_files(data) != value['protected_files']:
        raise ValueError('protected observation changed during runtime checks')
    return {'result': 'PASS', 'phase': phase, 'commit': expected_commit,
            'protected_data': 'UNCHANGED', 'publication_controls': 'UNCHANGED'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('pre', 'post', 'rollback-check', 'rollback'))
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--sealed-sha256', required=True)
    args = parser.parse_args(argv)
    result = verify(args.phase, Path('/sealed.json'), args.sealed_sha256, Path('/previous.json'), args.work)
    with (args.work / 'result.json').open('x') as output:
        json.dump(result, output, sort_keys=True); output.flush(); os.fsync(output.fileno())
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'result': 'FAIL', 'error_type': type(error).__name__}))
        raise SystemExit(2)
