"""Filesystem-only guard regressions; no historical source or banking fixtures."""
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from cdr_historical_fee_plan_budget import PhaseBudget


def guarded(tmp_path):
    paths = [tmp_path / 'shared' / name for name in ('archive', 'anchor', 'output')]
    for path in paths:
        path.mkdir(parents=True)
    phase = PhaseBudget(deadline=time.monotonic() + 30)
    phase.guard_directories(paths)
    return phase, paths


def test_each_checkpoint_freshly_checks_shared_ancestors_once(tmp_path, monkeypatch):
    phase, paths = guarded(tmp_path)
    calls = []
    original = Path.lstat

    def record(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'lstat', record)
    expected = {part for path in paths for part in (path, *path.parents)}
    for _ in range(2):
        calls.clear()
        phase.check()
        assert set(calls) == expected
        assert len(calls) == len(expected)


def test_replacement_after_success_is_detected(tmp_path):
    phase, paths = guarded(tmp_path)
    phase.check()
    paths[0].rename(paths[0].with_name('preserved-original'))
    paths[0].mkdir()
    with pytest.raises(ValueError, match='directory_identity_changed'):
        phase.check()


def test_new_claim_is_guarded_on_every_check(tmp_path):
    phase, _ = guarded(tmp_path)
    added = tmp_path / 'new-claim'
    phase.claim_directory(added)
    added.rename(tmp_path / 'preserved-claim')
    added.mkdir()
    with pytest.raises(ValueError, match='directory_identity_changed'):
        phase.check()


def test_ancestor_reparse_after_success_is_detected(tmp_path, monkeypatch):
    phase, paths = guarded(tmp_path)
    phase.check()
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == paths[0].parent:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, 'lstat', reparse)
    with pytest.raises(ValueError, match='input_reparse_or_symlink_refused'):
        phase.check()


def test_expired_checkpoint_still_refuses_before_accounting(tmp_path):
    phase, _ = guarded(tmp_path)
    phase.deadline = 0
    with pytest.raises(ValueError, match='archive_deadline_exceeded'):
        phase.check('verified_read', 1)
    assert phase.counts == {}
