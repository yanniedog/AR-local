"""The narrow publisher backport must fail closed and preserve daily arguments."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

import pi_payload_archive_launcher as launcher


@pytest.fixture
def staged(tmp_path, monkeypatch):
    source, package = tmp_path / 'producer', tmp_path / 'package'
    source.mkdir(); package.mkdir()
    original = source / (launcher.MODULE + '.py')
    original.write_text('VALUE = "old"\n')
    replacement = package / original.name
    replacement.write_text('VALUE = "replacement"\n')
    (source / 'pi_daily_sync.py').write_text('raise AssertionError("must not run during checks")\n')
    for args in [('init',), ('add', '.'), ('-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')]:
        subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    monkeypatch.delitem(sys.modules, launcher.MODULE, raising=False)
    monkeypatch.syspath_prepend(str(source))
    yield source, package, commit, launcher.sha(original), launcher.sha(replacement)
    sys.modules.pop(launcher.MODULE, None)


def test_verified_replacement_is_imported_before_daily(staged):
    module = launcher.prepare(*staged)
    assert module.VALUE == 'replacement'
    assert Path(module.__file__).parent == staged[1]
    assert sys.modules[launcher.MODULE] is module


@pytest.mark.parametrize('target', ['source', 'package', 'commit', 'digest'])
def test_drift_refuses_before_import(staged, target):
    values = list(staged)
    if target == 'source':
        (values[0] / 'pi_daily_sync.py').write_text('changed\n')
    elif target == 'package':
        (values[1] / (launcher.MODULE + '.py')).write_text('raise AssertionError("tampered")\n')
    elif target == 'commit':
        values[2] = '0' * 40
    else:
        values[4] = '0' * 64
    with pytest.raises(ValueError):
        launcher.prepare(*values)
    assert launcher.MODULE not in sys.modules


def test_preloaded_archive_module_is_not_silently_replaced(staged, monkeypatch):
    monkeypatch.setitem(sys.modules, launcher.MODULE, object())
    with pytest.raises(ValueError, match='already loaded'):
        launcher.prepare(*staged)


def test_only_existing_daily_arguments_reach_original_entrypoint(staged, monkeypatch):
    source, package, commit, old_sha, new_sha = staged
    base = ['launcher', '--source-root', str(source), '--package-root', str(package),
            '--source-commit', commit, '--original-sha256', old_sha,
            '--replacement-sha256', new_sha]
    monkeypatch.setattr(sys, 'argv', base + ['--', '--banks-only', '--skip-git-sync'])
    calls = []
    monkeypatch.setattr(launcher.runpy, 'run_path', lambda path, **kwargs: calls.append((path, list(sys.argv), kwargs)))
    launcher.main()
    assert calls == [(str(source / 'pi_daily_sync.py'),
                      [str(source / 'pi_daily_sync.py'), '--banks-only', '--skip-git-sync'],
                      {'run_name': '__main__'})]


def test_ingest_options_cannot_change_through_launcher(staged, monkeypatch):
    source, package, commit, old_sha, new_sha = staged
    monkeypatch.setattr(sys, 'argv', ['launcher', '--source-root', str(source), '--package-root', str(package),
                        '--source-commit', commit, '--original-sha256', old_sha,
                        '--replacement-sha256', new_sha, '--', '--force'])
    with pytest.raises(ValueError, match='existing natural daily'):
        launcher.main()
