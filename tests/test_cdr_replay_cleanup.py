"""Cleanup directory replacement controls; no financial acceptance data."""
import os
import pytest
import cdr_replay_cleanup as cleanup


def prepared(tmp_path):
    root = tmp_path / 'owned'; root.mkdir(); (root / 'rows.sqlite').write_bytes(b'owned')
    info = root.stat()
    return root, (info.st_dev, info.st_ino)


@pytest.mark.skipif(os.name == 'posix', reason='Windows/non-POSIX retention contract')
def test_nonposix_retains_complete_successful_scratch(tmp_path):
    root, identity = prepared(tmp_path)
    result = cleanup.cleanup(root, identity, {'rows.sqlite'})
    assert result['state'] == 'RETAINED_UNSUPPORTED_ANCHORED_DELETE'
    assert (root / 'rows.sqlite').read_bytes() == b'owned'


@pytest.mark.skipif(os.name != 'posix', reason='real POSIX dir-fd contract')
def test_posix_keeps_empty_directory_and_does_not_path_rmdir(tmp_path):
    root, identity = prepared(tmp_path)
    result = cleanup.cleanup(root, identity, {'rows.sqlite'})
    assert result['state'] == 'FILES_REMOVED_EMPTY_DIRECTORY_RETAINED'
    assert root.is_dir() and not list(root.iterdir())


@pytest.mark.skipif(os.name != 'posix', reason='real POSIX dir-fd contract')
@pytest.mark.parametrize('when', ['before_open', 'after_open'])
def test_replaced_root_never_redirects_deletion_to_foreign_files(tmp_path, monkeypatch, when):
    root, identity = prepared(tmp_path); moved = tmp_path / 'moved'
    real_open, real_listdir = os.open, os.listdir
    changed = False
    def replace():
        nonlocal changed
        if changed: return
        changed = True; root.rename(moved); root.mkdir()
        (root / 'rows.sqlite').write_bytes(b'foreign')
    def opened(*args, **kwargs):
        if when == 'before_open': replace()
        return real_open(*args, **kwargs)
    def listed(*args, **kwargs):
        if when == 'after_open': replace()
        return real_listdir(*args, **kwargs)
    monkeypatch.setattr(os, 'open', opened); monkeypatch.setattr(os, 'listdir', listed)
    with pytest.raises(RuntimeError, match='changed'): cleanup.cleanup(root, identity, {'rows.sqlite'})
    assert (root / 'rows.sqlite').read_bytes() == b'foreign'
    assert moved.is_dir()
    if when == 'before_open': assert (moved / 'rows.sqlite').read_bytes() == b'owned'


@pytest.mark.skipif(os.name != 'posix', reason='real POSIX dir-fd contract')
def test_unknown_entry_stops_before_any_cleanup(tmp_path):
    root, identity = prepared(tmp_path); (root / 'foreign').write_bytes(b'preserve')
    with pytest.raises(RuntimeError, match='unknown'): cleanup.cleanup(root, identity, {'rows.sqlite'})
    assert (root / 'rows.sqlite').read_bytes() == b'owned'
    assert (root / 'foreign').read_bytes() == b'preserve'
