"""Private bounded source bytes. Public graph descriptors never replace originals."""
import gzip
import hashlib
import io
import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from .identity import require_sha

_OPERATION=ContextVar('monetary_private_evidence',default=None)
MAX_MEMBER=2*1024*1024


class EvidenceOperation:
    def __init__(self,store):
        self.store=store;self.db=store.db;self.raw={};self.decoded={};self.raw_bytes=0;self.decoded_bytes=0;self.captures={}
        self.adopted={};self.adopted_sizes={};self.adopted_raw_bytes=0;self.adopted_decoded_bytes=0
        self.subjects=set();self.authorities=set();self.observations=set();self.documents=set();self.intervals=set();self.postings=set();self.supersessions=set();self.rules=set()

    def read_blob(self,identity):
        require_sha(identity)
        if identity in self.raw:return self.raw[identity]
        if len(self.raw)>=512:raise ValueError('Monetary private member count exceeded')
        path=Path(self.store.root)/'blobs'/identity[:2]/identity
        if path.is_symlink() or path.resolve()!=path or not path.is_file():raise ValueError('Unsafe monetary source member')
        size=path.stat().st_size
        if size>MAX_MEMBER or self.raw_bytes+size>32*1024*1024:raise ValueError('Monetary private byte budget exceeded')
        if hasattr(self.store,'used'):
            if self.store.used+size>512*1024*1024:raise ValueError('Terms projection work budget exceeded')
            self.store.used+=size
        with path.open('rb') as stream:raw=stream.read(size+1)
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=identity:raise ValueError('Monetary source bytes changed')
        self.raw_bytes+=len(raw);self.raw[identity]=raw
        return raw

    def member(self,descriptor):
        identity=descriptor['sha256'];raw=self.read_blob(identity)
        if len(raw)!=descriptor['bytes']:raise ValueError('Monetary member byte descriptor differs')
        prior=self.decoded.get(identity)
        if prior:
            if (prior[0] is not None and prior[0]!=descriptor) or prior[2]!=(descriptor['encoding']=='gzip') or len(prior[1])!=descriptor['decodedBytes']:
                raise ValueError('Monetary contradictory member descriptor')
            self.decoded[identity]=(descriptor,prior[1],prior[2])
            return prior[1]
        if self.decoded_bytes+descriptor['decodedBytes']>24*1024*1024:raise ValueError('Monetary decoded operation bound exceeded')
        if descriptor['encoding']=='gzip':
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:body=stream.read(MAX_MEMBER+1)
        else:body=raw
        if len(body)!=descriptor['decodedBytes'] or len(body)>MAX_MEMBER:raise ValueError('Monetary decoded descriptor differs')
        self.decoded_bytes+=len(body);self.decoded[identity]=(descriptor,body,descriptor['encoding']=='gzip')
        return body

    def adopted_json(self,identity,*,compressed=True):
        """Public adopted snapshot budget is separate from private historical members."""
        require_sha(identity)
        if identity in self.adopted:
            if self.adopted[identity][0]!=compressed:raise ValueError('Adopted asset encoding differs')
            return self.adopted[identity][1]
        path=Path(self.store.root)/'blobs'/identity[:2]/identity
        if path.is_symlink() or path.resolve()!=path or not path.is_file():raise ValueError('Unsafe adopted source asset')
        size=path.stat().st_size
        if size>8*1024*1024 or self.adopted_raw_bytes+size>8*1024*1024:raise ValueError('Adopted compressed snapshot bound exceeded')
        if hasattr(self.store,'used'):
            if self.store.used+size>512*1024*1024:raise ValueError('Terms projection work budget exceeded')
            self.store.used+=size
        with path.open('rb') as stream:raw=stream.read(size+1)
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=identity:raise ValueError('Adopted asset bytes changed')
        remaining=24*1024*1024-self.adopted_decoded_bytes
        if compressed:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:body=stream.read(remaining+1)
        else:body=raw
        if len(body)>remaining:raise ValueError('Adopted expanded snapshot bound exceeded')
        self.adopted_raw_bytes+=len(raw);self.adopted_decoded_bytes+=len(body)
        value=json.loads(body)
        self.adopted[identity]=(compressed,value)
        self.adopted_sizes[identity]=(len(raw),len(body))
        return value

    def admit(self,subject):
        if subject['id'] in self.subjects:return
        graph=subject['authorityGraph']
        self.subjects.add(subject['id']);self.authorities.update(x['id'] for x in graph['authorities'])
        self.documents.update(subject['documentVersionIds'])
        for authority in graph['authorities']:
            self.observations.update(x['observationId'] for x in authority.get('observations',[]))
        self.intervals.update((subject['id'],x['id']) for x in subject['policy']['intervals'])
        self.postings.update((subject['id'],x) for x in subject['policy']['postingInventory']['dueDates'])
        self.supersessions.update(json.dumps(x,sort_keys=True) for x in graph['supersessions'])
        pending=[subject['policy']['eligibility']]
        while pending:
            rule=pending.pop();self.rules.add((subject['id'],rule['id']));pending.extend(rule.get('rules',[]))
            if 'rule' in rule:pending.append(rule['rule'])
        if any(len(items)>cap for items,cap in ((self.authorities,64),(self.documents,256),(self.observations,366),(self.intervals,128),(self.postings,366),(self.supersessions,64),(self.rules,512))):
            raise ValueError('Monetary whole-operation inventory bound exceeded')
        for descriptor in graph['members']:self.member(descriptor)


@contextmanager
def evidence_operation(store):
    current=_OPERATION.get()
    if current is not None and current.store is store:
        yield current;return
    operation=EvidenceOperation(store);token=_OPERATION.set(operation)
    try:yield operation
    finally:_OPERATION.reset(token)


def evidence_checked(function):
    @wraps(function)
    def checked(store,*args,**kwargs):
        with evidence_operation(store):return function(store,*args,**kwargs)
    return checked
