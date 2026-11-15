"""Actual local private namespace creation/reuse; no finance acceptance data."""
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from cdr_replay_paths import private_replay_parent


def test_new_private_namespace_reuses_without_mutating_retained_bytes(tmp_path):
    path = tmp_path / '.daily-replay-stage'
    assert private_replay_parent(path) == path
    (path / 'retained').write_bytes(b'original')
    before = path.stat()
    assert private_replay_parent(path) == path
    after = path.stat()
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    assert (path / 'retained').read_bytes() == b'original'
    if os.name == 'posix': assert after.st_mode & 0o777 == 0o700


def test_existing_nonprivate_namespace_fails_without_repermissioning(tmp_path):
    path = tmp_path / 'foreign'; path.mkdir(mode=0o755)
    (path / 'kept').write_bytes(b'original')
    before = path.stat()
    with pytest.raises(ValueError, match='private|DACL'): private_replay_parent(path)
    assert path.stat().st_mode == before.st_mode and (path / 'kept').read_bytes() == b'original'


def test_reparse_ancestry_rejects_before_creating_namespace(tmp_path, monkeypatch):
    path = tmp_path / 'new'; real = Path.lstat
    def flagged(self):
        info = real(self)
        if self == tmp_path:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info
    monkeypatch.setattr(Path, 'lstat', flagged)
    with pytest.raises(ValueError, match='reparse ancestry'): private_replay_parent(path)
    assert not path.exists()


def test_namespace_parent_traversal_is_not_normalized_into_another_target(tmp_path):
    with pytest.raises(ValueError, match='canonical'):
        private_replay_parent(tmp_path / '..' / 'not-an-owned-target')


@pytest.mark.parametrize('private', [True, False])
def test_concurrent_first_creator_is_revalidated_without_changing_its_files(tmp_path, monkeypatch, private):
    import pi_plain_backup_restore
    create = pi_plain_backup_restore.private_workspace
    path = tmp_path / 'simultaneous-first-create'
    def another_creator(destination):
        if private: create(destination)
        else: destination.mkdir(mode=0o755)
        (destination / 'retained').write_bytes(b'other owner evidence')
        raise FileExistsError('other creator won')
    monkeypatch.setattr(pi_plain_backup_restore, 'private_workspace', another_creator)
    if private: assert private_replay_parent(path) == path
    else:
        with pytest.raises(ValueError, match='private|DACL'): private_replay_parent(path)
    assert (path / 'retained').read_bytes() == b'other owner evidence'


@pytest.mark.parametrize('replacement', ['file', 'reparse', 'symlink'])
def test_concurrent_creator_cannot_substitute_nondirectory_or_alias(tmp_path, monkeypatch, replacement):
    import pi_plain_backup_restore
    if replacement == 'symlink' and os.name != 'posix': pytest.skip('actual POSIX symlink control')
    create = pi_plain_backup_restore.private_workspace
    path = tmp_path / 'concurrent-substitute'; foreign = tmp_path / 'foreign'
    create(foreign); (foreign / 'retained').write_bytes(b'unchanged')
    real = Path.lstat
    def flagged(self):
        info = real(self)
        if self == path and replacement == 'reparse':
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info
    def raced(destination):
        if replacement == 'file': destination.write_bytes(b'foreign file')
        elif replacement == 'symlink': destination.symlink_to(foreign, target_is_directory=True)
        else: create(destination)
        raise FileExistsError('concurrent substitution')
    monkeypatch.setattr(pi_plain_backup_restore, 'private_workspace', raced)
    monkeypatch.setattr(Path, 'lstat', flagged)
    with pytest.raises(ValueError, match='unsafe directory/reparse ancestry'):
        private_replay_parent(path)
    assert (foreign / 'retained').read_bytes() == b'unchanged'
    if replacement == 'file': assert path.read_bytes() == b'foreign file'
