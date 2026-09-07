import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import laptop_backup_user_update as update
from tests.test_laptop_backup_runtime_ancestry import _chain, _pin


@pytest.mark.parametrize('fault', [None, 'digest', 'mixed_pair', 'missing', 'runtime', 'transport'])
def test_transition_probe_is_read_only_and_authenticates_full_predecessor(tmp_path, monkeypatch, fault):
    target = tmp_path / 'target'
    chain = _chain(target)
    pointer = target / 'catalog/latest-scheduled.json'
    pointer.write_text(json.dumps(dict(chain[-1], result='PASS')))
    old_root, new_root = tmp_path / 'old', tmp_path / 'new'
    old_root.mkdir()
    new_root.mkdir()
    old = dict.fromkeys(update.user.KEYS, '')
    old.update(receiver=str(old_root / 'source'), target=str(target), operator_sid='pytest',
               protected_sha='4'*40, candidate_sha='d'*40, transport={'pin': 'unchanged'})
    new = dict(old, receiver=str(new_root / 'source'), candidate_sha='e'*40,
               previous_runtime=_pin(target, chain[-1]))
    if fault == 'digest':
        new['previous_runtime']['record_sha256'] = 'f'*64
    elif fault == 'mixed_pair':
        new['previous_runtime']['receiver_sha'] = 'a'*40
    elif fault == 'missing':
        (target / chain[0]['record_path']).unlink()
    elif fault == 'runtime':
        new['protected_sha'] = '5'*40
    elif fault == 'transport':
        new['transport'] = {'pin': 'different'}
    old_path, new_path = (root / update.user.CONFIG_NAME for root in (old_root, new_root))
    old_path.write_text(json.dumps(old))
    new_path.write_text(json.dumps(new))
    monkeypatch.setattr(update.user, 'load_config', lambda *args: new)
    monkeypatch.setattr(update.user, 'verify_release', lambda value: None)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    if fault:
        with pytest.raises((ValueError, FileNotFoundError)):
            update.verify(old_path, update.user.digest(old_path), new_path, update.user.digest(new_path))
    else:
        result = update.verify(old_path, update.user.digest(old_path), new_path, update.user.digest(new_path))
        assert result['read_only'] and len(result['authenticated_historical_pairs']) == 4
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
def test_task_update_transaction_and_rollback(shell, tmp_path):
    executable = shutil.which(shell)
    if not executable:
        pytest.skip(f'{shell} unavailable')
    root = Path(update.__file__).parent
    env = {k: v for k, v in os.environ.items() if k.lower() != 'psmodulepath'}
    result = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-File',
                             str(root / 'tests/test_laptop_backup_user_update.ps1'),
                             str(root / 'laptop_backup_user_update.ps1'), str(tmp_path)],
                            capture_output=True, text=True, timeout=30, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
