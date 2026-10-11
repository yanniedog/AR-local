import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pi_shared_network_watchdog as network
import ar_local_operation_lock
import subprocess
from datetime import datetime, timezone
import pytest


def result(stdout='', code=0):
    return SimpleNamespace(stdout=stdout, returncode=code)


def test_healthy_gateway_never_restarts_network_for_internet_outage(tmp_path):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[0] == 'ip':
            return result('[{"gateway":"192.168.1.1","dev":"wlan0"}]')
        if args[0] == 'ping':
            return result(code=0 if args[-1] == '192.168.1.1' else 1)
        raise AssertionError(args)
    with patch.object(network, 'command', run):
        assert 'healthy' in network.recover(tmp_path / 'state.json', tmp_path)
    assert [row[0] for row in calls] == ['ip', 'ping']


def test_remote_deployment_prevents_recovery_after_repeated_gateway_failures(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 2}))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return {'ip': result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'),
                'ping': result(code=1), 'nmcli': result('wifi'),
                'ss': result('ESTAB remote SSH'), 'who': result(), 'ps': result('tailscaled /usr/sbin/tailscaled')}[args[0]]
    with patch.object(network, 'command', run):
        assert 'remote session active' in network.recover(state, tmp_path)
    assert [row for row in calls if row[0] in {'nmcli', 'systemctl'}] == [['nmcli', '-g', 'GENERAL.TYPE', 'device', 'show', 'wlan0']]


def test_missing_session_evidence_prevents_recovery():
    with patch.object(network, 'command', side_effect=[result(code=1), result(), result('tailscaled /usr/sbin/tailscaled')]):
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
        if 'connect' in args:
            return result()
        return {'ip': result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'),
                'ping': result(code=1), 'nmcli': result('wifi'), 'ss': result(),
                'who': result(), 'ps': result('tailscaled /usr/sbin/tailscaled'), 'systemctl': result(units, code=3)}[args[0]]
    with patch.object(network, 'command', run), patch.object(
            network, 'production_lock_factory', return_value=lambda *args: nullcontext()):
        network.recover(state, tmp_path)
    mutations = [row for row in calls if row[0] in {'nmcli', 'systemctl'} and row not in [
        ['nmcli', '-g', 'GENERAL.TYPE', 'device', 'show', 'wlan0'],
        ['systemctl', 'is-active', 'ar-local-daily.service', 'ar-local-ingest-now.service', 'ar-local-daily-watchdog.service']]]
    assert mutations == ([['nmcli', '--wait', '20', 'device', 'connect', 'wlan0']] if expected else [])
    if expected:
        assert json.loads(state.read_text())['failures'] == 0


@pytest.mark.parametrize('login,remote', [('pi :0 (:0)', False), ('pi pts/0 (192.168.1.2)', True)])
def test_local_display_does_not_block_recovery(login, remote):
    with patch.object(network, 'command', side_effect=[result(), result(login), result('tailscaled /usr/sbin/tailscaled')]):
        assert network.remote_sessions_active() is remote


@pytest.mark.parametrize('old_state', ['broken JSON', '[]', '{"failures": "bad"}'])
def test_corrupt_state_restarts_threshold_without_recovery(tmp_path, old_state):
    state = tmp_path / 'state.json'
    state.write_text(old_state)
    with patch.object(network, 'command', side_effect=[
            result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'), result(code=1)]):
        assert 'below' in network.recover(state, tmp_path)
    assert json.loads(state.read_text()) == {'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 1}


def test_eligible_dry_run_preserves_state_and_never_acquires_lease(tmp_path):
    state = tmp_path / 'state.json'
    original = json.dumps({'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 2})
    state.write_text(original)
    def run(args, **kwargs):
        assert 'connect' not in args
        return {'ip': result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'),
                'ping': result(code=1), 'nmcli': result('wifi'), 'ss': result(),
                'who': result(), 'ps': result('tailscaled /usr/sbin/tailscaled'), 'systemctl': result('inactive\nfailed\ninactive\n', code=3)}[args[0]]
    with patch.object(network, 'command', run), patch.object(ar_local_operation_lock, 'production_lock') as lease:
        assert 'eligible' in network.recover(state, tmp_path, dry_run=True)
        lease.assert_not_called()
    assert state.read_text() == original
    assert not (tmp_path / 'state.tmp').exists()


@pytest.mark.parametrize('processes', [
    'tailscaled /usr/sbin/tailscaled be-child ssh --uid=1000',
    'sshd sshd: operator@notty',
    'sshd-session sshd-session: operator',
])
def test_non_pty_and_nonstandard_port_sessions_are_detected(processes):
    with patch.object(network, 'command', side_effect=[result(), result(), result(processes)]):
        assert network.remote_sessions_active()


def test_unavailable_process_inventory_blocks_recovery():
    with patch.object(network, 'command', side_effect=[result(), result(), result(code=1)]):
        assert network.remote_sessions_active()


@pytest.mark.parametrize('time,blocked', [
    ('2026-10-11T13:27:29+00:00', False),
    ('2026-10-11T13:27:30+00:00', True),
    ('2026-10-11T14:00:00+00:00', True),
    ('2026-10-11T15:00:00+00:00', False),
])
def test_complete_service_budget_respects_ingest_quiet_window(time, blocked):
    assert network.quiet_window(datetime.fromisoformat(time)) is blocked


def test_quiet_window_refuses_even_eligible_wifi_before_acquiring_a_lease(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 2}))
    with patch.object(network, 'command', side_effect=[
            result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'), result(code=1)]) as commands, \
            patch.object(network, 'quiet_window', return_value=True), \
            patch.object(network, 'production_lock_factory') as factory:
        assert 'protected ingest window' in network.recover(state, tmp_path)
    factory.assert_not_called()
    assert len(commands.mock_calls) == 2


@pytest.mark.parametrize('failure', [OSError('missing'), ValueError('malformed'), subprocess.TimeoutExpired('ip', 5)])
def test_aborted_watchdog_reports_failure(failure):
    with patch.object(network, 'recover', side_effect=failure):
        assert network.main() == 1


def test_root_lock_loader_rejects_a_user_writable_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(network, 'TRUSTED_ROOT', tmp_path)
    for name in network.LOCK_MODULES:
        (tmp_path / (name + '.py')).write_text('raise AssertionError("untrusted code executed")')
    with pytest.raises(RuntimeError, match='not protected'):
        network.production_lock_factory()


def test_gateway_cannot_supply_command_options():
    with patch.object(network, 'command', return_value=result('[{"gateway":"-f","dev":"wlan0"}]')) as commands:
        with pytest.raises(ValueError):
            network.default_route()
    assert len(commands.mock_calls) == 1
