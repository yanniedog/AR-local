"""The installed writer must recover after an abruptly terminated reader."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from laptop_backup_atomic import ReceiverLock
from laptop_recovery_lock import process_writer_lock


@pytest.mark.skipif(os.name != "nt", reason="Windows delete-on-close semantics")
def test_killed_reader_releases_both_names_for_installed_writer(tmp_path):
    locations = (tmp_path, tmp_path / "user-session-lock")
    for location in locations:
        (location / "catalog").mkdir(parents=True)
    code = """import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from laptop_recovery_lock import process_writer_lock
root = Path(sys.argv[2])
with process_writer_lock(root / 'user-session-lock'), process_writer_lock(root):
    print('ready', flush=True)
    sys.stdin.read()
"""
    child = subprocess.Popen(
        [sys.executable, "-I", "-S", "-B", "-c", code,
         str(Path(__file__).parents[1]), str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        for location in locations:
            assert (location / "catalog/.receiver.lock").exists()
            with pytest.raises(FileExistsError):
                with ReceiverLock(location):
                    pytest.fail("installed writer entered while reader held the lock")
        child.kill()  # TerminateProcess; Python finally blocks do not run.
        child.wait(timeout=10)
        for location in locations:
            assert not (location / "catalog/.receiver.lock").exists()
            with ReceiverLock(location):
                assert (location / "catalog/.receiver.lock").exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


@pytest.mark.skipif(os.name == "nt", reason="Unsupported live platform")
def test_non_windows_lock_refuses_without_creating_files(tmp_path):
    with pytest.raises(ValueError, match="require Windows"):
        with process_writer_lock(tmp_path):
            pytest.fail("unsupported live lock entered")
    assert not list(tmp_path.iterdir())
