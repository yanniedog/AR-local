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
