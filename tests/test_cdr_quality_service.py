import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_cdr_quality_service as service

BOOT = 'cf36b73c-1111-4111-8111-111111111111'


@pytest.fixture
def binding(tmp_path, monkeypatch):
    operation = tmp_path/'operation'; operation.mkdir()
    monkeypatch.setattr(service, '_boot_id', lambda: BOOT)
    return {'schema':service.SCHEMA,'source_sha256':service.source_sha256(),'source_commit':'a'*40,
            'operation':str(operation),'unit':'ar-local-quality-test.service','boot_id':BOOT,'nonce':'b'*64}


def snapshot(binding, *, seq=1, start=100., finish=101.):
    return {'schema':service.SNAPSHOT_SCHEMA,'binding_sha256':service._binding(binding),'seq':seq,
            'started_monotonic':start,'finished_monotonic':finish,'initial_pass_finished_monotonic':101.,
            'probe_count':seq*2,'failed_probe_count':0,'failure_latched':False,'max_latency_s':.5,
            'max_round_gap_s':0. if seq==1 else 6.,'max_pair_duration_s':1.,
            'probes':[{'endpoint':name,'status':'PASS','http_status':200,'run_date':'2026-11-03',
                       'rate_count':16273,'latency_s':.5} for name in service.ENDPOINTS]}


def files(binding, value):
    directory=Path(binding['operation'])/'pressure';directory.mkdir()
    service._write(directory,'binding.json',binding)
    service._write(directory,'snapshot.json',value,replace=True)
    return directory


def test_binding_and_snapshot_roundtrip(binding):
    value=snapshot(binding);directory=files(binding,value)
    assert service.read_binding(directory)==(binding,service._binding(binding))
    assert service.read_service_snapshot(directory,binding,None,102.)==value
    assert service.read_service_snapshot(directory,binding,value,102.)==value


def test_now_taken_after_read(binding,monkeypatch):
    value=snapshot(binding);directory=files(binding,value)
    monkeypatch.setattr(service,'_monotonic',lambda:101.)
    assert service.read_service_snapshot(directory,binding,None,None)==value
    monkeypatch.setattr(service,'_monotonic',lambda:100.99)
    with pytest.raises(ValueError,match='future'):
        service.read_service_snapshot(directory,binding,None,None)


@pytest.mark.parametrize('fault',['schema','binding','future','stale','reset','same_seq','latch','count',
                                 'latency','pair','gap','initial','unknown_field'])
def test_snapshot_fail_closed(binding,fault):
    previous=snapshot(binding);value=snapshot(binding,seq=2,start=106.,finish=107.);now=108.
    if fault=='schema':value['schema']='old'
    elif fault=='binding':value['binding_sha256']='0'*64
    elif fault=='future':now=106.9
    elif fault=='stale':now=144.01
    elif fault=='reset':value['seq']=0;value['probe_count']=0
    elif fault=='same_seq':value['seq']=1;value['probe_count']=2;value['max_round_gap_s']=0;value['initial_pass_finished_monotonic']=107.
    elif fault=='latch':value['failed_probe_count']=1;value['failure_latched']=True
    elif fault=='count':value['probe_count']=3
    elif fault=='latency':value['max_latency_s']=15.01
    elif fault=='pair':value['max_pair_duration_s']=30.01
    elif fault=='gap':value['max_round_gap_s']=37.01
    elif fault=='initial':value['initial_pass_finished_monotonic']=102.
    elif fault=='unknown_field':value['response_body']='must not persist'
    with pytest.raises(ValueError):service._snapshot(value,service._binding(binding),previous,now)


@pytest.mark.parametrize('key',['max_latency_s','max_round_gap_s','max_pair_duration_s'])
def test_cumulative_maxima_cannot_reset(binding,key):
    first=snapshot(binding,seq=2,start=106.,finish=107.);first[key]=10.
    last=snapshot(binding,seq=3,start=112.,finish=113.)
    with pytest.raises(ValueError,match='cumulative_reset'):
        service._snapshot(last,service._binding(binding),first,114.)


def test_atomic_file_replacement_and_no_reuse(binding):
    first=snapshot(binding);directory=files(binding,first)
    last=snapshot(binding,seq=2,start=106.,finish=107.)
    service._write(directory,'snapshot.json',last,replace=True)
    assert service.read_service_snapshot(directory,binding,first,108.)==last
    with pytest.raises(FileExistsError):service._write(directory,'binding.json',binding)


def test_old_snapshot_inode_can_be_read_while_atomically_replaced():
    fields=dict(st_dev=1,st_ino=2,st_mode=0o100600,st_nlink=1,st_uid=3,st_gid=4,
                st_size=100,st_mtime_ns=5,st_ctime_ns=6)
    opened=SimpleNamespace(**fields)
    after=SimpleNamespace(**{**fields,'st_nlink':0,'st_ctime_ns':7})
    final=SimpleNamespace(**{**fields,'st_ino':9})
    service._atomic_snapshot_identity(opened,after,final)
    for key,value in [('st_size',101),('st_mtime_ns',8),('st_nlink',2),('st_mode',0o100400)]:
        bad=SimpleNamespace(**{**vars(after),key:value})
        with pytest.raises(ValueError):service._atomic_snapshot_identity(opened,bad,final)
    with pytest.raises(ValueError):service._atomic_snapshot_identity(opened,after,opened)


def test_linked_ctime_change_refused():
    fields=dict(st_dev=1,st_ino=2,st_mode=0o100600,st_nlink=1,st_uid=3,st_gid=4,
                st_size=100,st_mtime_ns=5,st_ctime_ns=6)
    opened=SimpleNamespace(**fields);after=SimpleNamespace(**{**fields,'st_ctime_ns':8})
    with pytest.raises(ValueError,match='ctime'):service._atomic_snapshot_identity(opened,after,after)


def test_hardlinked_snapshot_refused(binding,monkeypatch):
    directory=files(binding,snapshot(binding));native=Path.lstat
    def metadata(path):
        info=native(path)
        if path==directory/'snapshot.json':
            return SimpleNamespace(st_mode=info.st_mode,st_nlink=2,st_size=info.st_size)
        return info
    monkeypatch.setattr(Path,'lstat',metadata)
    with pytest.raises(ValueError,match='file_type'):service.read_service_snapshot(directory,binding,None,102.)


def test_symlink_snapshot_refused(binding,tmp_path):
    directory=files(binding,snapshot(binding));target=tmp_path/'target';target.write_bytes((directory/'snapshot.json').read_bytes())
    (directory/'snapshot.json').unlink()
    try:(directory/'snapshot.json').symlink_to(target)
    except OSError:pytest.skip('Windows symlink privilege unavailable; type guard separately covered')
    with pytest.raises(ValueError,match='file_type'):service.read_service_snapshot(directory,binding,None,102.)


@pytest.mark.parametrize('fault',['boot','source','nonce','operation','unit'])
def test_binding_faults(binding,fault):
    if fault=='boot':binding['boot_id']='00000000-0000-4000-8000-000000000000'
    elif fault=='source':binding['source_sha256']='0'*64
    elif fault=='nonce':binding['nonce']='missing'
    elif fault=='operation':binding['operation']='relative'
    else:binding['unit']='bad.service\n'
    with pytest.raises(ValueError):service._binding(binding,live=True)


def response(body,headers=b''):
    return b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\n'+headers+b'\r\n'+body


def test_http_parser_content_length_and_chunked():
    assert service._body(response(b'{}'))==b'{}'
    raw=b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n'
    assert service._body(raw)==b'{}'
    assert service._body(response(b'{}')[:-1]) is None
    assert service._body(response(b'{}', b'Vary: origin\r\nVary: accept-encoding\r\n'))==b'{}'


@pytest.mark.parametrize('wire',[
    b'HTTP/1.1 302 Found\r\nLocation: http://elsewhere\r\n\r\n',
    b'HTTP/1.1 200 OK\r\nContent-Length: 65537\r\n\r\n',
    response(b'{}',b'Content-Encoding: gzip\r\n'),
    response(b'{}',b'Content-Length: 2\r\n'),
    response(b'{}',b'Transfer-Encoding: chunked\r\n'),
    b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2;x=y\r\n{}\r\n0\r\n\r\n',
    b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\nX: y\r\n\r\n',
    b'x'*16385])
def test_http_surprises_rejected(wire):
    with pytest.raises(ValueError):service._body(wire)


@pytest.mark.parametrize('body',[b'[]',b'{"banks_counts":{"rates":true},"run_date":"2026-11-03"}',
    b'{"banks_counts":{"rates":1.5},"run_date":"2026-11-03"}',
    b'{"banks_counts":{"rates":0},"run_date":"2026-11-03"}',
    b'{"banks_counts":{"rates":3},"run_date":"2026-02-30"}',
    b'{"banks_counts":{"rates":3,"rates":4},"run_date":"2026-11-03"}',b' '*65537])
def test_manifest_validation_bounded(monkeypatch,body):
    monkeypatch.setattr(service,'_http',lambda *a:body)
    with pytest.raises((ValueError,json.JSONDecodeError)):service._probe('nginx',115.)


def test_probe_retains_only_health_fields(monkeypatch):
    monkeypatch.setattr(service,'_http',lambda *a:b'{"banks_counts":{"rates":12},"run_date":"2026-11-03","private":"not retained"}')
    assert service._probe('nginx',115.)=={'http_status':200,'run_date':'2026-11-03','rate_count':12}


def test_direct_socket_deadline_no_proxy_dns_retry(monkeypatch):
    ticks=[100.];observed=[];wire=[response(b'{}')]
    class FakeSocket:
        def __enter__(self):return self
        def __exit__(self,*a):observed.append('closed')
        def setblocking(self,value):assert value is False
        def connect_ex(self,address):observed.append(address);return 0
        def getsockopt(self,*a):return 0
        def send(self,data):observed.append(data);return len(data)
        def recv(self,size):assert size==4096;return wire.pop(0)
    monkeypatch.setattr(service.socket,'socket',lambda *a:FakeSocket())
    monkeypatch.setattr(service,'_monotonic',lambda:ticks[0])
    def select(read,write,error,timeout):
        observed.append(timeout);ticks[0]+=.01;return read,write,[]
    monkeypatch.setattr(service.select,'select',select)
    assert service._http('dashboard',115.)==b'{}'
    assert observed.count(('127.0.0.1',8808))==1 and observed[-1]=='closed'
    assert any(isinstance(x,bytes) and b'GET /api/latest HTTP/1.1' in x and b'Host: localhost:8808' in x for x in observed)
    ticks[0]=116.
    with pytest.raises(ValueError,match='deadline'):service._http('nginx',115.)


def test_context_first_pass_and_bounded_stop(binding,monkeypatch):
    monkeypatch.setattr(service,'_probe',lambda *a:{'http_status':200,'run_date':'2026-11-03','rate_count':3})
    with service.ServiceCompanion(Path(binding['operation'])/'pressure',binding) as companion:
        assert companion._thread.daemon and companion._thread.is_alive()
        assert companion._last['seq']==1 and companion._last['probe_count']==2
        assert companion.binding_sha256==service.read_binding(companion.directory)[1]
    assert not companion._thread.is_alive()


def test_startup_failure_stops_thread(binding,monkeypatch):
    monkeypatch.setattr(service,'_probe',lambda *a:(_ for _ in ()).throw(ValueError('body must not escape')))
    companion=service.ServiceCompanion(Path(binding['operation'])/'pressure',binding)
    with pytest.raises(ValueError):companion.__enter__()
    assert not companion._thread.is_alive()
    raw=(companion.directory/'snapshot.json').read_text()
    assert 'body must not escape' not in raw and json.loads(raw)['failure_latched']


def test_failure_latch_survives_recovery_and_exit(binding,monkeypatch):
    monkeypatch.setattr(service,'_probe',lambda *a:{'http_status':200,'run_date':'2026-11-03','rate_count':3})
    companion=service.ServiceCompanion(Path(binding['operation'])/'pressure',binding);companion.__enter__()
    monkeypatch.setattr(service,'_probe',lambda *a:(_ for _ in ()).throw(TimeoutError()))
    companion._round()
    monkeypatch.setattr(service,'_probe',lambda *a:{'http_status':200,'run_date':'2026-11-03','rate_count':3})
    companion._round()
    assert companion._last['failed_probe_count']==2 and companion._last['failure_latched']
    with pytest.raises(ValueError,match='failure_latched'):companion.__exit__(None,None,None)
    assert not companion._thread.is_alive()


def test_join_failure_propagates(binding):
    class Stuck:
        def join(self,timeout):assert timeout==31.
        def is_alive(self):return True
    companion=service.ServiceCompanion(Path(binding['operation'])/'pressure',binding);companion._thread=Stuck()
    with pytest.raises(ValueError,match='did_not_terminate'):companion._finish()


def receipt(binding):
    return {'schema':service.RECEIPT_SCHEMA,'binding':binding,'binding_sha256':service._binding(binding),
            'initial_snapshot':snapshot(binding),'last_snapshot':snapshot(binding,seq=2,start=106.,finish=107.),
            'observations':8,'max_age_s':6.,'max_observation_gap_s':1.,
            'window_started_monotonic':101.,'window_finished_monotonic':109.,
            'first_observed_monotonic':102.,'last_observed_monotonic':109.}


def test_receipt_independent_validation(binding):
    value=receipt(binding)
    assert service.require_service_receipt(value,binding,started_monotonic=101.,finished_monotonic=109.)==value


def test_receipt_service_read_completes_after_host_sample(binding):
    value=receipt(binding)
    value['first_observed_monotonic']=101.01
    value['last_observed_monotonic']=109.01
    value['max_observation_gap_s']=1.2
    assert service.require_service_receipt(value,binding,started_monotonic=101.,finished_monotonic=109.)==value
    value['last_observed_monotonic']=111.01
    with pytest.raises(ValueError,match='window_coverage'):
        service.require_service_receipt(value,binding,started_monotonic=101.,finished_monotonic=109.)


@pytest.mark.parametrize('fault',['old','late_start','early_end','gap','age','observations','binding','latch','initial','window'])
def test_receipt_rejects_incomplete_coverage(binding,fault):
    value=receipt(binding)
    if fault=='old':value['schema']='old'
    elif fault=='late_start':value['first_observed_monotonic']=104.
    elif fault=='early_end':value['window_finished_monotonic']=112.
    elif fault=='gap':value['max_observation_gap_s']=2.01
    elif fault=='age':value['max_age_s']=37.01
    elif fault=='observations':value['observations']=1
    elif fault=='binding':value['binding_sha256']='0'*64
    elif fault=='latch':value['last_snapshot']['failure_latched']=True;value['last_snapshot']['failed_probe_count']=1
    elif fault=='initial':value['window_started_monotonic']=100.
    else:value['window_started_monotonic']=101.5
    with pytest.raises(ValueError):service.require_service_receipt(value,binding,started_monotonic=101.,finished_monotonic=109.)
