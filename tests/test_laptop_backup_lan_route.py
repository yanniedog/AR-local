import json
import socket
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import laptop_backup_lan_route as route
import laptop_backup_user_session as user


def failed_lookup(_name):
    try:
        raise socket.gaierror(11001, 'name unavailable')
    except OSError as exc:
        raise ValueError('SSH LAN endpoint discovery failed') from exc


def test_lookup_failure_uses_only_explicit_lan_hint(monkeypatch):
    monkeypatch.setattr(route, 'discover_endpoint', failed_lookup)
    with pytest.raises(ValueError, match='eligible configured fallback'):
        route.resolve_route()
    assert route.resolve_route('192.168.20.19') == {
        'endpoint': '192.168.20.19', 'source': 'configured_lan_fallback'}


def test_successful_discovery_takes_precedence_over_old_hint(monkeypatch):
    monkeypatch.setattr(route, 'discover_endpoint', lambda name: '192.168.20.25')
    assert route.resolve_route('192.168.20.19')['endpoint'] == '192.168.20.25'


@pytest.mark.parametrize('hint', ['100.78.28.10', '203.0.113.1', '127.0.0.1', 'bad', '192.168.020.19'])
def test_invalid_hint_is_rejected_before_lookup(monkeypatch, hint):
    monkeypatch.setattr(route, 'discover_endpoint', lambda name: pytest.fail('no lookup allowed'))
    with pytest.raises(ValueError):
        route.resolve_route(hint)


@pytest.mark.parametrize('answers', [[], ['192.168.20.19', '192.168.20.20'], ['203.0.113.1'], ['bad']])
def test_invalid_or_ambiguous_answer_never_uses_hint(monkeypatch, answers):
    from laptop_backup_ssh_endpoint import select_endpoint
    monkeypatch.setattr(route, 'discover_endpoint', lambda name: select_endpoint(answers))
    with pytest.raises(ValueError):
        route.resolve_route('192.168.20.19')


def test_stuck_resolver_is_bounded(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(route, 'discover_endpoint', lambda name: release.wait(2))
    try:
        assert route.resolve_route('192.168.20.19', timeout=0.01)['source'] == 'configured_lan_fallback'
    finally:
        release.set()


def execution_setup(monkeypatch, tmp_path, response):
    import laptop_backup_scheduled as scheduled
    records, calls = [], []
    monkeypatch.setattr(user, 'verify_release', lambda config: None)
    monkeypatch.setattr(user, 'legacy_idle', lambda name: None)
    monkeypatch.setattr(user, 'allowed_start', lambda now: True)
    monkeypatch.setenv('AR_USER_BACKUP_CONFIG_SHA256', 'old')
    transport = {key: key for key in ['ssh_user', 'ssh_path', 'ssh_sha256', 'scp_path',
                                     'scp_sha256', 'ssh_identity_path', 'ssh_known_hosts_path']}
    transport['ssh_port'] = 22
    monkeypatch.setattr(user, 'transport_contract', lambda: transport)
    monkeypatch.setattr(user, 'record', lambda *args, **kw: records.append((args, kw)))
    monkeypatch.setattr(user.subprocess, 'run', lambda *args, **kw: response())
    monkeypatch.setattr(scheduled, 'main', lambda args: calls.append(args) or 0)
    config = {'receiver': str(tmp_path), 'target': str(tmp_path/'target'), 'legacy_task': 'old',
              'recovery_image': 'image', 'candidate_sha': 'a'*40, 'protected_sha': 'b'*40,
              'operator_sid': 'sid', 'lan_fallback_ipv4': '192.168.20.19'}
    return config, records, calls


def test_runner_passes_route_through_pinned_transport(monkeypatch, tmp_path):
    config, records, calls = execution_setup(monkeypatch, tmp_path, lambda: SimpleNamespace(
        stdout=json.dumps({'endpoint': '192.168.20.19', 'source': 'configured_lan_fallback'})))
    assert user.execute(config, 'run', 'c'*64) == 0
    args = calls[0]
    assert args[args.index('--host')+1] == config['lan_fallback_ipv4']
    assert args[args.index('--protected-code-sha')+1] == 'b'*40
    assert args[args.index('--ssh-known-hosts')+1] == 'ssh_known_hosts_path'
    assert records[0][1]['source'] == 'configured_lan_fallback'
    assert records[-1][0][1] == 'PASS'


def test_unconfigured_returned_route_blocks_before_backup(monkeypatch, tmp_path):
    config, records, calls = execution_setup(monkeypatch, tmp_path, lambda: SimpleNamespace(
        stdout=json.dumps({'endpoint': '192.168.20.25', 'source': 'configured_lan_fallback'})))
    with pytest.raises(ValueError, match='before Pi access'):
        user.execute(config, 'run', 'c'*64)
    assert not calls and records[-1][0][1] == 'BLOCKED'


def test_discovery_process_failure_is_preserved(monkeypatch, tmp_path):
    def failure():
        raise subprocess.CalledProcessError(1, ['resolver'])
    config, records, calls = execution_setup(monkeypatch, tmp_path, failure)
    with pytest.raises(ValueError, match='before Pi access'):
        user.execute(config, 'run', 'c'*64)
    assert not calls and records[-1][1]['stage'] == 'lan_discovery'


def test_fallback_is_bound_to_configuration_digest(monkeypatch, tmp_path):
    source = tmp_path/'source'
    source.mkdir()
    executable = tmp_path/'interpreter'
    executable.write_bytes(b'test executable')
    monkeypatch.setattr(user, '__file__', str(source/'laptop_backup_user_session.py'))
    monkeypatch.setattr(user, 'ordinary_identity', lambda: 'sid')
    monkeypatch.setattr(user.sys, 'executable', str(executable))
    config = dict.fromkeys(user.KEYS, '')
    config.update(schema=user.SCHEMA, operator_sid='sid', receiver=str(source),
                  target=str(tmp_path/'target'), legacy_target=str(tmp_path/'legacy'),
                  python_path=str(executable), git_path=str(executable),
                  python_sha256=user.digest(executable), git_sha256=user.digest(executable),
                  lan_fallback_ipv4='192.168.20.19')
    path = tmp_path/user.CONFIG_NAME
    path.write_text(json.dumps(config))
    digest = user.digest(path)
    assert user.load_config(path, digest)['lan_fallback_ipv4'] == '192.168.20.19'
    config['lan_fallback_ipv4'] = '192.168.20.25'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match='configuration changed'):
        user.load_config(path, digest)
