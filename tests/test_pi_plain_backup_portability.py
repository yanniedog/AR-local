"""Archive metadata and transfer boundaries; generic bytes, no business records."""
from decimal import Decimal
import io
from pathlib import Path
import tarfile

import pytest

from pi_plain_backup_packs import PackIndex, header
from pi_plain_backup_transport import Rclone
import pi_plain_drive_backup as pipeline


def test_external_control_is_rejected_before_workspace_or_source_read(tmp_path, monkeypatch):
    sensitive = tmp_path / 'outside-source.txt'
    sensitive.write_bytes(b'generic external bytes that must never be uploaded')
    monkeypatch.setattr(pipeline, 'freeze', lambda *a, **k: pytest.fail('freeze must not run'))
    with pytest.raises(ValueError, match='external control'):
        pipeline.run(tmp_path / 'data', tmp_path / 'operation', object(),
                     controls=[sensitive], inherited_lease=object(), guard=lambda: None)
    assert not (tmp_path / 'operation').exists()
    assert sensitive.read_bytes().startswith(b'generic external')


def test_cli_has_no_external_control_argument():
    with pytest.raises(SystemExit) as caught:
        pipeline.main(['--data-root', '/source', '--operation', '/new-operation',
            '--rclone-config', '/private.conf', '--remote', 'approved:plaintext-recovery',
            '--drive-root-folder-id', 'approved-folder-id', '--attestation-fd', '3',
            '--deadline', '2026-10-24T06:00:00+00:00', '--control-file', '/external'])
    assert caught.value.code == 2


@pytest.mark.parametrize('paths', [
    ['data/runs/date/A.bin', 'data/runs/date/a.bin'],
    ['data/runs/date/first.bin', 'data/runs/date/first.bin'],
    [r'data/runs/date/..\outside.bin'],
    ['data/runs//date/bytes.bin'],
])
def test_pack_index_rejects_nonportable_paths_before_any_archive(tmp_path, paths):
    rows = [{'logical_path': name, 'size': 0} for name in paths]
    with pytest.raises(ValueError):
        PackIndex(tmp_path / 'index.sqlite', rows, lambda: None)
    assert not list(tmp_path.glob('*.zst'))


@pytest.mark.parametrize('nanoseconds', [-1, -999999999, -1000000001, -1500000000, -2000000000, 0, 1, 1500000000])
def test_real_pax_header_preserves_signed_nanosecond_timestamp(nanoseconds):
    row = dict(size=1, mode='0o640', uid=1000, gid=1000, mtime_ns=nanoseconds)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as archive:
        archive.addfile(header('data/bytes.bin', row), io.BytesIO(b'x'))
    with tarfile.open(fileobj=io.BytesIO(buffer.getvalue()), mode='r:') as archive:
        member = archive.next()
        assert Decimal(member.pax_headers['mtime']) * 10**9 == nanoseconds
        assert archive.extractfile(member).read() == b'x'


@pytest.mark.parametrize('direction,relative,local', [
    ('upload', '../outside/file', '/source'),
    ('download', 'catalogs/latest.json', '/destination'),
    ('sync', 'catalogs/' + 'a' * 64 + '.json', '/destination'),
    ('upload', 'catalogs/' + 'a' * 64 + '.json', 'other-remote:arbitrary'),
])
def test_raw_transfer_cannot_bypass_destination_policy(direction, relative, local):
    transport = Rclone.__new__(Rclone)
    transport.remote = 'approved:plaintext-recovery'
    transport.guard = lambda: pytest.fail('invalid endpoints reached transfer')
    with pytest.raises(ValueError):
        transport._copyto(direction, relative, Path(local))
    assert not hasattr(transport, 'command')
