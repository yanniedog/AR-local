"""Verify a dependency-only ordinary-user Git replacement without trusting drift.

The old configuration remains immutable. Neither this verifier nor package
staging changes a scheduled task, invokes a backup or contacts the Pi.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, 'noncanonical path')
    for item in (path, *path.parents):
        if item.exists():
            require(not item.is_symlink() and not
                    (getattr(item.lstat(), 'st_file_attributes', 0) & 0x400),
                    'reparse path')
    return path


def digest(path):
    value = hashlib.sha256()
    with canonical(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def config(path, sha):
    require(digest(path) == sha, 'configuration digest mismatch')
    value = json.loads(path.read_bytes(), object_pairs_hook=unique_pairs)
    require(isinstance(value, dict), 'configuration must be an object')
    require(path == canonical(value['receiver']).parent / 'user-session-backup.json',
            'configuration is outside exact receiver release')
    return value


def members(archive, expected_sha, required=('cmd/git.exe',)):
    require(digest(archive) == expected_sha, 'package digest mismatch')
    result, seen = {}, set()
    with zipfile.ZipFile(archive) as source:
        require(sum(item.file_size for item in source.infolist()) < 256 * 1024**2,
                'package inflated size exceeds bound')
        for item in source.infolist():
            # ZipInfo normalizes backslashes on Windows; validate original input.
            name = item.orig_filename.rstrip('/')
            path = PurePosixPath(name)
            require(name and not path.is_absolute() and '\\' not in name
                    and ':' not in name and path.as_posix() == name
                    and all(part not in {'.', '..'} and part.rstrip(' .') == part
                            for part in path.parts), 'unsafe package path')
            require(name.casefold() not in seen, 'package path collision')
            seen.add(name.casefold())
            mode = stat.S_IFMT(item.external_attr >> 16)
            require(mode in {0, stat.S_IFREG, stat.S_IFDIR}, 'package contains special file')
            if not item.is_dir():
                result[name] = source.read(item)
    require(set(required).issubset(result), 'package lacks required entrypoint')
    return result


def stage(archive, expected_sha, root):
    files = members(archive, expected_sha)
    canonical(root).mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        path = canonical(root / name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as output:
            output.write(raw)
    return verify_package(archive, expected_sha, root)


def verify_package(archive, expected_sha, root, required=('cmd/git.exe',)):
    files = members(archive, expected_sha, required)
    canonical(root)
    actual = set()
    for item in root.rglob('*'):
        canonical(item)
        if item.is_file():
            actual.add(item.relative_to(root).as_posix())
    require(actual == set(files), 'package file membership changed')
    manifest = []
    for name, raw in sorted(files.items()):
        sha = hashlib.sha256(raw).hexdigest()
        require(digest(root / name) == sha, 'package member changed: ' + name)
        manifest.append({'path': name, 'bytes': len(raw), 'sha256': sha})
    return {'package_sha256': expected_sha, 'files': manifest}


def compare_configs(old, new):
    changed = {'receiver', 'git_path', 'git_sha256', 'transport'}
    require(set(old) == set(new), 'configuration field membership changed')
    require({k: v for k, v in old.items() if k not in changed} ==
            {k: v for k, v in new.items() if k not in changed},
            'dependency-only update changed identity, code, paths or transport')
    tool_fields = {'ssh_path', 'ssh_sha256', 'scp_path', 'scp_sha256', 'ssh_null_device'}
    require((set(old['transport']) - {'ssh_null_device'}) ==
            (set(new['transport']) - {'ssh_null_device'}) and
            {k: v for k, v in old['transport'].items() if k not in tool_fields} ==
            {k: v for k, v in new['transport'].items() if k not in tool_fields},
            'dependency-only update changed SSH identity or host-key contract')
    require(new['transport'].get('ssh_null_device', 'NUL') in {'NUL', '/dev/null'},
            'unsupported SSH null device')
    require(old['receiver'] != new['receiver'], 'separate immutable release required')
    require(old['git_path'] != new['git_path'], 'separate private Git required')
    require(old['authority'] == 'D-015-USER-SESSION-NO-UAC', 'authority changed')


def git_read(git, root, *args):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('GIT_', 'PYTHON'))}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    return subprocess.run([str(git), '--no-optional-locks', '-c', 'core.fsmonitor=false',
                           '-c', 'core.untrackedCache=false', '-C', str(root), *args],
                          env=env, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, check=True, timeout=30).stdout.strip()


def verify_release(git, root, sha):
    require(git_read(git, root, 'rev-parse', '--show-toplevel').replace('\\', '/') ==
            str(root).replace('\\', '/'), 'Git root changed')
    require(git_read(git, root, 'rev-parse', 'HEAD') == sha, 'receiver commit changed')
    flags = git_read(git, root, 'ls-files', '-v', '-z')
    require(all(item[0] not in 'Sabcdefghijklmnopqrstuvwxyz'
                for item in flags.split('\0') if item), 'hidden Git index flags')
    require(not git_read(git, root, 'status', '--porcelain=v1', '--untracked-files=all',
                         '--ignore-submodules=none'), 'receiver dirty')
    require(git_read(git, root, 'log', '-1', '--format=%H', '--',
                     'docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md') ==
            '9094a8e115958fcaf2cb36525736bd5e297e6b04', 'plan authority changed')


def verify_current(new_path, new_sha, archive, package_sha, package_root,
                   ssh_archive, ssh_sha, ssh_root):
    new = config(new_path, new_sha)
    require(Path(new['git_path']) == package_root / 'cmd/git.exe', 'Git outside package')
    package = verify_package(archive, package_sha, package_root)
    ssh_relative = Path(new['transport']['ssh_path']).relative_to(ssh_root).as_posix()
    require(ssh_relative in {'ssh.exe', 'usr/bin/ssh.exe', 'OpenSSH-Win64/ssh.exe'},
            'unsupported SSH package layout')
    expected_null = '/dev/null' if ssh_relative == 'usr/bin/ssh.exe' else 'NUL'
    require(new['transport'].get('ssh_null_device', 'NUL') == expected_null,
            'SSH package requires matching null-device syntax')
    ssh_bin = Path(ssh_relative).parent
    ssh_package = verify_package(ssh_archive, ssh_sha, ssh_root,
                                 (ssh_relative, (ssh_bin / 'scp.exe').as_posix()))
    for name in ('ssh', 'scp'):
        executable = ssh_root / ssh_bin / (name + '.exe')
        require(Path(new['transport'][name + '_path']) == executable and
                digest(executable) == new['transport'][name + '_sha256'],
                'SSH executable outside authenticated package')
    require(digest(new['git_path']) == new['git_sha256'], 'new Git pin mismatch')
    require(Path(sys.executable).resolve() == Path(new['python_path']) and
            digest(new['python_path']) == new['python_sha256'], 'Python pin mismatch')
    verify_release(new['git_path'], canonical(new['receiver']), new['candidate_sha'])
    return {'result': 'PASS', 'read_only': True,
            'new_config_sha256': new_sha, 'package_sha256': package_sha,
            'package_files_verified': len(package['files']),
            'ssh_package_sha256': ssh_sha, 'ssh_files_verified': len(ssh_package['files']),
            'candidate_sha': new['candidate_sha'], 'production_sha': new['protected_sha']}


def verify(old_path, old_sha, new_path, new_sha, archive, package_sha, package_root,
           ssh_archive, ssh_sha, ssh_root):
    old, new = config(old_path, old_sha), config(new_path, new_sha)
    compare_configs(old, new)
    result = verify_current(new_path, new_sha, archive, package_sha, package_root,
                            ssh_archive, ssh_sha, ssh_root)
    # Never execute the drifted system Git to inspect its predecessor.
    verify_release(new['git_path'], canonical(old['receiver']), old['candidate_sha'])
    return dict(result, old_config_sha256=old_sha,
                changes=sorted(k for k in old if old[k] != new[k]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('stage', 'verify', 'current'))
    for name in ('archive', 'package-root', 'old-config', 'new-config', 'ssh-archive', 'ssh-root'):
        parser.add_argument('--' + name, type=Path, required=name in {'archive', 'package-root'})
    for name in ('package-sha256', 'old-sha256', 'new-sha256', 'ssh-sha256'):
        parser.add_argument('--' + name, required=name == 'package-sha256')
    args = parser.parse_args()
    try:
        if args.mode == 'stage':
            result = stage(args.archive, args.package_sha256, args.package_root)
        else:
            require(all((args.new_config, args.new_sha256,
                         args.ssh_archive, args.ssh_root, args.ssh_sha256)),
                    'exact configuration and package identities required')
            inputs = (args.new_config, args.new_sha256, args.archive, args.package_sha256,
                      args.package_root, args.ssh_archive, args.ssh_sha256, args.ssh_root)
            if args.mode == 'current':
                result = verify_current(*inputs)
            else:
                require(args.old_config and args.old_sha256, 'previous configuration required')
                result = verify(args.old_config, args.old_sha256, *inputs)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
