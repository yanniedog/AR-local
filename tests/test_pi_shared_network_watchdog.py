import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pi_shared_network_watchdog as network
import ar_local_operation_lock
import pytest


def result(stdout='', code=0):
    return SimpleNamespace(stdout=stdout, returncode=code)


def test_healthy_gateway_never_restarts_network_for_internet_outage(tmp_path):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[0] == 'ip':
            return result('[{"gateway":"192.168.1.1","dev":"wlan0"}]')
        return result()
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
                'ss': result('ESTAB remote SSH'), 'who': result()}[args[0]]
    with patch.object(network, 'command', run):
        assert 'remote session active' in network.recover(state, tmp_path)
    assert not any('connect' in row for row in calls)


def test_missing_session_evidence_prevents_recovery():
    with patch.object(network, 'command', side_effect=[result(code=1), result()]):
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
                'who': result(), 'systemctl': result(units, code=3)}[args[0]]
    with patch.object(network, 'command', run), patch.object(
            ar_local_operation_lock, 'production_lock', return_value=nullcontext()):
        network.recover(state, tmp_path)
    mutations = [row for row in calls if 'connect' in row]
    assert mutations == ([['nmcli', '--wait', '20', 'device', 'connect', 'wlan0']] if expected else [])
    if expected:
        assert json.loads(state.read_text())['failures'] == 0


@pytest.mark.parametrize('login,remote', [('pi :0 (:0)', False), ('pi pts/0 (192.168.1.2)', True)])
def test_local_display_does_not_block_recovery(login, remote):
    with patch.object(network, 'command', side_effect=[result(), result(login)]):
        assert network.remote_sessions_active() is remote


@pytest.mark.parametrize('old_state', ['broken JSON', '[]', '{"failures": "bad"}'])
def test_corrupt_state_restarts_threshold_without_recovery(tmp_path, old_state):
    state = tmp_path / 'state.json'
    state.write_text(old_state)
    with patch.object(network, 'command', side_effect=[
            result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'), result(code=1)]):
        assert 'below' in network.recover(state, tmp_path)


def test_eligible_dry_run_preserves_state_and_never_acquires_lease(tmp_path):
    state = tmp_path / 'state.json'
    original = json.dumps({'gateway': '192.168.1.1', 'interface': 'wlan0', 'failures': 2})
    state.write_text(original)
    def run(args, **kwargs):
        assert 'connect' not in args
        return {'ip': result('[{"gateway":"192.168.1.1","dev":"wlan0"}]'),
                'ping': result(code=1), 'nmcli': result('wifi'), 'ss': result(),
                'who': result(), 'systemctl': result('inactive\nfailed\ninactive\n', code=3)}[args[0]]
    with patch.object(network, 'command', run), patch.object(ar_local_operation_lock, 'production_lock') as lease:
        assert 'eligible' in network.recover(state, tmp_path, dry_run=True)
        lease.assert_not_called()
    assert state.read_text() == original
    assert not (tmp_path / 'state.tmp').exists()
