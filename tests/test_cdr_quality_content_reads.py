"""Protocol tests for required supervised reads; no Pi or business fixtures."""
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import sys

import pytest
import pi_cdr_quality_read_io as reader
import ar_local_restore_io as restore
import cdr_export_contract as contracts
import cdr_quality_sources as sources


@pytest.fixture
def preadv(monkeypatch):
    calls=[]
    def positional(fd,buffers,offset,flags):
        assert flags==reader.RWF_DONTCACHE
        assert len(buffers)==1
        calls.append((offset,len(buffers[0]),flags))
        original=os.lseek(fd,0,os.SEEK_CUR)
        try:
            os.lseek(fd,offset,os.SEEK_SET)
            data=os.read(fd,len(buffers[0]))
        finally:os.lseek(fd,original,os.SEEK_SET)
        buffers[0][:len(data)]=data
        return len(data)
    monkeypatch.setattr(reader.sys,'platform','linux')
    monkeypatch.setattr(reader.os,'preadv',positional,raising=False)
    return calls


class NoOrdinaryRead:
    def __init__(self,stream):self.stream=stream
    def fileno(self):return self.stream.fileno()
    def tell(self):return self.stream.tell()
    def seek(self,position):return self.stream.seek(position)
    def read(self,*_):raise AssertionError('ordinary read called inside required scope')


def test_copy_source_stream_is_bounded_and_dropbehind(tmp_path,preadv):
    payload=bytes(range(256))*(reader.READ_BYTES//256+3)
    path=tmp_path/'input';path.write_bytes(payload)
    target=tmp_path/'copy'
    with path.open('rb') as stream,reader.require_dropbehind_reads():
        digest=restore.copy_stream(NoOrdinaryRead(stream),(0,0,0,len(payload)),target)
        assert stream.tell()==len(payload)
    assert target.read_bytes()==payload and digest==hashlib.sha256(payload).hexdigest()
    assert max(n for _,n,_ in preadv)<=reader.READ_BYTES
    assert preadv[-1]==(len(payload),1,reader.RWF_DONTCACHE)


def test_portable_copy_unchanged_outside_scope(tmp_path,monkeypatch):
    monkeypatch.setattr(restore,'chunks_dropbehind',lambda *a,**k:pytest.fail('must remain portable'))
    payload=b'unchanged portable copy'
    assert restore.copy_stream(io.BytesIO(payload),(0,0,0,len(payload)),tmp_path/'out')==hashlib.sha256(payload).hexdigest()
    assert (tmp_path/'out').read_bytes()==payload


@pytest.mark.parametrize('size',[0,1,reader.READ_BYTES,reader.READ_BYTES+1])
@pytest.mark.parametrize('capture',[False,True])
def test_hash_and_capture_equivalence(tmp_path,preadv,size,capture):
    payload=(b'pattern7'*(size//8+1))[:size]
    path=tmp_path/'input';path.write_bytes(payload)
    with path.open('rb') as f:
        digest,body=reader.hash_dropbehind(f.fileno(),size,capture)
    assert digest==hashlib.sha256(payload).hexdigest()
    assert body==(payload if capture else None)
    assert preadv[-1]==(size,1,reader.RWF_DONTCACHE)


@pytest.mark.parametrize('change',['truncate','grow'])
def test_size_mutation_rejected(tmp_path,preadv,change):
    path=tmp_path/'input';path.write_bytes(b'x'*20)
    with path.open('rb') as f:
        if change=='truncate':path.write_bytes(b'x'*19)
        else:path.write_bytes(b'x'*21)
        with pytest.raises(ValueError,match='size changed'):
            list(reader.chunks_dropbehind(f.fileno(),20))


def test_required_copy_rejects_partial_stream(tmp_path,preadv):
    path=tmp_path/'input';path.write_bytes(b'123')
    with path.open('rb') as f,reader.require_dropbehind_reads():
        f.seek(1)
        with pytest.raises(ValueError,match='offset zero'):list(restore.chunks(f,2))
    assert not preadv


def test_required_unsupported_does_not_fallback(tmp_path,monkeypatch):
    path=tmp_path/'input';path.write_bytes(b'data')
    monkeypatch.setattr(reader.sys,'platform','linux')
    def unsupported(*a):raise OSError(95,'operation not supported')
    monkeypatch.setattr(reader.os,'preadv',unsupported,raising=False)
    with path.open('rb') as f,reader.require_dropbehind_reads(),pytest.raises(OSError):
        list(restore.chunks(NoOrdinaryRead(f),4))


def test_contract_parser_routes_all_bytes_and_preserves_budget(tmp_path,preadv):
    path=tmp_path/'contract';payload=br'{"protocol":"\u00e9"}';path.write_bytes(payload)
    charged=[]
    with reader.require_dropbehind_reads():
        value=contracts.read_json(path,budget=lambda **k:charged.append(k),max_bytes=64)
    assert value=={'protocol':'\u00e9'}
    assert sum(x.get('size',0) for x in charged)==len(payload)
    assert charged[0]=={'entries':1} and preadv[-1][0]==len(payload)


def test_contract_limit_blocks_before_read(tmp_path,preadv):
    path=tmp_path/'contract';path.write_bytes(b'12345')
    with reader.require_dropbehind_reads(),pytest.raises(ValueError,match='bounded read limit'):
        contracts.read_json(path,max_bytes=4)
    assert not preadv


@pytest.mark.parametrize('maximum',[32*1024**2,512*1024**2])
def test_json_uses_identity_bound_capture(tmp_path,monkeypatch,maximum):
    path=tmp_path/'json';path.write_bytes(b'{"protocol":1}')
    calls=[]
    def capture(p,**kw):calls.append((p,kw));return None,b'{"protocol":1}'
    monkeypatch.setattr(sources,'read_digest',capture)
    with reader.require_dropbehind_reads():assert sources.read_source_bytes(path,maximum)==b'{"protocol":1}'
    assert calls==[(path,dict(capture=True,max_bytes=maximum))]


def test_metadata_and_dashboard_route_through_helper(tmp_path,monkeypatch):
    path=tmp_path/'json';path.write_text('{}')
    calls=[]
    monkeypatch.setattr(sources,'read_source_bytes',lambda p,m:calls.append((p,m)) or b'{}')
    with reader.require_dropbehind_reads():assert sources.read_object(path)=={}
    assert calls==[(path,32*1024**2)]
    tree=ast.parse(Path(sources.__file__).read_bytes())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='audit_source')
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='read_source_bytes'
               for n in ast.walk(function))
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='read_bytes'
                   for n in ast.walk(function))
