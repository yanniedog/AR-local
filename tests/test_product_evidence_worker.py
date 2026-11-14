"""Finite disk observation: no process/service operations or large allocations."""
from types import SimpleNamespace
import os
from pathlib import Path
import pytest
import pi_product_evidence_worker as worker


@pytest.fixture(autouse=True)
def native_stat_controls(monkeypatch):
    monkeypatch.setattr(worker,'os',SimpleNamespace(**vars(os)))
    # Windows DirEntry caches st_dev=0; execution is Linux-only. Preserve real
    # temporary-file identities in these platform-independent disk controls.
    if os.name!='nt':return
    original=os.scandir
    class Entries:
        def __init__(self,path):self.values=original(path)
        def __enter__(self):
            return (SimpleNamespace(path=item.path,stat=lambda follow_symlinks=False,path=item.path:Path(path).lstat()) for item in self.values)
        def __exit__(self,*args):self.values.close()
    monkeypatch.setattr(worker.os,'scandir',Entries)


def usage(free=16*1024**3,inodes=100000):
    return SimpleNamespace(f_bavail=free,f_frsize=1,f_favail=inodes)


def test_disk_failure_is_latched_even_after_free_space_recovers(tmp_path,monkeypatch):
    monkeypatch.setattr(worker.os,'statvfs',lambda path:usage(),raising=False)
    monkeypatch.setattr(worker.os,'getuid',lambda:tmp_path.stat().st_uid,raising=False)
    (tmp_path/'retained.json').write_bytes(b'original failed evidence')
    with worker.DiskGuard(tmp_path) as guard:
        assert guard.check() is None
        monkeypatch.setattr(worker.os,'statvfs',lambda path:usage(inodes=4095))
        failure=guard.check();assert 'reserve exhausted' in failure
        monkeypatch.setattr(worker.os,'statvfs',lambda path:usage())
        assert guard.check()==failure
    assert (tmp_path/'retained.json').read_bytes()==b'original failed evidence'


def test_disk_sweep_lifetime_and_cumulative_growth_never_reset(tmp_path,monkeypatch):
    clock=[100.];monkeypatch.setattr(worker.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(worker.os,'statvfs',lambda path:usage(),raising=False)
    monkeypatch.setattr(worker.os,'getuid',lambda:tmp_path.stat().st_uid,raising=False)
    with worker.DiskGuard(tmp_path) as guard:
        clock[0]+=15
        assert 'stale' in guard.check()
    clock[0]=100.
    with worker.DiskGuard(tmp_path) as guard:
        monkeypatch.setattr(worker.os,'statvfs',lambda path:usage(14*1024**3-1))
        assert 'growth exhausted' in guard.check()


def test_disk_inventory_rejects_other_devices_and_retained_oversize_without_allocation(tmp_path,monkeypatch):
    monkeypatch.setattr(worker.os,'statvfs',lambda path:usage(),raising=False)
    monkeypatch.setattr(worker.os,'getuid',lambda:tmp_path.stat().st_uid,raising=False)
    info=tmp_path.stat()
    class Entries:
        def __enter__(self):return iter([SimpleNamespace(path=str(tmp_path/'large'),stat=lambda **kw:SimpleNamespace(
            st_mode=0o100600,st_dev=info.st_dev,st_uid=info.st_uid,st_nlink=1,st_size=2*1024**3+1))])
        def __exit__(self,*args):pass
    monkeypatch.setattr(worker.os,'scandir',lambda path:Entries())
    with pytest.raises(ValueError,match='retained optional stage storage exhausted'):
        with worker.DiskGuard(tmp_path):pass


def test_complete_terminal_sweep_detects_growth_missed_by_incremental_tick(tmp_path,monkeypatch):
    monkeypatch.setattr(worker.os,'statvfs',lambda path:usage(),raising=False)
    monkeypatch.setattr(worker.os,'getuid',lambda:tmp_path.stat().st_uid,raising=False)
    clock=[100.];monkeypatch.setattr(worker.time,'monotonic',lambda:clock[0])
    info=tmp_path.stat();sizes=[6*1024**2]*300
    class Entries:
        def __enter__(self):return iter([SimpleNamespace(path=str(tmp_path/str(index)),stat=lambda size=size,**kw:SimpleNamespace(
            st_mode=0o100600,st_dev=info.st_dev,st_uid=info.st_uid,st_nlink=1,st_size=size)) for index,size in enumerate(sizes)])
        def __exit__(self,*args):pass
    monkeypatch.setattr(worker.os,'scandir',lambda path:Entries())
    with worker.DiskGuard(tmp_path) as guard:
        assert guard.peak==1800*1024**2
        sizes.append(512*1024**2)
        assert guard.check() is None and guard.entries==256
        with pytest.raises(ValueError,match='retained optional stage storage exhausted'):guard.finish(120.)
        assert 'storage exhausted' in guard.check()


def test_terminal_sweep_cannot_renew_original_deadline(tmp_path,monkeypatch):
    monkeypatch.setattr(worker.os,'statvfs',lambda path:usage(),raising=False)
    monkeypatch.setattr(worker.os,'getuid',lambda:tmp_path.stat().st_uid,raising=False)
    clock=[100.];monkeypatch.setattr(worker.time,'monotonic',lambda:clock[0])
    with worker.DiskGuard(tmp_path) as guard:
        clock[0]=101.
        with pytest.raises(ValueError,match='deadline exhausted'):guard.finish(101.)
        assert 'deadline exhausted' in guard.check()
