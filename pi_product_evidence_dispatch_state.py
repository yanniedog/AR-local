"""Independent create-once preparation intents and bounded phase CAS.

No financial pending mutation, discovery of uncommitted outputs or scheduling.
All paths are below the existing full-backup state scope.
"""
from datetime import date, datetime, timedelta
from pathlib import Path
import os
import re
import stat
import uuid

from app_payload_product_evidence_contract import canonical, decode, digest, fields, require, SHA
from app_payload_product_evidence_delivery_check import read_stable
from app_payload_product_evidence_reference import LANES, bound_bundle_sha256
from app_payload_revisions_state import validate_index, validate_manifest, revision_tag
from app_payload_common import DEFAULT_REPO
from cdr_atomic import atomic_write_bytes, atomic_write_json
from cdr_file_lock import FileLock
from cdr_product_evidence_delivery_policy import STATUS, validate_enabled
from cdr_product_evidence_source import safe_path
from pi_product_evidence_locations import supported_location

DIRECTORY='product-evidence-dispatch-v1'
SCHEMA='ar-product-evidence-dispatch-v1'
PHASES=('snapshot','facts','responses','delivery','publish')
MAX_REQUEST=98304
MAX_ATTEMPTS=8
NONCE=re.compile('[0-9a-f]{32}')


def private_directory(path):
    # Exact existing 80b dependency: validates protected Windows DACL as well as
    # POSIX owner/mode and rechecks type/ancestry after concurrent creation.
    from cdr_replay_paths import private_replay_parent
    return private_replay_parent(path)


def financial_manifest(manifest):
    """Exact projection, with financial metadata/asset bytes left unchanged."""
    return {key:value for key,value in manifest.items() if key not in (*LANES,STATUS)}


def current_pointer(state):
    """Read the actual selection bytes; canonical reserialization is not a pin."""
    root=Path(state)/'observation-pointers-v2'
    observed,_=read_stable(root/'latest-observation.json',65536)
    role=decode(observed).get('observation_state')
    require(role in ('partial','complete'),'failed or unsupported selected source')
    raw=observed if role=='partial' else read_stable(root/'latest-complete.json',65536)[0]
    value=decode(raw)
    from cdr_product_evidence_source import FinalizedSource
    FinalizedSource._pointer_fields(value)
    require(value['observation_state']==role,'selected pointer role differs')
    return value,digest(raw)


def register(state,pointer,*,published_root,index_raw,expected_index_sha256,enabled,writer_revision,writer_tree):
    validate_enabled(enabled);require(bool(enabled),'disabled preparation has no request')
    require(type(writer_revision) is str and re.fullmatch('[0-9a-f]{40}',writer_revision), 'invalid writer revision')
    require(type(writer_tree) is str and re.fullmatch('[0-9a-f]{40}',writer_tree),'invalid writer tree')
    state=Path(state).absolute();published_root=supported_location(state,published_root)
    require(type(index_raw) is bytes and len(index_raw)<=8*1024**2 and digest(index_raw)==expected_index_sha256,
            'published index differs from explicit pin')
    raw,_=read_stable(published_root/'manifest.json',65536);published=decode(raw)
    index=decode(index_raw);validate_index(index,repo=DEFAULT_REPO)
    day=published['run_date'];head=index.get('revision_heads',{}).get(day)
    require(type(head) is dict and head['manifest_sha256']==digest(raw)
            and head['bundle_sha256']==bound_bundle_sha256(published)
            and published.get('tag')==revision_tag(day,head['revision'])
            and published.get('repo')==DEFAULT_REPO,'published preparation predecessor differs')
    require(all(published.get('payload_revision',{}).get(key)==head[key]
                for key in ('revision','generation_id','bundle_sha256')),'published revision differs')
    validate_manifest(published,published_root)
    source=published.get('source_observation',{})
    require(type(pointer) is dict and all(pointer.get(key)==source.get(key) for key in
            ('generation_id','observation_date','observation_state')),'published/source pointer differs')
    selected,pointer_sha=current_pointer(state)
    require(canonical(selected)==canonical(pointer),'preparation source is no longer selected')
    base=financial_manifest(published)
    value=dict(schema=SCHEMA,pointer=pointer,pointer_sha256=pointer_sha,source=source,enabled=list(enabled),writer_revision=writer_revision,writer_tree=writer_tree,
        predecessor=head,predecessor_index_sha256=expected_index_sha256,
        published_directory=published_root.relative_to(state).as_posix(),published_manifest_sha256=digest(raw),
        financial_manifest_sha256=digest(canonical(base)),publication_authorized=False)
    raw=canonical(value);require(len(raw)<=MAX_REQUEST,'preparation request exceeds bound')
    checksum=digest(raw);parent=private_directory(state/DIRECTORY)
    parent=private_directory(parent/day);root=private_directory(parent/checksum)
    atomic_write_bytes(root/'published-index.json',index_raw,create_once=True)
    atomic_write_bytes(root/'request.json',raw,create_once=True)
    return {'day':day,'sha256':checksum}


class Work:
    def __init__(self,state,pin):
        fields(pin,('day','sha256'))
        require(type(pin['day']) is str and date.fromisoformat(pin['day']).isoformat()==pin['day']
                and type(pin['sha256']) is str and SHA.fullmatch(pin['sha256']),'invalid preparation pin')
        self.state=Path(state).absolute();self.pin=dict(pin)
        self.root=safe_path(self.state,f"{DIRECTORY}/{pin['day']}/{pin['sha256']}")
        supported_location(self.state,self.root)
        raw,_=read_stable(self.root/'request.json',MAX_REQUEST)
        require(digest(raw)==pin['sha256'],'preparation request changed')
        self.request=decode(raw);fields(self.request,('schema','pointer','pointer_sha256','source','enabled','writer_revision','writer_tree',
            'predecessor','predecessor_index_sha256','published_directory','published_manifest_sha256',
            'financial_manifest_sha256','publication_authorized'))
        require(self.request['schema']==SCHEMA and self.request['publication_authorized'] is False,
                'unsupported preparation request')
        validate_enabled(self.request['enabled'])
        require(bool(self.request['enabled']) and re.fullmatch('[0-9a-f]{40}',self.request['writer_revision']),
                'invalid enabled/writer binding')
        require(type(self.request['writer_tree']) is str and re.fullmatch('[0-9a-f]{40}',self.request['writer_tree']),'invalid writer tree')
        require(self.request['source']['observation_date']==pin['day'],'preparation day differs')
        require(canonical(self.request)==raw,'noncanonical preparation request')
        for key in ('pointer_sha256','predecessor_index_sha256','published_manifest_sha256','financial_manifest_sha256'):
            require(type(self.request[key]) is str and SHA.fullmatch(self.request[key]),'invalid preparation digest')
        index_raw,_=read_stable(self.root/'published-index.json',8*1024**2)
        require(digest(index_raw)==self.request['predecessor_index_sha256'],'retained published index changed')
        index=decode(index_raw);validate_index(index,repo=DEFAULT_REPO)
        require(index['revision_heads'].get(pin['day'])==self.request['predecessor'],'retained predecessor differs')
        safe_path(self.state,self.request['published_directory'])
        self.path=self.root/'progress.json'

    def progress(self):
        if not self.path.exists():return {'stages':{},'attempts':{}}
        raw,_=read_stable(self.path,65536);value=decode(raw)
        require(type(value) is dict and set(value)<={'request_sha256','stages','attempts','attempt_id','phase',
            'status','next_attempt_at','reason'} and value.get('request_sha256')==self.pin['sha256'],
            'preparation progress differs')
        require(type(value.get('stages')) is dict and set(value['stages'])<=set(PHASES)
                and type(value.get('attempts')) is dict and set(value['attempts'])<=set(PHASES),'invalid phase progress')
        for phase,count in value['attempts'].items():require(type(count) is int and 0<count<=MAX_ATTEMPTS,'invalid phase attempt count')
        for phase,pin in value['stages'].items():
            fields(pin,('file','sha256'));require(type(pin['sha256']) is str and SHA.fullmatch(pin['sha256']),'invalid phase pin')
            safe_path(self.root,pin['file'])
        if 'attempt_id' in value:
            require(NONCE.fullmatch(value['attempt_id']) and value.get('phase') in PHASES
                    and value.get('status') in ('running','failed','complete','superseded','blocked'),'invalid preparation attempt')
            require(datetime.fromisoformat(value['next_attempt_at']).tzinfo is not None,'preparation cooldown lacks timezone')
        return value

    def next_phase(self):
        stages=self.progress()['stages']
        wanted=['snapshot']
        if 'product_evidence_v1' in self.request['enabled']:wanted.append('facts')
        if 'product_response_evidence_v1' in self.request['enabled']:wanted.append('responses')
        wanted+=['delivery','publish']
        return next((name for name in wanted if name not in stages),None)

    def stage(self,phase):
        pin=self.progress()['stages'].get(phase);require(pin is not None,'required committed phase missing')
        raw,_=read_stable(safe_path(self.root,pin['file']),MAX_REQUEST)
        require(digest(raw)==pin['sha256'],'committed phase changed')
        result=decode(raw)
        require(result.get('schema')=='ar-product-evidence-stage-v1' and result.get('result')=='PASS'
                and result.get('request_sha256')==self.pin['sha256'] and result.get('phase')==phase,
                'committed phase identity differs')
        require(pin['file']==f"attempts/{result.get('attempt_id')}/result.json"
                and type(result.get('attempt_id')) is str and NONCE.fullmatch(result['attempt_id']),
                'committed phase attempt differs')
        return result

    def begin(self,now):
        require(now.tzinfo is not None,'preparation clock lacks timezone')
        with FileLock(self.path.with_suffix('.lock')):
            row=self.progress();phase=self.next_phase()
            if not phase or row.get('status') in ('superseded','blocked'):return None
            if row.get('next_attempt_at') and now<datetime.fromisoformat(row['next_attempt_at']):return None
            count=row['attempts'].get(phase,0)
            if count>=MAX_ATTEMPTS:return None
            attempt=uuid.uuid4().hex
            private_directory(self.root/'attempts');private_directory(self.root/'attempts'/attempt)
            row.update(request_sha256=self.pin['sha256'],phase=phase,attempt_id=attempt,status='running',
                next_attempt_at=(now+timedelta(seconds=1800+45+3600)).isoformat(),reason='')
            row['attempts'][phase]=count+1;atomic_write_json(self.path,row)
            return {'phase':phase,'attempt_id':attempt}

    def finish(self,attempt,*,now,status,reason=''):
        require(now.tzinfo is not None and status in ('complete','failed','superseded','blocked'),'invalid phase outcome')
        with FileLock(self.path.with_suffix('.lock')):
            row=self.progress()
            if row.get('attempt_id')!=attempt['attempt_id'] or row.get('phase')!=attempt['phase'] or row.get('status')!='running':return False
            if status=='complete':
                relative=f"attempts/{attempt['attempt_id']}/result.json"
                raw,_=read_stable(safe_path(self.root,relative),MAX_REQUEST);value=decode(raw)
                require(value.get('result')=='PASS' and value.get('request_sha256')==self.pin['sha256']
                        and value.get('phase')==attempt['phase'] and value.get('attempt_id')==attempt['attempt_id']
                        and value.get('schema')=='ar-product-evidence-stage-v1','phase result is not this attempt')
                row['stages'][attempt['phase']]={'file':relative,'sha256':digest(raw)}
            delay=0 if status=='complete' else min(3600*2**min(row['attempts'][attempt['phase']]-1,3),21600)
            row.update(status=status,reason=str(reason)[:256],next_attempt_at=(now+timedelta(seconds=delay)).isoformat())
            atomic_write_json(self.path,row);return True
