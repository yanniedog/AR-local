import json
import subprocess
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pi_shared_network_watchdog as network
import pytest


@pytest.fixture(autouse=True)
def ordinary_recovery_context(monkeypatch, tmp_path):
    original_window = getattr(network, 'recovery_window_blocked', None)
    # Unit recovery fixtures must never inspect or lock the operator's queue.
    # Dedicated queue-guard tests supply their own real temporary queue.
    monkeypatch.setattr(network, 'QUEUE_ROOT', tmp_path / 'shared-pi-queue')
    monkeypatch.setattr(network.os, 'geteuid', lambda: 1000, raising=False)
    monkeypatch.setattr(network, 'recovery_window_blocked', lambda: False, raising=False)
    return original_window


def result(stdout='', code=0):
    return SimpleNamespace(stdout=stdout, returncode=code)


READ_ONLY_ROUTE_COMMAND = ['ip', '-j', 'route', 'show', 'default']


def network_mutations(calls):
    """Only explicitly enumerated observations are safe in deferred paths."""
    observations = {'ping', 'ss', 'who', 'ps'}
    return [args for args in calls if args[0] not in observations
            and args != READ_ONLY_ROUTE_COMMAND
            and args != ['tailscale', 'debug', 'prefs']
            and not (args[0] == 'systemctl' and args[1] in {'is-active', 'show'})
            and not (args[0] == 'nmcli' and args[1:3] == ['-g', 'GENERAL.TYPE'])]


def test_healthy_gateway_never_restarts_network_for_internet_outage(tmp_path):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[0] == 'ip':
            return result('[{"gateway":"192.168.1.1","dev":"wlan0"}]')
        if args[0] == 'ping':
            return result(code=0 if args[-1] == '192.168.1.1' else 1)
        raise AssertionError(f'unexpected command: {args}')
    with patch.object(network, 'command', run):
        assert 'healthy' in network.recover(tmp_path / 'state.json', tmp_path)
    assert [row[0] for row in calls] == ['ip', 'ping']
    assert calls[1] == ['ping', '-c1', '-W3', '192.168.1.1']


def test_remote_deployment_prevents_recovery_after_repeated_gateway_failures(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 2}))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return {'ip': result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'),
                'ping': result(code=1), 'nmcli': result('wifi'),
                'ss': result('ESTAB remote SSH'), 'who': result(),
                'ps': result(), 'tailscale': result('{"RunSSH":false}')}[args[0]]
    with patch.object(network, 'command', run):
        assert 'remote session active' in network.recover(state, tmp_path)
    assert network_mutations(calls) == []


def test_missing_session_evidence_prevents_recovery():
    with patch.object(network, 'command', side_effect=lambda args, **kw: result(code=1)):
        assert network.remote_sessions_active()


def test_single_gateway_failure_does_not_mutate_network(tmp_path):
    with patch.object(network, 'command', side_effect=[
            result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'), result(code=1)]):
        assert 'below' in network.recover(tmp_path / 'state.json', tmp_path)


@pytest.mark.parametrize('units,expected', [('failed\ninactive\ninactive\n', True),
    ('active\ninactive\ninactive\n', False), ('inactive\ninactive\nactive\n', False), ('', False)])
def test_only_idle_verified_wifi_can_be_recovered(tmp_path, units, expected):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 2}))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[0] == 'sudo':
            return result()
        return {'ip': result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'),
                'ping': result(code=1), 'nmcli': result('wifi'), 'ss': result(),
                'who': result(), 'ps': result(), 'tailscale': result('{"RunSSH":false}'),
                'systemctl': result(units, code=3)}[args[0]]
    with patch.object(network, 'command', run), patch.object(
            network, 'native_network_lease', return_value=nullcontext(True)):
        network.recover(state, tmp_path)
    mutations = network_mutations(calls)
    assert mutations == ([['sudo', '-n', '/usr/bin/nmcli', '--wait', '20',
                           'device', 'connect', 'wlan0']] if expected else [])
    if expected:
        assert json.loads(state.read_text())['failures'] == 0


@pytest.mark.parametrize('login,remote', [('pi :0 (:0)', False), ('pi pts/0 (192.168.1.2)', True)])
def test_local_display_does_not_block_recovery(login, remote):
    def run(args, **kwargs):
        return {'ss': result(), 'who': result(login), 'ps': result(),
                'tailscale': result('{"RunSSH":false}')}[args[0]]
    with patch.object(network, 'command', run):
        assert network.remote_sessions_active() is remote


@pytest.mark.parametrize('old_state', ['broken JSON', '[]', '{"failures": "bad"}'])
def test_corrupt_state_restarts_threshold_without_recovery(tmp_path, old_state):
    state = tmp_path / 'state.json'
    state.write_text(old_state)
    with patch.object(network, 'command', side_effect=[
            result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'), result(code=1)]):
        assert 'below' in network.recover(state, tmp_path)
    assert json.loads(state.read_text()) == {
        'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 1}


def test_eligible_dry_run_preserves_state_and_never_acquires_lease(tmp_path):
    state = tmp_path / 'state.json'
    original = json.dumps({'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 2})
    state.write_text(original)
    def run(args, **kwargs):
        assert 'connect' not in args
        return {'ip': result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'),
                'ping': result(code=1), 'nmcli': result('wifi'), 'ss': result(),
                'who': result(), 'ps': result(), 'tailscale': result('{"RunSSH":false}'),
                'systemctl': result('inactive\nfailed\ninactive\n', code=3)}[args[0]]
    with patch.object(network, 'command', run), patch.object(network, 'native_network_lease') as lease:
        assert 'eligible' in network.recover(state, tmp_path, dry_run=True)
        lease.assert_not_called()
    assert state.read_text() == original
    assert not (tmp_path / 'state.tmp').exists()


def prepared_state(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 2}))
    return state


def eligible_commands(calls):
    responses = {
        tuple(READ_ONLY_ROUTE_COMMAND): result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'),
        ('ping', '-c1', '-W3', '192.168.1.1'): result(code=1),
        ('nmcli', '-g', 'GENERAL.TYPE', 'device', 'show', 'wlan0'): result('wifi'),
        ('ss', '-Htn', 'state', 'established', '( sport = :22 )'): result(),
        ('who',): result(), ('ps', '-eo', 'comm,args'): result(),
        ('tailscale', 'debug', 'prefs'): result('{"RunSSH":false}'),
        ('systemctl', 'is-active', 'ar-local-daily.service', 'ar-local-ingest-now.service',
         'ar-local-daily-watchdog.service'): result('inactive\nfailed\ninactive\n', code=3),
        ('sudo', '-n', '/usr/bin/nmcli', '--wait', '20', 'device', 'connect', 'wlan0'): result(),
    }
    def run(args, **kwargs):
        calls.append(args)
        if tuple(args) not in responses:
            raise AssertionError(f'unexpected command: {args}')
        return responses[tuple(args)]
    return run


def test_quiet_window_never_takes_ingest_lease(tmp_path):
    calls = []
    with patch.object(network, 'command', eligible_commands(calls)), patch.object(
            network, 'recovery_window_blocked', return_value=True), patch.object(
            network, 'native_network_lease') as lease:
        assert 'deferred' in network.recover(prepared_state(tmp_path), tmp_path)
    lease.assert_not_called()
    assert network_mutations(calls) == []


def test_quiet_window_entered_during_inspection_prevents_mutation(tmp_path):
    calls = []
    with patch.object(network, 'command', eligible_commands(calls)), patch.object(
            network, 'recovery_window_blocked', side_effect=[False, False, True]), patch.object(
            network, 'native_network_lease', return_value=nullcontext(True)) as lease:
        assert 'deferred' in network.recover(prepared_state(tmp_path), tmp_path)
    lease.assert_called_once()
    assert network_mutations(calls) == []


def test_root_recovery_rejected_before_acquiring_native_lease(tmp_path):
    calls = []
    with patch.object(network.os, 'geteuid', return_value=0), patch.object(
            network, 'command', eligible_commands(calls)), patch.object(
            network, 'native_network_lease') as lease:
        with pytest.raises(RuntimeError):
            network.recover(prepared_state(tmp_path), tmp_path)
    lease.assert_not_called()
    assert network_mutations(calls) == []


@pytest.mark.parametrize('prefs', ['{"RunSSH":true}', '{}', 'broken JSON'])
def test_tailscale_ssh_or_unknown_preferences_defer_without_pty(prefs):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return result(prefs if args[0] == 'tailscale' else '')
    with patch.object(network, 'command', run):
        assert network.remote_sessions_active()
    assert network_mutations(calls) == []


@pytest.mark.parametrize('processes', ['sshd sshd: pi@notty', 'sshd sshd: pi@pts/1',
                                       'tailscaled /usr/sbin/tailscaled be-child ssh --uid=1000'])
def test_nonstandard_port_or_noninteractive_sshd_session_is_detected(processes):
    def run(args, **kwargs):
        return result('{"RunSSH":false}' if args[0] == 'tailscale'
                      else processes if args[0] == 'ps' else '')
    with patch.object(network, 'command', run):
        assert network.remote_sessions_active()


@pytest.mark.parametrize('error', [OSError('unavailable'), RuntimeError('failed reconnect'),
    ValueError('bad route'), subprocess.TimeoutExpired('observation', 5)])
def test_operational_failure_is_nonzero_and_does_not_expose_details(error, capsys):
    with patch.object(network, 'recover', side_effect=error):
        assert network.main() != 0
    captured = capsys.readouterr()
    assert type(error).__name__ in captured.err
    assert str(error) not in captured.err


def test_normal_deferral_is_success(capsys):
    with patch.object(network, 'recover', return_value='recovery deferred: ingest active'):
        assert network.main() == 0
    assert 'deferred' in capsys.readouterr().out


def test_failed_interface_reconnect_is_operational_failure(tmp_path):
    calls = []
    base = eligible_commands(calls)
    def run(args, **kwargs):
        return result(code=1) if args[0] == 'sudo' else base(args, **kwargs)
    with patch.object(network, 'command', run), patch.object(
            network, 'native_network_lease', return_value=nullcontext(True)):
        with pytest.raises(RuntimeError):
            network.recover(prepared_state(tmp_path), tmp_path)


@pytest.mark.parametrize('clock,blocked', [('00:27:59', False), ('00:28:00', True),
    ('00:29:59', True), ('00:30:00', True), ('01:00:00', True), ('01:59:59', True),
    ('02:00:00', False), ('23:59:59', False)])
def test_hobart_recovery_window_and_full_execution_lookahead(
        ordinary_recovery_context, clock, blocked):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.fromisoformat('2026-10-11T' + clock).replace(tzinfo=ZoneInfo('Australia/Hobart'))
    assert ordinary_recovery_context(now) is blocked


def test_naive_recovery_clock_cannot_prove_safe_window(ordinary_recovery_context):
    from datetime import datetime
    with pytest.raises(ValueError):
        ordinary_recovery_context(datetime(2026, 10, 11, 4))


@pytest.mark.parametrize('gateway,interface', [('-f', 'wlan0'), ('192.168.1.1', '--help'),
    ('not-an-address', 'wlan0'), ('192.168.1.1', 'wlan0;reboot')])
def test_untrusted_route_cannot_supply_command_options(gateway, interface):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return result(json.dumps([{'gateway': gateway, 'dev': interface}]))
    with patch.object(network, 'command', run):
        with pytest.raises(RuntimeError):
            network.default_route()
    assert calls == [['ip', '-j', 'route', 'show', 'default']]


def test_occupied_native_lease_is_normal_deferral(tmp_path):
    calls = []
    with patch.object(network, 'command', eligible_commands(calls)), patch.object(
                network, 'native_network_lease', return_value=nullcontext(False)):
        assert 'lease occupied' in network.recover(prepared_state(tmp_path), tmp_path)
    assert network_mutations(calls) == []


def test_command_deadline_bounds_entire_run(monkeypatch):
    monkeypatch.setattr(network, 'COMMAND_DEADLINE', 122)
    monkeypatch.setattr(network.time, 'monotonic', lambda: 120)
    with patch.object(network.subprocess, 'run', return_value=result()) as run:
        network.command(['who'], timeout=25)
    assert run.call_args.kwargs['timeout'] == 2
    assert run.call_args.args == (['who'],)
    assert run.call_args.kwargs.get('shell', False) is False


def test_exhausted_command_budget_never_spawns_process(monkeypatch):
    monkeypatch.setattr(network, 'COMMAND_DEADLINE', 120)
    monkeypatch.setattr(network.time, 'monotonic', lambda: 120)
    with patch.object(network.subprocess, 'run') as run:
        with pytest.raises(TimeoutError):
            network.command(['who'])
    run.assert_not_called()


@pytest.mark.parametrize('missing_source', ['ps', 'tailscale', 'ss', 'who'])
def test_any_unavailable_session_observation_defers(missing_source):
    def run(args, **kwargs):
        return result('{"RunSSH":false}' if args[0] == 'tailscale' else '',
                      code=1 if args[0] == missing_source else 0)
    with patch.object(network, 'command', run):
        assert network.remote_sessions_active()


def test_unexpected_native_lease_error_remains_operational_failure(tmp_path):
    calls = []
    @contextmanager
    def unavailable():
        raise RuntimeError('unexpected inspection failure')
        yield
    with patch.object(network, 'command', eligible_commands(calls)), patch.object(
            network, 'native_network_lease', return_value=unavailable()):
        with pytest.raises(RuntimeError, match='unexpected inspection failure'):
            network.recover(prepared_state(tmp_path), tmp_path)
    assert network_mutations(calls) == []


@pytest.mark.parametrize('mutation', [
    ['ip', 'link', 'set', 'wlan0', 'down'],
    ['ip', 'route', 'flush', 'default'],
    ['ip', 'route', 'add', 'default', 'via', '192.168.1.1'],
])
def test_command_test_helpers_reject_ip_mutations(mutation):
    assert network_mutations([READ_ONLY_ROUTE_COMMAND, mutation]) == [mutation]
    with pytest.raises(AssertionError, match='unexpected command'):
        eligible_commands([])(mutation)


@pytest.mark.parametrize('abort', [False, True])
def test_main_initializes_execution_deadline_before_recovery_and_restores_it(monkeypatch, abort):
    clock = [1000]
    monkeypatch.setattr(network.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(network, 'COMMAND_DEADLINE', 77)
    observed_timeouts = []
    def run(args, **kwargs):
        observed_timeouts.append(kwargs['timeout'])
        return result()
    def recover(*args, **kwargs):
        assert network.COMMAND_DEADLINE == 1000 + network.RECOVERY_BUDGET_SECONDS
        clock[0] = network.COMMAND_DEADLINE - 2
        network.command(['who'], timeout=5)
        if abort:
            clock[0] = network.COMMAND_DEADLINE
            network.command(['who'])
        return 'recovery deferred: ingest active'
    with patch.object(network, 'recover', recover), patch.object(network.subprocess, 'run', run):
        assert network.main() == (1 if abort else 0)
    assert observed_timeouts == [2]
    assert network.COMMAND_DEADLINE == 77


@pytest.fixture
def native_boot_identifier(tmp_path, monkeypatch):
    boot = tmp_path / 'boot-id'
    boot.write_text('11111111-1111-4111-8111-111111111111\n', encoding='ascii')
    monkeypatch.setattr(network, 'BOOT_ID_PATH', boot)
    return boot.read_text().strip()


def test_native_network_lease_uses_exclusive_create_and_exact_producer_schema(
        tmp_path, native_boot_identifier):
    path = tmp_path / 'daily-ingest.lock'
    with network.native_network_lease(path) as acquired:
        assert acquired is True
        assert path.read_text() == (f'pid={network.os.getpid()}\nrole=network-watchdog\n'
                                    f'boot_id={native_boot_identifier}\n')
        with network.native_network_lease(path) as contender:
            assert contender is False
        assert path.exists()
    assert not path.exists()


@pytest.mark.parametrize('existing', [
    'pid=999999999\nrole=old-producer\nboot_id=22222222-2222-4222-8222-222222222222\n',
    'pid=999999999\nrole=old-producer\nrecovery=manual\n',
    'corrupted or unknown predecessor',
])
def test_native_network_lease_preserves_every_existing_or_stale_record(
        tmp_path, native_boot_identifier, existing):
    path = tmp_path / 'daily-ingest.lock'
    path.write_text(existing)
    original = path.stat()
    with network.native_network_lease(path) as acquired:
        assert acquired is False
    current = path.stat()
    assert (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino)
    assert path.read_text() == existing


def test_native_network_lease_releases_owned_file_on_exception(tmp_path, native_boot_identifier):
    path = tmp_path / 'daily-ingest.lock'
    with pytest.raises(RuntimeError, match='command failed'):
        with network.native_network_lease(path) as acquired:
            assert acquired is True
            raise RuntimeError('command failed')
    assert not path.exists()


def test_native_network_lease_does_not_unlink_replacement_identity(
        tmp_path, native_boot_identifier, monkeypatch):
    path = tmp_path / 'daily-ingest.lock'
    successor = tmp_path / 'successor.lock'
    successor.write_text('another operation owns this lease')
    replacement_identity = successor.stat()
    original_lstat = type(path).lstat
    def observe(current):
        return replacement_identity if current == path else original_lstat(current)
    with network.native_network_lease(path) as acquired:
        assert acquired is True
        # Inject the replacement identity because Windows forbids removing an
        # open predecessor; this models the POSIX replacement cleanup boundary.
        path.write_text(successor.read_text())
        monkeypatch.setattr(type(path), 'lstat', observe)
    assert path.read_text() == 'another operation owns this lease'
    assert successor.read_text() == 'another operation owns this lease'


@pytest.mark.parametrize('boot_id', ['', 'not-a-uuid', '11111111111141118111111111111111'])
def test_native_network_lease_requires_canonical_boot_evidence(tmp_path, monkeypatch, boot_id):
    boot = tmp_path / 'boot-id'
    boot.write_text(boot_id)
    monkeypatch.setattr(network, 'BOOT_ID_PATH', boot)
    path = tmp_path / 'daily-ingest.lock'
    with pytest.raises(ValueError):
        with network.native_network_lease(path):
            pytest.fail('malformed ownership evidence admitted')
    assert not path.exists()


@pytest.mark.skipif(network.os.name != 'posix', reason='open inode replacement requires POSIX')
def test_native_network_lease_preserves_real_replacement_inode(tmp_path, native_boot_identifier):
    path = tmp_path / 'daily-ingest.lock'
    with network.native_network_lease(path) as acquired:
        assert acquired is True
        successor = tmp_path / 'successor.lock'
        successor.write_text('another operation owns this lease')
        successor.replace(path)
        replacement_identity = path.stat()
    current = path.stat()
    assert (current.st_dev, current.st_ino) == (replacement_identity.st_dev, replacement_identity.st_ino)
    assert path.read_text() == 'another operation owns this lease'


@pytest.mark.skipif(network.os.name != 'posix', reason='portable Windows symlink privileges differ')
def test_native_network_lease_preserves_dangling_symlink(tmp_path, native_boot_identifier):
    path = tmp_path / 'daily-ingest.lock'
    target = tmp_path / 'missing-target'
    path.symlink_to(target)
    with network.native_network_lease(path) as acquired:
        assert acquired is False
    assert path.is_symlink()
    assert not target.exists()


def test_occupied_queue_defers_before_native_lease_or_reconnect(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 2}))
    calls = []
    @contextmanager
    def occupied():
        raise RuntimeError('shared queue occupied or ownership unavailable')
        yield
    with patch.object(network, 'command', side_effect=eligible_commands(calls)), \
            patch.object(network, 'queue_guard', occupied), \
            patch.object(network, 'native_network_lease') as lease:
        with pytest.raises(RuntimeError, match='shared queue occupied'):
            network.recover(state, tmp_path)
    lease.assert_not_called()
    assert network_mutations(calls) == []
