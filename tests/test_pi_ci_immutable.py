"""File-only transaction fault tests; no Pi, service, SSH, sudo or cloud calls."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
from types import SimpleNamespace

import pytest

import pi_ci_access as access
import pi_ci_activate as activate
import pi_ci_client as client
import pi_ci_release as release
import pi_ci_snapshot as snapshot
import pi_deploy_service_snapshot as legacy


def digest(body):
    return hashlib.sha256(body).hexdigest()


def descriptor():
    files = {'program.py': b'print("approved source")\n', '.git/HEAD': b'a' * 40 + b'\n',
             '.git/config': release.SAFE_GIT_CONFIG, '.git/index': b'bounded test index bytes'}
    value = {'schema': 'ar-local-ci-release-v1', 'commit': 'a' * 40, 'files': {
        name: {'sha256': digest(body), 'bytes': len(body), 'mode': 0o444} for name, body in files.items()}}
    return value, files


@pytest.fixture
def portable_writes(monkeypatch):
    # POSIX root ownership and directory-fsync need separate Linux qualification.
    # File bytes, create-only semantics and directory identities stay real.
    if not hasattr(os, 'O_NOFOLLOW'): monkeypatch.setattr(os, 'O_NOFOLLOW', 0, raising=False)
    monkeypatch.setattr(release, 'sync_directory', lambda path: None)


@pytest.fixture
def transaction(tmp_path, monkeypatch, portable_writes):
    old = tmp_path / 'production'; old.mkdir()
    (old / 'tracked.py').write_bytes(b'previous approved source')
    (old / 'untracked-work').mkdir(); (old / 'untracked-work' / 'unique.txt').write_bytes(b'irreplaceable')
    (old / '.env').write_bytes(b'preserved private configuration')
    stage = tmp_path / 'stage'; stage.mkdir(); (stage / 'tracked.py').write_bytes(b'target approved source')
    context = dict(id='1' * 64, plan={'target_commit': 'a' * 40}, profile={}, stage=stage,
                   release={}, exchanged=tmp_path / 'retained', work=tmp_path / 'transaction')
    identities = {'old': release.identity(old)}
    monkeypatch.setattr(activate, 'PRODUCTION', old)
    monkeypatch.setattr(activate, 'check_profile', lambda value: None)
    monkeypatch.setattr(release, 'protected', lambda path, **kwargs: path)
    monkeypatch.setattr(release, 'verify_tree', lambda root, value, guard: guard())
    def materialize(source, target, value, guard):
        guard(); shutil.copytree(source, target)
        identities['new'] = release.identity(target)
        return identities['new']
    monkeypatch.setattr(release, 'materialize', materialize)
    def exchange(first, second, one, two):
        assert release.identity(first) == one and release.identity(second) == two
        temporary = tmp_path / 'exchanging'
        first.rename(temporary); second.rename(first); temporary.rename(second)
    monkeypatch.setattr(release, 'exchange', exchange)
    monkeypatch.setattr(activate, 'accept_release', lambda value: 'd' * 64)
    class Backend:
        binding = {'job_id': 'admitted-existing-host-job'}
        fail = set()
        def __init__(self):
            self.states = {name: 'active' if i == 0 else 'inactive' for i, name in enumerate(activate.TIMERS)}
            self.states.update({name: 'inactive' for name in activate.IDLE})
            self.states.update({'ar-local-dashboard.service': 'active', 'ar-local-daily.timer': 'active'})
            self.actions = []; self.phases = []
        def guard(self): pass
        def state(self, unit): return self.states[unit]
        def action(self, action, unit):
            self.actions.append((action, unit)); self.states[unit] = 'active' if action == 'start' else 'inactive'
        def worker(self, phase):
            self.phases.append(phase)
            if phase in self.fail: raise RuntimeError('injected ' + phase)
    return context, Backend(), old, identities


def test_success_retains_whole_previous_tree_and_only_restores_original_timers(transaction):
    context, backend, old, ids = transaction
    backend.binding['cgroup'] = '/system.slice/test-ci-transaction.service'
    result = activate.transaction(context, backend)
    assert result['result'] == 'PASS' and result['previous_checkout'] == 'RETAINED_COMPLETE'
    assert (old / 'tracked.py').read_bytes() == b'target approved source'
    assert (context['exchanged'] / 'untracked-work/unique.txt').read_bytes() == b'irreplaceable'
    assert (context['exchanged'] / '.env').read_bytes() == b'preserved private configuration'
    assert backend.phases == ['pre', 'post']
    assert all(unit == activate.TIMERS[0] for action, unit in backend.actions if unit.endswith('.timer'))
    assert all(action in ('stop', 'start') for action, unit in backend.actions)


@pytest.mark.parametrize('phase,expected', [('pre', 'FAILED_BEFORE_SWITCH'), ('post', 'ROLLED_BACK')])
def test_verifier_failure_restores_previous_identity_and_untracked_bytes(transaction, phase, expected):
    context, backend, old, ids = transaction; backend.fail = {phase}
    result = activate.transaction(context, backend)
    assert result['result'] == expected and release.identity(old) == ids['old']
    assert (old / 'untracked-work/unique.txt').read_bytes() == b'irreplaceable'
    assert backend.states[activate.TIMERS[0]] == 'active'
    if phase == 'post': assert backend.phases == ['pre', 'post', 'rollback-check', 'rollback']


def test_exchange_completed_but_fsync_readback_failed_is_rolled_back(transaction, monkeypatch):
    context, backend, old, ids = transaction
    real = release.exchange; calls = []
    def fail_after_exchange(*args):
        real(*args); calls.append(True)
        if len(calls) == 1: raise OSError('injected post-exchange fsync failure')
    monkeypatch.setattr(release, 'exchange', fail_after_exchange)
    assert activate.transaction(context, backend)['result'] == 'ROLLED_BACK'
    assert release.identity(old) == ids['old'] and len(calls) == 2


def test_unproven_rollback_keeps_coordination_stopped_and_no_terminal_claim(transaction):
    context, backend, old, ids = transaction; backend.fail = {'post', 'rollback-check'}
    with pytest.raises(RuntimeError, match='keep coordination stopped'):
        activate.transaction(context, backend)
    assert not (context['work'] / 'terminal.json').exists()
    assert backend.states[activate.TIMERS[0]] == 'inactive'


def test_resource_failure_after_exchange_requires_fresh_independent_finalizer(transaction, monkeypatch, tmp_path):
    context, backend, old, ids = transaction
    backend.binding['cgroup'] = '/system.slice/test-ci-transaction.service'
    state = tmp_path / 'ci-state'; state.mkdir(); (state / 'accepted').mkdir(); (state / 'completed').mkdir()
    monkeypatch.setattr(activate, 'STATE', state)
    context['previous'] = {'source_files': {'tracked.py': digest(b'previous approved source')}}
    failed = {'value': False}
    class Monitor:
        def __init__(self, fresh=False): self.fresh = fresh
        def check(self):
            if failed['value'] and not self.fresh: raise RuntimeError('whole-transaction host_swap_out_activity')
        def close(self): return {'result': 'PASS' if self.fresh else 'FAIL'}
    backend.monitor = Monitor(); backend.deadline = __import__('time').monotonic() + 1800
    backend.next_lease = 0; backend.finalizing = False
    backend.lease = lambda: activate.Native.lease(backend)
    original_native = activate.Native
    def worker(phase):
        backend.phases.append(phase)
        if phase == 'post': failed['value'] = True; backend.monitor.check()
        if phase.startswith('rollback'): original_native.rollback_guard(backend)
    backend.worker = worker
    with pytest.raises(RuntimeError, match='keep coordination stopped'):
        activate.transaction(context, backend)
    assert release.identity(old) == ids['new'] and not (context['work'] / 'terminal.json').exists()
    assert backend.states[activate.TIMERS[0]] == 'inactive'
    release.write(context['work'] / 'resources.json', {'result': 'FAIL', 'reason': 'host_swap_out_activity'})
    fresh = SimpleNamespace(binding=backend.binding, monitor=Monitor(fresh=True),
        action=backend.action, state=backend.state, rollback_guard=lambda: None,
        worker=lambda phase: backend.phases.append('fresh-' + phase))
    monkeypatch.setattr(activate, 'Native', lambda context, binding, finalizing: fresh)
    monkeypatch.setattr(activate, 'plan_context', lambda *args, **kwargs: context)
    monkeypatch.setattr(activate, 'finish_binding', lambda *args: None)
    monkeypatch.setattr(activate, 'properties', lambda unit, fields: {'ActiveState': backend.state(unit)})
    monkeypatch.setattr('pi_ci_resources.members', lambda group: {os.getpid()})
    # Queue/native admission is injected; actual finalizer filesystem decisions,
    # retained predecessor hashes/exchange, timer restoration and proof run.
    assert activate.finalize(context['id']) == 0
    assert release.identity(old) == ids['old']
    assert (old / 'untracked-work/unique.txt').read_bytes() == b'irreplaceable'
    assert backend.states[activate.TIMERS[0]] == 'active'
    result = release.read(state / 'completed' / (context['id'] + '.json'))
    assert result['result'] == 'ABORTED_RESTORED'
    assert result['acceptance'] == 'NOT_GRANTED_RUNTIME_RECHECK_REQUIRED'
    assert 'fresh-rollback-check' in backend.phases


def test_source_hash_inventory_detects_extra_changed_and_symlink_inputs(tmp_path):
    value, files = descriptor()
    for name, body in files.items():
        path = tmp_path / name; path.parent.mkdir(exist_ok=True, parents=True); path.write_bytes(body)
    release.descriptor(value, 'a' * 40, {'program.py': digest(files['program.py'])})
    release.verify_tree(tmp_path, value, lambda: None, trusted=False)
    (tmp_path / 'unapproved').write_bytes(b'extra')
    with pytest.raises(ValueError, match='extra'):
        release.verify_tree(tmp_path, value, lambda: None, trusted=False)
    (tmp_path / 'unapproved').unlink()
    (tmp_path / 'program.py').write_bytes(b'corrupted approved source')
    with pytest.raises(ValueError): release.verify_tree(tmp_path, value, lambda: None, trusted=False)


@pytest.mark.parametrize('name', ['../x', '/etc/passwd', '.git/hooks/post-checkout', '.git/objects/info/alternates'])
def test_release_rejects_external_paths_git_hooks_and_config(name):
    value, files = descriptor(); value['files'][name] = copy.deepcopy(value['files']['program.py'])
    with pytest.raises(ValueError): release.descriptor(value, 'a' * 40, {'program.py': digest(files['program.py'])})


def test_native_command_flags_preserved_while_runtime_timestamps_may_advance():
    value = {'type': 'a(sasasttttuii)', 'data': [['/usr/bin/python3', ['python3', '/source.py'], [], 0, 0, 0, 0, 0, 0, 0]]}
    changed = copy.deepcopy(value); changed['data'][0][3:] = [1, 2, 3, 4, 5, 1, 0]
    assert activate.execution_definition(value) == activate.execution_definition(changed)
    changed['data'][0][2] = ['privileged']
    assert activate.execution_definition(value) != activate.execution_definition(changed)
    changed['data'][0][3] = True
    with pytest.raises(ValueError): activate.execution_definition(changed)


def test_real_worker_launcher_has_private_pid_ro_sources_and_fixed_privilege_drop(tmp_path, monkeypatch, portable_writes):
    work = tmp_path / 'transaction'; work.mkdir()
    source = tmp_path / 'sealed-source'; source.mkdir()
    context = {'id': 'a' * 64, 'work': work, 'stage': tmp_path / 'stage',
               'sealed': {'source_root': str(source)}, 'plan': {'sealed_manifest_sha256': 'b' * 64}}
    native = activate.Native.__new__(activate.Native)
    native.context = context; native.binding = {'cgroup': '/system.slice/fixed-ci.service'}
    native.pi = SimpleNamespace(pw_uid=1000, pw_gid=1000); native.finalizing = False
    native.guard = native.rollback_guard = lambda: None; native.monitor = object()
    monkeypatch.setattr(os, 'chown', lambda *args: None, raising=False)
    real_stat = Path.stat
    monkeypatch.setattr(Path, 'stat', lambda path, **kw: SimpleNamespace(st_ino=123)
        if path.as_posix().startswith('/proc/self/ns/') else real_stat(path, **kw))
    calls = []
    def worker(argv, binding, guard, output, observer):
        calls.append(argv)
        (work / 'worker-pre/result.json').write_text(json.dumps({'result': 'PASS', 'phase': 'pre'}))
    monkeypatch.setattr(activate, 'monitored_worker', worker)
    assert native.worker('pre')['result'] == 'PASS'
    argv = calls[0]
    assert '--unshare-pid' in argv and '--unshare-user' not in argv and '--cap-add' not in argv
    assert argv[argv.index('--ro-bind'):argv.index('--ro-bind') + 3] == ['--ro-bind', '/', '/']
    assert all(option in argv for option in ('--no-new-privs', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all', '--clear-groups'))
    assert argv[argv.index('/usr/bin/python3') + 1:][:3] == ['-I', '-B', '/worker.py']
    assert '/namespace.json' in argv and 'GIT_CONFIG_VALUE_0' in argv
    assert not any('PYTHONPATH' in token or 'LD_PRELOAD' in token for token in argv)


@pytest.mark.parametrize('repo', ['/srv/ar local/repo', '/srv/ar; echo injection/repo', "/srv/ar'$(echo injection)/repo"])
def test_verifier_path_is_one_literal_shell_argument_without_executing_it(repo):
    script = legacy._post_start_shell(repo)
    command = shlex.split(script[script.index('/usr/bin/python3 '):])
    assert command[:2] == ['/usr/bin/python3', repo + '/verify_local.py']
    assert command[2] == '--base-url=http://127.0.0.1:8808/'
    for name in ('ar-local-daily.service', 'ar-local-ingest-now.service'):
        unit = (Path(__file__).resolve().parents[1] / 'deploy/pi' / name).read_text()
        line = next(line for line in unit.splitlines() if line.startswith('ExecStartPost=/bin/sh'))
        assert '{{AR_LOCAL_REPO}}' not in line
        decoded = shlex.split(line.split('=', 1)[1])[2].replace('$$', '$').replace('%%', '%')
        assert decoded == legacy._post_start_shell(repo, working_directory=True)


def test_legacy_native_reads_are_parallel_bounded_and_keep_ex_flags(monkeypatch):
    argv = shlex.split(legacy._ingest_definition_script('DAILY', 'ar-local-daily.service').removesuffix('; '))
    code = argv[-1]; calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'type': 'a(sasasttttuii)', 'data': [['flags-retained']]}))
    monkeypatch.setattr('subprocess.run', run)
    namespace = {}; exec(compile(code, 'actual-remote-native-read-program', 'exec'), namespace)
    assert len(calls) == 12 and all(options['timeout'] == 4 and options['shell'] is False for _, options in calls)
    native = [command for command, _ in calls if command[0] == 'busctl']
    assert len(native) == 8 and all('--timeout=3' in command for command in native)
    assert any(command[-1] == 'ExecStopPostEx' for command in native)


def test_restricted_client_mismatch_never_activates(monkeypatch):
    calls = []
    monkeypatch.setattr(client, 'call', lambda command, **kwargs: calls.append(command) or {'result': 'APPROVED_PLAN'})
    args = SimpleNamespace(allow_empty_rates=False, dry_run=False, deploy=True, approved_plan='a' * 64)
    with pytest.raises(ValueError, match='differs'):
        client.execute(args, host='ar-local-pi5', expected_commit='b' * 40, canary_sha256='c' * 64, canary_tag='canary-approved')
    assert calls == ['check ' + 'a' * 64]


def test_restricted_client_never_sends_shell_scripts_or_owner_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(client.subprocess, 'run', lambda argv, **kw: calls.append((argv, kw)) or SimpleNamespace(stdout='{"result":"OBSERVED"}'))
    assert client.call('status', host='ar-local-pi5')['result'] == 'OBSERVED'
    assert calls[0][0][-2:] == ['ar-local-pi5', 'status'] and calls[0][1]['shell'] is False
    for text in ('status; id', 'bash -c status', 'activate ../x'):
        with pytest.raises(ValueError): client.call(text, host='ar-local-pi5')


@pytest.mark.parametrize('version', [True, False, 2.0, '2', None])
def test_v2_plan_rejects_noninteger_schema_before_any_other_reads(monkeypatch, version):
    keys = {'schema_version', 'scope', 'target_commit', 'previous_commit', 'expires_at',
            'sealed_manifest_sha256', 'recovery_approval_sha256', 'adapter_sha256', 'runtime_profile_sha256',
            'release_manifest_sha256', 'predecessor_manifest_sha256', 'canary_manifest_sha256', 'canary_release_tag'}
    value = dict.fromkeys(keys, 'x'); value['schema_version'] = version
    monkeypatch.setattr(release, 'read', lambda *args: value)
    with pytest.raises(ValueError, match='invalid immutable'):
        activate.plan_context('a' * 64)


@pytest.mark.skipif(os.name != 'posix', reason='openat dir_fd/no-follow qualification runs on Linux')
@pytest.mark.parametrize('mutation', ['none', 'changed_bytes', 'symlink', 'fifo', 'raced_symlink'])
def test_untrusted_input_is_only_read_beneath_held_fds_and_never_executed(tmp_path, monkeypatch, mutation):
    value, files = descriptor()
    source = tmp_path / 'input'; source.mkdir()
    target = tmp_path / 'root-stage'
    for name, body in files.items():
        path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
    outside = tmp_path / 'outside-private'; outside.write_bytes(b'never copy this unapproved data')
    if mutation == 'changed_bytes': (source / 'program.py').write_bytes(b'wrong bytes')
    if mutation in ('symlink', 'fifo'):
        (source / 'program.py').unlink()
        if mutation == 'symlink': (source / 'program.py').symlink_to(outside)
        else: os.mkfifo(source / 'program.py')
    real_open = os.open
    if mutation == 'raced_symlink':
        def raced(path, flags, *args, **kwargs):
            if path == 'program.py' and kwargs.get('dir_fd') is not None:
                (source / 'program.py').unlink(); (source / 'program.py').symlink_to(outside)
            return real_open(path, flags, *args, **kwargs)
        monkeypatch.setattr(os, 'open', raced)
    monkeypatch.setattr(release, 'protected', lambda path, **kwargs: path)
    real_verify = release.verify_tree
    monkeypatch.setattr(release, 'verify_tree', lambda root, value, guard: real_verify(root, value, guard, trusted=False))
    if mutation == 'none':
        release.stage_input(source, target, value, lambda: None)
        assert (target / 'program.py').read_bytes() == files['program.py']
    else:
        with pytest.raises((ValueError, OSError)): release.stage_input(source, target, value, lambda: None)
        assert target.stat().st_mode & 0o777 == 0o700
    assert outside.read_bytes() == b'never copy this unapproved data'


@pytest.mark.skipif(os.name != 'posix', reason='native POSIX directory umask semantics')
def test_materialized_nested_release_is_traversable_with_umask_0077(tmp_path, monkeypatch):
    import stat
    value, files = descriptor()
    files['package/nested/module.py'] = b'VALUE = 42\n'
    value['files']['package/nested/module.py'] = {'sha256': digest(files['package/nested/module.py']), 'bytes': 11, 'mode': 0o444}
    source = tmp_path / 'source'; source.mkdir()
    for name, body in files.items():
        path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
    monkeypatch.setattr(release, 'protected', lambda path, **kwargs: path)
    actual = release.verify_tree
    monkeypatch.setattr(release, 'verify_tree', lambda root, value, guard: actual(root, value, guard, trusted=False))
    destination = tmp_path / 'release'
    previous = os.umask(0o077)
    try: release.materialize(source, destination, value, lambda: None)
    finally: os.umask(previous)
    for directory, _, _ in os.walk(destination): assert stat.S_IMODE(Path(directory).stat().st_mode) == 0o755
    assert (destination / 'package/nested/module.py').read_bytes() == b'VALUE = 42\n'
