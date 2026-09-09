import hashlib
import stat
import zipfile

import pytest

import laptop_backup_git_dependency as dependency


def archive(tmp_path, entries=None):
    path = tmp_path / 'package.zip'
    with zipfile.ZipFile(path, 'w') as output:
        for name, raw in (entries or {'cmd/git.exe': b'git', 'mingw64/bin/library.dll': b'library'}).items():
            item = zipfile.ZipInfo('member')
            item.filename = name  # Preserve deliberately malformed separators on Windows.
            output.writestr(item, raw)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_staging_authenticates_whole_package_and_preserves_existing_root(tmp_path):
    path, sha = archive(tmp_path)
    root = tmp_path / 'private'
    result = dependency.stage(path, sha, root)
    assert len(result['files']) == 2
    with pytest.raises(FileExistsError):
        dependency.stage(path, sha, root)
    assert (root / 'cmd/git.exe').read_bytes() == b'git'


@pytest.mark.parametrize('mutation', ['changed', 'extra', 'missing'])
def test_changed_dll_or_membership_fails(tmp_path, mutation):
    path, sha = archive(tmp_path)
    root = tmp_path / 'private'
    dependency.stage(path, sha, root)
    dll = root / 'mingw64/bin/library.dll'
    if mutation == 'changed':
        dll.write_bytes(b'tampered')
    elif mutation == 'extra':
        (root / 'extra.dll').write_bytes(b'extra')
    else:
        dll.unlink()
    with pytest.raises(ValueError, match='changed'):
        dependency.verify_package(path, sha, root)


def test_package_hash_checked_before_any_extraction(tmp_path):
    path, _ = archive(tmp_path)
    root = tmp_path / 'private'
    with pytest.raises(ValueError, match='digest mismatch'):
        dependency.stage(path, '0' * 64, root)
    assert not root.exists()


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'cmd/../escape',
                                'C:/escape', 'cmd\\escape', 'cmd/./escape', 'bad.'])
def test_package_path_escape_rejected(tmp_path, name):
    path, sha = archive(tmp_path, {'cmd/git.exe': b'git', name: b'bad'})
    with pytest.raises(ValueError, match='unsafe'):
        dependency.stage(path, sha, tmp_path / 'private')


def test_package_symlink_rejected(tmp_path):
    path, _ = archive(tmp_path)
    with zipfile.ZipFile(path, 'a') as output:
        item = zipfile.ZipInfo('linked')
        item.create_system = 3
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(item, 'target')
    with pytest.raises(ValueError, match='special file'):
        dependency.members(path, dependency.digest(path))


def configs():
    old = {'receiver': '/old/source', 'git_path': '/system/git', 'git_sha256': 'old',
           'authority': 'D-015-USER-SESSION-NO-UAC', 'candidate_sha': 'a' * 40,
           'protected_sha': 'b' * 40, 'transport': {'ssh_sha256': 'pin'},
           'target': '/backup', 'previous_runtime': {'record_sha256': 'receipt'}}
    new = dict(old, receiver='/new/source', git_path='/private/git', git_sha256='new')
    return old, new


def test_only_dependency_and_release_location_may_change():
    old, new = configs()
    dependency.compare_configs(old, new)


def test_dependency_only_migration_can_select_explicit_msys_null_device():
    old, new = configs()
    new['transport'] = dict(new['transport'], ssh_null_device='/dev/null')
    dependency.compare_configs(old, new)
    new['transport']['ssh_null_device'] = '/unsafe/config'
    with pytest.raises(ValueError, match='null device'):
        dependency.compare_configs(old, new)


@pytest.mark.parametrize('field', ['candidate_sha', 'protected_sha',
                                 'target', 'previous_runtime', 'authority'])
def test_dependency_transition_cannot_change_backup_authority(field):
    old, new = configs()
    new[field] = 'changed'
    with pytest.raises(ValueError, match='dependency-only'):
        dependency.compare_configs(old, new)


def test_ssh_key_or_host_contract_cannot_change():
    old, new = configs()
    new['transport'] = {'ssh_sha256': 'new', 'ssh_known_hosts_sha256': 'bad'}
    with pytest.raises(ValueError, match='SSH identity'):
        dependency.compare_configs(old, new)


def test_extra_config_field_and_duplicate_json_rejected():
    old, new = configs()
    new['extra'] = True
    with pytest.raises(ValueError, match='membership'):
        dependency.compare_configs(old, new)
    with pytest.raises(ValueError, match='duplicate'):
        dependency.unique_pairs([('path', 'first'), ('path', 'second')])


def test_git_reads_disable_hidden_changes_and_redirecting_environment(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv('GIT_DIR', '/wrong/repo')
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout='clean\n')
    monkeypatch.setattr(dependency.subprocess, 'run', run)
    assert dependency.git_read('/private/git', '/receiver', 'status') == 'clean'
    argv, kwargs = calls[0]
    assert argv[0] == '/private/git'
    assert '--no-optional-locks' in argv
    assert 'core.fsmonitor=false' in argv
    assert 'GIT_DIR' not in kwargs['env']
    assert kwargs['env']['GIT_OPTIONAL_LOCKS'] == '0'


def test_windows_wrapper_pins_child_git_and_preserves_exit_code(tmp_path):
    import ctypes
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    if os.name != 'nt' or ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip('requires an ordinary Windows token')
    powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    identity = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                              capture_output=True, text=True, check=True).stdout
    import csv
    sid = list(csv.reader(identity.splitlines()))[0][1]
    root = tmp_path / 'source'
    root.mkdir()
    private = tmp_path / 'private'
    private.mkdir()
    (private / 'git.exe').write_bytes(b'test path resolution only; never executed')
    verifier = tmp_path / 'verify.py'
    verifier.write_text('print(\'{"result":"PASS"}\')\n')
    launcher = root / 'run_laptop_backup_user_session.ps1'
    launcher.write_text(
        "param($ConfigPath,$ConfigSha256,$Mode)\n"
        "[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'resolved.txt'),"
        "(Get-Command git.exe).Source)\nexit 7\n")
    new = tmp_path / 'new.json'
    new.write_text(json.dumps({'receiver': str(root), 'git_path': str(private / 'git.exe')}))
    wrapper = Path(dependency.__file__).with_name('laptop_backup_private_git.ps1')
    data = {'schema': 'ARL-PRIVATE-GIT-V1', 'operator_sid': sid,
            'wrapper_sha256': dependency.digest(wrapper),
            'python_path': sys.executable, 'python_sha256': dependency.digest(sys.executable),
            'verifier_path': str(verifier), 'verifier_sha256': dependency.digest(verifier),
            'launcher_path': str(launcher), 'launcher_sha256': dependency.digest(launcher),
            'new_config': str(new), 'new_sha256': dependency.digest(new)}
    deployment = tmp_path / 'deployment.json'
    deployment.write_text(json.dumps(data))
    env = {k: v for k, v in os.environ.items() if k.lower() != 'psmodulepath'}
    result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-File', str(wrapper),
                             '-DeploymentPath', str(deployment), '-DeploymentSha256',
                             dependency.digest(deployment), '-Mode', 'probe'],
                            capture_output=True, text=True, timeout=30, env=env)
    assert result.returncode == 7, result.stdout + result.stderr
    assert (root / 'resolved.txt').read_text() == str(private / 'git.exe')
