"""Boundary tests for a root-attested private-PID recovery worker."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import sys

import pytest
import pi_plain_backup_attestation as a


@pytest.fixture
def context(tmp_path):
    now = datetime.now(timezone.utc)
    nonce = 'a' * 32
    return dict(schema='ar-local-plain-backup-attestation-v1', nonce=nonce,
        unit='ar-local-plain-backup-' + nonce + '.service', boot_id='protocol-boot',
        queue=dict(job_id='b' * 32, owner_pid=100, owner_ticks=1000, invocation='c' * 32,
            cgroup='/system.slice/ar-local-plain-backup-' + nonce + '.service', device=7, inode=9),
        source=dict(device=7, inode=8), data_root=str(tmp_path / 'data'), operation=str(tmp_path / 'operation'),
        source_closure_sha256='d' * 64, remote='approved:plaintext-recovery', drive_root_folder_id='folder-id-test-only',
        issued_at=(now - timedelta(seconds=1)).isoformat(), expires_at=(now + timedelta(seconds=300)).isoformat(),
        issued_monotonic=time.monotonic() - 1, deadline_monotonic=time.monotonic() + 300,
        monitor=dict(pid=200, start_ticks=2000, user_namespace_inode=11, pid_namespace_inode=22, mount_namespace_inode=33),
        sandbox=dict(private_mount=True, private_pid=True, host_uid_mapping=True, readonly_source=True,
            no_new_privileges=True, capabilities_dropped=True), worker=dict(uid=1000, gid=1000))


def test_context_requires_complete_root_scope_and_finite_six_hour_lifetime(context):
    assert a.validate_context(context) == context
    for mutate in (lambda v: v['sandbox'].update(private_pid=False),
                   lambda v: v['worker'].update(uid=0),
                   lambda v: v.update(deadline_monotonic=float('inf')),
                   lambda v: v.update(deadline_monotonic=v['issued_monotonic'] + 21601),
                   lambda v: v.update(unit='another.service'),
                   lambda v: v['queue'].update(cgroup='/other'),
                   lambda v: v.update(unreviewed_extra='value')):
        value = deepcopy(context); mutate(value)
        with pytest.raises(ValueError): a.validate_context(value)


@pytest.fixture
def sealed(context, monkeypatch):
    raw = json.dumps(context).encode()
    state = dict(uid=0, mode=0o100440, links=0, flags=0, seals=15, raw=raw)
    fcntl = SimpleNamespace(F_SEAL_WRITE=8, F_SEAL_GROW=4, F_SEAL_SHRINK=2, F_SEAL_SEAL=1,
        F_GETFL=3, F_GET_SEALS=1034)
    fcntl.fcntl = lambda fd, operation: state['flags'] if operation == 3 else state['seals']
    monkeypatch.setitem(sys.modules, 'fcntl', fcntl)
    fake_os = SimpleNamespace(O_ACCMODE=3, O_RDONLY=0,
        fstat=lambda fd: SimpleNamespace(st_mode=state['mode'], st_uid=state['uid'], st_nlink=state['links'],
            st_size=len(state['raw']), st_dev=77, st_ino=88), pread=lambda *args: state['raw'])
    monkeypatch.setattr(a, 'os', fake_os)
    return state


def test_sealed_root_memfd_accepts_exact_readonly_capability(context, sealed):
    value, sha, identity = a.sealed_context(3)
    assert value == context and len(sha) == 64 and identity == (77, 88)


@pytest.mark.parametrize('field,value', [('uid', 1000), ('links', 1), ('mode', 0o100640),
    ('flags', 2), ('seals', 14), ('seals', 7)])
def test_worker_cannot_forge_root_capability_or_pass_writable_unsealed_fd(sealed, field, value):
    sealed[field] = value
    with pytest.raises(ValueError): a.sealed_context(3)


@pytest.fixture
def sandbox(context, monkeypatch):
    lease = a.AttestedHostLease(3, context, 'e' * 64, (77, 88))
    state = dict(uid=1000, gid=1000, nnp=1, caps=0, userns=11, pidns=44, mntns=55,
        readonly=True, native_inode=9, boot='protocol-boot', cgroup=context['queue']['cgroup'], role='shared-pi-host-task:' + 'b' * 32)
    monkeypatch.setattr(a, 'sealed_context', lambda fd: (deepcopy(context), 'e' * 64, (77, 88)))
    def read(path):
        if path.endswith('boot_id'): return state['boot']
        if path.endswith('status'):
            return 'NoNewPrivs:\t' + str(state['nnp']) + '\n' + ''.join(
                key + ':\t' + format(state['caps'], '016x') + '\n' for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))
        if path.endswith('cgroup'): return '0::' + state['cgroup'] + '\n'
        raise AssertionError('outside-host proc access: ' + path)
    def proc(path):
        return SimpleNamespace(read_text=lambda: read(path),
            stat=lambda: SimpleNamespace(st_ino=state[{'user': 'userns', 'pid': 'pidns', 'mnt': 'mntns'}[path.rsplit('/', 1)[-1]]]))
    monkeypatch.setattr(a, 'Path', proc)
    fake_os = SimpleNamespace(name='posix', ST_RDONLY=1,
        getuid=lambda: state['uid'], geteuid=lambda: state['uid'],
        getgid=lambda: state['gid'], getegid=lambda: state['gid'],
        statvfs=lambda data: SimpleNamespace(f_flag=1 if state['readonly'] else 0))
    monkeypatch.setattr(a, 'os', fake_os)
    monkeypatch.setattr(a, 'read_native', lambda *_: dict(pid='100', boot_id='protocol-boot', role=state['role'], recovery='manual'))
    class Source:
        def __str__(self): return context['data_root']
        def stat(self): return SimpleNamespace(st_dev=7, st_ino=8)
        def __truediv__(self, value):
            assert value == 'state/daily-ingest.lock'
            return SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=0o100600, st_uid=1000,
                st_nlink=1, st_size=100, st_dev=7, st_ino=state['native_inode']))
    return lease, state, Source()


def test_private_pid_worker_uses_root_attestation_without_host_proc_escape(sandbox):
    lease, _, data = sandbox
    lease.verify(data)


@pytest.mark.parametrize('field,value', [('uid', 1001), ('gid', 1001), ('nnp', 0), ('caps', 1),
    ('userns', 999), ('pidns', 22), ('mntns', 33), ('readonly', False), ('native_inode', 999),
    ('boot', 'old-boot'), ('cgroup', '/other'), ('role', 'ingest')])
def test_changed_identity_namespace_readonly_or_native_binding_refuses(sandbox, field, value):
    lease, state, data = sandbox; state[field] = value
    with pytest.raises(ValueError): lease.verify(data)


def test_attestation_argument_pins_destination_and_source(context, monkeypatch):
    monkeypatch.setattr(a, 'sealed_context', lambda fd: (deepcopy(context), 'e' * 64, (77, 88)))
    monkeypatch.setattr(a.AttestedHostLease, 'verify', lambda *args: None)
    args = dict(deadline=context['expires_at'], remote=context['remote'],
        drive_root_folder_id=context['drive_root_folder_id'], data_root=Path(context['data_root']),
        operation=Path(context['operation']))
    assert isinstance(a.inherited_from_attestation_fd(3, **args), a.AttestedHostLease)
    for key, value in (('remote', 'another:plaintext-recovery'), ('drive_root_folder_id', 'another-root-id'),
                       ('data_root', Path(context['operation'])), ('operation', Path(context['data_root']))):
        changed = dict(args); changed[key] = value
        with pytest.raises(ValueError): a.inherited_from_attestation_fd(3, **changed)


def test_primary_io_failure_is_preserved_if_lease_exit_also_fails(monkeypatch):
    lease = a.AttestedHostLease.__new__(a.AttestedHostLease)
    calls = 0
    def verify(data):
        nonlocal calls
        calls += 1
        if calls > 1: raise ValueError('secondary ownership loss')
    monkeypatch.setattr(lease, 'verify', verify)
    with pytest.raises(RuntimeError, match='primary IO failure'):
        with lease.hold(None): raise RuntimeError('primary IO failure')


@pytest.mark.parametrize('raw', [b'pid=1\npid=1\nrole=host\nrecovery=manual\n',
    b'pid=1\nrole=host\n', b'x' * 4097, b'pid=1\nboot_id=b\nrole=host\ninvalid\n'])
def test_native_duplicate_truncated_or_oversize_records_refused(raw):
    with pytest.raises(ValueError): a.parse_native(raw)
