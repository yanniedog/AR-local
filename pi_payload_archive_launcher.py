"""Load one verified archive-I/O backport before the pinned daily entry point.

This launcher does not install itself or start a service. The operator supplies
an immutable, protected package and the existing producer invocation unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

MODULE = 'app_payload_revisions_github'


def regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file() or path.absolute() != path.resolve():
        raise ValueError('noncanonical or linked launcher input')
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(regular(path).read_bytes()).hexdigest()


def prepare(source: Path, package: Path, commit: str, old_sha: str, new_sha: str):
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('invalid pinned source commit')
    if not all(re.fullmatch('[a-f0-9]{64}', value) for value in (old_sha, new_sha)):
        raise ValueError('invalid module digest')
    if source.absolute() != source.resolve() or package.absolute() != package.resolve():
        raise ValueError('noncanonical launcher directory')
    if source == package or source in package.parents or package in source.parents:
        raise ValueError('overlapping launcher directories')
    def git(*args):
        return subprocess.run(['git', '-C', str(source), *args], check=True,
                              capture_output=True, text=True, timeout=30).stdout.strip()
    if git('rev-parse', 'HEAD') != commit or git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('producer source drift')
    replacement = package / (MODULE + '.py')
    if sha(source / (MODULE + '.py')) != old_sha or sha(replacement) != new_sha:
        raise ValueError('archive module drift')
    regular(source / 'pi_daily_sync.py')
    if MODULE in sys.modules:
        raise ValueError('archive module already loaded')
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location(MODULE, replacement)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(MODULE, None)
        raise
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--package-root', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--original-sha256', required=True)
    parser.add_argument('--replacement-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    module = prepare(args.source_root, args.package_root, args.source_commit,
                     args.original_sha256, args.replacement_sha256)
    if args.check_only:
        print(json.dumps({'status': 'READY', 'source_commit': args.source_commit,
                          'module_sha256': sha(Path(module.__file__))}))
        return
    forwarded = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    if forwarded != ['--banks-only', '--skip-git-sync']:
        raise ValueError('only the existing natural daily invocation is supported')
    entry = args.source_root / 'pi_daily_sync.py'
    sys.argv = [str(entry), *forwarded]
    runpy.run_path(str(entry), run_name='__main__')


if __name__ == '__main__':
    main()
