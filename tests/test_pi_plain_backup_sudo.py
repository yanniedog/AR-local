"""Observed setuid sudo identities and secret-free root failure diagnostics."""
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import pytest
import pi_plain_backup_linux as linux
import pi_plain_backup_entry as entry
import pi_plain_backup_parent as parent
import pi_plain_drive_resources as resources
from tests.test_pi_plain_backup_host_control import packet,NONCE


def controller_fixture(monkeypatch,action='acquire'):
    p=packet();group='/system.slice/'+p['unit']
    python=str(Path('/usr/bin/python3').resolve());sudo=str(Path('/usr/bin/sudo').resolve())
    root_argv=['/usr/bin/python3','-I','-B',str(linux.ROOT/'broker.py'),action,NONCE]
    def item(pid,ppid,uids,gids,exe,argv):
        return {'pid':pid,'ppid':ppid,'ticks':pid+100,'uid':uids[0],'uids':uids,'gids':gids,
            'nnp':0,'cgroup':group,'exe':exe,'argv':argv}
    rows={300:item(300,200,[0]*4,[0]*4,python,root_argv),
        200:item(200,100,[1000,0,0,0],[0]*4,sudo,['/usr/bin/sudo','-n',*root_argv]),
        100:item(100,50,[1000]*4,[1000]*4,python,
            ['/usr/bin/python3','-I','-B',str(linux.ROOT/'parent.py'),NONCE])}
    monkeypatch.setattr(os,'getpid',lambda:300);monkeypatch.setattr(os,'getppid',lambda:200)
    monkeypatch.setattr(linux,'identity',lambda pid:deepcopy(rows[pid]))
    monkeypatch.setattr(linux,'digest',lambda path:p['parent_sha256'])
    return linux.Host(NONCE),p,rows


@pytest.mark.parametrize('action',['acquire','finish'])
def test_observed_setuid_sudo_real_pi_effective_saved_fs_root_is_admitted(monkeypatch,action):
    host,p,rows=controller_fixture(monkeypatch,action)
    selected,intermediates=host._controller(p)
    assert selected==rows[100] and intermediates==[rows[200]]


@pytest.mark.parametrize('uids',[[0,0,0,0],[1000,1000,0,0],[1000,0,1000,0],[1000,0,0,1000],[2000,0,0,0]])
def test_unobserved_sudo_uid_matrix_never_gets_root_controller_trust(monkeypatch,uids):
    host,p,rows=controller_fixture(monkeypatch);rows[200]['uids']=uids
    with pytest.raises(linux.Blocked):host._controller(p)


@pytest.mark.parametrize('field,value',[('gids',[1000,0,0,0]),('nnp',1),('cgroup','/foreign'),
    ('exe','/tmp/sudo'),('argv',['/usr/bin/sudo','-n','/bin/sh'])])
def test_sudo_ancestry_keeps_full_command_executable_group_nnp_and_scope_guards(monkeypatch,field,value):
    host,p,rows=controller_fixture(monkeypatch);rows[200][field]=value
    with pytest.raises(linux.Blocked):host._controller(p)


@pytest.mark.parametrize('pid,field,value',[(100,'uids',[1000,0,1000,1000]),(100,'gids',[1000,0,1000,1000]),
    (100,'nnp',1),(300,'uids',[0,1000,0,0]),(300,'gids',[0,1000,0,0]),(300,'nnp',1)])
def test_pi_parent_and_root_python_still_require_all_four_exact_ids(monkeypatch,pid,field,value):
    host,p,rows=controller_fixture(monkeypatch);rows[pid][field]=value
    with pytest.raises(linux.Blocked):host._controller(p)


def test_same_prefix_wrong_action_or_extra_sudo_argument_is_rejected(monkeypatch):
    host,p,rows=controller_fixture(monkeypatch);rows[200]['argv'].insert(-1,'extra')
    with pytest.raises(linux.Blocked):host._controller(p)


def test_root_sudo_executable_must_remain_root_protected(monkeypatch):
    host,p,_=controller_fixture(monkeypatch)
    monkeypatch.setattr(linux,'digest',lambda path:(_ for _ in ()).throw(linux.Blocked('untrusted root source')))
    with pytest.raises(linux.Blocked):host._controller(p)


@pytest.mark.skipif(os.name!='posix',reason='actual Linux proc credential arrays and pidfd')
def test_actual_identity_and_memory_accounting_expose_all_kernel_uid_gid_fields():
    actual=linux.identity(os.getpid());memory=resources.process_memory(os.getpid())
    assert len(actual['uids'])==len(actual['gids'])==4
    assert actual['uid']==actual['uids'][0]
    assert memory['uids']==actual['uids'] and memory['gids']==actual['gids']


def test_parent_preserves_acquire_failure_when_finish_also_fails(monkeypatch):
    primary=parent.HelperFailure('acquire','admission_controller','Blocked');calls=[]
    def helper(action,nonce):
        calls.append(action)
        if action=='acquire':raise primary
        raise parent.HelperFailure('finish','finish_policy','Blocked')
    monkeypatch.setattr(parent,'helper',helper)
    with pytest.raises(parent.HelperFailure) as captured:parent.run_helpers(NONCE)
    assert captured.value is primary and calls==['acquire','finish']
    assert parent.failure_output(primary)=={'result':'BLOCKED','error':'HelperFailure','action':'acquire',
        'stage':'admission_controller','helper_error':'Blocked','cleanup_error':'HelperFailure'}


def test_finish_is_still_attempted_after_successful_acquire(monkeypatch):
    calls=[];monkeypatch.setattr(parent,'helper',lambda action,nonce:calls.append(action))
    assert parent.run_helpers(NONCE)==0 and calls==['acquire','finish']


def test_helper_forwards_only_bounded_structured_labels_not_stderr_command_or_exception_body(monkeypatch):
    private='secret-provider-body-and-argv'
    result=SimpleNamespace(returncode=2,stdout=json.dumps({'result':'BLOCKED','stage':'controls_native','error':'Blocked',
        'message':private,'argv':[private]}),stderr=private)
    monkeypatch.setattr(parent.subprocess,'run',lambda *a,**kw:result)
    with pytest.raises(parent.HelperFailure) as captured:parent.helper('acquire',NONCE)
    value=parent.failure_output(captured.value)
    assert value['stage']=='controls_native' and private not in json.dumps(value)
    result.stdout=private
    with pytest.raises(parent.HelperFailure) as captured:parent.helper('acquire',NONCE)
    assert parent.failure_output(captured.value)['stage']=='unknown'


@pytest.mark.parametrize('stdout',['x'*4097,json.dumps({'result':'BLOCKED','stage':'not a label','error':'bad body'})])
def test_helper_malformed_or_oversize_output_is_not_echoed(monkeypatch,stdout):
    monkeypatch.setattr(parent.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=2,stdout=stdout,stderr='private'))
    with pytest.raises(parent.HelperFailure) as captured:parent.helper('acquire',NONCE)
    assert parent.failure_output(captured.value)['stage']=='unknown'


@pytest.mark.skipif(os.name!='posix',reason='actual root-private diagnostic descriptor semantics')
def test_failure_receipt_is_private_bounded_first_failure_and_never_contains_exception_text(tmp_path,monkeypatch):
    private=tmp_path/NONCE;private.mkdir(mode=0o700)
    monkeypatch.setattr(entry,'STATE',tmp_path)
    original=Path.lstat
    def trusted_stat(path):
        # Filesystem effect test need not be privileged. Keep actual directory
        # descriptors/modes and test production custody rejection separately.
        info=original(path)
        return SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|(0o700 if path==private else 0o755))
    monkeypatch.setattr(Path,'lstat',trusted_stat)
    entry.failure_record('acquire',NONCE,'admission_controller',RuntimeError('private-token-and-command'))
    path=private/'failure-acquire.json';raw=path.read_bytes();value=json.loads(raw)
    assert len(raw)<1024 and b'private-token' not in raw and value['stage']=='admission_controller'
    assert stat.S_IMODE(path.stat().st_mode)==0o600
    with pytest.raises(FileExistsError):entry.failure_record('acquire',NONCE,'worker',ValueError('second'))
    assert path.read_bytes()==raw


def test_failure_receipt_refuses_untrusted_parent_custody(monkeypatch):
    monkeypatch.setattr(Path,'lstat',lambda path:SimpleNamespace(st_uid=1000,st_mode=stat.S_IFDIR|0o700))
    with pytest.raises(RuntimeError):entry.failure_record('acquire',NONCE,'admission_controller',RuntimeError('private'))



def test_control_loader_executes_frozen_verified_bytes_and_never_searches_whole_root(tmp_path,monkeypatch):
    import py_compile,sys
    names=('pi_plain_backup_core','pi_shared_queue_post_hooks','pi_plain_drive_resources','pi_plain_backup_linux')
    for name in names:monkeypatch.delitem(sys.modules,name,raising=False)
    monkeypatch.setattr(entry,'ROOT',tmp_path)
    path=tmp_path/'pi_plain_backup_core.py'
    path.write_text("VALUE='stale___'\n",encoding='utf-8');original=path.stat()
    py_compile.compile(str(path),doraise=True)
    path.write_text("VALUE='approved'\n",encoding='utf-8');os.utime(path,ns=(original.st_atime_ns,original.st_mtime_ns))
    bodies={name+'.py':b"VALUE='approved'\n" for name in names}
    bodies['pi_plain_backup_linux.py']=b'from pi_plain_backup_core import VALUE\n'
    # Even changing source after verification cannot alter executed snapshots.
    path.write_text("VALUE='on_disk_changed'\n",encoding='utf-8')
    before=list(sys.path);entry.load_controls(bodies)
    assert sys.path==before and str(tmp_path) not in sys.path
    assert all(sys.modules[name].VALUE=='approved' for name in names)


def test_control_loader_rejects_preexisting_unqualified_module_cache(monkeypatch):
    import sys,types
    monkeypatch.setitem(sys.modules,'pi_plain_backup_core',types.ModuleType('pi_plain_backup_core'))
    with pytest.raises(RuntimeError):entry.load_controls({})


def test_parent_imports_only_hashed_snapshot_without_root_search_path(monkeypatch):
    import hashlib,sys
    raw=b'def approval(*args,**kwargs): return {"qualified":True}\ndef root_json(path): return {}\n'
    own=b'approved parent source'
    manifest={'pi_shared_queue_post_hooks.py':hashlib.sha256(raw).hexdigest(),'parent.py':hashlib.sha256(own).hexdigest()}
    rows={parent.ROOT/'root-control-manifest.json':json.dumps(manifest).encode(),
        parent.ROOT/'pi_shared_queue_post_hooks.py':raw,parent.ROOT/'parent.py':own}
    monkeypatch.setattr(parent,'trusted_bytes',lambda path:rows[path])
    before=list(sys.path);module=parent.load_hooks()
    assert module.approval()['qualified'] and sys.path==before
    rows[parent.ROOT/'pi_shared_queue_post_hooks.py']=b'raise RuntimeError("unapproved source")'
    with pytest.raises(RuntimeError):parent.load_hooks()
