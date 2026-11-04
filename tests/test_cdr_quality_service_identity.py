"""Transport/ownership controls only; no live systemd, proc or HTTP calls."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import pi_cdr_quality_service_identity as identity


def unit():
    return dict(Type='simple', ActiveState='active', SubState='running', MainPID='1149',
                InvocationID='c'*32, ExecMainStartTimestampMonotonic='70989441',
                ControlGroup=identity.CGROUP)


def tcp(inode=12345, address='00000000', port='2268'):
    return f'0: {address}:{port} 00000000:0000 0A 0:0 00:0 0 1000 0 {inode} 1\n'


@pytest.fixture
def host(monkeypatch):
    state = {'unit':unit(), 'stat':'1149 (python (dashboard)) S ' + '0 '*18 + '7098\n',
             'cgroup':'0::'+identity.CGROUP+'\n', 'tcp':tcp(), 'tcp6':'', 'link':'socket:[12345]'}
    calls = []
    monkeypatch.setattr(identity.time, 'monotonic', lambda:100.)
    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs['timeout'] == 2. and kwargs['check'] is True
        return SimpleNamespace(stdout=''.join(k+'='+v+'\n' for k,v in state['unit'].items()).encode(), stderr=b'')
    monkeypatch.setattr(identity.subprocess, 'run', run)
    def read(path, limit, deadline):
        if path.startswith('/proc/net/'):
            return 'sl local_address rem_address st\n'+state[path.rsplit('/',1)[1]]
        assert path.startswith('/proc/1149/')
        return state[path.rsplit('/',1)[1]]
    monkeypatch.setattr(identity, '_read', read)
    monkeypatch.setattr(identity.os, 'scandir', lambda path:nullcontext(iter([SimpleNamespace(path=path+'/3')])))
    monkeypatch.setattr(identity.os, 'readlink', lambda path:state['link'])
    return state, calls


@pytest.mark.parametrize('address',['00000000','0100007F'])
def test_listener_is_owned_by_stable_active_unit(host,address):
    state,calls=host; state['tcp']=tcp(address=address)
    result=identity.read_dashboard_identity(110.)
    assert result['main_pid']==1149 and result['start_ticks']==7098 and result['listener_inode']==12345
    assert len(calls)==2 and calls[0]==calls[1]
    assert calls[0]==['/usr/bin/systemctl','show',identity.UNIT,'--no-pager',
                       '--property='+','.join(identity.PROPERTIES)]


@pytest.mark.parametrize('fault',['inactive','zero_pid','bad_invocation','cgroup','zombie','wrong_owner',
                                 'missing','ambiguous','ipv6','wrong_port'])
def test_spoofed_or_unavailable_dashboard_refused(host,fault):
    state,_=host
    if fault=='inactive':state['unit']['ActiveState']='inactive'
    elif fault=='zero_pid':state['unit']['MainPID']='0'
    elif fault=='bad_invocation':state['unit']['InvocationID']='0'*32
    elif fault=='cgroup':state['cgroup']='0::/unrelated.service\n'
    elif fault=='zombie':state['stat']=state['stat'].replace(')) S ', ')) Z ')
    elif fault=='wrong_owner':state['link']='socket:[98765]'
    elif fault=='missing':state['tcp']=''
    elif fault=='ambiguous':state['tcp']+=tcp(12346,'0100007F')
    elif fault=='ipv6':state['tcp6']=tcp(12346,'0'*32)
    elif fault=='wrong_port':state['tcp']=tcp(port='0050')
    with pytest.raises(ValueError):identity.read_dashboard_identity(110.)


@pytest.mark.parametrize('kind',['unit','process','listener'])
def test_identity_race_refused(host,monkeypatch,kind):
    name={'unit':'_unit','process':'_process','listener':'_listener'}[kind]
    original=getattr(identity,name); count=0
    def changing(*args):
        nonlocal count
        result=original(*args);count+=1
        if count==2:
            return {**result,'InvocationID':'d'*32} if kind=='unit' else result+1
        return result
    monkeypatch.setattr(identity,name,changing)
    with pytest.raises(ValueError,match='changed'):identity.read_dashboard_identity(110.)


def test_unreadable_fd_refuses_without_elevation(host,monkeypatch):
    monkeypatch.setattr(identity.os,'readlink',lambda path:(_ for _ in ()).throw(PermissionError()))
    with pytest.raises(PermissionError):identity.read_dashboard_identity(110.)


def test_fd_enumeration_bound(host,monkeypatch):
    monkeypatch.setattr(identity.os,'scandir',lambda path:nullcontext(iter(
        [SimpleNamespace(path=path+'/'+str(i)) for i in range(513)])))
    with pytest.raises(ValueError,match='fd_bound'):identity.read_dashboard_identity(110.)


def test_deadline_expiry_refuses(host):
    with pytest.raises(ValueError,match='deadline'):identity.read_dashboard_identity(100.)


@pytest.mark.parametrize('fault',['oversize','stderr','duplicate','missing','timeout'])
def test_unit_read_fails_closed(host,monkeypatch,fault):
    raw=''.join(k+'='+v+'\n' for k,v in unit().items()).encode()
    def run(*args,**kwargs):
        if fault=='timeout':raise identity.subprocess.TimeoutExpired(args[0],2.)
        return SimpleNamespace(stdout=(b'x'*8193 if fault=='oversize' else
            raw+b'Type=simple\n' if fault=='duplicate' else b'Type=simple\n' if fault=='missing' else raw),
            stderr=b'unknown diagnostic' if fault=='stderr' else b'')
    monkeypatch.setattr(identity.subprocess,'run',run)
    with pytest.raises((ValueError,identity.subprocess.TimeoutExpired)):
        identity.read_dashboard_identity(110.)


def test_bounded_proc_read(tmp_path):
    path=tmp_path/'metadata';path.write_bytes(b'12345')
    with pytest.raises(ValueError,match='read_bound'):identity._read(path,4,identity.time.monotonic()+2.)


@pytest.mark.parametrize('bad',['unknown','bool','missing'])
def test_receipt_identity_strict(host,bad):
    value=identity.read_dashboard_identity(110.)
    if bad=='unknown':value['extra']='x'
    elif bad=='bool':value['main_pid']=True
    else:del value['listener_inode']
    with pytest.raises(ValueError):identity.validate_identity(value)
