"""Mock actual supervisor effects: resource breaches and cleanup identity scope."""
from types import SimpleNamespace
import os
import signal
import pytest
import pi_plain_drive_resources as r
from tests.test_pi_plain_backup_host_control import packet,host_sample


def monitor(monkeypatch,violation=None):
    monkeypatch.setattr(r.os,"WNOHANG",1,raising=False)
    monkeypatch.setattr(r.signal,"SIGKILL",9,raising=False)
    monkeypatch.setattr(r.os,"waitstatus_to_exitcode",lambda status:status,raising=False)
    p=packet();owner={'owner_pid':111,'owner_ticks':1,'controller_pid':112,'controller_ticks':2,
        'cgroup':'/system.slice/'+p['unit'],'device':4,'inode':5,'boot_id':'same','job_id':'job',
        'resource_baseline':host_sample()}
    root=os.getpid();ticks={111:1,112:2,root:3,444:4}
    class H:
        def _controller(self,p):return ({'pid':112,'ticks':2},[])
        def process_identity(self,pid):return {'pid':pid,'ticks':ticks[pid],'cgroup':owner['cgroup']}
        def _job(self,p):return None
        def _lease(self,job):return SimpleNamespace(st_dev=4,st_ino=5)
        def _members(self,group):return [111,112,root,444] if not state['ended'] else [111,112,root]
        def trusted_namespace_process(self,*args):return False
    state={'ended':False,'samples':0,'kills':[]}
    monkeypatch.setattr(r,'sample_host',lambda:host_sample())
    monkeypatch.setattr(r,'context',lambda *args:{'monitor':{'start_ticks':3},'deadline_monotonic':999999999999})
    monkeypatch.setattr(r,'sealed_context',lambda value:999)
    monkeypatch.setattr(r,'fork_worker',lambda *args:444)
    monkeypatch.setattr(r.os,'close',lambda fd:None)
    monkeypatch.setattr(r.time,'sleep',lambda seconds:None)
    def memory(pid):
        state['samples']+=1
        return {'rss':640*r.MIB if violation=='rss' else 1,'swap':1 if violation=='swap' else 0,
            'uid':1000,'uids':[1000]*4,'gids':[1000]*4,'nnp':1,'capabilities':1 if violation=='caps' else 0}
    monkeypatch.setattr(r,'process_memory',memory)
    monkeypatch.setattr(r,'snapshot_member',lambda host,pid,group,**kw:(host.process_identity(pid),r.process_memory(pid)))
    def kill(pid,sig,**kwargs):
        assert kwargs['group']==owner['cgroup']
        state['kills'].append((pid,sig,kwargs));state['ended']=True
    monkeypatch.setattr(r,'signal_pid',kill)
    def wait(pid,flags):
        state['ended']=True
        return 444,0
    monkeypatch.setattr(r.os,'waitpid',wait)
    return H(),p,owner,state


def test_actual_monitor_normal_completion_requires_zero_exit_and_clean_cgroup(monkeypatch):
    h,p,o,state=monitor(monkeypatch)
    result=r.supervise(h,p,o)
    assert result['result']=='PASS' and result['group_clean'] and result['samples']==1
    assert not state['kills']


@pytest.mark.parametrize('violation,reason',[('rss','aggregate_rss_early_stop'),('swap','workload_swapped'),('caps','producer privilege fences differ')])
def test_actual_monitor_breach_kills_only_bound_scope_and_keeps_failure(monkeypatch,violation,reason):
    h,p,o,state=monitor(monkeypatch,violation)
    result=r.supervise(h,p,o)
    assert result['result']=='FAIL' and reason in result['reason'] and result['group_clean']
    assert state['kills'][0][0]==444 and state['kills'][0][2]['expected_ticks']==4


def test_actual_monitor_detects_native_inode_change_before_sampling_worker(monkeypatch):
    h,p,o,state=monitor(monkeypatch);h._lease=lambda job:SimpleNamespace(st_dev=4,st_ino=999)
    result=r.supervise(h,p,o)
    assert result['result']=='FAIL' and 'native lease inode changed' in result['reason']
    assert state['samples']==0

@pytest.mark.parametrize('swap,reason',[(0,'aggregate_rss_early_stop'),(1,'workload_swapped')])
def test_trusted_wrapper_memory_and_swap_are_included_in_same_budget(monkeypatch,swap,reason):
    h,p,o,state=monitor(monkeypatch)
    def memory(pid):
        return {'rss':640*r.MIB if pid==111 and not swap else 1,'swap':swap if pid==111 else 0,
            'uid':1000,'uids':[1000]*4,'gids':[1000]*4,'nnp':0 if pid==111 else 1,'capabilities':7 if pid==111 else 0}
    monkeypatch.setattr(r,'process_memory',memory)
    result=r.supervise(h,p,o)
    assert result['result']=='FAIL' and reason in result['reason']
    assert result['group_clean']

@pytest.mark.parametrize('trusted',[False,True])
def test_snapshot_exit_between_cgroup_and_identity_is_skipped_only_for_untrusted_child(monkeypatch,trusted):
    state={'exited':False}
    class Poll:
        def register(self,*args):pass
        def poll(self,timeout):return [(999,1)] if state['exited'] else []
    class Host:
        def process_identity(self,pid):
            state['exited']=True
            raise FileNotFoundError('normal completed child')
    monkeypatch.setattr(r.os,'pidfd_open',lambda pid:999,raising=False)
    monkeypatch.setattr(r.select,'poll',Poll,raising=False)
    monkeypatch.setattr(r.select,'POLLIN',1,raising=False)
    monkeypatch.setattr(r.os,'close',lambda fd:None)
    if trusted:
        with pytest.raises(FileNotFoundError):r.snapshot_member(Host(),444,'/owned',trusted=True)
    else:assert r.snapshot_member(Host(),444,'/owned') is None


def test_snapshot_live_identity_io_error_still_fails_closed(monkeypatch):
    class Poll:
        def register(self,*args):pass
        def poll(self,timeout):return []
    class Host:
        def process_identity(self,pid):raise PermissionError('live proof unreadable')
    monkeypatch.setattr(r.os,'pidfd_open',lambda pid:999,raising=False)
    monkeypatch.setattr(r.select,'poll',Poll,raising=False)
    monkeypatch.setattr(r.select,'POLLIN',1,raising=False)
    monkeypatch.setattr(r.os,'close',lambda fd:None)
    with pytest.raises(PermissionError):r.snapshot_member(Host(),444,'/owned')


def test_trusted_setuid_sudo_is_still_inside_whole_cgroup_rss_budget(monkeypatch):
    h,p,o,state=monitor(monkeypatch);old_controller=h._controller;old_identity=h.process_identity;old_members=h._members
    h._controller=lambda packet:(old_controller(packet)[0],[{'pid':555,'ticks':5}])
    h.process_identity=lambda pid:({'pid':555,'ticks':5,'cgroup':o['cgroup']} if pid==555 else old_identity(pid))
    h._members=lambda group:old_members(group)+[555]
    old_memory=r.process_memory
    r.process_memory=lambda pid:({'rss':640*r.MIB,'swap':0,'uid':1000,'uids':[1000,0,0,0],
        'gids':[0]*4,'nnp':0,'capabilities':1} if pid==555 else old_memory(pid))
    result=r.supervise(h,p,o)
    assert result['result']=='FAIL' and result['reason'].endswith('aggregate_rss_early_stop')
    assert result['peak_rss_bytes']>=640*r.MIB


def test_untrusted_mixed_uid_process_cannot_pass_as_nnp_pi_producer(monkeypatch):
    h,p,o,state=monitor(monkeypatch);old_memory=r.process_memory
    def memory(pid):
        value=old_memory(pid)
        if pid==444:value['uids']=[1000,0,0,0]
        return value
    r.process_memory=memory
    result=r.supervise(h,p,o)
    assert result['result']=='FAIL' and result['reason'].endswith('producer privilege fences differ')
