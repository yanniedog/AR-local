"""Fixed legacy credential custody and actual POSIX umask/descriptor behavior."""
from pathlib import Path
from types import SimpleNamespace
import os
import stat
import pytest
import pi_plain_backup_packet as packet
import pi_plain_backup_install as install


def directory_info(uid=0,gid=0,mode=0o755):
    return SimpleNamespace(st_uid=uid,st_gid=gid,st_mode=stat.S_IFDIR|mode)


def test_only_two_fixed_legacy_directories_allow_pi_private_custody():
    for path in (packet.CONFIG.parent,packet.CONFIG.parent.parent.parent):
        packet.validate_credential_directory(directory_info(1000,1000,0o700),path,1000,1000)
        for info in (directory_info(0,0,0o700),directory_info(1000,1000,0o750),directory_info(1000,0,0o700)):
            with pytest.raises(RuntimeError):packet.validate_credential_directory(info,path,1000,1000)
    path=packet.CONFIG.parent.parent
    packet.validate_credential_directory(directory_info(0,0,0o700),path,1000,1000)
    with pytest.raises(RuntimeError):packet.validate_credential_directory(directory_info(1000,1000,0o700),path,1000,1000)
    with pytest.raises(RuntimeError):packet.validate_credential_directory(directory_info(1000,1000,0o700),Path('/var/lib/other'),1000,1000)
    with pytest.raises(RuntimeError):packet.validate_credential_directory(directory_info(0,0,0o777),Path('/var/lib'),1000,1000)


@pytest.mark.parametrize('module',[packet,install])
def test_requested_directory_custody_is_exact_without_relaxing_incumbents(module):
    module.validate_directory_stat(directory_info(0,1000,0o750),0o750,1000)
    for info in (directory_info(0,1000,0o700),directory_info(1000,1000,0o750),directory_info(0,0,0o750)):
        with pytest.raises(RuntimeError):module.validate_directory_stat(info,0o750,1000)


posix=pytest.mark.skipif(os.name!='posix',reason='real Linux dirfd/nofollow/fchmod/umask semantics')


@posix
@pytest.mark.parametrize('module',[packet,install])
@pytest.mark.parametrize('mode,gid',[(0o755,0),(0o750,1000),(0o700,0)])
def test_new_directories_get_exact_mode_under_actual_service_umask(tmp_path,monkeypatch,module,mode,gid):
    # Runner need not have root: test the real filesystem's0077 filtering and
    # fchmod, and separately test the strict ownership policy above.
    calls=[]
    monkeypatch.setattr(os,'fchown',lambda fd,uid,group:calls.append((uid,group)))
    monkeypatch.setattr(module,'validate_directory_stat',lambda *args:None)
    previous=os.umask(0o077)
    try:
        path=tmp_path/'new';module.directory(path,mode,gid)
    finally:os.umask(previous)
    assert stat.S_IMODE(path.stat().st_mode)==mode
    assert calls==[(0,gid)]


@posix
@pytest.mark.parametrize('module',[packet,install])
def test_incumbent_directory_is_never_chmodded_or_chowned(tmp_path,monkeypatch,module):
    path=tmp_path/'incumbent';path.mkdir(mode=0o700);before=path.stat()
    monkeypatch.setattr(os,'fchmod',lambda *args:pytest.fail('incumbent chmod'))
    monkeypatch.setattr(os,'fchown',lambda *args:pytest.fail('incumbent chown'))
    monkeypatch.setattr(module,'validate_directory_stat',lambda *args:(_ for _ in ()).throw(RuntimeError('mode differs')))
    with pytest.raises(RuntimeError):module.directory(path,0o755,0)
    after=path.stat()
    assert (before.st_mode,before.st_uid,before.st_gid,before.st_ino)==(after.st_mode,after.st_uid,after.st_gid,after.st_ino)


def fixture_config(tmp_path,monkeypatch):
    base=tmp_path/'legacy';credentials=base/'credentials';dedicated=credentials/'dedicated'
    dedicated.mkdir(parents=True);path=dedicated/'credential.conf'
    path.write_bytes(b'private-test-placeholder');path.chmod(0o600)
    monkeypatch.setattr(packet,'CONFIG',path)
    # Real runner temp ancestors need not be root. Exact production custody
    # policy is covered independently; here exercise actual kernel traversal.
    monkeypatch.setattr(packet,'validate_credential_directory',lambda info,*args:None)
    return path


@posix
def test_descriptor_reader_preserves_source_bytes_metadata_and_closes_fds(tmp_path,monkeypatch):
    path=fixture_config(tmp_path,monkeypatch);before=path.stat()
    assert packet.credential_original(os.getuid(),os.getgid())==path.read_bytes()
    after=path.stat()
    assert packet._credential_identity(before)==packet._credential_identity(after)


@posix
@pytest.mark.parametrize('which',['leaf','parent'])
def test_descriptor_reader_never_follows_symlink(tmp_path,monkeypatch,which):
    path=fixture_config(tmp_path,monkeypatch)
    target=path if which=='leaf' else path.parent
    other=target.with_name(target.name+'-retained');target.rename(other);target.symlink_to(other,target_is_directory=which=='parent')
    with pytest.raises(OSError):packet.credential_original(os.getuid(),os.getgid())
    assert other.exists()


@posix
def test_descriptor_reader_rejects_same_inode_hardlinked_leaf(tmp_path,monkeypatch):
    path=fixture_config(tmp_path,monkeypatch);os.link(path,path.with_name('duplicate'))
    with pytest.raises(RuntimeError):packet.credential_original(os.getuid(),os.getgid())


@posix
@pytest.mark.parametrize('which',['leaf','parent','inplace'])
def test_descriptor_reader_rechecks_namespace_and_leaf_after_read(tmp_path,monkeypatch,which):
    path=fixture_config(tmp_path,monkeypatch);read=os.read
    def changed(fd,maximum):
        raw=read(fd,maximum)
        if which=='leaf':
            old=path.with_name('retained');path.rename(old);path.write_bytes(raw);path.chmod(0o600)
        elif which=='parent':
            old=path.parent.with_name('retained');path.parent.rename(old);path.parent.mkdir()
            path.write_bytes(raw);path.chmod(0o600)
        else:
            with path.open('r+b') as stream:stream.write(b'X')
        return raw
    monkeypatch.setattr(os,'read',changed)
    with pytest.raises(RuntimeError):packet.credential_original(os.getuid(),os.getgid())


@posix
def test_rejected_directory_does_not_leak_open_descriptor(tmp_path,monkeypatch):
    fixture_config(tmp_path,monkeypatch);opened=[];closed=[];open_fd=os.open;close_fd=os.close
    def tracked_open(*args,**kwargs):
        fd=open_fd(*args,**kwargs);opened.append(fd);return fd
    def tracked_close(fd):closed.append(fd);return close_fd(fd)
    monkeypatch.setattr(os,'open',tracked_open);monkeypatch.setattr(os,'close',tracked_close)
    monkeypatch.setattr(packet,'validate_credential_directory',lambda *args:(_ for _ in ()).throw(RuntimeError('custody')))
    with pytest.raises(RuntimeError):packet.credential_original(os.getuid(),os.getgid())
    assert opened==closed
