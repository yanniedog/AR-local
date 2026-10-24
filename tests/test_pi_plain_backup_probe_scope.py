"""Read-only commissioning scope checks; no root, subprocess or cloud activity."""
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

import pi_plain_backup_attestation as attestation
import pi_plain_backup_probe as probe
import pi_plain_backup_transport as transport
import pi_plain_drive_backup as pipeline


@pytest.fixture
def probe_scope(tmp_path, monkeypatch):
    data = (tmp_path / 'data').resolve()
    (data / 'runs').mkdir(parents=True)
    (data / 'state').mkdir()
    operation = tmp_path / 'sandbox/archive'
    config = tmp_path / 'credentials-copy.conf'
    config.write_bytes(b'generic protocol fixture')
    verify = []
    monkeypatch.setattr(attestation, 'inherited_from_attestation_fd',
        lambda *a, **k: SimpleNamespace(verify=lambda root: verify.append(root)))
    monkeypatch.setattr(attestation, 'protected_file', lambda *_: None)
    original_stat = Path.stat
    monkeypatch.setattr(Path, 'stat', lambda path, *a, **k:
        SimpleNamespace(st_mode=stat.S_IFREG | 0o440) if path == config else original_stat(path, *a, **k))
    monkeypatch.setattr(pipeline, 'freeze', lambda *a, **k: pytest.fail('probe must not freeze'))
    monkeypatch.setattr(transport, 'Rclone', lambda *a, **k: pytest.fail('probe must not contact Drive'))
    argv = ['--data-root', str(data), '--operation', str(operation),
        '--rclone-config', str(config), '--remote', 'approved:plaintext-recovery',
        '--drive-root-folder-id', 'approved-folder', '--attestation-fd', '3',
        '--deadline', '2026-10-24T07:00:00+00:00']
    return data, operation, argv, verify


def test_probe_exercises_retained_stage_scope_without_freezing_or_network(probe_scope, capsys):
    data, operation, argv, verify = probe_scope
    retained = data / '.daily-export-stage/2026-09-19/retained.bin'
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b'retained generic export bytes')
    assert probe.main(argv) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['result'] == 'PROBE_PASS'
    assert receipt['data_scope']['policy_version'] == 2
    assert '.daily-export-stage' in receipt['data_scope']['included']
    assert len(verify) == 2 and not operation.exists()
    assert retained.read_bytes() == b'retained generic export bytes'


def test_probe_rejects_unclassified_actual_source_before_pass_receipt(probe_scope, capsys):
    data, operation, argv, _ = probe_scope
    (data / 'unknown-root').mkdir()
    with pytest.raises(ValueError, match='unclassified'):
        probe.main(argv)
    assert 'PROBE_PASS' not in capsys.readouterr().out
    assert not operation.exists()
