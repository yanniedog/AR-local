"""Commissioning effects stay in temporary files; Root trust is simulated."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_ci_install as installer


def test_every_source_byte_is_pinned_before_any_staged_module_executes(tmp_path, monkeypatch):
    files = {}
    for name in sorted(installer.MODULES):
        # If code executes before the final worker hash check, this distinct
        # sentinel raises and the expected independent-digest error is absent.
        body = b"raise RuntimeError('STAGED_IMPORT_BEFORE_TRUST')\n"
        files[tmp_path / name] = body
    approval = {'schema': 'ar-local-ci-commission-v1', 'source_commit': 'a' * 40,
        'files': {path.name: hashlib.sha256(body).hexdigest() for path, body in files.items()},
        'runtime_sha256': 'b' * 64}
    approval_path = tmp_path / 'approval.json'; files[approval_path] = json.dumps(approval).encode()
    files[tmp_path / 'pi_ci_worker.py'] += b'unapproved modification'
    monkeypatch.setattr(installer, 'protected_bytes', lambda path: files[Path(path)])
    with pytest.raises(ValueError, match='independently reviewed staging hash differs'):
        installer.validate(tmp_path, approval_path, hashlib.sha256(files[approval_path]).hexdigest(),
                           tmp_path / 'recovery.json', 'c' * 64)


@pytest.fixture
def install_tree(tmp_path, monkeypatch):
    lib = tmp_path / 'lib'; lib.mkdir()
    state = tmp_path / 'state'; state.mkdir()
    config = tmp_path / 'etc'; config.mkdir()
    binpath = tmp_path / 'bin'; binpath.mkdir()
    login, control = binpath / 'login', binpath / 'control'
    for path in (login, control): path.write_bytes(b'original restricted foundation helper')
    for name, value in (('LIB', lib), ('STATE', state), ('RUNTIME', config / 'runtime.json'),
                        ('LOGIN', login), ('CONTROL', control)):
        monkeypatch.setattr(installer, name, value)
    if not hasattr(os, 'O_NOFOLLOW'): monkeypatch.setattr(os, 'O_NOFOLLOW', 0, raising=False)
    monkeypatch.setattr(installer, 'protected_bytes', lambda path: path.read_bytes())
    effects = SimpleNamespace(protected=lambda path, **kwargs: path, sync_directory=lambda path: None)
    bodies = {name: ('approved ' + name).encode() for name in installer.MODULES}
    return lib, state, login, control, bodies, effects


def test_commission_retains_old_helpers_and_publishes_profile_after_fixed_closure(install_tree):
    lib, state, login, control, bodies, effects = install_tree
    installer.install(bodies, b'approved runtime profile', effects)
    assert (state / 'pre-immutable-control.py').read_bytes() == b'original restricted foundation helper'
    assert login.read_bytes() == control.read_bytes() == bodies['pi_ci_access.py']
    assert all((lib / name).read_bytes() == body for name, body in bodies.items() if name != 'pi_ci_access.py')
    assert installer.RUNTIME.read_bytes() == b'approved runtime profile'
    assert (state / 'authority').is_dir() and (state / 'completed').is_dir()
    with pytest.raises(ValueError): installer.install(bodies, b'approved runtime profile', effects)


def test_conflicting_state_is_detected_before_any_helper_or_module_write(install_tree):
    lib, state, login, control, bodies, effects = install_tree
    (state / 'transactions').mkdir()
    with pytest.raises(ValueError, match='state already exists'):
        installer.install(bodies, b'approved profile', effects)
    assert not list(lib.iterdir()) and not (state / 'pre-immutable-control.py').exists()
    assert login.read_bytes() == control.read_bytes() == b'original restricted foundation helper'
