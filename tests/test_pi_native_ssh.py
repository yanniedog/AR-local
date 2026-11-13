from datetime import datetime, timezone
import base64
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pi_native_ssh as native


def approval():
    key = 'ssh-ed25519 ' + base64.b64encode(b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes(range(32))).decode()
    return dict(schema=native.SCHEMA, source_commit='a' * 40, installer_sha256='b' * 64,
                address='100.99.88.77', port=2222, user='operator', authorized_key=key, host_public_key=key)


@pytest.mark.parametrize('field,value', [
    ('address', '0.0.0.0'), ('address', '127.0.0.1'), ('address', '192.168.1.2'),
    ('address', '::1'), ('address', '100.64.0.1\nListenAddress 0.0.0.0'),
    ('port', 22), ('port', True), ('port', 65536), ('port', '2222'),
    ('user', 'root'), ('user', 'pi\nAllowUsers *'), ('user', '*'),
    ('source_commit', 'main'), ('installer_sha256', 'pending'),
    ('authorized_key', 'command="x" ssh-ed25519 AAAA'), ('host_public_key', 'ssh-ed25519 AAAA')])
def test_approval_rejects_ambiguous_or_public_surface(field, value):
    value_dict = approval(); value_dict[field] = value
    with pytest.raises(ValueError):
        native.render(value_dict)


def test_configuration_is_standalone_private_and_public_key_only():
    value = approval(); bodies = native.render(value)
    config = bodies['sshd_config'].decode()
    assert f"ListenAddress {value['address']}\n" in config
    assert 'AddressFamily inet\n' in config
    assert 'Include ' not in '\n'.join(line for line in config.splitlines() if not line.startswith('#'))
    for item in ('AuthenticationMethods publickey', 'PermitRootLogin no', 'PasswordAuthentication no',
                 'KbdInteractiveAuthentication no', 'DisableForwarding yes', 'StrictModes yes', 'Subsystem sftp internal-sftp'):
        assert item + '\n' in config
    unit = bodies['unit'].decode()
    assert 'StartLimitIntervalSec=0\n' in unit and 'RestartSec=30s\n' in unit
    assert 'ExecStart=/usr/sbin/sshd -D -e -f /etc/ar-local-native-ssh/sshd_config' in unit
    assert 'NoNewPrivileges' not in unit and 'ProtectHome' not in unit
    assert 'MemoryMax=512M' in unit and 'TasksMax=128' in unit


@pytest.mark.parametrize('stamp,allowed', [
    ('2026-11-14T00:00:00+11:00', True), ('2026-11-14T00:27:59+11:00', True),
    ('2026-11-14T00:28:01+11:00', False), ('2026-11-14T00:30:00+11:00', False),
    ('2026-11-14T03:29:59+11:00', False), ('2026-11-14T03:30:00+11:00', True),
    ('2026-11-14T23:59:59+11:00', True), ('2026-06-14T00:30:00+10:00', False)])
def test_admission_preserves_quiet_and_cleanup_budget(stamp, allowed):
    value = datetime.fromisoformat(stamp)
    if allowed:
        native.window(value)
    else:
        with pytest.raises(ValueError): native.window(value)


def claim():
    group = '/system.slice/ar-local-queue-task-' + 'a' * 32 + '.service'
    job = dict(id='job', project='ar-local', state='running', resources=['ar-local', 'host'],
               mode='exclusive', cgroup=group, unit=group.split('/')[-1], boot_id='boot', pid=123,
               invocation_id='b' * 32)
    props = dict(ControlGroup=group, ActiveState='active', MainPID='123', InvocationID='b' * 32)
    lease = dict(pid='123', boot_id='boot', role='shared-pi-host-task:job', recovery='manual')
    return {'jobs': [job]}, group, 'boot', props, lease


def test_current_exclusive_host_native_claim_accepted():
    assert native.queue_claim(*claim())['id'] == 'job'


@pytest.mark.parametrize('field,value', [('resources', ['ar-local']), ('resources', 'host ar-local'),
    ('resources', ['ar-local', {}]), ('state', 'waiting'), ('mode', 'shared'), ('boot_id', 'old'),
    ('invocation_id', 'old'), ('pid', 124), ('unit', 'another.service')])
def test_queue_identity_and_scope_must_match(field, value):
    args = list(claim()); args[0]['jobs'][0][field] = value
    with pytest.raises(ValueError): native.queue_claim(*args)


def test_claim_requires_native_lease_and_no_duplicates():
    args = list(claim()); args[4]['role'] = 'other'
    with pytest.raises(ValueError): native.queue_claim(*args)
    args = list(claim()); args[0]['jobs'] *= 2
    with pytest.raises(ValueError): native.queue_claim(*args)


def proof():
    return dict(schema='ar-local-native-ssh-wire-v1', approval_sha256='a' * 64,
                verified_at='2026-11-14T03:45:00+11:00', native_banner='SSH-2.0-OpenSSH_10.0',
                publickey_authenticated=True, host_pin_matched=True, sftp_roundtrip_verified=True, wrong_key_rejected=True,
                password_rejected=True, root_rejected=True, exclusive_tailnet_binding=True)


def test_enable_proof_is_generation_bound_fresh_and_native():
    value = proof(); now = datetime.fromisoformat('2026-11-14T03:46:00+11:00')
    native.validate_proof(value, 'a' * 64, now)
    for key, replacement in [('native_banner', 'SSH-2.0-Tailscale'), ('publickey_authenticated', False),
                             ('approval_sha256', 'b' * 64), ('wrong_key_rejected', 'true'),
                             ('verified_at', '2026-11-14T03:00:00+11:00'),
                             ('verified_at', '2026-11-14T04:00:00+11:00')]:
        changed = dict(value); changed[key] = replacement
        with pytest.raises(ValueError): native.validate_proof(changed, 'a' * 64, now)


def test_service_dropins_cannot_silently_override_approved_definition(monkeypatch):
    monkeypatch.setattr(native, 'run', lambda args: SimpleNamespace(stdout=f'FragmentPath={native.UNIT}\nDropInPaths=\n'))
    native.service_definition()
    monkeypatch.setattr(native, 'run', lambda args: SimpleNamespace(stdout=f'FragmentPath={native.UNIT}\nDropInPaths=/etc/unreviewed.conf\n'))
    with pytest.raises(ValueError): native.service_definition()


def test_failed_admission_prevents_every_mutation(monkeypatch):
    def blocked(_): raise ValueError('quiet')
    monkeypatch.setattr(native, 'admit', blocked)
    monkeypatch.setattr(native, 'run', lambda *a, **kw: pytest.fail('must not invoke systemctl'))
    for action in ('install', 'start', 'enable', 'rollback'):
        with pytest.raises(ValueError): native.mutate(action, approval(), native.render(approval()), b'{}', 1000)


def test_create_only_refuses_any_existing_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(native, 'ROOT', tmp_path)
    monkeypatch.setattr(native, 'admit', lambda _: None)
    monkeypatch.setattr(native, 'run', lambda *a, **kw: pytest.fail('must not invoke systemctl'))
    with pytest.raises(ValueError): native.mutate('install', approval(), native.render(approval()), b'{}', 1000)


def test_modified_owned_files_block_start_enable_and_rollback(monkeypatch):
    monkeypatch.setattr(native, 'admit', lambda _: None)
    monkeypatch.setattr(native, 'protected', lambda *a, **kw: b'tampered')
    monkeypatch.setattr(native, 'run', lambda *a, **kw: pytest.fail('must not invoke systemctl'))
    for action in ('start', 'enable', 'rollback'):
        with pytest.raises(ValueError): native.mutate(action, approval(), native.render(approval()), b'{}', 1000)


def test_duplicate_approval_fields_rejected():
    with pytest.raises(ValueError): json.loads('{"port":2222,"port":22}', object_pairs_hook=native.unique)


def test_rollback_remains_available_with_broken_network_keys_or_sshd(tmp_path, monkeypatch):
    root = tmp_path / 'owned'; root.mkdir()
    unit = tmp_path / 'owned.service'; unit.write_bytes(b'unit')
    monkeypatch.setattr(native, 'ROOT', root); monkeypatch.setattr(native, 'UNIT', unit)
    monkeypatch.setattr(native, 'admit', lambda _: None)
    monkeypatch.setattr(native, 'installed', lambda *_: {unit: b'unit'})
    monkeypatch.setattr(native, 'effective_validate', lambda *_: pytest.fail('broken sshd must not block rollback'))
    monkeypatch.setattr(native, 'create', lambda path, body: path.write_bytes(body))
    calls = []
    def fake_run(args):
        calls.append(args)
        return SimpleNamespace(stdout='ActiveState=failed\nMainPID=0\nControlGroup=\n' if 'show' in args else '')
    monkeypatch.setattr(native, 'run', fake_run)
    assert native.mutate('rollback', approval(), {}, b'{}', 1000) == 'ROLLED_BACK_EVIDENCE_RETAINED'
    assert not unit.exists() and (root / 'retired-unit.service').read_bytes() == b'unit'
    assert all('start' not in command and 'enable' not in command for command in calls)


def test_rollback_main_skips_network_and_key_readiness(monkeypatch):
    import sys
    body = json.dumps(approval()).encode()
    monkeypatch.setattr(native.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setattr(native, 'checked', lambda *_: body)
    monkeypatch.setattr(native, 'host_validate', lambda *_: pytest.fail('readiness blocks recovery'))
    monkeypatch.setitem(sys.modules, 'pwd', SimpleNamespace(getpwnam=lambda _: SimpleNamespace(pw_uid=1000)))
    monkeypatch.setattr(native, 'mutate', lambda action, *_: 'ROLLED_BACK' if action == 'rollback' else pytest.fail())
    assert native.main(['--approval', 'approval.json', '--approval-sha256', 'a' * 64, '--action', 'rollback']) == 0


def test_failed_effective_validation_never_publishes_unit(tmp_path, monkeypatch):
    root = tmp_path / 'new'; unit = tmp_path / 'new.service'
    monkeypatch.setattr(native, 'ROOT', root); monkeypatch.setattr(native, 'UNIT', unit)
    monkeypatch.setattr(native, 'admit', lambda _: None)
    monkeypatch.setattr(native, 'protected_directory', lambda _: None)
    monkeypatch.setattr(native, 'create', lambda path, body: path.write_bytes(body))
    calls = []
    def fake_run(args):
        calls.append(args); return SimpleNamespace(stdout='LoadState=not-found\n')
    def bad_effective(*_): raise ValueError('sshd effective auth differs')
    monkeypatch.setattr(native, 'run', fake_run)
    monkeypatch.setattr(native, 'effective_validate', bad_effective)
    with pytest.raises(ValueError): native.mutate('install', approval(), native.render(approval()), b'{}', 1000)
    assert not unit.exists() and (root / 'approval.json').read_bytes() == b'{}'
    assert len(calls) == 1 and 'show' in calls[0]


def test_enable_requires_real_kernel_resource_enforcement(monkeypatch):
    text = ('MemoryMax=536870912\nMemorySwapMax=0\nCPUQuotaPerSecUSec=1s\nTasksMax=128\n'
            'ControlGroup=/system.slice/ar-local-native-ssh.service\n')
    monkeypatch.setattr(native, 'run', lambda _: SimpleNamespace(stdout=text))
    values = {'memory.max': '536870912', 'memory.swap.max': '0', 'pids.max': '128', 'cpu.max': '100000 100000'}
    monkeypatch.setattr(Path, 'read_text', lambda self, **_: values[self.name])
    native.live_limits()
    for name, value in [('memory.max', 'max'), ('memory.swap.max', 'max'), ('pids.max', 'max'), ('cpu.max', 'max 100000')]:
        previous = values[name]; values[name] = value
        with pytest.raises(ValueError): native.live_limits()
        values[name] = previous


def test_each_service_mutation_rechecks_window_after_preparation(monkeypatch):
    def closed(_): raise ValueError('window closed during preparation')
    monkeypatch.setattr(native, 'window', closed)
    monkeypatch.setattr(native.subprocess, 'run', lambda *a, **kw: pytest.fail('must not mutate late'))
    for action in ('daemon-reload', 'start', 'enable', 'disable'):
        with pytest.raises(ValueError): native.run(['/usr/bin/systemctl', action, native.SERVICE])


@pytest.mark.parametrize('state', ['running', 'quarantined', 'unknown', None])
def test_exclusive_host_rejects_other_active_or_ambiguous_claims(state):
    args = list(claim()); other = {'id': 'other', 'cgroup': '/other', 'state': state}
    args[0]['jobs'].append(other)
    with pytest.raises(ValueError, match='another active or ambiguous'): native.queue_claim(*args)


def test_exclusive_host_allows_waiting_jobs():
    args = list(claim()); args[0]['jobs'].append({'id': 'other', 'cgroup': '/other', 'state': 'waiting'})
    assert native.queue_claim(*args)['id'] == 'job'


@pytest.mark.parametrize('recovery', [None, 'automatic', ''])
def test_native_lease_requires_exact_manual_recovery_marker(recovery):
    args = list(claim())
    if recovery is None: args[4].pop('recovery')
    else: args[4]['recovery'] = recovery
    with pytest.raises(ValueError): native.queue_claim(*args)


def test_native_lease_rejects_unexpected_fields():
    args = list(claim()); args[4]['unknown'] = 'value'
    with pytest.raises(ValueError): native.queue_claim(*args)
