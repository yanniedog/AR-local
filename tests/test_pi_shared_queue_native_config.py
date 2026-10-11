"""Fixed-layout native bridge checks never need Linux processes or Pi access."""
from pathlib import Path
import subprocess
from contextlib import contextmanager
import os
from types import SimpleNamespace

import pytest

from pi_shared_queue_native import _environment_file_roots, verify_native_deployment


def inspect(environment='AR_LOCAL_DATA_ROOT=/srv/ar-local/data AR_LOCAL_PORTABLE_ROOT=/srv/ar-local',
            files='', passed='', unset='', loaded='loaded'):
    return SimpleNamespace(stdout='\n'.join([
        'LoadState=' + loaded, 'Environment=' + environment,
        'EnvironmentFiles=' + files, 'PassEnvironment=' + passed,
        'UnsetEnvironment=' + unset]))


def check(result=None, **kwargs):
    return verify_native_deployment(environ={}, run=lambda *a, **k: result or inspect(),
                                    resolve=lambda path: path, **kwargs)


def test_fixed_producer_layout_is_accepted():
    check()


@pytest.mark.parametrize('name,value', [
    ('AR_LOCAL_DATA_ROOT', '/other/data'),
    ('AR_LOCAL_PORTABLE_ROOT', '/other'),
    ('AR_LOCAL_DATA_ROOT', ''),
])
def test_caller_override_is_rejected_before_inspection(name, value):
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported caller layout must not inspect services')
    with pytest.raises(ValueError, match='unsupported native bridge'):
        verify_native_deployment(environ={name: value}, run=forbidden)


@pytest.mark.parametrize('result', [
    inspect(environment='AR_LOCAL_DATA_ROOT=/other/data'),
    inspect(environment='AR_LOCAL_PORTABLE_ROOT=/srv/ar-local'),
    inspect(passed='AR_LOCAL_DATA_ROOT'),
    inspect(unset='AR_LOCAL_DATA_ROOT'),
    inspect(unset='AR_LOCAL_DATA_ROOT=/srv/ar-local/data'),
    inspect(loaded='not-found'),
    inspect(files='/etc/env* (ignore_errors=yes)'),
    inspect(files='/etc/../env (ignore_errors=no)'),
    inspect(files='/etc/some env (ignore_errors=no)'),
])
def test_unsupported_effective_producer_configuration_denies(result):
    with pytest.raises(ValueError):
        check(result)


def test_environment_files_are_inspected_for_overrides():
    seen = []
    def read(path):
        seen.append(path)
        return {'AR_LOCAL_DATA_ROOT': '/other/data'}
    with pytest.raises(ValueError, match='unsupported native bridge'):
        check(inspect(files='/etc/ar-local.env (ignore_errors=no)'), read_roots=read)
    assert seen == [Path('/etc/ar-local.env')]


def test_repeated_environment_file_properties_keep_first_file_override():
    result = inspect(files='/etc/first.env (ignore_errors=no)')
    result.stdout += '\nEnvironmentFiles=/etc/second.env (ignore_errors=no)'
    seen = []
    def read(path):
        seen.append(path)
        return {'AR_LOCAL_DATA_ROOT': '/other/data'} if path.name == 'first.env' else {}
    with pytest.raises(ValueError, match='unsupported native bridge'):
        check(result, read_roots=read)
    assert seen == [Path('/etc/first.env')]


def test_repeated_environment_file_properties_are_read_in_order():
    result = inspect(files='/etc/first.env (ignore_errors=no)')
    result.stdout += '\nEnvironmentFiles=/etc/second.env (ignore_errors=no)'
    seen = []
    def read(path):
        seen.append(path)
        return {'AR_LOCAL_DATA_ROOT': '/srv/ar-local/data'}
    check(result, read_roots=read)
    assert seen == [Path('/etc/first.env'), Path('/etc/second.env')]


@pytest.mark.parametrize('field', ['Environment', 'LoadState', 'PassEnvironment', 'UnsetEnvironment'])
def test_duplicate_non_file_properties_are_ambiguous(field):
    result = inspect()
    result.stdout += '\n' + field + '='
    with pytest.raises(ValueError, match='duplicate'):
        check(result)


def test_environment_file_can_explicitly_supply_fixed_data_root():
    check(inspect(environment='', files='/etc/ar-local.env (ignore_errors=no)'),
          read_roots=lambda path: {'AR_LOCAL_DATA_ROOT': '/srv/ar-local/data'})


def test_only_missing_optional_file_is_ignored():
    def missing(path):
        raise FileNotFoundError(path)
    check(inspect(files='/etc/missing.env (ignore_errors=yes)'), read_roots=missing)
    with pytest.raises(FileNotFoundError):
        check(inspect(files='/etc/missing.env (ignore_errors=no)'), read_roots=missing)
    def unreadable(path):
        raise PermissionError(path)
    with pytest.raises(PermissionError):
        check(inspect(files='/etc/missing.env (ignore_errors=yes)'), read_roots=unreadable)


def test_symlinked_fixed_root_denies():
    with pytest.raises(ValueError, match='symlinks'):
        verify_native_deployment(environ={}, run=lambda *a, **k: inspect(),
                                  resolve=lambda path: Path('/different/root'))


@pytest.mark.parametrize('value', ['/srv/ar-local/data', '"/srv/ar-local/data"', "'/srv/ar-local/data'"])
def test_environment_file_accepts_only_simple_fixed_assignments(tmp_path, value):
    path = tmp_path / 'producer.env'
    path.write_text('TOKEN=private\nAR_LOCAL_DATA_ROOT=' + value + '\n', encoding='utf-8')
    assert _environment_file_roots(path) == {'AR_LOCAL_DATA_ROOT': '/srv/ar-local/data'}


@pytest.mark.parametrize('value', ['/other/data', '$HOME/data', '"/srv/ar-local/data\\\n/other"', ''])
def test_environment_file_root_syntax_fails_closed_without_secret_output(tmp_path, value):
    path = tmp_path / 'producer.env'
    path.write_text('TOKEN=private\nAR_LOCAL_DATA_ROOT=' + value + '\n', encoding='utf-8')
    with pytest.raises(ValueError) as error:
        _environment_file_roots(path)
    assert 'private' not in str(error.value)
    assert value not in str(error.value) if value else True


def test_readonly_inspection_uses_only_show_and_keeps_environment_private(capsys):
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return inspect(environment='TOKEN=private AR_LOCAL_DATA_ROOT=/srv/ar-local/data')
    verify_native_deployment(environ={}, run=run, resolve=lambda path: path)
    assert commands[0][:3] == ['systemctl', 'show', 'ar-local-daily.service']
    assert capsys.readouterr().out == ''


def test_root_only_environment_file_is_read_privately_and_bounded(monkeypatch, capsys):
    def denied(*args, **kwargs):
        raise PermissionError('root-only environment directory')
    monkeypatch.setattr(Path, 'open', denied)
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        assert kwargs['capture_output'] is True and kwargs['check'] is True
        return SimpleNamespace(stdout=b'TOKEN=private\nAR_LOCAL_DATA_ROOT=/srv/ar-local/data\n')
    monkeypatch.setattr('pi_shared_queue_native.subprocess.run', run)
    assert _environment_file_roots(Path('/etc/ar-local/app-payload.env')) == {
        'AR_LOCAL_DATA_ROOT': '/srv/ar-local/data'}
    assert commands[0][:3] == ['sudo', '-n', '/usr/bin/python3']
    assert 's.st_uid==0' in commands[0][4]
    assert 'os.O_NOFOLLOW' in commands[0][4]
    compile(commands[0][4], '<bounded root reader>', 'exec')
    assert capsys.readouterr().out == ''


def test_root_only_oversized_file_fails_closed(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError()
    monkeypatch.setattr(Path, 'open', denied)
    monkeypatch.setattr('pi_shared_queue_native.subprocess.run',
                        lambda *a, **k: SimpleNamespace(stdout=b'x' * 65537))
    with pytest.raises(ValueError, match='oversized'):
        _environment_file_roots(Path('/etc/ar-local/app-payload.env'))


def test_missing_root_only_optional_file_is_still_optional(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError()
    def missing(command, **kwargs):
        raise subprocess.CalledProcessError(44, command)
    monkeypatch.setattr(Path, 'open', denied)
    monkeypatch.setattr('pi_shared_queue_native.subprocess.run', missing)
    check(inspect(files='/etc/ar-local/missing.env (ignore_errors=yes)'))


@pytest.fixture
def native_cleanup(tmp_path, monkeypatch):
    if os.name != 'posix':
        pytest.skip('native lease unlink and directory fsync require POSIX')
    import pi_shared_queue_native as native
    job = {'id': 'recovered-job', 'project': 'other', 'resources': ['host'],
           'mode': 'exclusive', 'cpu_slots': 1, 'max_duration_seconds': 600,
           'state': 'running', 'sequence': 0, 'queued_monotonic': 100,
           'pid': 123, 'start_ticks': 100,
           'boot_id': '12345678-1234-1234-1234-123456789abc',
           'unit': 'shared-pi-task-recovered.service', 'invocation_id': 'a' * 32,
           'cgroup': '/system.slice/shared-pi-task-recovered.service'}
    path = tmp_path / 'daily-ingest.lock'
    body = 'pid=123\nboot_id=' + job['boot_id'] + '\nrole=shared-pi-host-task:recovered-job\n'
    active = [False]
    @contextmanager
    def lock(target):
        assert target == path
        assert not active[0]
        active[0] = True
        try:
            yield
        finally:
            active[0] = False
    return native, job, path, body, lock, active


@pytest.mark.parametrize('marker', ['', 'recovery=manual\n'])
def test_exact_pre_marker_and_marked_native_claims_are_recovered(native_cleanup, marker):
    native, job, path, body, lock, active = native_cleanup
    path.write_text(body + marker)
    assert native.clear_native_manual(job, path, recovery_lock_factory=lock)
    assert not path.exists() and not active[0]


@pytest.mark.parametrize('change', ['foreign-role', 'foreign-pid', 'foreign-boot', 'unknown-key', 'automatic'])
def test_native_cleanup_preserves_foreign_or_unrecognized_claims(native_cleanup, change):
    native, job, path, body, lock, active = native_cleanup
    if change == 'foreign-role':
        body = body.replace('recovered-job', 'other-job')
    elif change == 'foreign-pid':
        body = body.replace('pid=123', 'pid=124')
    elif change == 'foreign-boot':
        body = body.replace(job['boot_id'], '87654321-1234-1234-1234-123456789abc')
    else:
        body += 'unknown=value\n' if change == 'unknown-key' else 'recovery=automatic\n'
    path.write_text(body)
    assert not native.clear_native_manual(job, path, recovery_lock_factory=lock)
    assert path.read_text() == body


def test_native_cleanup_reads_and_unlinks_only_inside_recovery_lock(native_cleanup, monkeypatch):
    native, job, path, body, lock, active = native_cleanup
    path.write_text(body)
    original_read, original_unlink = native._native_values, Path.unlink
    def read(fd):
        assert active[0]
        return original_read(fd)
    def unlink(target, *args, **kwargs):
        assert active[0]
        return original_unlink(target, *args, **kwargs)
    monkeypatch.setattr(native, '_native_values', read)
    monkeypatch.setattr(Path, 'unlink', unlink)
    assert native.clear_native_manual(job, path, recovery_lock_factory=lock)


def test_native_cleanup_rechecks_a_claim_changed_before_lock_acquisition(native_cleanup):
    native, job, path, body, lock, active = native_cleanup
    path.write_text(body)
    replacement = body.replace('recovered-job', 'new-owner')
    @contextmanager
    def competing_recovery(target):
        with lock(target):
            target.write_text(replacement)
            yield
    assert not native.clear_native_manual(job, path, recovery_lock_factory=competing_recovery)
    assert path.read_text() == replacement


def test_native_cleanup_does_not_unlink_changed_inode(native_cleanup, monkeypatch):
    native, job, path, body, lock, active = native_cleanup
    path.write_text(body)
    original_lstat = Path.lstat
    def changed(target, *args, **kwargs):
        info = original_lstat(target, *args, **kwargs)
        return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino + 1) if target == path else info
    monkeypatch.setattr(Path, 'lstat', changed)
    assert not native.clear_native_manual(job, path, recovery_lock_factory=lock)
    assert path.read_text() == body


def test_native_recovery_uses_deployed_helper_lock_namespace(monkeypatch):
    import pi_shared_queue_native as native
    seen = []
    namespace = {'FileLock': lambda path: seen.append(path) or 'lock-context',
                 'recovery_lock_path': lambda path: path.with_name('.' + path.name + '.recovery-lock')}
    exec('def factory():\n    pass\n', namespace)
    factory = namespace['factory']
    monkeypatch.setattr(native, 'native_lock_factory', lambda: factory)
    path = Path('/srv/ar-local/data/state/daily-ingest.lock')
    assert native._native_recovery_lock(path) == 'lock-context'
    assert seen == [path.with_name('.daily-ingest.lock.recovery-lock')]


def test_native_recovery_unwraps_contextmanager_helper(monkeypatch):
    import pi_shared_queue_native as native
    seen = []
    namespace = {'contextmanager': contextmanager,
                 'FileLock': lambda path: seen.append(path) or 'wrapped-lock',
                 'recovery_lock_path': lambda path: path.with_name('.' + path.name + '.recovery-lock')}
    exec('@contextmanager\ndef production_lock():\n    yield\n', namespace)
    factory = namespace['production_lock']
    assert 'FileLock' not in factory.__globals__
    monkeypatch.setattr(native, 'native_lock_factory', lambda: factory)
    path = Path('/srv/ar-local/data/state/daily-ingest.lock')
    assert native._native_recovery_lock(path) == 'wrapped-lock'
    assert seen == [path.with_name('.daily-ingest.lock.recovery-lock')]


def test_native_recovery_missing_api_fails_closed(monkeypatch):
    import pi_shared_queue_native as native
    monkeypatch.setattr(native, 'native_lock_factory', lambda: lambda: None)
    with pytest.raises(ValueError, match='API unavailable'):
        native._native_recovery_lock(Path('/srv/ar-local/data/state/daily-ingest.lock'))
