"""Bounded byte/protocol validation, never a real installed-host attestation."""
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

import pi_drive_backup_hold_activate as activation
from tests.drive_guard_inventory_fixture import installed_fixture


@pytest.fixture
def installed(tmp_path, monkeypatch):
    return installed_fixture(tmp_path, monkeypatch)


def verify(installed):
    return activation.verify_guard_inventory([installed.spool])


def test_complete_exact_byte_inventory_is_bound_to_receipt(installed):
    result = verify(installed)
    assert result['proof_sha256'] == hashlib.sha256(installed.path.read_bytes()).hexdigest()
    assert result['verified_files'] == 7
    assert result['verified_bytes'] == sum(record['bytes'] for record in
        installed.proof['bundle']['files'] + installed.proof['artifacts'])
    assert result['authority'] == 'OPERATOR_REVIEWED_AUTHORIZED_DISPATCH_CLOSURE'
    assert not (installed.marker.parent / activation.GLOBAL_LOCK_NAME).exists()


@pytest.mark.parametrize('fault', ['unknown', 'bool_version', 'missing_attestation', 'unguarded',
    'wrong_spool', 'missing_module', 'duplicate_file', 'duplicate_artifact', 'wrong_helper',
    'unknown_role', 'missing_control', 'unbound_artifact', 'unsafe_isolation', 'bad_digest',
    'bool_size', 'escape_path', 'wrong_protocol'])
def test_malformed_or_incomplete_inventory_refuses_before_activation(installed, monkeypatch, fault):
    proof = installed.proof
    if fault == 'unknown': proof['unknown'] = 'must refuse'
    elif fault == 'bool_version': proof['schema_version'] = True
    elif fault == 'missing_attestation': proof['attestation'].pop('unguarded_dispatch_paths_disabled')
    elif fault == 'unguarded': proof['attestation']['unguarded_dispatch_paths_disabled'] = False
    elif fault == 'wrong_spool': proof['spools'] = [str(installed.spool.parent)]
    elif fault == 'missing_module': proof['bundle']['files'].pop()
    elif fault == 'duplicate_file': proof['bundle']['files'].append(proof['bundle']['files'][0])
    elif fault == 'duplicate_artifact': proof['artifacts'].append(proof['artifacts'][0])
    elif fault == 'wrong_helper': proof['artifacts'][0]['path'] = str(installed.bundle / 'pi_drive_backup.py')
    elif fault == 'unknown_role': proof['artifacts'][0]['role'] = 'unreviewed'
    elif fault == 'missing_control': proof['dispatchers'][0]['controls'] = []
    elif fault == 'unbound_artifact': proof['dispatchers'][0]['launcher'] = str(installed.helper)
    elif fault == 'unsafe_isolation': proof['dispatchers'][0]['isolation'] = 'ordinary-checkout'
    elif fault == 'bad_digest': proof['bundle']['files'][0]['sha256'] = '3' * 64
    elif fault == 'bool_size': proof['bundle']['files'][0]['bytes'] = True
    elif fault == 'escape_path': proof['bundle']['files'][0]['path'] = '../activate.py'
    elif fault == 'wrong_protocol': proof['protocol'] = 'legacy-symlink-only'
    installed.write()
    monkeypatch.setattr(activation, 'require_trusted_runtime', lambda: None)
    with pytest.raises((ValueError, OSError)):
        activation.activate_hold([installed.spool], 'private protocol request')
    assert not installed.marker.exists()
    assert not (installed.marker.parent / activation.GLOBAL_LOCK_NAME).exists()
    assert not list(installed.spool.iterdir())


def test_duplicate_json_key_refused(installed):
    body = installed.path.read_text()
    installed.path.write_text('{"schema_version":1,' + body[1:])
    with pytest.raises(ValueError, match='duplicate'):
        verify(installed)


@pytest.mark.parametrize('fault', ['foreign_owner', 'foreign_group', 'writable_file', 'special_mode',
                                  'writable_ancestor', 'hardlink', 'wrong_proof_mode'])
def test_protected_metadata_is_verified_not_just_claimed(installed, fault):
    target = installed.helper
    if fault == 'foreign_owner': change = {'st_uid': 1000}
    elif fault == 'foreign_group': change = {'st_gid': 1000}
    elif fault == 'writable_file': change = {'st_mode': stat.S_IFREG | 0o577}
    elif fault == 'special_mode': change = {'st_mode': stat.S_IFREG | 0o4555}
    elif fault == 'hardlink': change = {'st_nlink': 2}
    elif fault == 'writable_ancestor':
        target, change = installed.helper.parent, {'st_mode': stat.S_IFDIR | 0o777}
    else: target, change = installed.path, {'st_mode': stat.S_IFREG | 0o644}
    installed.faults[target] = change
    with pytest.raises(ValueError):
        verify(installed)


def test_unlisted_bundle_file_refused(installed):
    (installed.bundle / 'sitecustomize.py').write_text('unreviewed startup bytes')
    with pytest.raises(ValueError, match='unlisted'):
        verify(installed)


def test_bundle_symlink_refused(installed):
    os.symlink(installed.helper, installed.bundle / 'unknown.py')
    with pytest.raises(ValueError, match='symbolic links'):
        verify(installed)


def test_changed_installed_bytes_refused(installed):
    target = installed.bundle / installed.proof['bundle']['files'][0]['path']
    body = target.read_bytes()
    target.write_bytes(b'X' + body[1:])
    with pytest.raises(ValueError, match='differs'):
        verify(installed)


def test_proof_bound_checked_before_read(installed, monkeypatch):
    installed.path.write_bytes(b' ' * (activation.MAX_PROOF_BYTES + 1))
    monkeypatch.setattr(Path, 'open', lambda *_a, **_k: pytest.fail('oversized proof was read'))
    with pytest.raises(ValueError, match='byte bound'):
        verify(installed)


@pytest.mark.parametrize('budget', ['files', 'bytes', 'one_file'])
def test_explicit_verification_budgets_refuse(installed, monkeypatch, budget):
    if budget == 'files': monkeypatch.setattr(activation, 'MAX_INSTALLED_FILES', 4)
    elif budget == 'bytes': monkeypatch.setattr(activation, 'MAX_INSTALLED_BYTES', 1)
    else: monkeypatch.setattr(activation, 'MAX_INSTALLED_FILE_BYTES', 1)
    with pytest.raises(ValueError):
        verify(installed)


def test_slow_chunk_crossing_deadline_refuses_immediately_after_read(installed, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(activation.time, 'monotonic', lambda: clock[0])
    original = Path.open
    class SlowRead:
        def __init__(self, handle): self.handle = handle
        def __enter__(self): return self
        def __exit__(self, *args): self.handle.close()
        def fileno(self): return self.handle.fileno()
        def read(self, count):
            data = self.handle.read(count)
            clock[0] += 31
            return data
    monkeypatch.setattr(Path, 'open', lambda path, *a, **k: SlowRead(original(path, *a, **k)))
    with pytest.raises(ValueError, match='deadline'):
        verify(installed)
    assert not (installed.marker.parent / activation.GLOBAL_LOCK_NAME).exists()


def test_mutation_during_hashing_refuses(installed, monkeypatch):
    original = activation.protected_metadata
    reads = []
    def changed(path, **kwargs):
        info = original(path, **kwargs)
        if path == installed.path:
            reads.append(path)
            if len(reads) == 2:
                info.st_size += 1
        return info
    monkeypatch.setattr(activation, 'protected_metadata', changed)
    with pytest.raises(ValueError, match='changed during'):
        verify(installed)
