"""Retained namespace races and measured-duration policy; generic bytes only."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_drive_backup_source as source
import pi_plain_drive_backup as pipeline
from pi_drive_backup_manifest import ManifestIndex, close_manifest
from tests.test_pi_plain_drive_backup import Drive, layout


def retained_file(data):
    path = data / '.daily-export-stage/2026-10-24/_exports/retained.bin'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'generic retained bytes')
    return path


def freeze(tmp_path, layout, **kwargs):
    data, lease = layout
    return source.freeze(data, tmp_path / 'freeze', controls=[], guard=lambda: None,
        inherited_lease=lease, include_retained_export_stage=True, **kwargs)


def test_addition_during_retained_inventory_refuses_completion(tmp_path, layout, monkeypatch):
    path = retained_file(layout[0])
    original_copy = source._copy
    def copy(src, target, guard):
        original_copy(src, target, guard)
        if src == path:
            (path.parent / 'late.bin').write_bytes(b'late external writer')
    monkeypatch.setattr(source, '_copy', copy)
    with pytest.raises(ValueError, match='directory membership changed'):
        freeze(tmp_path, layout)


@pytest.mark.parametrize('mutation', ['addition', 'removal', 'replacement', 'content'])
def test_retained_changes_after_freeze_refuse_acceptance(tmp_path, layout, mutation):
    path = retained_file(layout[0])
    manifest = freeze(tmp_path, layout)
    try:
        if mutation == 'addition':
            (path.parent / 'late.bin').write_bytes(b'late')
        elif mutation == 'removal':
            path.unlink()
        elif mutation == 'replacement':
            replacement = path.with_name('replacement.bin')
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        else:
            path.write_bytes(b'changed retained bytes')
        with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
            source.verify_direct_sources(manifest)
    finally:
        close_manifest(manifest)


def test_empty_directories_are_disk_indexed_and_proofs_survive_reopen(tmp_path, layout):
    data, _ = layout
    stage = data / '.daily-export-stage'
    for number in range(300):
        (stage / str(number)).mkdir(parents=True)
    manifest = freeze(tmp_path, layout)
    index = manifest['files'].index
    assert index.db.execute('SELECT count(*) FROM retained_directories').fetchone()[0] == 301
    assert index.db.execute('PRAGMA cache_size').fetchone()[0] == -2048
    path = index.path
    close_manifest(manifest)
    reopened = ManifestIndex(path)
    manifest['files'] = reopened.rows()
    try:
        source.verify_direct_sources(manifest)
        (stage / '0/late.bin').write_bytes(b'new file in formerly empty directory')
        with pytest.raises(ValueError, match='directory membership changed'):
            source.verify_direct_sources(manifest)
    finally:
        close_manifest(manifest)


def test_missing_private_directory_proof_cannot_be_silently_recreated(tmp_path, layout):
    retained_file(layout[0])
    manifest = freeze(tmp_path, layout)
    try:
        manifest['files'].index.db.execute('DROP TABLE retained_directories')
        with pytest.raises(ValueError, match='proof is missing'):
            source.verify_direct_sources(manifest)
    finally:
        close_manifest(manifest)


def test_upload_time_retained_addition_never_publishes_catalog(tmp_path, layout):
    path = retained_file(layout[0])
    class ConcurrentDrive(Drive):
        def upload(self, relative, local):
            super().upload(relative, local)
            if relative.endswith('.tar.zst'):
                (path.parent / 'late.bin').write_bytes(b'late external mutation')
    drive = ConcurrentDrive()
    with pytest.raises(ValueError, match='directory membership changed'):
        pipeline.run(layout[0], tmp_path / 'operation', drive,
            controls=[], inherited_lease=layout[1], guard=lambda: None)
    assert not any(name.startswith('catalogs/') for name in drive.objects)
    assert not (tmp_path / 'operation/candidate.json').exists()


@pytest.mark.parametrize('manual', [False, True])
def test_only_manual_freeze_uses_attested_remaining_operation_deadline(tmp_path, layout, monkeypatch, manual):
    data, lease = layout
    now = [0.0]
    monkeypatch.setattr(source, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    lease.context = {'deadline_monotonic': 3600.0}
    def guard():
        now[0] = 1300.0
    kwargs = dict(inherited_lease=lease, include_retained_export_stage=True) if manual else {}
    if manual:
        manifest = source.freeze(data, tmp_path / 'manual', controls=[], guard=guard,
            max_freeze_seconds=None, **kwargs)
        close_manifest(manifest)
    else:
        with pytest.raises(source.SourceFreezeDeadline):
            source.freeze(data, tmp_path / 'legacy', controls=[], guard=guard, **kwargs)


def test_manual_freeze_still_stops_at_attested_deadline_and_classifies_safely(tmp_path, layout, monkeypatch):
    data, lease = layout
    now = [0.0]
    monkeypatch.setattr(source, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    lease.context = {'deadline_monotonic': 3600.0}
    def guard():
        now[0] = 3600.0
    with pytest.raises(source.SourceFreezeDeadline) as caught:
        source.freeze(data, tmp_path / 'manual', controls=[], guard=guard,
            max_freeze_seconds=None, inherited_lease=lease, include_retained_export_stage=True)
    assert pipeline.failure_receipt(caught.value) == {
        'result': 'FAIL', 'error_type': 'SourceFreezeDeadline', 'error_code': 'source_freeze_deadline'}
    assert pipeline.failure_receipt(RuntimeError('/private/path secret message')) == {
        'result': 'FAIL', 'error_type': 'RuntimeError'}


def test_operation_bound_freeze_requires_typed_manual_admission_before_workspace(tmp_path, layout):
    data, lease = layout
    for admitted, include in ((None, False), (object(), True), (lease, False)):
        stage = tmp_path / ('unadmitted-' + str(include))
        with pytest.raises(ValueError, match='typed manual host admission'):
            source.freeze(data, stage, controls=[], guard=lambda: None, max_freeze_seconds=None,
                inherited_lease=admitted, include_retained_export_stage=include)
        assert not stage.exists()


def test_manual_freeze_preserves_outer_quiet_resource_guard(tmp_path, layout):
    def guard():
        raise RuntimeError('quiet-window or resource stop')
    with pytest.raises(RuntimeError, match='quiet-window or resource stop'):
        source.freeze(layout[0], tmp_path / 'manual', controls=[], guard=guard,
            max_freeze_seconds=None, inherited_lease=layout[1], include_retained_export_stage=True)
